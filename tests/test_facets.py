"""Facet selection — budgets, rename guard, apply — no network, no Word."""

from __future__ import annotations

from resume_tailor import config, facets
from resume_tailor.data import Education, MasterResume, Project, load
from resume_tailor.facets import (
    FacetResult,
    FacetSelection,
    ProjectTech,
    apply,
    budget_only,
    finalise_selection,
    fit_coursework_to_budget,
    fit_tech_to_budget,
    labels_are_equivalent,
    project_header_tech_budget,
    rename_is_jd_anchored,
    select_facets,
)
from resume_tailor.jd import JobRequirements, Keyword


def _requirements(*phrases: tuple[str, str]) -> JobRequirements:
    """Build a minimal JobRequirements from (phrase, canonical) pairs."""
    return JobRequirements(
        title="Engineer",
        seniority="mid",
        keywords=[
            Keyword(phrase=p, canonical=c, importance="must_have", kind="technical")
            for p, c in phrases
        ],
    )


def _project(**kwargs) -> Project:
    """Minimal project with defaults for budget tests."""
    base = dict(
        id="proj_x",
        name="Demo Project",
        tech=["Python", "FastAPI", "Docker", "React", "PostgreSQL"],
        date="Jan 2026",
        link="Github",
        url="https://example.com",
        bullets=[],
    )
    base.update(kwargs)
    return Project(**base)


def test_fit_tech_respects_tag_cap():
    """More than MAX_PROJECT_TECH never survives even with a huge budget."""
    tags = [f"Tag{i}" for i in range(10)]
    kept = fit_tech_to_budget(tags, budget=10_000)
    assert len(kept) == config.MAX_PROJECT_TECH
    assert kept == tags[: config.MAX_PROJECT_TECH]


def test_fit_tech_respects_character_budget():
    """A tag that would push past the budget is dropped; earlier tags stay."""
    kept = fit_tech_to_budget(
        ["Python", "FastAPI", "Docker"],
        budget=len("Python, FastAPI"),
    )
    assert kept == ["Python", "FastAPI"]


def test_fit_tech_honours_include_project_links():
    """Suppressing the link widens the header budget so more tags can fit."""
    proj = _project(
        name="A" * 40,
        tech=["Alpha", "Bravo", "Charlie", "Delta"],
        date="Jan 2026 - Mar 2026",
        link="Github",
    )
    with_link = project_header_tech_budget(proj, include_project_links=True)
    without = project_header_tech_budget(proj, include_project_links=False)
    assert without > with_link
    assert len(fit_tech_to_budget(proj.tech, without)) >= len(
        fit_tech_to_budget(proj.tech, with_link)
    )


def test_rename_accepts_postgres_to_postgresql():
    """Prefix equivalence plus a JD phrase licenses the rename."""
    reqs = _requirements(("PostgreSQL", "postgresql"))
    assert labels_are_equivalent("Postgres", "PostgreSQL")
    assert rename_is_jd_anchored("PostgreSQL", reqs)


def test_rename_accepts_grpo_acronym():
    """Acronym expansion works in either direction."""
    assert labels_are_equivalent("GRPO", "Group Relative Policy Optimization")
    assert labels_are_equivalent("Group Relative Policy Optimization", "GRPO")


def test_rename_rejects_sql_to_snowflake():
    """A more specific product is not equivalent to a generic pool label."""
    assert not labels_are_equivalent("SQL", "Snowflake")


def test_rename_rejects_sql_to_mysql():
    """Suffix containment must not license claiming MySQL from SQL."""
    assert not labels_are_equivalent("SQL", "MySQL")
    from resume_tailor.facets import _alnum_compact

    # sql is only a suffix of mysql — prefix rule correctly rejects both directions.
    assert not _alnum_compact("mysql").startswith(_alnum_compact("sql"))
    assert not _alnum_compact("sql").startswith(_alnum_compact("mysql"))


def test_finalise_drops_out_of_pool_tags():
    """Tags the model invents are discarded with a warning."""
    resume = MasterResume(
        contact={"name": "X", "email": "x@y.z"},
        education=[],
        experience=[],
        projects=[_project(tech=["Python", "Docker"])],
        skills=[],
    )
    raw = FacetSelection(
        projects=[
            ProjectTech(id="proj_x", tech=["Python", "Kubernetes", "Docker"]),
        ]
    )
    result = finalise_selection(resume, raw, _requirements(("Python", "python")))
    assert "Kubernetes" not in result.projects["proj_x"]
    assert any("Kubernetes" in w for w in result.warnings)


def test_finalise_rejects_bad_rename_keeps_original():
    """Failed rename guard keeps the pool label, does not fail the run."""
    resume = MasterResume(
        contact={"name": "X", "email": "x@y.z"},
        education=[],
        experience=[],
        projects=[_project(tech=["SQL"])],
        skills=[],
    )
    raw = FacetSelection(
        projects=[
            ProjectTech(
                id="proj_x",
                tech=["SQL"],
                renamed={"SQL": "Snowflake"},
            )
        ]
    )
    reqs = _requirements(("Snowflake", "snowflake"))
    result = finalise_selection(resume, raw, reqs)
    assert result.projects["proj_x"] == ["SQL"]
    assert any("Snowflake" in w for w in result.warnings)


