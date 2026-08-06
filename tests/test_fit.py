"""Tests for the fit loop.

No test here exercises a live API call or Word/COM — `rewrite_bullets` and the
`render` module are monkeypatched so the loop's selection/shorten/underflow logic is
verified in isolation, matching the rest of the suite's no-network convention.
"""

from __future__ import annotations

import pytest

from resume_tailor import config, fit as fit_mod
from resume_tailor.data import (
    Bullet,
    EducationSection,
    Experience,
    ExperienceSection,
    MasterResume,
    Project,
    SkillGroup,
    SkillsSection,
)
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor.rewrite import RewriteOutcome


def _requirements() -> JobRequirements:
    return JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def _identity_rewrite(
    bullets,
    requirements,
    *,
    char_budget,
    shorten_pct=0,
    repair_widows=True,
    repair_verbs=True,
    merge_groups=None,
    on_event=None,
):
    """Pass-through rewrite stub that ignores polish and merge knobs."""
    return RewriteOutcome({b.id: b.text for b in bullets})


def _test_resume() -> MasterResume:
    """A resume generous enough to exercise the fit loop's entry-capping, budget-growth,
    and page-fitting logic meaningfully — several tests below assert their own sizing
    assumptions explicitly (e.g. "test needs room to grow the selection") and fail with
    a clear message if this fixture is ever too small for them, rather than passing
    vacuously. Sized well above `config.MAX_EXPERIENCE_ENTRIES`/`MAX_PROJECT_ENTRIES`
    (3/2) specifically so `choose_entries`'s default caps always drop something real,
    and every entry carries multiple bullets so a per-entry cap has something to cut.
    """
    return MasterResume(
        contact={"name": "N", "email": "n@example.com"},
        tag_vocabulary=["python"],
        education=[
            {
                "school": "State University",
                "degree": "BS Computer Science",
                "dates": "2019 - 2023",
                "coursework": ["Algorithms", "Databases"],
            }
        ],
        experience=[
            Experience(
                company=f"Company {n}", title="Engineer", start="2020-01", end="2020-06",
                bullets=[
                    Bullet(id=f"exp{n}_b{i}", text=f"Company {n} did thing {i}.", tags=["python"])
                    for i in range(1, 6)
                ],
            )
            for n in range(1, 6)
        ],
        projects=[
            Project(
                id=f"proj{n}", name=f"Project {n}", tech=["Python"],
                bullets=[
                    Bullet(id=f"proj{n}_b{i}", text=f"Project {n} built thing {i}.", tags=["python"])
                    for i in range(1, 5)
                ],
            )
            for n in range(1, 5)
        ],
        skills=[SkillGroup(label="Tools", items=["Python"])],
    )


def test_estimate_lines_scales_with_bullet_count():
    resume = _test_resume()
    empty = fit_mod.estimate_lines(resume, {})
    full = fit_mod.estimate_lines(resume, {b.id: b.text for b in resume.all_bullets()})
    assert full > empty


def test_fixed_overhead_uses_shared_skill_line():
    """Skills overhead is measured via `config.skill_group_line`, the same helper the
    `facets` stage guards renames against — so the two cannot silently drift apart.
    """
    resume = _test_resume()
    expected = 2  # name + contact
    layout = fit_mod.active_layout()
    enabled = layout.get("enabled") or {}
    if enabled.get("education", True):
        expected += 1
        for edu in resume.education:
            expected += 1
            expected += config.line_span(fit_mod.render._degree_line(edu))
            for detail in fit_mod.render._education_details(edu):
                expected += config.line_span(detail)
    if enabled.get("skills", True) and resume.skills:
        expected += 1
        for group in resume.skills:
            expected += config.line_span(
                config.skill_group_line(group.label, group.items)
            )
    assert fit_mod._fixed_overhead_lines(resume) == expected


def test_estimate_lines_respects_disabled_sections(monkeypatch):
    """Disabled education/skills/projects shrink the estimate and selection pool."""
    resume = _test_resume()
    layout = {
        "contact_separator": " • ",
        "contact_field_order": ["location", "email", "phone", "linkedin", "github"],
        "enabled": {
            "education": False,
            "experience": True,
            "projects": False,
            "skills": False,
        },
    }
    monkeypatch.setattr(fit_mod, "active_layout", lambda: layout)
    empty = fit_mod.estimate_lines(resume, {}, layout=layout)
    # Name + contact only when education/skills are off and no bullets selected.
    assert empty == 2

    entries = fit_mod.choose_entries(resume, _requirements(), layout=layout)
    assert all(hasattr(e, "company") for e in entries)  # experience only
    assert not any(hasattr(e, "tech") for e in entries)


