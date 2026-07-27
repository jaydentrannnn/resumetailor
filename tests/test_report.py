"""Tests for the run summary.

`format_report` is pure formatting over already-computed results, so these run without
Word, without the API, and without rendering anything.
"""

from __future__ import annotations

from pathlib import Path

from resume_tailor import report
from resume_tailor.data import load
from resume_tailor.fit import FitResult
from resume_tailor.jd import JobRequirements, Keyword


def _requirements(*pairs: tuple[str, str]) -> JobRequirements:
    return JobRequirements(
        title="ML Engineer",
        seniority="entry",
        keywords=[
            Keyword(phrase=c, canonical=c, importance=i)  # type: ignore[arg-type]
            for c, i in pairs
        ],
    )


def _result(resume, bullets: dict[str, str], **kw) -> FitResult:
    defaults = dict(
        out_path=Path("output/tailored.docx"),
        pages=1,
        pages_are_estimated=False,
        iterations=1,
        bullets_selected=len(bullets),
        bullets_total=len(resume.all_bullets()),
        bullets=bullets,
    )
    return FitResult(**{**defaults, **kw})


def test_report_shows_coverage_and_output_path():
    resume = load()
    reqs = _requirements(("python", "must_have"), ("rust", "must_have"))
    first = resume.experience[0]
    result = _result(resume, {b.id: b.text for b in first.bullets})

    text = report.format_report(resume, reqs, result)

    assert "1/2" in text  # python is covered, rust is not
    assert "output" in text and "tailored.docx" in text
    assert "1 page(s)" in text


def test_report_names_unsupported_must_haves():
    """A keyword the master resume cannot support is a gap worth stating outright."""
    resume = load()
    reqs = _requirements(("rust", "must_have"))
    result = _result(resume, {b.id: b.text for b in resume.experience[0].bullets})

    text = report.format_report(resume, reqs, result)
    assert "rust" in text.lower()
    assert report.missing_must_haves(reqs, resume) == ["rust"]


def test_report_counts_only_actually_changed_bullets_as_rewritten():
    """The fit loop keeps original text for bullets the model dropped; those aren't rewrites."""
    resume = load()
    reqs = _requirements(("python", "must_have"))
    entry = resume.experience[0]
    bullets = {b.id: b.text for b in entry.bullets}
    bullets[entry.bullets[0].id] = "Reworded first bullet."

    text = report.format_report(resume, reqs, _result(resume, bullets))

    assert f"{entry.company}: {len(entry.bullets)}/{len(entry.bullets)} bullets, 1 rewritten" in text


def test_report_lists_entries_dropped_entirely():
    resume = load()
    reqs = _requirements(("python", "must_have"))
    kept = resume.experience[0]
    result = _result(resume, {b.id: b.text for b in kept.bullets})

    text = report.format_report(resume, reqs, result)

    assert "Dropped entirely:" in text
    assert resume.experience[1].company in text
    assert kept.company in text


def test_report_names_canonicals_that_matched_no_tag():
    """A vocabulary miss is otherwise completely silent — it just scores zero."""
    resume = load()
    reqs = _requirements(("python", "must_have"), ("rust", "nice_to_have"))
    result = _result(resume, {b.id: b.text for b in resume.experience[0].bullets})

    text = report.format_report(resume, reqs, result)

    assert "Matched no tag" in text
    assert "rust" in text
    # Nice-to-haves count here even though they never reach `missing_must_haves`.
    assert report.unmatched_canonicals(reqs, resume) == [("rust", "rust")]


def test_report_omits_the_unmatched_line_when_everything_matched():
    resume = load()
    reqs = _requirements(("python", "must_have"))
    result = _result(resume, {b.id: b.text for b in resume.experience[0].bullets})

    assert "Matched no tag" not in report.format_report(resume, reqs, result)


def test_report_states_which_ranking_was_used():
    """With semantic scoring off, ranking is pure tag overlap — worth saying so."""
    resume = load()
    reqs = _requirements(("python", "must_have"))
    bullets = {b.id: b.text for b in resume.experience[0].bullets}

    keyword_only = report.format_report(resume, reqs, _result(resume, bullets))
    assert "Ranking: keyword overlap only" in keyword_only

    with_semantic = report.format_report(
        resume, reqs, _result(resume, bullets, semantic_used=True)
    )
    assert "semantic relevance" in with_semantic


def test_report_flags_estimated_page_count_and_warnings():
    resume = load()
    reqs = _requirements(("python", "must_have"))
    result = _result(
        resume,
        {b.id: b.text for b in resume.experience[0].bullets},
        pages_are_estimated=True,
        warnings=["PDF measurement unavailable: Word is not installed"],
    )

    text = report.format_report(resume, reqs, result)

    assert "estimated" in text
    assert "WARNING: PDF measurement unavailable" in text


# --------------------------------------------------------------------------------------
# Line waste
#
# Reported on its own line because a wasted line is invisible in a page count: a resume can
# hit its page target while throwing several lines away on bullets that wrapped onto a
# final line holding one word.
# --------------------------------------------------------------------------------------


def test_report_states_line_waste_even_when_there_is_none():
    resume = load()
    reqs = _requirements(("python", "must_have"))
    result = _result(resume, {b.id: b.text for b in resume.experience[0].bullets})

    text = report.format_report(resume, reqs, result)

    assert "Line waste: 0 widowed line(s)" in text


def test_report_credits_the_bullets_the_widow_pass_tightened():
    resume = load()
    reqs = _requirements(("python", "must_have"))
    result = _result(
        resume,
        {b.id: b.text for b in resume.experience[0].bullets},
        widows_repaired=3,
        widows_remaining=0,
    )

    text = report.format_report(resume, reqs, result)

    assert "Line waste: 0 widowed line(s) (3 bullet(s) tightened)" in text


def test_report_shows_a_surviving_widow():
    resume = load()
    reqs = _requirements(("python", "must_have"))
    result = _result(
        resume,
        {b.id: b.text for b in resume.experience[0].bullets},
        widows_repaired=1,
        widows_remaining=2,
    )

    assert "Line waste: 2 widowed line(s)" in report.format_report(resume, reqs, result)
