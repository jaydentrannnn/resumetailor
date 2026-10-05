"""Main rewrite number retention shares the single factual retry, never extra rounds."""

from types import SimpleNamespace

import pytest

from resume_tailor.content.data import Bullet
from resume_tailor.infra import llm, telemetry
from resume_tailor.pipeline import bullet_checks, followups, rewrite, rewrite_prompts
from resume_tailor.pipeline.jd import JobRequirements


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    replies = []

    def parse(**kwargs):
        recorded.append(kwargs)
        texts = replies.pop(0)
        if isinstance(texts, Exception):
            raise texts
        result = (
            None
            if texts is None
            else rewrite_prompts.RewriteResult(
                bullets=[
                    rewrite_prompts.RewrittenBullet(id=bid, text=text)
                    for bid, text in texts.items()
                ]
            )
        )
        return SimpleNamespace(parsed_output=result, stop_reason="stop")

    monkeypatch.setattr(
        rewrite.llm,
        "client_for",
        lambda _: SimpleNamespace(
            messages=SimpleNamespace(parse=parse),
        ),
    )
    return recorded, replies


def run(sources):
    return rewrite.rewrite_bullets(
        sources,
        JobRequirements(title="Engineer", seniority="entry"),
        char_budget=200,
        repair_verbs=False,
        repair_widows=False,
    )


def test_missing_metrics_are_restored_in_one_targeted_retry(calls, tmp_path):
    recorded, replies = calls
    source = Bullet(
        id="a",
        text="Built a Python service for 1,000 requests at 99% uptime and 0.8 seconds latency.",
        tags=["python"],
    )
    other = Bullet(id="b", text="Shipped a Python tool.", tags=["python"])
    replies.extend([{"a": "Built a Python service.", "b": other.text}, {"a": source.text}])
    with telemetry.recording(tmp_path) as measured:
        outcome = run([source, other])
    assert len(recorded) == 2
    retry = recorded[1]["messages"][0]["content"]
    assert "missing_numbers=" in retry and "1,000" in retry and "99%" in retry and "0.8" in retry
    assert "id='b'" not in retry
    assert "drop the number entirely" not in retry
    assert outcome.texts == {"a": source.text, "b": other.text}
    assert any(e.get("number_omissions") == 1 for e in measured.data["events"])
    assert any(e.get("number_repairs") == 1 for e in measured.data["events"])


@pytest.mark.parametrize(
    "retry",
    [{"a": "Built a Python tool."}, {}, None, llm.LLMError("Bad repair response")],
)
def test_failed_or_missing_retry_falls_back_to_verbatim_source(calls, retry):
    recorded, replies = calls
    source = Bullet(id="a", text="Built a Python service for 40 users.", tags=["python"])
    replies.extend([{"a": "Built a Python service."}, retry])
    outcome = run([source])
    assert len(recorded) == 2
    assert outcome.texts["a"] == source.text
    assert outcome.fabrications_rejected["a"] == ["missing_number:40"]
    assert "missing source numbers 40" in followups._format_offender_summary(
        outcome.fabrications_rejected["a"],
    )


def test_mixed_missing_and_invented_numbers_share_retry(calls):
    recorded, replies = calls
    source = Bullet(id="a", text="Built a Python service for 40 users.", tags=["python"])
    replies.extend([{"a": "Built a Python service for 70 users."}, {"a": source.text}])
    outcome = run([source])
    assert len(recorded) == 2
    retry = recorded[1]["messages"][0]["content"]
    assert "rejected_terms='70'" in retry and "missing_numbers='40'" in retry
    assert outcome.texts["a"] == source.text


def test_numeric_tags_do_not_force_numbers_absent_from_source_text(calls):
    recorded, replies = calls
    source = Bullet(id="a", text="Built a Python service.", tags=["python", "aws-s3"])
    replies.append({"a": "Created a Python service."})
    outcome = run([source])
    assert len(recorded) == 1
    assert outcome.texts["a"] == "Created a Python service."


@pytest.mark.parametrize(
    "text,candidate",
    [
        ("Built a Python service for 130+ users.", "Built a Python service for over 130 users."),
        ("Built a Python service for over 130 users.", "Built a Python service for 130+ users."),
        ("Built a Python service for 130 users.", "Built a Python service for 130 users."),
    ],
)
def test_existing_supported_lower_bound_equivalence_passes(text, candidate):
    source = Bullet(id="a", text=text, tags=["python"])
    assert not bullet_checks.guard_offenders([source], candidate, preserve_numbers=True)


def test_verb_polish_cannot_drop_an_accepted_metric():
    source = Bullet(id="a", text="Built a Python service for 40 users.", tags=["python"])
    assert not followups._accept_verb_swap(source.text, "Created a Python service.", source, set())


def test_guard_retention_is_opt_in_for_other_existing_callers():
    source = Bullet(id="a", text="Built a service for 40 users.", tags=["service"])
    assert bullet_checks.guard_offenders([source], "Built a service.") == []
    assert bullet_checks.guard_offenders([source], "Built a service.", preserve_numbers=True) == [
        "missing_number:40"
    ]