def _spacer_test_resume() -> MasterResume:
    """Small hand-built resume with a known, easy-to-hand-verify section/entry shape:
    2 education entries, 3 experience entries (one of which will have every bullet
    excluded from the `bullets` filter in tests below, so it does not "survive"), and
    one non-empty skills section."""
    return MasterResume(
        contact={"name": "N", "email": "n@example.com"},
        sections=[
            EducationSection(
                id="edu",
                title="EDUCATION",
                entries=[
                    {"school": "A", "degree": "BA", "dates": "2020"},
                    {"school": "B", "degree": "MA", "dates": "2022"},
                ],
            ),
            ExperienceSection(
                id="work",
                title="WORK",
                entries=[
                    Experience(
                        company="X", title="Eng", start="2020", end="2021",
                        bullets=[Bullet(id="b1", text="did x", tags=["x"])],
                    ),
                    Experience(
                        company="Y", title="Eng2", start="2021", end="2022",
                        bullets=[Bullet(id="b2", text="did y", tags=["x"])],
                    ),
                    Experience(
                        company="Z", title="Eng3", start="2022", end="2023",
                        bullets=[Bullet(id="b3", text="did z", tags=["x"])],
                    ),
                ],
            ),
            SkillsSection(
                id="skills", title="SKILLS", entries=[SkillGroup(label="Tools", items=["Python"])]
            ),
        ],
    )


def test_spacer_lines_zero_when_layout_has_no_spacing():
    """No `spacing` key at all (every pre-existing profile) contributes nothing."""
    resume = _spacer_test_resume()
    layout = {"section_mode": "generic", "enabled": {}}
    assert fit_mod._spacer_lines(resume, {}, layout=layout) == 0


def test_spacer_lines_zero_when_donors_all_none():
    resume = _spacer_test_resume()
    layout = {
        "section_mode": "generic",
        "enabled": {},
        "spacing": {"before_heading": [], "after_heading": [], "between_entries": []},
    }
    assert fit_mod._spacer_lines(resume, {}, layout=layout) == 0


def test_spacer_lines_counts_before_after_and_between():
    """2 education entries (always survive), 2 of 3 experience entries surviving the
    bullets filter, 1 non-empty skills section: 3 rendered sections, so before_heading
    contributes 2 (rendered - 1), after_heading contributes 3 (one per rendered
    section), and between_entries contributes 1 (education, 2-1) + 1 (experience,
    2 surviving - 1) = 2. Total 2 + 3 + 2 = 7."""
    resume = _spacer_test_resume()
    bullets = {"b1": "did x", "b2": "did y"}  # b3 excluded — entry Z does not survive
    layout = {
        "section_mode": "generic",
        "enabled": {"education": True, "skills": True},
        "spacing": {"before_heading": [1], "after_heading": [1], "between_entries": [1]},
    }
    assert fit_mod._spacer_lines(resume, bullets, layout=layout) == 7


def test_spacer_lines_scale_with_run_length():
    """A slot's cost is its run length — a rule-plus-blank `after_heading` is two lines
    per rendered section, not one. Getting this wrong under-counts every heading."""
    resume = _spacer_test_resume()
    bullets = {"b1": "did x", "b2": "did y"}
    layout = {
        "section_mode": "generic",
        "enabled": {"education": True, "skills": True},
        "spacing": {"before_heading": [], "after_heading": [1, 2], "between_entries": []},
    }
    # 3 rendered sections x 2 paragraphs each.
    assert fit_mod._spacer_lines(resume, bullets, layout=layout) == 6


def test_spacer_lines_only_the_set_donors_contribute():
    resume = _spacer_test_resume()
    bullets = {"b1": "did x", "b2": "did y"}
    layout = {
        "section_mode": "generic",
        "enabled": {"education": True, "skills": True},
        "spacing": {"before_heading": [1], "after_heading": [], "between_entries": []},
    }
    assert fit_mod._spacer_lines(resume, bullets, layout=layout) == 2  # rendered - 1