def test_finalise_accepts_jd_anchored_equivalent_rename():
    """Postgres -> PostgreSQL survives when the JD asks for PostgreSQL."""
    resume = MasterResume(
        contact={"name": "X", "email": "x@y.z"},
        education=[],
        experience=[],
        projects=[_project(tech=["Postgres", "Python"])],
        skills=[],
    )
    raw = FacetSelection(
        projects=[
            ProjectTech(
                id="proj_x",
                tech=["Postgres", "Python"],
                renamed={"Postgres": "PostgreSQL"},
            )
        ]
    )
    reqs = _requirements(("PostgreSQL", "postgresql"), ("Python", "python"))
    result = finalise_selection(resume, raw, reqs)
    assert "PostgreSQL" in result.projects["proj_x"]
    assert "Postgres" not in result.projects["proj_x"]


def test_apply_does_not_mutate_input():
    """apply() deep-copies; the caller's MasterResume is untouched."""
    resume = load()
    original_tech = [list(p.tech) for p in resume.projects]
    original_coursework = [list(e.coursework) for e in resume.education]
    result = budget_only(resume, _requirements(("Python", "python")))
    updated = apply(resume, result)
    assert [list(p.tech) for p in resume.projects] == original_tech
    assert [list(e.coursework) for e in resume.education] == original_coursework
    assert updated is not resume


def test_coursework_fits_two_lines():
    """Joined coursework under the budget spans at most COURSEWORK_MAX_LINES."""
    pool = [
        "Project in Artificial Intelligence",
        "Algorithm Design & Analysis",
        "Machine Learning & Data Mining",
        "Information Retrieval",
        "Linear Algebra",
        "Project in Computer Vision",
        "Distributed Systems",
        "Operating Systems",
        "Compilers",
        "Database Systems",
    ]
    kept = fit_coursework_to_budget(pool)
    line = "Relevant Coursework: " + ", ".join(kept)
    assert config.line_span(line) <= config.COURSEWORK_MAX_LINES


def test_budget_only_truncates_without_llm():
    """--no-facets path still enforces the one-line / two-line guarantees."""
    resume = load()
    result = budget_only(resume, _requirements(("Python", "python")))
    for proj in resume.projects:
        assert len(result.projects[proj.id]) <= config.MAX_PROJECT_TECH
        budget = project_header_tech_budget(proj, include_project_links=True)
        assert len(", ".join(result.projects[proj.id])) <= budget
    if result.coursework:
        line = "Relevant Coursework: " + ", ".join(result.coursework)
        assert config.line_span(line) <= config.COURSEWORK_MAX_LINES


def test_select_facets_uses_fake_client(monkeypatch, tmp_path):
    """Happy path through select_facets with a stubbed llm.client_for."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)

    resume = MasterResume(
        contact={"name": "X", "email": "x@y.z"},
        education=[
            Education(
                school="U",
                degree="BS",
                dates="2020-2024",
                coursework=["Machine Learning", "Linear Algebra", "Compilers"],
            )
        ],
        experience=[],
        projects=[_project(id="proj_a", tech=["Python", "FastAPI", "Docker", "React"])],
        skills=[],
    )
    reqs = _requirements(("Python", "python"), ("FastAPI", "fastapi"))

    class _FakeMessages:
        def parse(self, **kwargs):
            assert kwargs["output_format"] is FacetSelection

            class _Resp:
                parsed_output = FacetSelection(
                    projects=[
                        ProjectTech(id="proj_a", tech=["Python", "FastAPI", "Docker"]),
                    ],
                    coursework=["Machine Learning", "Linear Algebra"],
                )
                stop_reason = "end_turn"

            return _Resp()

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr(facets.llm, "client_for", lambda purpose: _FakeClient())

    result = select_facets(resume, reqs, use_cache=False)
    assert result.projects["proj_a"][:2] == ["Python", "FastAPI"]
    assert "Machine Learning" in result.coursework
    # Cache written for a subsequent hit.
    assert list(tmp_path.glob("*.facets.json"))


def test_apply_writes_coursework_on_first_education_only():
    """Shared coursework selection lands on the first education entry with a pool."""
    resume = MasterResume(
        contact={"name": "X", "email": "x@y.z"},
        education=[
            Education(
                school="A",
                degree="BS",
                dates="2020",
                coursework=["ML", "IR", "LA"],
            ),
            Education(
                school="B",
                degree="MS",
                dates="2024",
                coursework=["Advanced ML"],
            ),
        ],
        experience=[],
        projects=[],
        skills=[],
    )
    result = FacetResult(coursework=["ML", "IR"])
    updated = apply(resume, result)
    assert updated.education[0].coursework == ["ML", "IR"]
    assert updated.education[1].coursework == []
