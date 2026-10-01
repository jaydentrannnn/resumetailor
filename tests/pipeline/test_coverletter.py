"""Tests for the opt-in cover letter stage.

No network: LLM calls are stubbed at ``llm.client_for`` with a shared reply queue,
matching the house convention in ``tests/pipeline/test_expand.py``.
"""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.content import style
from resume_tailor.content.data import Bullet, Contact, Experience, ExperienceSection, MasterResume
from resume_tailor.infra import llm
from resume_tailor.pipeline import coverletter
from resume_tailor.pipeline.coverletter import (
    CoverLetterLLM,
    _accept_letter,
    _cache_path,
    _claim_fabrication_offenders,
    _validate_posting_fields,
    ai_tells,
    consecutive_first_person,
    draft_letter,
)
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from tests.fixtures import synthetic_resume


def _reqs() -> JobRequirements:
    """Minimal requirements for cover-letter tests."""
    return JobRequirements(
        title="ML Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def _bullets(resume: MasterResume) -> dict[str, str]:
    """Map every bullet id to its master text."""
    return {b.id: b.text for b in resume.all_bullets()}


def _words(n: int) -> str:
    """Build a sentence with exactly ``n`` words (no embedded digits)."""
    pool = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]
    return " ".join(pool[i % len(pool)] for i in range(n))


def _paragraphs(word_counts: list[int]) -> list[str]:
    """Build body paragraphs with the given per-paragraph word counts."""
    return [_words(n) for n in word_counts]


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
            raise AssertionError("cover fake client has no replies left")
        return _FakeResponse(self._replies.pop(0))


class _FakeClient:
    """Stand-in for any backend's client. Queue and call log are shared."""

    def __init__(self, replies: list, calls: list[dict]):
        self.messages = _FakeMessages(replies, calls)


