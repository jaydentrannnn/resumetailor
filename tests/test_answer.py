"""Tests for guarded application-question answers."""

from __future__ import annotations

import pytest

from resume_tailor import config, llm
from resume_tailor.apply.answer import AnswerLLM, answer_question, normalize_question
from resume_tailor.apply.profile import ApplicantProfile
from resume_tailor.jd import JobRequirements, Keyword
from tests.fixtures import synthetic_resume


class _FakeResponse:
    """Mimic ``messages.parse`` return value."""

    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    """Pop one reply per ``parse`` call from a shared queue."""

    def __init__(self, replies: list, calls: list[dict]):
        self._replies = replies
        self._calls = calls

    def parse(self, **kwargs):
        """Record kwargs and return the next queued parsed output."""
        self._calls.append(kwargs)
        if not self._replies:
            raise AssertionError("answer fake client has no replies left")
        return _FakeResponse(self._replies.pop(0))


class _FakeClient:
    """Stand-in for any backend's client."""

    def __init__(self, replies: list, calls: list[dict]):
        self.messages = _FakeMessages(replies, calls)


@pytest.fixture
def answer_calls(monkeypatch, tmp_path):
    """Stub ``llm.client_for`` with a shared reply queue and isolated cache."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    config.CACHE_DIR.mkdir()
    config.resolve("claude")

    replies: list = []
    calls: list[dict] = []

    def client_for(purpose: str):
        """Return a fake that appends every ``parse`` call to one shared list."""
        assert purpose == "answer"
        return _FakeClient(replies, calls)

    monkeypatch.setattr(llm, "client_for", client_for)

    def queue(*parsed):
        """Enqueue model replies and return the shared call list."""
        replies.extend(parsed)
        return calls

    yield queue
    config.resolve("claude")


def _resume_and_bullets():
    """Return a synthetic resume and its master bullet map."""
    resume = synthetic_resume()
    bullets = {b.id: b.text for b in resume.all_bullets()}
    return resume, bullets


def _reqs() -> JobRequirements:
    """Minimal requirements for answer tests."""
    return JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def test_normalize_question_strips_punctuation():
    """Normalization lowercases and removes punctuation for matching."""
    assert normalize_question("  How did you hear about us?  ") == "how did you hear about us"


def test_profile_short_circuit(answer_calls):
    """Matching ``custom_answers`` bypass the LLM entirely."""
    resume, bullets = _resume_and_bullets()
    profile = ApplicantProfile(
        custom_answers={"how did you hear about us": "Found through a job board."}
    )
    calls = answer_calls()
    result = answer_question(
        "How did you hear about us?",
        resume=resume,
        bullets=bullets,
        requirements=_reqs(),
        profile=profile,
        jd_text="Python role.",
        use_cache=False,
    )
    assert result.source == "profile"
    assert result.answer == "Found through a job board."
    assert calls == []


def test_clean_llm_answer_passes_guard(answer_calls):
    """A guard-clean draft is returned from the LLM path."""
    resume, bullets = _resume_and_bullets()
    profile = ApplicantProfile()
    answer_calls(
        AnswerLLM(
            answer=(
                "I improved reliability and throughput for production Python services "
                "at Example Corp."
            )
        )
    )
    result = answer_question(
        "Why are you a good fit?",
        resume=resume,
        bullets=bullets,
        requirements=_reqs(),
        profile=profile,
        jd_text="Python engineer role.",
        use_cache=False,
    )
    assert result.source == "llm"
    assert result.answer
    assert result.offenders == []


def test_fabricated_answer_retries_then_empty(answer_calls):
    """Unsupported claims retry once, then return an empty guarded answer."""
    resume, bullets = _resume_and_bullets()
    profile = ApplicantProfile()
    fabricated = "I built Kubernetes clusters for production workloads."
    answer_calls(
        AnswerLLM(answer=fabricated),
        AnswerLLM(answer=fabricated),
    )
    result = answer_question(
        "Describe your infrastructure experience.",
        resume=resume,
        bullets=bullets,
        requirements=_reqs(),
        profile=profile,
        jd_text="Python role.",
        use_cache=False,
    )
    assert result.answer == ""
    assert result.offenders
    assert any("kubernetes" in o.lower() for o in result.offenders)
    assert any("discarded" in w.lower() for w in result.warnings)


def test_char_cap_truncates_at_sentence_boundary(answer_calls):
    """Overlong answers are truncated with a warning."""
    resume, bullets = _resume_and_bullets()
    profile = ApplicantProfile()
    long_answer = "First sentence is safe. " + ("word " * 400)
    answer_calls(AnswerLLM(answer=long_answer))
    result = answer_question(
        "Tell us more.",
        resume=resume,
        bullets=bullets,
        requirements=_reqs(),
        profile=profile,
        max_chars=80,
        jd_text="Python role.",
        use_cache=False,
    )
    assert len(result.answer) <= 80
    assert any("truncated" in w.lower() for w in result.warnings)


def test_guard_failure_is_not_cached(answer_calls):
    """A discarded answer must not pin the question to "" — the next call asks again."""
    resume, bullets = _resume_and_bullets()
    fabricated = "I built Kubernetes clusters for production workloads."
    clean = "I improved reliability and throughput for production Python services at Example Corp."
    calls = answer_calls(
        AnswerLLM(answer=fabricated),
        AnswerLLM(answer=fabricated),
        AnswerLLM(answer=clean),
    )
    kwargs = dict(
        resume=resume, bullets=bullets, requirements=_reqs(), profile=ApplicantProfile(),
        jd_text="Python role.", use_cache=True,
    )

    first = answer_question("Describe your infrastructure experience.", **kwargs)
    assert first.answer == ""
    assert list(config.CACHE_DIR.glob("*.answer.json")) == []

    second = answer_question("Describe your infrastructure experience.", **kwargs)
    assert second.answer == clean
    assert len(calls) == 3
    assert len(list(config.CACHE_DIR.glob("*.answer.json"))) == 1
