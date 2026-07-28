"""Tests for application-form experience expansion.

No network: LLM calls are stubbed at `llm.client_for` with a shared reply queue, matching
the house convention in `tests/test_rewrite.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor import config, expand, llm
from resume_tailor.data import Bullet, Experience, MasterResume, Contact, load
from resume_tailor.expand import (
    ExpandedEntryLLM,
    ExpansionLLMResult,
    _accept_bullets,
    choose_entries,
    expand_experience,
    format_markdown,
)
from resume_tailor.fit import FitResult
from resume_tailor.jd import JobRequirements, Keyword


def _bullet(bid: str, text: str, tags: list[str]) -> Bullet:
    """Build one validated bullet for fixture resumes."""
    return Bullet(id=bid, text=text, tags=tags)


def _reqs(*canonicals: str) -> JobRequirements:
    """Minimal JobRequirements keyed by canonical tag names."""
    return JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[
            Keyword(phrase=c, canonical=c, importance="must_have") for c in canonicals
        ],
    )


def _tiny_resume() -> MasterResume:
    """Three experience entries with known tags for selection tests."""
    return MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        experience=[
            Experience(
                company="Alpha Co",
                title="Engineer",
                location="Remote",
                start="2024",
                end="Present",
                bullets=[
                    _bullet("a1", "Built a Python API serving 1,000 users.", ["python"]),
                    _bullet("a2", "Shipped FastAPI endpoints.", ["python", "fastapi"]),
                ],
            ),
            Experience(
                company="Beta Inc",
                title="Intern",
                location="NYC",
                start="2023",
                end="2023",
                bullets=[
                    _bullet("b1", "Wrote React dashboards.", ["react"]),
                ],
            ),
            Experience(
                company="Gamma LLC",
                title="Support",
                location="",
                start="2022",
                end="2022",
                bullets=[
                    _bullet("c1", "Answered tickets.", ["customer support"]),
                ],
            ),
        ],
    )


class _FakeResponse:
    """Mimic `messages.parse` return value."""

    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    """Pop one reply per `parse` call from a shared queue."""

    def __init__(self, replies: list):
        self._replies = replies
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        """Record kwargs and return the next queued parsed output."""
        self.calls.append(kwargs)
        if not self._replies:
            raise AssertionError("expand fake client has no replies left")
        return _FakeResponse(self._replies.pop(0))


class _FakeClient:
    """Stand-in for any backend's client. Queue is shared across instances."""

    def __init__(self, replies: list, recorder: list):
        self.messages = _FakeMessages(replies)
        recorder.append(self.messages)


@pytest.fixture
def expand_calls(monkeypatch, tmp_path):
    """Stub `llm.client_for` with a shared reply queue; isolate the cache dir."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    config.CACHE_DIR.mkdir()
    config.resolve("claude")

    replies: list = []
    recorders: list = []

    def client_for(purpose: str):
        """Return a fake whose messages share the same reply list."""
        assert purpose == "expand"
        client = _FakeClient(replies, recorders)
        return client

    monkeypatch.setattr(llm, "client_for", client_for)

    def queue(*parsed):
        """Enqueue model replies and return the list of FakeMessages recorders."""
        replies.extend(parsed)
        return recorders

    yield queue
    config.resolve("claude")


def test_choose_entries_force_includes_resume_roles():
    """An entry on the tailored resume is kept even when ranking would drop it."""
    resume = _tiny_resume()
    reqs = _reqs("python")
    # Only Gamma is on the "resume" (irrelevant). With limit 2, Alpha fills the rest.
    chosen = choose_entries(
        resume, reqs, resume_bullet_ids={"c1"}, semantic=None, limit=2
    )
    companies = [e.company for e in chosen]
    assert "Gamma LLC" in companies
    assert "Alpha Co" in companies
    assert "Beta Inc" not in companies


def test_choose_entries_preserves_master_order():
    """Paste order follows the master resume, not score order."""
    resume = _tiny_resume()
    reqs = _reqs("python", "react")
    chosen = choose_entries(resume, reqs, limit=2)
    assert [e.company for e in chosen] == ["Alpha Co", "Beta Inc"]


def test_hard_facts_come_from_master_not_model(expand_calls, tmp_path):
    """A model that invents a company name still yields the master resume's facts."""
    resume = _tiny_resume()
    reqs = _reqs("python")
    fit = FitResult(
        out_path=tmp_path / "o.docx",
        pages=1,
        pages_are_estimated=True,
        iterations=1,
        bullets_selected=1,
        bullets_total=3,
        bullets={"a1": "Built a Python API serving 1,000 users."},
    )
    expand_calls(
        ExpansionLLMResult(
            entries=[
                ExpandedEntryLLM(
                    entry_key="exp:0",
                    bullets=[
                        "Built a Python API serving 1,000 users across production.",
                        "Shipped FastAPI endpoints for internal tooling.",
                    ],
                )
            ]
        )
    )
    result = expand_experience(resume, reqs, fit_result=fit, use_cache=False)
    assert result.entries
    entry = next(e for e in result.entries if e.entry_key == "exp:0")
    assert entry.company == "Alpha Co"
    assert entry.title == "Engineer"
    assert entry.location == "Remote"
    assert entry.start == "2024"
    assert entry.end == "Present"
    assert entry.on_resume is True


