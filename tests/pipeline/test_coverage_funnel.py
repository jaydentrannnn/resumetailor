"""Must-have coverage from master resume to page (`pipeline/coverage.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.content import bullet_tags
from resume_tailor.content.data import (
    Bullet,
    Contact,
    Education,
    Experience,
    MasterResume,
    Project,
    SkillGroup,
)
from resume_tailor.document import render
from resume_tailor.pipeline import coverage, report
from resume_tailor.pipeline.fit_types import FitResult
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from resume_tailor.web import job_outputs

PY = "Built a Python service for the billing team."
DASH = "Built dashboards for the sales team."
K8S = "Ran the deployment platform for twelve services."


def _resume(*, skills: list[str] | None = None, education=(), title="Engineer") -> MasterResume:
    job = Experience(
        company="ACME", title=title, start="2020-01", end="2021-01",
        bullets=[
            Bullet(id="py", text=PY),
            Bullet(id="dash", text=DASH, tags=["Tableau"]),
            Bullet(id="k8s", text=K8S),
        ],
    )
    proj = Project(
        id="side-proj", name="Side", tech=["Rust"], bullets=[Bullet(id="side", text="Wrote a small tool.")]
    )
    return MasterResume(
        comment=None, contact=Contact(name="T", email="t@example.com", phone=""),
        education=list(education), summary_variants=[], experience=[job], projects=[proj],
        skills=[SkillGroup(label="Tools", items=skills or [])],
    )


def _reqs(*phrases: str) -> JobRequirements:
    return JobRequirements(
        title="Engineer", seniority="entry",
        keywords=[
            Keyword(phrase=p, canonical=bullet_tags.config.canonical_tag(p), importance="must_have")
            for p in phrases
        ],
    )


@pytest.fixture
def inferred_k8s():
    resume = _resume()
    bullet_tags.annotate(resume, {K8S: ["kubernetes"]})
    yield
    bullet_tags.clear()


def _status(f: coverage.CoverageFunnel) -> dict[str, tuple[str | None, str | None]]:
    return {k.phrase: (k.resume, k.page) for k in f.keywords}


def test_each_must_have_ends_where_the_page_leaves_it(inferred_k8s):
    resume = _resume()
    bullets = {"py": PY, "dash": DASH}
    visible = render.visible_text(resume, bullets, layout={})
    f = coverage.funnel(
        _reqs("Python", "Tableau", "Kubernetes", "Go"), resume, resume, bullets, visible
    )
    assert _status(f) == {
        "Python": ("stated", "expressed"),
        "Tableau": ("tagged", "tag_only"),
        "Kubernetes": ("inferred", "not_selected"),
        "Go": (None, None),
    }
    assert (f.total, f.in_resume, f.on_page) == (4, 3, 1)


def test_in_resume_matches_the_existing_figure(inferred_k8s):
    resume = _resume()
    reqs = _reqs("Python", "Tableau", "Kubernetes", "Go")
    f = coverage.funnel(reqs, resume, resume, {"py": PY}, [PY])
    assert f.in_resume == report.keyword_coverage(reqs, resume)[0]


def test_inferred_only_on_page_is_not_counted_as_expressed(inferred_k8s):
    resume = _resume()
    bullets = {"k8s": K8S}
    f = coverage.funnel(_reqs("Kubernetes"), resume, resume, bullets, [K8S])
    assert _status(f) == {"Kubernetes": ("inferred", "inferred_only")}
    assert f.on_page == 0


def test_rendered_skills_and_tech_count_as_expressed():
    resume = _resume(skills=["Tableau"])
    bullets = {"side": "Wrote a small tool."}
    visible = render.visible_text(resume, bullets, layout={})
    assert "Rust" in visible and "Tableau" in visible
    f = coverage.funnel(_reqs("Rust", "Tableau"), resume, resume, bullets, visible)
    assert f.on_page == 2


def test_dropped_entries_and_disabled_sections_are_not_on_the_page():
    resume = _resume(skills=["Tableau"])
    visible = render.visible_text(
        resume, {"py": PY}, layout={"enabled": {"skills": False}}
    )
    assert visible == ["Engineer", PY], (
        "no project bullets left: its name and tech drop too; skills disabled")


def test_headers_count_as_page_text():
    """Job titles, project names, degree lines and skill-group labels are on the page."""
    resume = _resume(skills=["Tableau"], title="Data Engineer", education=[
        Education(school="UCI", degree="B.S. Computer Science", dates="2024")])
    bullets = {"py": PY, "side": "Wrote a small tool."}
    visible = render.visible_text(resume, bullets, layout={})
    assert {"Data Engineer", "Side", "B.S. Computer Science", "Tools"} <= set(visible)
    f = coverage.funnel(_reqs("Data Engineer", "Computer Science"), resume, resume,
                        bullets, visible)
    assert f.on_page == 2


def test_a_bullet_in_a_disabled_section_backs_nothing():
    resume = _resume()
    layout = {"enabled": {"experience": False}}
    bullets = {"dash": DASH}
    assert render.page_bullet_ids(resume, bullets, layout=layout) == set()
    f = coverage.funnel(_reqs("Tableau"), resume, resume, bullets,
                        render.visible_text(resume, bullets, layout=layout),
                        page_ids=render.page_bullet_ids(resume, bullets, layout=layout))
    assert _status(f) == {"Tableau": ("tagged", "not_selected")}
    assert f.unsupported_additions == []


def test_refresh_follows_an_edit_and_keeps_the_resume_side(inferred_k8s):
    resume = _resume()
    reqs = _reqs("Python", "Tableau", "Kubernetes")
    first = coverage.funnel(reqs, resume, resume, {"py": PY, "dash": DASH},
                            render.visible_text(resume, {"py": PY, "dash": DASH}, layout={}))
    assert first.on_page == 1
    saved = coverage.from_dict(coverage.to_dict(first))
    after = coverage.refresh(saved, reqs, resume, {"dash": DASH}, layout={})
    assert after.on_page == 0
    assert _status(after) == {"Python": ("stated", "not_selected"),
                              "Tableau": ("tagged", "tag_only"),
                              "Kubernetes": ("inferred", "not_selected")}


def test_skills_a_rewrite_adds_beyond_its_source_are_listed():
    resume = _resume()
    bullets = {"py": "Built a Python and Docker service for the billing team."}
    f = coverage.funnel(_reqs("Python"), resume, resume, bullets, list(bullets.values()))
    assert f.unsupported_additions == [("py", bullet_tags.config.canonical_tag("docker"))]


def test_a_merged_bullet_is_supported_by_all_its_members():
    resume = _resume()
    bullets = {"py": "Built a Python service and Tableau dashboards for two teams."}
    f = coverage.funnel(
        _reqs("Python"), resume, resume, bullets, list(bullets.values()),
        merges=[("py", ("py", "dash"))],
    )
    assert f.unsupported_additions == []


def test_report_carries_both_numbers_to_the_api():
    resume = _resume()
    result = FitResult(
        out_path=Path("output/tailored.docx"), pages=1, pages_are_estimated=False,
        iterations=1, bullets_selected=1, bullets_total=4, bullets={"dash": DASH},
    )
    data = report.report_data(resume, _reqs("Python", "Tableau"), result)
    assert (data.coverage_matched, data.page_coverage_matched) == (2, 0)
    out = job_outputs._to_report_out(data)
    assert out.page_coverage_matched == 0
    assert [k.page for k in out.coverage_funnel.keywords] == ["not_selected", "tag_only"]
    assert "2/2 (100%) in your resume, 0/2 on this page" in report.format_report(
        resume, _reqs("Python", "Tableau"), result
    )


def _kw(phrase: str, canonical: str, *, kind: str = "technical") -> Keyword:
    return Keyword(phrase=phrase, canonical=canonical, importance="must_have", kind=kind)


def _with(*keywords: Keyword) -> JobRequirements:
    return JobRequirements(title="Engineer", seniority="entry", keywords=list(keywords))


def test_the_canonical_named_on_the_page_counts_as_expressed():
    """The posting said "problem-solving"; the page says "troubleshooting"."""
    resume = _resume()
    text = "Led troubleshooting for the billing service."
    f = coverage.funnel(_with(_kw("problem-solving", "troubleshooting")), resume, resume,
                        {"py": text}, [text])
    assert [k.page for k in f.keywords] == ["expressed"]
    assert f.on_page == 1


def test_a_soft_skill_shown_by_an_on_page_bullet_counts_as_demonstrated():
    """The rewrite never names soft skills, so a backing bullet covers one."""
    job = Experience(company="ACME", title="Engineer", start="2020-01", end="2021-01", bullets=[
        Bullet(id="talk", text="Presented weekly results to the sales team.",
               tags=["communication"]),
        Bullet(id="lead", text="Ran a three-person pod.", tags=["leadership"]),
    ])
    resume = MasterResume(
        comment=None, contact=Contact(name="T", email="t@example.com", phone=""),
        education=[], summary_variants=[], experience=[job], projects=[], skills=[],
    )
    bullets = {"talk": job.bullets[0].text, "lead": job.bullets[1].text}
    reqs = _with(_kw("communication", "communication", kind="soft"),
                 _kw("teamwork", "teamwork", kind="soft"),
                 _kw("Tableau", "tableau"))
    f = coverage.funnel(reqs, resume, resume, bullets, list(bullets.values()))
    assert {k.canonical: k.page for k in f.keywords} == {
        "communication": "demonstrated",  # its own Extra skill
        "teamwork": "demonstrated",  # `leadership` is a related tag
        "tableau": None,
    }
    assert f.on_page == 2


def test_a_skill_the_posting_names_twice_counts_once_at_its_best():
    resume = _resume()
    text = "Wrote technical documentation for the billing service."
    reqs = _with(_kw("communication", "communication"),
                 _kw("technical documentation", "communication"), _kw("Python", "python"))
    f = coverage.funnel(reqs, resume, resume, {"py": text}, [text])
    assert [(k.phrase, k.page) for k in f.keywords] == [
        ("technical documentation", "expressed"), ("Python", "tag_only")]
    assert (f.total, f.on_page) == (2, 1)
    assert report.keyword_coverage(reqs, resume) == (1, 2)


def test_named_in_your_resume_leaves_out_extra_skill_only_support(inferred_k8s):
    resume = _resume()
    f = coverage.funnel(_reqs("Python", "Tableau", "Kubernetes"), resume, resume,
                        {"py": PY}, [PY])
    assert {k.phrase: k.resume for k in f.keywords} == {
        "Python": "stated", "Tableau": "tagged", "Kubernetes": "inferred"}
    assert (f.in_resume, f.in_resume_text) == (3, 1)


def test_an_older_saved_funnel_loads_and_refreshes_without_the_named_figure():
    resume = _resume()
    old = {"total": 1, "in_resume": 1, "on_page": 0, "unsupported_additions": [],
           "keywords": [{"canonical": "tableau", "phrase": "Tableau", "resume": "stated",
                         "page": "tag_only"}]}
    saved = coverage.from_dict(old)
    assert saved.in_resume_text is None
    after = coverage.refresh(saved, _reqs("Tableau"), resume, {"dash": DASH}, layout={})
    assert after.in_resume_text is None
    assert [k.page for k in after.keywords] == ["tag_only"]


def test_coverage_reads_the_skill_a_phrase_claims_not_a_broader_one():
    """Extraction filed "TensorFlow" under `python`, which the resume has. Selection may
    keep that; the report must not say the resume has TensorFlow."""
    resume = _resume()
    reqs = _with(_kw("TensorFlow", "python"), _kw("Python", "python"))
    claimed = reqs.as_claimed()
    assert [k.canonical for k in claimed.keywords] == ["tensorflow", "python"]
    assert [k.canonical for k in reqs.keywords] == ["python", "python"], "a copy"
    result = FitResult(
        out_path=Path("output/tailored.docx"), pages=1, pages_are_estimated=False,
        iterations=1, bullets_selected=1, bullets_total=4, bullets={"py": PY},
    )
    data = report.report_data(resume, reqs, result)
    assert (data.coverage_matched, data.coverage_total) == (1, 2)
    assert data.missing_must_haves == ["TensorFlow"]


def test_a_phrase_that_is_more_than_one_skill_name_keeps_its_canonical():
    reqs = _with(_kw("GitHub Copilot", "github copilot"), _kw("Python", "python"),
                 _kw("hands-on TensorFlow work", "deep learning"))
    assert [k.canonical for k in reqs.as_claimed().keywords] == [
        "github copilot", "python", "deep learning"]
