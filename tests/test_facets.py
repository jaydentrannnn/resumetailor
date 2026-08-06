"""Facet selection — budgets, rename guard, apply — no network, no Word."""

from __future__ import annotations

from resume_tailor import config, facets
from resume_tailor.data import Education, MasterResume, Project, SkillGroup
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
    rename_preserves_claim,
    select_facets,
)
from resume_tailor.jd import JobRequirements, Keyword
from tests.fixtures import synthetic_resume


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


def test_rename_rejects_single_letter_alnum_prefix():
    """A one-character alphanumeric compaction must not license a prefix match.

    `_alnum_compact("C++")` is `"c"` (the `+`s are stripped), so without a length
    floor `"cloudcomputing".startswith("c")` and `"react".startswith("r")` both
    spuriously pass, which would let a posting's "cloud computing environments"
    requirement rename the skills list's "C++" entry — a real, reproduced hole
    reported live against this project's own resume. `rename_preserves_claim` does
    not guard this case (a single claim like "C++" cannot narrow by definition, so
    it is `True` regardless) — the fix has to live in `labels_are_equivalent`, and
    the end-to-end guard below confirms all three predicates reject it together.
    """
    assert not labels_are_equivalent("C++", "cloud computing")


def test_rename_keeps_two_char_alnum_prefix_matches():
    """The length-2 floor must not regress legitimate short-token renames."""
    assert labels_are_equivalent("Go", "Golang")
    assert labels_are_equivalent("CI", "CI/CD")
    assert labels_are_equivalent("Postgres", "PostgreSQL")


def test_aligns_rejects_single_letter_word_prefix():
    """The word-by-word alignment ladder has the same single-letter hole as the
    alphanumeric-prefix branch, in a different function.

    Reproduced live: `report.diagnose_gaps` misreported the Two Sigma posting's
    "Curiosity" requirement as evidenced by this resume's "C++" skill, because
    `_aligns("curiosity", "C++")` treated the lone "c" word as a valid prefix match
    for "curiosity". An exact single-letter match (not exercised here) must stay legal;
    only the *prefix* shortcut needed the floor.
    """
    from resume_tailor.facets import _aligns

    assert not _aligns("curiosity", "C++")
    assert not _aligns("C++", "curiosity")
    assert not _aligns("R", "React")
    assert not labels_are_equivalent("Curiosity", "C++")


def test_skill_rename_rejects_single_letter_alnum_prefix():
    """End-to-end: `_resolve_skill_group` must reject the C++ -> cloud computing hole.

    Reproduces the exact posting that exposed it (Two Sigma "Research Intern": must-have
    "cloud computing environments" -> canonical "cloud computing") against a skills group
    that carries "C++", the way this project's own `Tools & Languages` group does.
    """
    resume = _skills_resume(SkillGroup(label="Tools & Languages", items=["C++"]))
    raw = FacetSelection(skill_renames={"C++": "cloud computing"})
    reqs = _requirements(("cloud computing environments", "cloud computing"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["C++"]]
    assert any("rejected skill rename" in w for w in result.warnings)


def test_rename_accepts_acronym_embedded_in_phrase():
    """An acronym alongside other words expands too, not just a bare acronym label.

    Added for the skills rename feature (word-by-word `_aligns`), but the guard lives
    on the shared `labels_are_equivalent`, so project tech tags benefit as well.
    """
    assert labels_are_equivalent(
        "RAG pipelines", "retrieval-augmented generation pipelines"
    )
    assert labels_are_equivalent(
        "retrieval-augmented generation pipelines", "RAG pipelines"
    )
    # Still rejects when the phrase's other words don't line up at all.
    assert not labels_are_equivalent("RAG pipelines", "relational database systems")


def test_project_rename_accepts_acronym_expansion():
    """Project tech tags can rename an embedded acronym to its spelled-out JD form."""
    resume = MasterResume(
        contact={"name": "X", "email": "x@y.z"},
        education=[],
        experience=[],
        projects=[_project(tech=["RAG pipelines"])],
        skills=[],
    )
    raw = FacetSelection(
        projects=[
            ProjectTech(
                id="proj_x",
                tech=["RAG pipelines"],
                renamed={"RAG pipelines": "retrieval-augmented generation pipelines"},
            )
        ]
    )
    reqs = _requirements(
        (
            "retrieval-augmented generation pipelines",
            "retrieval-augmented generation pipelines",
        )
    )
    result = finalise_selection(resume, raw, reqs)
    assert result.projects["proj_x"] == ["retrieval-augmented generation pipelines"]


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
    resume = synthetic_resume()
    original_tech = [list(p.tech) for p in resume.projects]
    original_coursework = [list(e.coursework) for e in resume.education]
    original_skills = [list(g.items) for g in resume.skills]
    result = budget_only(resume, _requirements(("Python", "python")))
    updated = apply(resume, result)
    assert [list(p.tech) for p in resume.projects] == original_tech
    assert [list(e.coursework) for e in resume.education] == original_coursework
    assert [list(g.items) for g in resume.skills] == original_skills
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
    resume = synthetic_resume()
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
        skills=[SkillGroup(label="AI/ML", items=["Postgres", "RAG pipelines"])],
    )
    reqs = _requirements(
        ("Python", "python"),
        ("FastAPI", "fastapi"),
        ("PostgreSQL", "postgresql"),
    )

    captured_kwargs = {}

    class _FakeMessages:
        def parse(self, **kwargs):
            assert kwargs["output_format"] is FacetSelection
            captured_kwargs.update(kwargs)

            class _Resp:
                parsed_output = FacetSelection(
                    projects=[
                        ProjectTech(id="proj_a", tech=["Python", "FastAPI", "Docker"]),
                    ],
                    coursework=["Machine Learning", "Linear Algebra"],
                    skill_renames={"Postgres": "PostgreSQL"},
                )
                stop_reason = "end_turn"

            return _Resp()

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr(facets.llm, "client_for", lambda purpose: _FakeClient())

    result = select_facets(resume, reqs, use_cache=False)
    assert result.projects["proj_a"][:2] == ["Python", "FastAPI"]
    assert "Machine Learning" in result.coursework
    assert result.skills == [["PostgreSQL", "RAG pipelines"]]
    # Cache written for a subsequent hit.
    assert list(tmp_path.glob("*.facets.json"))

    user_content = captured_kwargs["messages"][0]["content"]
    assert "AI/ML" in user_content
    assert "RAG pipelines" in user_content


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


