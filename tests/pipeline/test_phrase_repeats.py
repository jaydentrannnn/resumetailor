"""The posting-phrase repeat cap: detection (`bullet_checks.phrase_collisions`) and the
silent repair in the shared repair engine (`followups._polish`). Production rewriting no
longer asks for that repair (the cosmetic pass was removed); the eval harness still does."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.content.data import Bullet
from resume_tailor.pipeline import bullet_checks, followups, rewrite, rewrite_prompts
from resume_tailor.pipeline.jd import JobRequirements, Keyword

PHRASE = "data engineering projects"


def _bullet(bid: str, text: str, tags: list[str] | None = None) -> Bullet:
    return Bullet(id=bid, text=text, tags=tags or ["python"])


def _reqs(*phrases: str) -> JobRequirements:
    return JobRequirements(
        title="Data Engineering Intern", seniority="intern",
        keywords=[
            Keyword(phrase=p, canonical=p.lower(), importance="must_have") for p in phrases
        ],
    )


class _Response:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _Client:
    def __init__(self, replies, calls):
        self.messages = self
        self._replies, self._calls = replies, calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        if not self._replies:
            raise AssertionError("model called more times than the test supplied replies")
        return _Response(self._replies.pop(0))


def _reply(**by_id) -> rewrite_prompts.RewriteResult:
    return rewrite_prompts.RewriteResult(
        bullets=[rewrite_prompts.RewrittenBullet(id=k, text=v) for k, v in by_id.items()]
    )


@pytest.fixture
def model(monkeypatch):
    """Queue replies; returns (calls, telemetry events)."""
    calls: list[dict] = []
    events: list[dict] = []

    def install(*replies):
        queue = list(replies)
        monkeypatch.setattr(rewrite.llm, "client_for", lambda purpose: _Client(queue, calls))
        return calls, events

    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(
        followups.telemetry, "event", lambda stage, **counts: events.append(counts)
    )
    return install


# --- the cap --------------------------------------------------------------------------


def test_cap_is_two_on_one_page_and_grows_one_per_extra_page():
    assert config.phrase_repeat_cap(1) == 2
    assert config.phrase_repeat_cap(2) == 3
    assert config.phrase_repeat_cap(3) == 4


# --- detection ------------------------------------------------------------------------


_OPENERS = {"a": "Built", "b": "Automated", "c": "Migrated"}


def _three_injected() -> tuple[dict[str, str], dict[str, Bullet]]:
    """Three bullets with distinct openers, each adding PHRASE to its source."""
    sources = {
        bid: _bullet(bid, f"{verb} pipeline {bid} in Python.") for bid, verb in _OPENERS.items()
    }
    texts = {
        bid: f"{verb} pipeline {bid} in Python for {PHRASE}." for bid, verb in _OPENERS.items()
    }
    return texts, sources


def test_third_injected_repeat_on_one_page_is_flagged():
    texts, sources = _three_injected()
    assert bullet_checks.phrase_collisions(texts, [PHRASE], sources, pages=1) == {
        "c": [PHRASE]
    }


def test_two_pages_allow_a_third_repeat():
    texts, sources = _three_injected()
    assert bullet_checks.phrase_collisions(texts, [PHRASE], sources, pages=2) == {}


def test_single_word_phrases_never_count():
    """A tool name recurring is the candidate's real stack, not stuffing."""
    sources = {bid: _bullet(bid, f"Used Python for {bid}.") for bid in "abcd"}
    texts = {bid: f"Used Python for {bid}." for bid in sources}
    assert bullet_checks.phrase_collisions(texts, ["Python"], sources, pages=1) == {}


def test_bullets_whose_source_says_it_keep_it_first():
    """Only a bullet that added the phrase is ever asked to remove it."""
    texts, sources = _three_injected()
    sources["c"] = _bullet("c", f"Migrated pipeline c in Python for {PHRASE}.")
    collisions = bullet_checks.phrase_collisions(texts, [PHRASE], sources, pages=1)
    assert collisions == {"b": [PHRASE]}


def test_source_owned_repeats_are_never_offenders():
    sources = {bid: _bullet(bid, f"Led {PHRASE} number {bid}.") for bid in "abc"}
    texts = {bid: s.text for bid, s in sources.items()}
    assert bullet_checks.phrase_collisions(texts, [PHRASE], sources, pages=1) == {}


def test_context_bullets_count_but_are_never_repaired():
    texts, sources = _three_injected()
    collisions = bullet_checks.phrase_collisions(
        texts, [PHRASE], sources, pages=1, repairable={"a"}
    )
    assert collisions == {"a": [PHRASE]}


def test_matching_ignores_case_and_whitespace_but_needs_whole_words():
    assert bullet_checks.contains_phrase("For Data  Engineering\nProjects.", PHRASE)
    assert not bullet_checks.contains_phrase("big data engineering projectsX", PHRASE)


# --- repair ---------------------------------------------------------------------------


def _run(model, final_reply, texts=None, sources=None, repairable=None):
    if texts is None:
        texts, sources = _three_injected()
    calls, events = model(final_reply)
    overuse = bullet_checks.phrase_collisions(
        texts, [PHRASE], sources, pages=1,
        repairable=set(texts) - set(bullet_checks.verb_collisions(texts))
        if repairable is None else repairable,
    )
    out, _, _, _ = followups._polish(
        texts, sources, _reqs(PHRASE), repair_widows=False, repair_verbs=True,
        phrase_overuse=overuse,
    )
    return out, calls, events


def test_repair_removes_the_repeat_and_logs_telemetry(model):
    out, calls, events = _run(model, _reply(c="Migrated pipeline c in Python."))
    assert "bullets_to_rephrase" in calls[0]["messages"][0]["content"]
    assert out["c"] == "Migrated pipeline c in Python."
    assert {"phrase_repeats": 1, "phrase_repaired": 1} in events


@pytest.mark.parametrize("reply", [
    f"Migrated pipeline c in Python for {PHRASE}.",  # phrase still there
    "Moved pipeline c in Python.",  # opener changed
    "Migrated pipeline c in Kubernetes.",  # fabricated
])
def test_unsafe_repair_keeps_the_original_silently(model, reply):
    out, _, events = _run(model, _reply(c=reply))
    assert out["c"] == f"Migrated pipeline c in Python for {PHRASE}."
    assert {"phrase_repeats": 1, "phrase_repaired": 0} in events


def test_rewriting_never_makes_a_follow_up_for_repeated_phrases(model):
    texts, sources = _three_injected()
    calls, events = model(_reply(**texts))
    outcome = rewrite.rewrite_bullets(list(sources.values()), _reqs(PHRASE), char_budget=202)
    assert len(calls) == 1
    assert outcome.texts == texts
    assert not any("phrase_repeats" in e for e in events)


def test_a_verb_colliding_bullet_keeps_the_phrase_and_another_gives_it_up(model):
    """One id gets one repair: the verb pass owns c, so b drops the phrase instead."""
    texts, sources = _three_injected()
    sources["c"] = _bullet("c", "Built pipeline c in Python.")
    texts["c"] = f"Built pipeline c in Python for {PHRASE}."
    out, calls, events = _run(
        model,
        _reply(c=f"Wrote pipeline c in Python for {PHRASE}.", b="Automated pipeline b in Python."),
        texts, sources,
    )
    prompt = calls[0]["messages"][0]["content"]
    assert "bullets_to_revoice" in prompt and "bullets_to_rephrase" in prompt
    assert out["b"] == "Automated pipeline b in Python."
    assert {"phrase_repeats": 1, "phrase_repaired": 1} in events