def test_fabricated_bullet_is_dropped_not_raised(expand_calls, tmp_path):
    """An unsupported tool drops one bullet; the expansion still succeeds."""
    resume = _tiny_resume()
    reqs = _reqs("python")
    expand_calls(
        ExpansionLLMResult(
            entries=[
                ExpandedEntryLLM(
                    entry_key="exp:0",
                    bullets=[
                        "Built a Python API serving 1,000 users.",
                        "Migrated the stack to Kubernetes and Terraform.",
                    ],
                )
            ]
        )
    )
    result = expand_experience(resume, reqs, use_cache=False)
    entry = next(e for e in result.entries if e.entry_key == "exp:0")
    assert len(entry.bullets) == 1
    assert "Kubernetes" not in " ".join(entry.bullets)
    assert any("unsupported" in w.lower() or "Kubernetes" in w for w in entry.warnings)


def test_missing_source_number_warns(expand_calls, tmp_path):
    """Dropping a source metric produces a warning, not a hard failure."""
    resume = _tiny_resume()
    reqs = _reqs("python")
    expand_calls(
        ExpansionLLMResult(
            entries=[
                ExpandedEntryLLM(
                    entry_key="exp:0",
                    bullets=["Built a Python API for production traffic."],
                )
            ]
        )
    )
    result = expand_experience(resume, reqs, use_cache=False)
    entry = next(e for e in result.entries if e.entry_key == "exp:0")
    assert any("number" in w.lower() for w in entry.warnings)


def test_cache_key_changes_with_backend(expand_calls, tmp_path, monkeypatch):
    """Switching expand backends must not reuse the other model's cached output."""
    resume = _tiny_resume()
    reqs = _reqs("python")
    reply = ExpansionLLMResult(
        entries=[
            ExpandedEntryLLM(
                entry_key="exp:0",
                bullets=["Built a Python API serving 1,000 users."],
            )
        ]
    )
    expand_calls(reply)
    config.resolve("claude")
    first = expand_experience(resume, reqs, use_cache=True)
    assert first.entries

    # Second call with the same backend should hit cache (no reply queued).
    second = expand_experience(resume, reqs, use_cache=True)
    assert second.entries[0].bullets == first.entries[0].bullets

    # Different fingerprint → cache miss → needs a new reply.
    config.resolve("ollama")
    with pytest.raises(AssertionError, match="no replies"):
        expand_experience(resume, reqs, use_cache=True)


def test_accept_bullets_strips_leading_glyphs():
    """Models that prepend • or - still produce clean paste text."""
    entry = _tiny_resume().experience[0]
    kept, _ = _accept_bullets(
        entry,
        ["• Built a Python API serving 1,000 users.", "- Shipped FastAPI endpoints."],
        char_limit=2000,
    )
    assert kept[0].startswith("Built")
    assert kept[1].startswith("Shipped")


def test_format_markdown_includes_hard_facts():
    """The copy-all markdown carries title/company/dates for form fields."""
    from resume_tailor.expand import ExpandedEntry, Expansion

    expansion = Expansion(
        entries=[
            ExpandedEntry(
                entry_key="exp:0",
                title="Engineer",
                company="Alpha Co",
                location="Remote",
                start="2024",
                end="Present",
                bullets=["Built things."],
                char_count=13,
                on_resume=True,
            )
        ],
        model="openai:gemma4:cloud",
        char_limit=2000,
    )
    text = format_markdown(expansion)
    assert "Engineer · Alpha Co" in text
    assert "Built things." in text


def test_hybrid_routes_expand_to_ollama():
    """Hybrid keeps rewrite on Claude and sends expand to the free backend."""
    try:
        backends = config.resolve("hybrid")
        assert backends["rewrite"].provider == "anthropic"
        assert backends["expand"].provider == "openai"
    finally:
        config.resolve("claude")