def test_spacer_lines_skips_a_disabled_kind():
    """A kind the active template has no prototype for never renders, so it must not
    count toward `rendered` or contribute a between-entries term."""
    resume = _spacer_test_resume()
    bullets = {"b1": "did x", "b2": "did y"}
    layout = {
        "section_mode": "generic",
        "enabled": {"education": True, "skills": False},
        "spacing": {"before_heading": [1], "after_heading": [1], "between_entries": []},
    }
    # rendered = education + experience only (skills disabled) = 2
    assert fit_mod._spacer_lines(resume, bullets, layout=layout) == 1 + 2  # (2-1) + 2


def test_spacer_lines_zero_when_nothing_survives():
    resume = _spacer_test_resume()
    layout = {
        "section_mode": "generic",
        "enabled": {"education": False, "skills": False},
        "spacing": {"before_heading": [1], "after_heading": [1], "between_entries": [1]},
    }
    assert fit_mod._spacer_lines(resume, {}, layout=layout) == 0


def test_estimate_lines_adds_spacer_term_under_generic_mode():
    resume = _spacer_test_resume()
    bullets = {"b1": "did x", "b2": "did y"}
    layout = {
        "contact_separator": " • ",
        "contact_field_order": ["location", "email"],
        "enabled": {"education": True, "experience": True, "projects": True, "skills": True},
        "section_mode": "generic",
        "spacing": {"before_heading": [1], "after_heading": [1], "between_entries": [1]},
    }
    layout_no_spacing = {**layout, "spacing": {}}
    with_spacing = fit_mod.estimate_lines(resume, bullets, layout=layout)
    without_spacing = fit_mod.estimate_lines(resume, bullets, layout=layout_no_spacing)
    assert with_spacing - without_spacing == 7


def test_estimate_lines_ignores_spacing_under_fixed_mode():
    """Fixed-mode layouts never carry a `spacing` key in practice, but the guard lives
    on `section_mode`, not presence-of-key, for defense in depth."""
    resume = _spacer_test_resume()
    bullets = {"b1": "did x", "b2": "did y"}
    layout = {
        "contact_separator": " • ",
        "contact_field_order": ["location", "email"],
        "enabled": {"education": True, "experience": True, "projects": True, "skills": True},
        "section_mode": "fixed",
        "spacing": {"before_heading": [1], "after_heading": [1], "between_entries": [1]},
    }
    layout_no_spacing = {**layout, "spacing": {}}
    with_spacing = fit_mod.estimate_lines(resume, bullets, layout=layout)
    without_spacing = fit_mod.estimate_lines(resume, bullets, layout=layout_no_spacing)
    assert with_spacing == without_spacing


def test_estimate_lines_counts_coursework_wrap():
    """Coursework joined into one detail line must contribute to fixed overhead."""
    resume = _test_resume()
    assert resume.education
    assert resume.education[0].coursework
    empty = fit_mod.estimate_lines(resume, {})
    # Overhead alone (no experience/project bullets) still includes the coursework wrap.
    assert empty >= 5


def test_include_apply_clearing_coursework_shrinks_fixed_overhead():
    """`include.apply(coursework=False)` must free exactly the coursework wrap's lines
    from `_fixed_overhead_lines` — the mechanism the fit loop relies on to reclaim that
    space via the grow step, with no fit.py-side special case for it."""
    from resume_tailor.include import IncludeOptions, apply as include_apply

    resume = _test_resume()
    assert resume.education
    assert resume.education[0].coursework  # sanity: fixture has some to clear

    with_coursework = fit_mod._fixed_overhead_lines(resume)
    trimmed = include_apply(resume, IncludeOptions(coursework=False))
    without_coursework = fit_mod._fixed_overhead_lines(trimmed)

    freed = sum(
        config.line_span("Relevant Coursework: " + ", ".join(edu.coursework))
        for edu in resume.education
        if edu.coursework
    )
    assert with_coursework - without_coursework == freed
    assert freed > 0


def test_tag_vocabulary_canonicalises_on_load():
    """Stored tag options are canonicalised the same way bullet tags are."""
    resume = _test_resume()
    assert resume.tag_vocabulary
    assert resume.tag_vocabulary == sorted(resume.tag_vocabulary)
    # Every in-use bullet tag should be in the seeded vocabulary after migration.
    used = {t for b in resume.all_bullets() for t in b.tags}
    assert used <= set(resume.tag_vocabulary)


