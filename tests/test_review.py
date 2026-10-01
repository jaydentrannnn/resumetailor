"""Tests for the opt-in hiring-manager review stage."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.pipeline import review
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from resume_tailor.pipeline.review import BulletVerdict, ReviewLLM
from tests.fixtures import synthetic_resume


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, queue, calls):
        self._queue = queue
        self._calls = calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return _FakeResponse(self._queue.pop(0))


class _FakeClient:
    def __init__(self, queue, calls):
        self.messages = _FakeMessages(queue, calls)


@pytest.fixture
def review_calls(monkeypatch):
    """Shared reply queue stubbed at ``llm.client_for``."""
    recorded: list[dict] = []
    queue: list = []

    def _client_for(purpose):
        return _FakeClient(queue, recorded)

    monkeypatch.setattr(review.llm, "client_for", _client_for)
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")

    def enqueue(*replies):
        queue.extend(replies)
        return recorded

    return enqueue


def _reqs() -> JobRequirements:
    """Minimal requirements for review tests."""
    return JobRequirements(
        title="ML Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def test_cut_verdict_renders(review_calls):
    """A cut verdict appears in the review result as-is."""
    resume = synthetic_resume()
    bullets = {b.id: b.text for b in resume.all_bullets()}
    bid = next(iter(bullets))
    review_calls(
        ReviewLLM(
            scope_read="Junior ML role focused on Python.",
            bullets=[
                BulletVerdict(id=bid, verdict="cut", reason="Off-topic for this role")
            ],
        )
    )
    result = review.review_bullets(resume, _reqs(), bullets)
    assert result.scope_read.startswith("Junior")
    assert result.bullets[0].verdict == "cut"
    assert result.bullets[0].reason == "Off-topic for this role"


def test_fabricating_rewrite_is_dropped_not_shown(review_calls):
    """A rewrite suggestion that invents a tool is dropped with a warning."""
    resume = synthetic_resume()
    bullets = {b.id: b.text for b in resume.all_bullets()}
    bid = next(iter(bullets))
    review_calls(
        ReviewLLM(
            scope_read="Python role.",
            bullets=[
                BulletVerdict(
                    id=bid,
                    verdict="rewrite",
                    reason="Lead with the tool",
                    replacement="Built Kubernetes clusters for production ML.",
                )
            ],
        )
    )
    result = review.review_bullets(resume, _reqs(), bullets)
    assert result.bullets[0].verdict == "rewrite"
    assert result.bullets[0].replacement == ""
    assert "fabricated" in result.bullets[0].dropped_note
    assert any("fabricated" in w for w in result.warnings)


def test_clean_rewrite_is_shown(review_calls):
    """A rewrite that stays within the source vocabulary is kept for display."""
    resume = synthetic_resume()
    bullets = {b.id: b.text for b in resume.all_bullets()}
    bid = next(iter(bullets))
    source_text = bullets[bid]
    # Rephrase without adding tokens — take the source text itself.
    review_calls(
        ReviewLLM(
            scope_read="Python role.",
            bullets=[
                BulletVerdict(
                    id=bid,
                    verdict="rewrite",
                    reason="Tighten the opener",
                    replacement=source_text,
                )
            ],
        )
    )
    result = review.review_bullets(resume, _reqs(), bullets)
    assert result.bullets[0].replacement == source_text
    assert result.bullets[0].dropped_note == ""