@pytest.fixture
def cover_calls(monkeypatch, tmp_path):
    """Stub ``llm.client_for`` with a shared reply queue; isolate cache and word band."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    config.CACHE_DIR.mkdir()
    monkeypatch.setattr(config, "COVER_WORD_BAND", (10, 80))
    config.resolve("claude")
    style.activate(cover=None)

    replies: list = []
    calls: list[dict] = []

    def client_for(purpose: str):
        """Return a fake that appends every ``parse`` call to one shared list."""
        assert purpose == "cover"
        return _FakeClient(replies, calls)

    monkeypatch.setattr(llm, "client_for", client_for)

    def queue(*parsed):
        """Enqueue model replies and return the shared call list."""
        replies.extend(parsed)
        return calls

    yield queue
    config.resolve("claude")
    style.activate(cover=None)


def test_ai_tells_flags_em_dash_and_blocklisted_phrase():
    """Long dashes and curated AI phrases are surfaced as offenders."""
    text = "I am passionate about Python\u2014it is my strength."
    offenders = ai_tells(text)
    assert any("long dash" in o for o in offenders)
    assert any("passionate about" in o for o in offenders)


def test_consecutive_first_person_detects_back_to_back_openers():
    """Two sentences in a row that both start with I are flagged."""
    paras = ["I built APIs. I shipped features quickly."]
    assert consecutive_first_person(paras)


def test_validate_posting_fields_blanks_company_not_in_jd():
    """Company names must appear verbatim in the posting or are omitted."""
    llm_result = CoverLetterLLM(company="Acme Corp", company_location="Boston, MA")
    jd = "We are hiring at Example Corp in Boston, MA."
    company, location, _addressee, warnings = _validate_posting_fields(llm_result, jd)
    assert company == ""
    assert location == "Boston, MA"
    assert any("Company" in w for w in warnings)


def test_accept_letter_rejects_invented_numbers():
    """Numbers absent from bullets and the posting are hard offenders."""
    resume = synthetic_resume()
    source = coverletter._source_bullets(resume, _bullets(resume))
    llm_result = CoverLetterLLM(
        paragraphs=[
            "I built Python services and improved latency by 9999 users in production."
        ]
    )
    accepted = _accept_letter(
        llm_result,
        source_bullets=source,
        jd_text="Python engineer role at Example Corp.",
        word_band=(5, 80),
    )
    assert any(o == "9999" or "9999" in o for o in accepted.hard_offenders)


def test_draft_letter_retries_after_em_dash(cover_calls):
    """A first draft with an em dash triggers one targeted retry."""
    resume = synthetic_resume()
    reqs = _reqs()
    jd = "Example Corp seeks a Python ML Engineer in Irvine, CA."
    bullets = _bullets(resume)
    calls = cover_calls(
        CoverLetterLLM(
            company="Example Corp",
            company_location="Irvine, CA",
            paragraphs=[_words(12) + "\u2014" + _words(8)],
        ),
        CoverLetterLLM(
            company="Example Corp",
            company_location="Irvine, CA",
            paragraphs=_paragraphs([20, 20, 15]),
        ),
    )
    letter = draft_letter(resume, reqs, bullets, jd, use_cache=False)
    assert len(calls) == 2
    assert "\u2014" not in "\n".join(letter.paragraphs)
    assert letter.company == "Example Corp"


def test_draft_letter_word_band_enforced(cover_calls):
    """Drafts outside the configured word band are retried once, then warned."""
    resume = synthetic_resume()
    reqs = _reqs()
    jd = "Python role."
    bullets = _bullets(resume)
    cover_calls(
        CoverLetterLLM(paragraphs=["Too short."]),
        CoverLetterLLM(paragraphs=["Still too short."]),
    )
    letter = draft_letter(resume, reqs, bullets, jd, use_cache=False)
    assert any("word count" in w for w in letter.warnings)


def test_cache_key_changes_when_cover_style_changes(cover_calls):
    """``style.digest('cover')`` is folded into the cache path."""
    resume = synthetic_resume()
    reqs = _reqs()
    bullets = _bullets(resume)
    jd = "Python role at Example Corp."
    style.activate(cover=None)
    path_default = _cache_path(
        bullets, reqs, jd_text=jd, word_band=config.COVER_WORD_BAND
    )
    style.activate(cover="Use shorter sentences.")
    path_override = _cache_path(
        bullets, reqs, jd_text=jd, word_band=config.COVER_WORD_BAND
    )
    assert path_default != path_override


def _resume_with_company(company: str) -> MasterResume:
    """Return ``synthetic_resume()`` with its experience company renamed."""
    resume = synthetic_resume()
    sections = []
    for section in resume.sections:
        if section.kind == "experience":
            entries = [entry.model_copy(update={"company": company}) for entry in section.entries]
            sections.append(section.model_copy(update={"entries": entries}))
        else:
            sections.append(section)
    return resume.model_copy(update={"sections": sections})


def test_employer_name_allowed_from_resume_context():
    """Employer names on entry headers are licensed for first-person claim sentences."""
    resume = _resume_with_company("Age of Learning Inc.")
    source = coverletter._source_bullets(resume, _bullets(resume))
    offenders = _claim_fabrication_offenders(
        ["I contributed at Age of Learning Inc. on production Python services."],
        source,
    )
    assert "Age" not in offenders
    assert "Learning" not in offenders
    assert "Inc" not in offenders


def test_invented_tool_still_rejected():
    """Technologies absent from bullets and resume headers remain fabrication offenders."""
    resume = synthetic_resume()
    source = coverletter._source_bullets(resume, _bullets(resume))
    offenders = _claim_fabrication_offenders(
        ["I built Kubernetes clusters for production workloads."],
        source,
    )
    assert any(term.lower() == "kubernetes" for term in offenders)


def test_check_claims_flags_resume_voice_invention():
    """Resume-voice sentences (no 'I') are checked — the gap the cover-letter filter leaves."""
    resume = synthetic_resume()
    result = coverletter.check_claims(
        resume,
        _bullets(resume),
        jd_text="Software Engineer role requiring Python.",
        text="Led a team of three engineers on a Kubernetes migration.",
    )
    assert result.ok is False
    assert any(term.lower() == "kubernetes" for term in result.unsupported_terms)


def test_check_claims_flags_first_person_invention():
    """First-person claim sentences are still flagged under check_claims."""
    resume = synthetic_resume()
    result = coverletter.check_claims(
        resume,
        _bullets(resume),
        jd_text="Software Engineer role requiring Python.",
        text="I built Kubernetes clusters for production workloads.",
    )
    assert result.ok is False
    assert any(term.lower() == "kubernetes" for term in result.unsupported_terms)


def test_check_claims_flags_invented_percentage():
    """A percentage absent from bullets and JD lands in unsupported_numbers."""
    resume = synthetic_resume()
    result = coverletter.check_claims(
        resume,
        _bullets(resume),
        jd_text="Software Engineer role requiring Python.",
        text="Improved reliability of production services by 47%.",
    )
    assert result.ok is False
    assert any("47" in n for n in result.unsupported_numbers)


def test_check_claims_allows_number_from_jd():
    """A number present only in the JD is allowed (same rule as cover-letter numbers)."""
    resume = synthetic_resume()
    result = coverletter.check_claims(
        resume,
        _bullets(resume),
        jd_text="We process 10,000 requests per second with Python.",
        text="Improved reliability for production services handling 10,000 requests.",
    )
    assert result.unsupported_numbers == []
    # "requests" / "handling" may or may not be in source; focus on the number rule.
    assert "10,000" not in result.unsupported_numbers
    assert "10000" not in {n.replace(",", "") for n in result.unsupported_numbers}


def test_angles_reach_the_prompt(cover_calls):
    """CoverAngles appear in a distinct <angles> block, not <extra_instruction>."""
    resume = synthetic_resume()
    reqs = _reqs()
    bullets = _bullets(resume)
    jd = "Python role at Example Corp in Austin."
    calls = cover_calls(
        CoverLetterLLM(
            company="Example Corp",
            company_location="Austin",
            paragraphs=[
                "I built Python services at Example Corp scale for ranking systems.",
                "The Austin team needs retrieval depth I already shipped.",
                "I would welcome a conversation about the Python role.",
            ],
        )
    )
    draft_letter(
        resume,
        reqs,
        bullets,
        jd,
        use_cache=False,
        angles=coverletter.CoverAngles(
            why_company="Their retrieval work",
            problem="Latency at scale",
            approach="Measure first",
            tone="direct",
        ),
    )
    content = calls[0]["messages"][0]["content"]
    assert "<angles>" in content
    assert "Their retrieval work" in content
    assert "<extra_instruction>" not in content


def test_cache_key_changes_with_each_angle_field():
    """Changing any angle field must invalidate the cover cache."""
    resume = synthetic_resume()
    reqs = _reqs()
    bullets = _bullets(resume)
    jd = "Python role."
    base = _cache_path(bullets, reqs, jd_text=jd, word_band=config.COVER_WORD_BAND)
    for field, value in (
        ("why_company", "why"),
        ("problem", "prob"),
        ("approach", "app"),
        ("tone", "direct"),
    ):
        other = _cache_path(
            bullets,
            reqs,
            jd_text=jd,
            word_band=config.COVER_WORD_BAND,
            angles=coverletter.CoverAngles(**{field: value}),
        )
        assert other != base, field


def test_angles_do_not_disable_caching_or_guard_retry(cover_calls, tmp_path, monkeypatch):
    """Unlike instruction, angles keep cache writes and the hard-offender retry."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    resume = synthetic_resume()
    reqs = _reqs()
    bullets = _bullets(resume)
    jd = "Python role at Example Corp requiring semantic search."
    # First reply: em dash (hard) — forces retry. Second: clean.
    bad = CoverLetterLLM(
        company="Example Corp",
        paragraphs=[
            "I built Python services \u2014 and semantic search systems at Example Corp.",
            "Their semantic search needs match work I already shipped.",
            "I would welcome a conversation about the Python role.",
        ],
    )
    good = CoverLetterLLM(
        company="Example Corp",
        paragraphs=[
            "I built Python services and semantic search systems at Example Corp.",
            "Their semantic search needs match work I already shipped.",
            "I would welcome a conversation about the Python role.",
        ],
    )
    calls = cover_calls(bad, good)
    angles = coverletter.CoverAngles(why_company="retrieval focus")
    letter = draft_letter(
        resume, reqs, bullets, jd, use_cache=True, angles=angles
    )
    assert len(calls) == 2, "angles must not skip the guard retry"
    cache = _cache_path(
        bullets, reqs, jd_text=jd, word_band=config.COVER_WORD_BAND, angles=angles
    )
    assert cache.exists(), "angles must not skip the cache write"
    assert letter.paragraphs == good.paragraphs


def test_genericness_warns_without_raising():
    """A letter naming neither company nor JD phrase is a soft AI-tell warning."""
    resume = synthetic_resume()
    llm_result = CoverLetterLLM(
        company="",
        paragraphs=[
            "I am a strong candidate for this opportunity.",
            "My background prepares me well for challenging work.",
            "I look forward to discussing next steps.",
        ],
    )
    accepted = _accept_letter(
        llm_result,
        source_bullets=coverletter._source_bullets(resume, _bullets(resume)),
        jd_text="Python FastAPI RAG engineer at Acme.",
        word_band=(1, 500),
    )
    assert any(o.startswith("generic:") for o in accepted.soft_offenders)
    assert not any(o.startswith("generic:") for o in accepted.hard_offenders)