def test_initial_selection_size_share_is_a_ceiling_not_a_floor():
    """`share=1.0` must reproduce the unbounded search exactly (no-behaviour-change)."""
    resume = _test_resume()
    requirements = _requirements()
    entries = fit_mod.choose_entries(resume, requirements)

    unbounded = fit_mod._initial_selection_size(resume, entries, requirements, target_pages=1)
    default_share = fit_mod._initial_selection_size(
        resume, entries, requirements, target_pages=1, share=1.0
    )
    assert default_share == unbounded


def test_initial_selection_size_share_caps_below_the_estimate():
    """A share below the unbounded result caps the search's upper bound exactly."""
    resume = _test_resume()
    requirements = _requirements()
    entries = fit_mod.choose_entries(resume, requirements)
    total = sum(len(e.bullets) for e in entries)

    unbounded = fit_mod._initial_selection_size(resume, entries, requirements, target_pages=1)
    share = 0.5
    capped_high = max(len(entries), min(total, round(total * share)))
    assume_room = capped_high < unbounded  # only a meaningful test if the cap actually bites
    assert assume_room, "fixture needs the cap to bind below the unbounded estimate"

    capped = fit_mod._initial_selection_size(
        resume, entries, requirements, target_pages=1, share=share
    )
    assert capped == capped_high
    assert capped < unbounded


def test_initial_selection_size_share_never_drops_below_one_bullet_per_entry():
    """A share so low it would fall under one bullet per entry is clamped up to the floor."""
    resume = _test_resume()
    requirements = _requirements()
    entries = fit_mod.choose_entries(resume, requirements)

    floor = len(entries)
    capped = fit_mod._initial_selection_size(
        resume, entries, requirements, target_pages=1, share=0.01
    )
    assert capped >= floor


#: A measured line count that clears UNDERFLOW_THRESHOLD, so the loop stops rather than
#: growing the selection. Derived from config so it tracks a re-calibration.
_FULL_LINES = config.LINES_PER_PAGE
_SPARSE_LINES = int(config.LINES_PER_PAGE * config.UNDERFLOW_THRESHOLD) - 5


