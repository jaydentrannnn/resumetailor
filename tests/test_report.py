"""Tests for the run summary.

`format_report` is pure formatting over already-computed results, so these run without
Word, without the API, and without rendering anything.
"""

from __future__ import annotations

from pathlib import Path

from resume_tailor import facets, report
from resume_tailor.data import (
    Bullet,
    Contact,
    Education,
    Experience,
    MasterResume,
    Project,
    SkillGroup,
    load,
)
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


def test_export_filename_uses_name_and_title():
    """Downloads and CLI defaults share '<name> Resume - <title>'."""
    assert (
        report.export_filename("Vu Tuong Huan Tran", "Software Engineer Intern")
        == "Vu Tuong Huan Tran Resume - Software Engineer Intern.docx"
    )
    assert (
        report.export_filename("Ada Lovelace", "SWE / Intern", suffix=".pdf")
        == "Ada Lovelace Resume - SWE Intern.pdf"
    )


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


def _synthetic_resume(
    *,
    bullet_tags: tuple[str, ...] = ("python",),
    project_tech: tuple[str, ...] = (),
    skill_items: tuple[str, ...] = (),
    coursework: tuple[str, ...] = (),
) -> MasterResume:
    """Minimal resume for gap-diagnosis tests, so they don't drift with real data."""
    return MasterResume(
        contact=Contact(name="X", email="x@y.z"),
        education=(
            [Education(school="U", degree="BS", dates="2020", coursework=list(coursework))]
            if coursework
            else []
        ),
        experience=[
            Experience(
                company="Acme",
                title="Engineer",
                start="2020",
                end="2021",
                bullets=[Bullet(id="b1", text="Did a thing.", tags=list(bullet_tags))],
            )
        ],
        projects=(
            [Project(id="proj_x", name="X", tech=list(project_tech))] if project_tech else []
        ),
        skills=[SkillGroup(label="Tools", items=list(skill_items))] if skill_items else [],
    )


def test_gap_reports_no_evidence_when_nothing_matches():
    resume = _synthetic_resume(bullet_tags=("python",))
    reqs = _requirements(("tensorflow", "must_have"))

    gaps = report.diagnose_gaps(reqs, resume)

    assert len(gaps) == 1
    assert gaps[0].reason == "no_evidence"
    assert gaps[0].evidence == []


def test_gap_reports_untagged_evidence_from_project_tech():
    """Real but untagged: PyTorch lives in the project's tech array, on no bullet tag."""
    resume = _synthetic_resume(bullet_tags=("python",), project_tech=("PyTorch",))
    reqs = JobRequirements(
        title="T",
        seniority="entry",
        keywords=[Keyword(phrase="PyTorch", canonical="pytorch", importance="must_have")],
    )

    gaps = report.diagnose_gaps(reqs, resume)

    assert len(gaps) == 1
    assert gaps[0].reason == "untagged_evidence"
    assert "proj_x" in gaps[0].evidence[0]
    assert "PyTorch" in gaps[0].evidence[0]


def test_gap_reports_untagged_evidence_from_skills_and_coursework():
    resume = _synthetic_resume(
        bullet_tags=("python",),
        skill_items=("Elasticsearch",),
        coursework=("Distributed Systems",),
    )
    reqs = JobRequirements(
        title="T",
        seniority="entry",
        keywords=[
            Keyword(phrase="Elasticsearch", canonical="elasticsearch", importance="must_have"),
            Keyword(
                phrase="Distributed Systems",
                canonical="distributed systems",
                importance="must_have",
            ),
        ],
    )

    gaps = {g.canonical: g for g in report.diagnose_gaps(reqs, resume)}

    assert gaps["elasticsearch"].reason == "untagged_evidence"
    assert "Tools" in gaps["elasticsearch"].evidence[0]
    assert gaps["distributed systems"].reason == "untagged_evidence"
    assert "coursework" in gaps["distributed systems"].evidence[0]


def test_gap_reports_near_miss_for_a_differently_spelled_tag():
    """`grpo` is not a `TAG_ALIASES` entry, so this only matches via `diagnose_gaps`'s
    reuse of `labels_are_equivalent`'s acronym-expansion branch — a genuine near-miss
    that canonicalisation alone does not already resolve (unlike e.g. "postgres", which
    `TAG_ALIASES` collapses onto "postgresql" before `diagnose_gaps` ever runs)."""
    resume = _synthetic_resume(bullet_tags=("grpo",))
    reqs = JobRequirements(
        title="T",
        seniority="entry",
        keywords=[
            Keyword(
                phrase="Group Relative Policy Optimization",
                canonical="group relative policy optimization",
                importance="must_have",
            )
        ],
    )

    gaps = report.diagnose_gaps(reqs, resume)

    assert len(gaps) == 1
    assert gaps[0].reason == "near_miss"
    assert "grpo" in gaps[0].evidence[0]


def test_tech_only_evidence_still_counts_as_a_miss():
    """`Project.tech` must never feed scoring/coverage — only `diagnose_gaps`.

    Pins the deliberate split in `report.diagnose_gaps`'s docstring: `tech` is
    per-*project* while `keyword_coverage` scores per-*bullet*, and folding it in would
    let one tech label inflate every bullet in that project's score.
    """
    resume = _synthetic_resume(bullet_tags=("python",), project_tech=("PyTorch",))
    reqs = JobRequirements(
        title="T",
        seniority="entry",
        keywords=[Keyword(phrase="PyTorch", canonical="pytorch", importance="must_have")],
    )

    assert report.keyword_coverage(reqs, resume) == (0, 1)
    assert report.missing_must_haves(reqs, resume) == ["PyTorch"]


def test_diagnosis_reads_the_unfaceted_master():
    """Regression for the facets-truncation trap.

    `facets.apply` trims `Project.tech` to its ≤4-label render budget, so a resume already
    run through facets can be missing the exact evidence `diagnose_gaps` looks for.
    `report_data`/`format_report`'s `master=` parameter exists so the *pre*-facets resume
    is what gets diagnosed.
    """
    resume = _synthetic_resume(
        bullet_tags=("python",),
        project_tech=("Alpha", "Bravo", "Charlie", "Delta", "PyTorch"),
    )
    reqs = JobRequirements(
        title="T",
        seniority="entry",
        keywords=[Keyword(phrase="PyTorch", canonical="pytorch", importance="must_have")],
    )
    facet_result = facets.budget_only(resume, reqs, include_project_links=True)
    faceted = facets.apply(resume, facet_result)
    # The trap: PyTorch was 5th of 5 and MAX_PROJECT_TECH truncates to 4, so it is gone
    # from the faceted resume — diagnosing that copy would wrongly say `no_evidence`.
    assert "PyTorch" not in faceted.projects[0].tech

    gaps_on_faceted = report.diagnose_gaps(reqs, faceted)
    assert gaps_on_faceted[0].reason == "no_evidence"  # wrong, and what `master=` avoids

    gaps_on_master = report.diagnose_gaps(reqs, resume)
    assert gaps_on_master[0].reason == "untagged_evidence"

    result = _result(resume, {"b1": "Did a thing."})
    text = report.format_report(faceted, reqs, result, master=resume)
    assert "Evidence exists but no bullet is tagged for it:" in text
    assert "PyTorch" in text
    assert "No evidence in the master resume" not in text


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