def _skills_resume(*groups: SkillGroup) -> MasterResume:
    """Minimal resume carrying only the given skill groups."""
    return MasterResume(
        contact={"name": "X", "email": "x@y.z"},
        education=[],
        experience=[],
        projects=[],
        skills=list(groups),
    )


def test_skill_rename_rejects_phrase_narrowing():
    """A multi-word item cannot be renamed down to one of its own words."""
    resume = _skills_resume(
        SkillGroup(label="AI/ML", items=["hybrid retrieval & reranking"])
    )
    raw = FacetSelection(skill_renames={"hybrid retrieval & reranking": "retrieval"})
    reqs = _requirements(("retrieval", "retrieval"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["hybrid retrieval & reranking"]]
    assert any("rejected skill rename" in w for w in result.warnings)


def test_skill_rename_rejects_prefix_narrowing():
    """Alphanumeric-prefix equivalence must not license dropping the rest of a phrase."""
    resume = _skills_resume(
        SkillGroup(
            label="AI/ML",
            items=["retrieval eval (Recall@k, MRR, LLM-as-judge)"],
        )
    )
    raw = FacetSelection(
        skill_renames={"retrieval eval (Recall@k, MRR, LLM-as-judge)": "retrieval"}
    )
    reqs = _requirements(("retrieval", "retrieval"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["retrieval eval (Recall@k, MRR, LLM-as-judge)"]]
    assert any("rejected skill rename" in w for w in result.warnings)


def test_skill_rename_rejects_subspan_acronym():
    """An acronym formed from only part of a phrase must not replace the whole item."""
    resume = _skills_resume(
        SkillGroup(label="AI/ML", items=["hybrid retrieval & reranking"])
    )
    raw = FacetSelection(skill_renames={"hybrid retrieval & reranking": "HR"})
    reqs = _requirements(("HR", "HR"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["hybrid retrieval & reranking"]]
    assert any("rejected skill rename" in w for w in result.warnings)


def test_skill_rename_rejects_compound_narrowing():
    """`/` separates distinct claims, so one side cannot stand in for the whole item."""
    resume = _skills_resume(
        SkillGroup(label="Tools & Languages", items=["Scikit-learn/XGBoost"])
    )
    raw = FacetSelection(skill_renames={"Scikit-learn/XGBoost": "scikit-learn"})
    reqs = _requirements(("scikit-learn", "scikit-learn"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["Scikit-learn/XGBoost"]]
    assert any("rejected skill rename" in w for w in result.warnings)


def test_skill_rename_accepts_jd_anchored_synonym():
    """A single-word item renames toward the JD's spelling; other groups stay untouched."""
    resume = _skills_resume(
        SkillGroup(label="Tools & Languages", items=["Postgres"]),
        SkillGroup(label="Languages", items=["English (fluent)"]),
    )
    raw = FacetSelection(skill_renames={"Postgres": "PostgreSQL"})
    reqs = _requirements(("PostgreSQL", "postgresql"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["PostgreSQL"], ["English (fluent)"]]


def test_skill_rename_accepts_longer_form_of_every_word():
    """Every source word growing to a longer form of itself is accepted."""
    resume = _skills_resume(SkillGroup(label="AI/ML", items=["fuzzy matching"]))
    raw = FacetSelection(skill_renames={"fuzzy matching": "fuzzy string matching"})
    reqs = _requirements(("fuzzy string matching", "fuzzy string matching"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["fuzzy string matching"]]


def test_skill_rename_accepts_acronym_expansion():
    """Spelling out an embedded acronym is the case this feature exists for."""
    resume = _skills_resume(SkillGroup(label="AI/ML", items=["RAG pipelines"]))
    raw = FacetSelection(
        skill_renames={
            "RAG pipelines": "retrieval-augmented generation pipelines"
        }
    )
    reqs = _requirements(
        (
            "retrieval-augmented generation pipelines",
            "retrieval-augmented generation pipelines",
        )
    )
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["retrieval-augmented generation pipelines"]]


def test_skill_rename_rejected_when_it_adds_a_line():
    """A rename that would push a group onto an extra rendered line is discarded."""
    label = "X"
    prefix_len = len(f"{label}: ")
    old_item = "A" * (config.CHARS_PER_LINE - prefix_len)
    new_item = old_item + "B"  # one character over the line boundary

    group = SkillGroup(label=label, items=[old_item])
    baseline = config.line_span(config.skill_group_line(label, [old_item]))
    assert config.line_span(config.skill_group_line(label, [new_item])) > baseline

    reqs = _requirements((new_item, new_item))
    warnings: list[str] = []
    kept = facets._resolve_skill_group(
        group,
        {facets._norm_ws(old_item): new_item},
        reqs,
        warnings=warnings,
    )
    assert kept == [old_item]
    assert any("would add a line" in w for w in warnings)


def test_skill_renames_preserve_count_and_order():
    """A mix of valid, rejected, and unmatched renames never reorders or drops items."""
    resume = _skills_resume(
        SkillGroup(label="Tools", items=["Postgres", "SQL", "Docker"])
    )
    raw = FacetSelection(
        skill_renames={
            "Postgres": "PostgreSQL",  # valid
            "SQL": "Snowflake",  # rejected: not equivalent
            "Unmatched Item": "Whatever",  # matches no item
        }
    )
    reqs = _requirements(("PostgreSQL", "postgresql"), ("Snowflake", "snowflake"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["PostgreSQL", "SQL", "Docker"]]
    assert any("rejected skill rename" in w and "Snowflake" in w for w in result.warnings)
    assert any("matched no item" in w for w in result.warnings)


def test_skill_rename_rejects_duplicate_item():
    """A rename that would duplicate an item already in the group is rejected."""
    resume = _skills_resume(
        SkillGroup(label="Tools", items=["Postgres", "PostgreSQL"])
    )
    raw = FacetSelection(skill_renames={"Postgres": "PostgreSQL"})
    reqs = _requirements(("PostgreSQL", "postgresql"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["Postgres", "PostgreSQL"]]
    assert any("would duplicate an existing item" in w for w in result.warnings)


def test_skill_rename_unknown_item_warns():
    """A rename key that matches no item in any group warns and changes nothing."""
    resume = _skills_resume(SkillGroup(label="Tools", items=["Python"]))
    raw = FacetSelection(skill_renames={"Not A Real Item": "Something"})
    reqs = _requirements(("Something", "something"))
    result = finalise_selection(resume, raw, reqs)
    assert result.skills == [["Python"]]
    assert any("matched no item" in w for w in result.warnings)


def test_budget_only_leaves_skills_untouched():
    """--no-facets path leaves every skill item exactly as in the master resume."""
    resume = synthetic_resume()
    original = [list(g.items) for g in resume.skills]
    result = budget_only(resume, _requirements(("Python", "python")))
    updated = apply(resume, result)
    assert [list(g.items) for g in updated.skills] == original


def test_cache_key_covers_skill_pools():
    """Changing a skill item, or the char budget, changes the facets cache key."""
    reqs = _requirements(("Python", "python"))
    base = _skills_resume(SkillGroup(label="Tools", items=["Python"]))
    changed = _skills_resume(SkillGroup(label="Tools", items=["Java"]))
    assert facets._cache_path(base, reqs) != facets._cache_path(changed, reqs)

    path_before = facets._cache_path(base, reqs)
    original_chars_per_line = config.CHARS_PER_LINE
    try:
        config.CHARS_PER_LINE = original_chars_per_line + 1
        path_after = facets._cache_path(base, reqs)
    finally:
        config.CHARS_PER_LINE = original_chars_per_line
    assert path_before != path_after