def test_fit_escalates_shorten_schedule_on_overflow(monkeypatch, tmp_path):
    resume = _test_resume()
    requirements = _requirements()

    calls: list[int] = []

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Record shorten_pct so the overflow schedule can be asserted."""
        calls.append(shorten_pct)
        return _identity_rewrite(bullets, requirements, char_budget=char_budget, shorten_pct=shorten_pct)

    pages = iter([2, 2, 1])  # overflow, overflow, fits on the third attempt

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(
        fit_mod.render, "measure_detail", lambda *a, **k: (next(pages), _FULL_LINES)
    )
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert calls == [0, *config.SHORTEN_SCHEDULE[:2]]
    assert result.pages == 1
    assert result.iterations == 3


def test_fit_raises_after_max_attempts_without_truncating(monkeypatch, tmp_path):
    resume = _test_resume()
    requirements = _requirements()

    calls: list[int] = []

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Record shorten_pct so exhausting MAX_FIT_ATTEMPTS can be asserted."""
        calls.append(shorten_pct)
        return _identity_rewrite(bullets, requirements, char_budget=char_budget, shorten_pct=shorten_pct)

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (2, _FULL_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    with pytest.raises(fit_mod.FitError, match="Could not fit"):
        fit_mod.fit(resume, requirements, target_pages=1)

    assert len(calls) == config.MAX_FIT_ATTEMPTS
    assert calls == [0, *config.SHORTEN_SCHEDULE[: config.MAX_FIT_ATTEMPTS - 1]]


def test_fit_restores_bullets_on_underflow(monkeypatch, tmp_path):
    """A sparse page must pull bullets back rather than shipping half-empty."""
    resume = _test_resume()
    requirements = _requirements()
    entries = fit_mod.choose_entries(resume, requirements)
    available = sum(len(e.bullets) for e in entries)
    initial_limit = fit_mod._initial_selection_size(resume, entries, requirements, target_pages=1)
    assert initial_limit < available, "test needs room to grow the selection"

    seen: dict[str, int] = {}

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Track selection size so underflow growth can be asserted."""
        seen["count"] = len(bullets)
        return _identity_rewrite(bullets, requirements, char_budget=char_budget, shorten_pct=shorten_pct)

    # Underfull while the selection is at its starting size; full once it has grown.
    def fake_measure(*a, **k):
        return (1, _SPARSE_LINES if seen["count"] <= initial_limit else _FULL_LINES)

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", fake_measure)
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert result.bullets_selected > initial_limit
    # Specifically no *underflow* warning — the point of the test is that growing worked.
    # A widow warning is unrelated here: this fake returns the master resume's own text
    # verbatim, and some source bullets happen to end on a near-empty line.
    assert not [w for w in result.warnings if "full" in w]


def test_fit_stops_growing_after_max_attempts_and_warns(monkeypatch, tmp_path):
    """Underflow is not fatal: return the fullest version reached, but say it is sparse."""
    resume = _test_resume()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _SPARSE_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert result.pages == 1
    assert any("full" in w for w in result.warnings)


def test_fit_growth_ceiling_stops_early_when_entries_are_capped(monkeypatch, tmp_path):
    """A per-entry cap can saturate the achievable selection below the raw bullet pool;
    growth must stop there instead of burning `MAX_GROW_ATTEMPTS` retrying a selection
    that never changes (each retry costs a rewrite call and a render).
    """
    resume = _test_resume()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _SPARSE_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1, max_bullets_per_entry=1)

    entries = fit_mod.choose_entries(resume, requirements)
    # Every entry is capped at its one floor bullet, so the achievable total equals the
    # entry count — reached immediately, with no room to grow into at all.
    assert result.bullets_selected == len(entries)
    assert result.iterations == 1
    assert any("selectable bullet cap" in w for w in result.warnings)


def test_fit_honours_entry_caps_and_never_drops_a_chosen_entry(monkeypatch, tmp_path):
    """Entry count is a shape decision; the loop may trim bullets but not whole entries."""
    resume = _test_resume()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _FULL_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1, max_experience=3, max_projects=2)

    rendered_jobs = [e for e in resume.experience if any(b.id in result.bullets for b in e.bullets)]
    rendered_projects = [
        p for p in resume.projects if any(b.id in result.bullets for b in p.bullets)
    ]
    assert len(rendered_jobs) == 3
    assert len(rendered_projects) == 2


def test_semantic_table_reaches_entry_selection(monkeypatch, tmp_path):
    """The relevance table must actually steer which entries appear, not just be accepted."""
    resume = _test_resume()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _FULL_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    # Pick a job that keyword ranking leaves out, and make it the most relevant thing on
    # the resume semantically.
    baseline = fit_mod.fit(resume, requirements, target_pages=1)
    excluded = next(
        e for e in resume.experience if not any(b.id in baseline.bullets for b in e.bullets)
    )
    table = {b.id: 10.0 for b in excluded.bullets}

    result = fit_mod.fit(resume, requirements, target_pages=1, semantic=table)

    assert any(b.id in result.bullets for b in excluded.bullets)
    assert result.semantic_used is True
    assert baseline.semantic_used is False


def test_fit_falls_back_to_budget_estimate_when_word_unavailable(monkeypatch, tmp_path):
    """render.measure_detail raising RuntimeError (no Word) must not crash the run."""
    resume = _test_resume()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")

    def fake_measure(*a, **k):
        raise RuntimeError("Word is not installed")

    monkeypatch.setattr(fit_mod.render, "measure_detail", fake_measure)
    monkeypatch.setattr(fit_mod, "estimate_lines", lambda resume, bullets: _FULL_LINES)

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert result.pages_are_estimated
    assert any("Word is not installed" in w for w in result.warnings)


def test_merge_proposals_wait_until_measured_overflow(monkeypatch, tmp_path):
    """With merge_bullets on, attempt 0 must not propose; overflow attempts may."""
    resume = _test_resume()
    requirements = _requirements()
    seen_groups: list[list] = []

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Capture merge_groups passed on each rewrite attempt."""
        seen_groups.append(list(merge_groups or []))
        return RewriteOutcome({b.id: b.text for b in bullets})

    pages = iter([2, 1])  # first measure overflows, second fits

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(
        fit_mod.render, "measure_detail", lambda *a, **k: (next(pages), _FULL_LINES)
    )
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    # Force a deterministic non-empty proposal after overflow so the gate is visible.
    sentinel = object()

    def fake_propose(*a, **k):
        """Return a sentinel group list whenever propose is reached."""
        return [sentinel]

    monkeypatch.setattr(fit_mod, "propose_merges", fake_propose)

    fit_mod.fit(resume, requirements, target_pages=1, merge_bullets=True)

    assert seen_groups[0] == [], "first draft must not merge"
    assert seen_groups[1] == [sentinel], "overflow attempt must be allowed to merge"
