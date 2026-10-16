"""A blank model reply never replaces text: each stage keeps what it already had."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.content.data import Bullet, Experience
from resume_tailor.pipeline import bullet_merge, expand, followups, merge, rewrite, rewrite_prompts
from resume_tailor.pipeline.jd import JobRequirements, Keyword

SOURCE = "Built a Python service for internal tooling."


class _Response:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _Messages:
    def __init__(self, replies, calls):
        self._replies, self._calls = replies, calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return _Response(self._replies.pop(0))


class _Client:
    def __init__(self, replies, calls):
        self.messages = _Messages(replies, calls)


@pytest.fixture
def replies(monkeypatch):
    """Queue replies on one shared queue; returns the recorded calls."""
    calls: list[dict] = []

    def install(*queued):
        queue = list(queued)
        monkeypatch.setattr(rewrite.llm, "client_for", lambda purpose: _Client(queue, calls))
        return calls

    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    return install


def _reply(**by_id) -> rewrite_prompts.RewriteResult:
    return rewrite_prompts.RewriteResult(
        bullets=[rewrite_prompts.RewrittenBullet(id=k, text=v) for k, v in by_id.items()]
    )


def _reqs() -> JobRequirements:
    return JobRequirements(
        title="Engineer", seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def _source(bid: str = "a", text: str = SOURCE) -> Bullet:
    return Bullet(id=bid, text=text, tags=["python"])


def test_blank_first_draft_keeps_the_source(replies):
    calls = replies(_reply(a="   "))
    outcome = rewrite.rewrite_bullets(
        [_source()], _reqs(), char_budget=202, repair_verbs=False
    )
    assert outcome.texts["a"] == SOURCE
    assert len(calls) == 1, "a blank draft is missing, not a fabrication to retry"


def test_blank_factual_retry_falls_back_to_the_source(replies):
    replies(_reply(a="Built a Kubernetes service in Python."), _reply(a=""))
    outcome = rewrite.rewrite_bullets(
        [_source()], _reqs(), char_budget=202, repair_verbs=False
    )
    assert outcome.texts["a"] == SOURCE
    assert "a" in outcome.fabrications_rejected


def test_blank_polish_keeps_the_accepted_text(replies):
    current = "Built a Python service for internal tooling, with logging and retries."
    for kind in ("ceilings", "targets"):
        calls = replies(_reply(a=" "))
        calls.clear()
        window = {"a": 60} if kind == "ceilings" else {"a": (0, 60)}
        out, fixed, _, _ = followups._polish(
            {"a": current}, {"a": _source()}, _reqs(), repair_widows=False, repair_verbs=False,
            **{kind: window},
        )
        assert len(calls) == 1
        assert fixed == 0 and out["a"] == current, kind


def test_blank_merge_keeps_the_constituent_bullets(replies):
    texts = {"a": SOURCE, "b": "Shipped a Python tool for the data team."}
    sources = {bid: _source(bid, text) for bid, text in texts.items()}
    group = merge.MergeGroup(survivor_id="a", member_ids=("a", "b"), affinity=1.0, reason="t")
    replies(_reply(a="  "))
    merged, accepted = bullet_merge._merge_bullets(
        texts, sources, [group], _reqs(), budget=202
    )
    assert accepted == [] and merged == texts


def test_blank_expansion_bullets_are_ignored():
    entry = Experience(
        company="ACME", title="Engineer", start="2020-01", end="2021-01", bullets=[_source()]
    )
    kept, _ = expand._accept_bullets(entry, ["", "   ", SOURCE], char_limit=2000)
    assert kept == [SOURCE]
