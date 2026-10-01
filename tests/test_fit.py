"""Tests for the fit loop.

No test here exercises a live API call or Word/COM — `rewrite_bullets` and the
`render` module are monkeypatched so the loop's selection/overflow-ladder/underflow logic is
verified in isolation, matching the rest of the suite's no-network convention.
"""

from __future__ import annotations

import math

import pytest

from resume_tailor import config
from resume_tailor import fit as fit_mod
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
    repair_widows=True,
    repair_verbs=True,
    merge_groups=None,
    on_event=None,
    verb_context=None,
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
    from resume_tailor.include import IncludeOptions
    from resume_tailor.include import apply as include_apply

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


def _stub_render(monkeypatch, tmp_path, *, pages_for, renders=None, layout_for=None):
    """Stub render/measure; `pages_for(texts)` returns the `(pages, lines)` a draft measures.

    Measuring by the *content* of the last render (not by call order) keeps a test valid
    however many renders the ladder chooses to do.
    """
    last: dict[str, dict] = {}

    def fake_render(*a, **k):
        last["texts"] = dict(k["bullets"])
        if layout_for is not None:
            (tmp_path / "out.pdf").touch()
        if renders is not None:
            renders.append(dict(k["bullets"]))
        return tmp_path / "out.docx"

    monkeypatch.setattr(fit_mod.render, "render", fake_render)
    monkeypatch.setattr(
        fit_mod.render, "measure_detail", lambda *a, **k: pages_for(last["texts"])
    )
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")
    if layout_for is not None:
        monkeypatch.setattr(
            fit_mod.render, "line_layout", lambda _pdf, texts: layout_for(last["texts"]),
        )


def test_measured_widow_pass_reverts_when_repair_overflows(monkeypatch, tmp_path):
    resume = _test_resume()
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    _stub_render(
        monkeypatch, tmp_path,
        pages_for=lambda texts: (2, _FULL_LINES + 5) if any(
            text.endswith(" repair") for text in texts.values()
        ) else (1, _FULL_LINES),
        layout_for=lambda texts: {
            bid: fit_mod.render.LineFit(2, 0.2, 100) if bid == "exp1_b1"
            else fit_mod.render.LineFit(1, 1.0, 100)
            for bid in texts
        },
    )

    def fake_polish(texts, sources, requirements, **kwargs):
        assert kwargs["targets"]["exp1_b1"][1] == 95
        return {**texts, "exp1_b1": texts["exp1_b1"] + " repair"}, 1, 0, {}

    monkeypatch.setattr(fit_mod, "_polish", fake_polish)
    result = fit_mod.fit(resume, _requirements(), target_pages=1, fill_target=0)
    assert not result.bullets["exp1_b1"].endswith(" repair")
    assert result.widows_repaired == 0 and result.widows_remaining == 1
    assert any("Widow repair overflowed" in warning for warning in result.warnings)


def test_measured_pass_refits_coursework_only_from_the_pool_it_is_given(monkeypatch, tmp_path):
    """The coursework pool reaches the measured pass as an argument, never via the resume."""
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    _stub_render(
        monkeypatch, tmp_path,
        pages_for=lambda texts: (1, _FULL_LINES),
        layout_for=lambda texts: {
            **{bid: fit_mod.render.LineFit(1, 1.0, 100) for bid in texts},
            "__coursework__": fit_mod.render.LineFit(2, 0.2, 100),
        },
    )
    pools: list[list[str]] = []

    def fake_fit_coursework(ordered, *args, pool=None, **kwargs):
        pools.append(list(pool))
        return [*ordered, "Operating Systems"]

    monkeypatch.setattr(fit_mod.facets, "fit_coursework_to_budget", fake_fit_coursework)
    pool = ["Algorithms", "Databases", "Operating Systems"]

    fit_mod.fit(
        _test_resume(), _requirements(), target_pages=1, fill_target=0, coursework_pool=pool
    )
    assert pools == [pool]

    pools.clear()
    fit_mod.fit(_test_resume(), _requirements(), target_pages=1, fill_target=0)
    assert pools == [], "without a pool, coursework is left as facets selected it"


def test_measured_widow_targets_choose_shortening_extension_and_merged_shortening():
    source = Bullet(id="a", text="x" * 220, tags=["python"])
    sources = {"a": source, "b": Bullet(id="b", text="y" * 220, tags=["python"])}
    texts = {"a": "x" * 120, "b": "y" * 120}
    fits = {
        "a": fit_mod.render.LineFit(2, 0.20, 100),
        "b": fit_mod.render.LineFit(2, 0.42, 100),
    }
    targets = fit_mod._widow_targets(
        texts, sources, fits, measured_lines=40, capacity=50, members={},
        estimated=False,
    )
    assert targets["a"] == (0, 95)
    assert targets["b"] == (133, 195)
    full_page = fit_mod._widow_targets(
        texts, sources, fits, measured_lines=50, capacity=50, members={},
        estimated=False,
    )
    assert full_page["b"] == (0, 95)
    merged = fit_mod._widow_targets(
        texts, sources, fits, measured_lines=40, capacity=50,
        members={"b": ("a", "b")}, estimated=False,
    )
    assert merged["b"] == (0, 95)


def test_estimated_widow_uses_conservative_threshold():
    source = {"a": Bullet(id="a", text="x" * 220, tags=["python"])}
    fits = {"a": fit_mod.render.LineFit(2, 0.40, 100)}
    assert fit_mod._widow_targets(
        {"a": "x" * 120}, source, fits, measured_lines=40, capacity=50,
        members={}, estimated=True,
    ) == {}


def test_fit_drops_weakest_bullets_on_overflow_without_another_rewrite(monkeypatch, tmp_path):
    """Overflow is relieved on the same draft: one rewrite call, bullets dropped whole."""
    resume = _test_resume()
    requirements = _requirements()
    calls: list[int] = []

    def fake_rewrite(bullets, requirements, **kwargs):
        calls.append(len(bullets))
        return _identity_rewrite(bullets, requirements, **kwargs)

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    first: dict[str, dict] = {}

    def pages_for(texts):
        first.setdefault("n", len(texts))
        return (1, _FULL_LINES) if len(texts) < first["n"] else (2, _FULL_LINES)

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for)

    result = fit_mod.fit(resume, requirements, target_pages=1, merge_bullets=False)

    assert result.pages == 1
    assert len(calls) == 1, "dropping must not trigger a second rewrite"
    assert result.dropped, "the dropped bullets must be reported"
    assert len(result.dropped) == first["n"] - len(result.bullets)
    assert not set(result.dropped) & set(result.bullets)


def test_fit_ladder_order_is_combine_then_pullback_then_drop(monkeypatch, tmp_path):
    resume = _test_resume()
    requirements = _requirements()
    order: list[str] = []
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)

    def fake_propose(entries, selected, *a, **k):
        order.append("propose")
        ids = [b.id for b in selected[:2]]
        return [fit_mod.MergeGroup(ids[0], tuple(ids), 1.0, "test")]

    def fake_merge(texts, sources, groups, requirements, *, char_budget):
        order.append("merge")
        return dict(texts), []  # rejected: nothing merged, so no extra render

    def fake_choose_pullbacks(texts, *a, **k):
        order.append("choose_pullbacks")
        return {next(iter(texts)): 10}

    def fake_pull_back(texts, sources, requirements, ceilings):
        order.append("pull_back")
        return dict(texts), 0, {}  # nothing shortened

    monkeypatch.setattr(fit_mod, "propose_merges", fake_propose)
    monkeypatch.setattr(fit_mod, "merge_into", fake_merge)
    monkeypatch.setattr(fit_mod, "_choose_pullbacks", fake_choose_pullbacks)
    monkeypatch.setattr(fit_mod, "pull_back", fake_pull_back)
    sizes: dict[str, int] = {}

    def pages_for(texts):
        sizes.setdefault("n", len(texts))
        if len(texts) < sizes["n"]:
            order.append("drop")
            return 1, _FULL_LINES
        return 2, _FULL_LINES

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for)

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert order == ["propose", "merge", "choose_pullbacks", "pull_back", "drop"]
    assert result.pages == 1 and result.dropped


def test_fit_stops_the_ladder_once_a_rung_fits(monkeypatch, tmp_path):
    resume = _test_resume()
    requirements = _requirements()
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)

    def fake_propose(entries, selected, *a, **k):
        ids = [b.id for b in selected[:2]]
        return [fit_mod.MergeGroup(ids[0], tuple(ids), 1.0, "test")]

    def fake_merge(texts, sources, groups, requirements, *, char_budget):
        merged = {k: v for k, v in texts.items() if k != groups[0].member_ids[1]}
        return merged, list(groups)

    def boom(*a, **k):
        raise AssertionError("pull-back must not run once the merge fit")

    monkeypatch.setattr(fit_mod, "propose_merges", fake_propose)
    monkeypatch.setattr(fit_mod, "merge_into", fake_merge)
    monkeypatch.setattr(fit_mod, "pull_back", boom)
    sizes: dict[str, int] = {}

    def pages_for(texts):
        sizes.setdefault("n", len(texts))
        return (1, _FULL_LINES) if len(texts) < sizes["n"] else (2, _FULL_LINES)

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for)

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert len(result.merges) == 1
    assert result.dropped == [] and result.pulled_back == 0


def test_fit_raises_when_the_ladder_is_exhausted_and_nothing_ever_fit(monkeypatch, tmp_path):
    resume = _test_resume()
    requirements = _requirements()
    renders: list[dict] = []
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    _stub_render(monkeypatch, tmp_path, pages_for=lambda t: (2, _FULL_LINES + 4), renders=renders)

    with pytest.raises(fit_mod.FitError, match="Could not fit") as excinfo:
        fit_mod.fit(resume, requirements, target_pages=1, merge_bullets=False)

    # First draft plus at most MAX_DROP_ROUNDS drop renders; no unbounded retrying.
    assert 1 < len(renders) <= 1 + config.MAX_DROP_ROUNDS
    assert "Measured" in str(excinfo.value)
    assert "~-" not in str(excinfo.value), "the report must never quote a negative overflow"


def test_fit_keeps_an_earlier_draft_that_fit_instead_of_failing(monkeypatch, tmp_path):
    """Grow → overflow → ladder exhausted: return the draft that fit, with a warning."""
    resume = _test_resume()
    requirements = _requirements()
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    first: dict[str, dict] = {}

    def pages_for(texts):
        first.setdefault("texts", dict(texts))
        return (1, _SPARSE_LINES) if texts == first["texts"] else (2, _FULL_LINES + 4)

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for)

    result = fit_mod.fit(resume, requirements, target_pages=1, merge_bullets=False)

    assert result.pages == 1
    assert result.bullets == first["texts"]
    assert any("kept the earlier" in w for w in result.warnings)


def test_fit_does_not_regrow_bullets_the_ladder_just_removed(monkeypatch, tmp_path):
    """A draft trimmed to fit, and then underfull, must not grow back into the overflow."""
    resume = _test_resume()
    requirements = _requirements()
    calls: list[int] = []

    def fake_rewrite(bullets, requirements, **kwargs):
        calls.append(len(bullets))
        return _identity_rewrite(bullets, requirements, **kwargs)

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    sizes: dict[str, int] = {}

    def pages_for(texts):
        sizes.setdefault("n", len(texts))
        return (1, _SPARSE_LINES) if len(texts) < sizes["n"] else (2, _FULL_LINES)

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for)

    result = fit_mod.fit(resume, requirements, target_pages=1, merge_bullets=False)

    # The loop rewrote the full set once and never grew back into the overflow; every
    # later call is the top-up rewriting only the bullets it tried to add.
    assert calls[0] == max(calls)
    assert all(n < calls[0] for n in calls[1:])
    assert not any(step["step"] == "grow" for step in result.trace)
    assert result.pages == 1
    assert any("overflowed the page" in w for w in result.warnings)


def _bullet_fixture(ids):
    return {i: Bullet(id=i, text="x", tags=["python"]) for i in ids}


def test_choose_pullbacks_only_takes_multiline_bullets_with_an_emptyish_last_line():
    width = config.CHARS_PER_LINE
    texts = {
        "half": "a" * (width + int(width * 0.5)),       # 50% last line: too full
        "fifth": "a" * (width + int(width * 0.2)),      # 20%: eligible
        "third": "a" * (width + int(width * 0.38)),     # 38%: eligible
        "one_line": "a" * 30,                           # single line: never
        "tenth": "a" * (2 * width + int(width * 0.1)),  # 3 lines, 10%: emptiest
    }
    requirements = _requirements()
    sources = _bullet_fixture(texts)

    picked = fit_mod._choose_pullbacks(texts, sources, requirements, None, {}, count=2)

    assert list(picked) == ["tenth", "fifth"], "emptiest last line first, limited to count"
    assert picked["tenth"] == 2 * width - config.WIDOW_SAFETY
    assert picked["fifth"] == width - config.WIDOW_SAFETY

    everything = fit_mod._choose_pullbacks(texts, sources, requirements, None, {}, count=10)
    assert set(everything) == {"tenth", "fifth", "third"}


def test_choose_pullbacks_skips_merged_survivors():
    width = config.CHARS_PER_LINE
    texts = {"m": "a" * (width + 5), "p": "a" * (width + 6)}
    picked = fit_mod._choose_pullbacks(
        texts, _bullet_fixture(texts), _requirements(), None, {"m": ("m", "z")}, count=5
    )
    assert list(picked) == ["p"]


def test_choose_drops_never_removes_an_entrys_last_bullet():
    resume = _test_resume()
    requirements = _requirements()
    entries = fit_mod.choose_entries(resume, requirements)
    sources = {b.id: b for e in entries for b in e.bullets}
    # Exactly one rendered bullet per entry: nothing may be dropped, however large the overflow.
    texts = {e.bullets[0].id: e.bullets[0].text for e in entries}

    assert fit_mod._choose_drops(entries, texts, sources, requirements, None, {}, overflow=50) == []

    # Two per entry: at most one per entry can go, and the weakest goes first.
    texts = {b.id: b.text for e in entries for b in e.bullets[:2]}
    doomed = fit_mod._choose_drops(entries, texts, sources, requirements, None, {}, overflow=500)
    per_entry = {id(e): sum(1 for b in e.bullets if b.id in texts and b.id not in doomed) for e in entries}
    assert all(n >= 1 for n in per_entry.values())
    assert len(doomed) == len(entries)


def test_choose_drops_prefers_the_weakest_bullet_tall_enough_to_cover_the_overflow():
    resume = _test_resume()
    requirements = _requirements()
    entries = fit_mod.choose_entries(resume, requirements)
    entry = entries[0]
    ids = [b.id for b in entry.bullets[:3]]
    sources = {b.id: b for b in entry.bullets}
    width = config.CHARS_PER_LINE
    texts = {ids[0]: "a" * 10, ids[1]: "a" * (2 * width - 5), ids[2]: "a" * (2 * width - 5)}
    # ids[0] is one line, the others two. Overflow 2: a one-line bullet cannot cover it,
    # so the pick must come from the two-line bullets even though ids[0] scores no higher.
    semantic = {ids[0]: 0.0, ids[1]: 5.0, ids[2]: 9.0}

    doomed = fit_mod._choose_drops(
        [entry], texts, sources, requirements, semantic, {}, overflow=2
    )

    assert doomed == [ids[1]]


def test_overflow_report_quotes_measured_lines_and_is_never_negative():
    resume = _test_resume()
    capacity = config.LINES_PER_PAGE
    bullets = {b.id: b.text for b in resume.all_bullets()}

    over = fit_mod._overflow_report(resume, bullets, 1, capacity + 3)
    assert f"Measured {capacity + 3} lines" in over and "over by 3" in over

    within = fit_mod._overflow_report(resume, bullets, 1, capacity - 4)
    assert "within the" in within and "over by" not in within


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
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Track selection size so underflow growth can be asserted."""
        seen["count"] = len(bullets)
        return _identity_rewrite(bullets, requirements, char_budget=char_budget)

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


def test_fit_warns_when_widow_repair_fabrication_is_discarded(monkeypatch, tmp_path):
    """A discarded widow-repair candidate completes the run and names the bullet in warnings."""
    resume = _test_resume()
    requirements = _requirements()

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Return one bullet plus a rejected widow repair for the fit warning path."""
        texts = {b.id: b.text for b in bullets}
        return RewriteOutcome(
            texts=texts,
            widow_repairs_rejected={"exp1_b1": ["Kubernetes"]},
        )

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _FULL_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert result.pages == 1
    assert any(
        "Widow repair was discarded" in w and "exp1_b1: Kubernetes" in w
        for w in result.warnings
    )


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
    # entry count — reached immediately, with no room to grow into at all. The loop
    # never re-rewrites; only the top-up runs, adding one more entry.
    steps = [step["step"] for step in result.trace]
    assert steps[0] == "draft"
    assert "grow" not in steps
    assert "topup-C" in steps
    assert result.bullets_selected == len(entries) + 1
    assert any("top-up limit reached after adding" in w for w in result.warnings)


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




# --------------------------------------------------------------------------------------
# Measured pull-back and the top-up ladder
# --------------------------------------------------------------------------------------


def test_choose_pullbacks_judges_measured_bullets_on_the_pdf_layout():
    width = config.CHARS_PER_LINE
    line_fit = fit_mod.render.LineFit
    texts = {
        # The estimate calls this two nearly-full lines; the PDF shows three with a
        # near-empty last line — the real near-widow.
        "pdf_widow": "a" * (width + int(width * 0.9)),
        # The estimate calls this a near-widow; the PDF shows its last line full.
        "pdf_full": "a" * (width + int(width * 0.1)),
        # Not measured at all: falls back to the estimate, which flags it.
        "unmeasured": "a" * (width + int(width * 0.1)),
    }
    layout = {
        "pdf_widow": line_fit(3, 0.1, float(width)),
        "pdf_full": line_fit(2, 0.9, float(width)),
        "unmeasured": line_fit(2, 0.1, float(width)),
    }
    picked = fit_mod._choose_pullbacks(
        texts, _bullet_fixture(texts), _requirements(), None, {}, count=5,
        layout=layout, measured_ids={"pdf_widow", "pdf_full"},
    )
    assert picked["pdf_widow"] == int(2 * width - config.WIDOW_SAFETY)
    assert "pdf_full" not in picked
    assert "unmeasured" in picked


def _entry_key(bullet_id: str) -> str:
    return bullet_id.split("_b")[0]


def _target_lines() -> int:
    return math.ceil(config.UNDERFLOW_THRESHOLD * config.LINES_PER_PAGE)


def _lines_with_headers(base: int):
    """`pages_for` charging one line per bullet and two per rendered entry over a fixed
    `base` — enough structure for the top-up's bullet-versus-entry arithmetic."""

    def pages_for(texts):
        lines = base + len(texts) + 2 * len({_entry_key(bid) for bid in texts})
        return (1 if lines <= config.LINES_PER_PAGE else 2, lines)

    return pages_for


def _capped_first_draft() -> int:
    """With `max_bullets_per_entry=1`, the first draft is one bullet per chosen entry."""
    return len(fit_mod.choose_entries(_test_resume(), _requirements()))


def test_top_up_adds_back_bullets_the_caps_allow(monkeypatch, tmp_path):
    """The loop stops underfull without growing; step A refills from the chosen entries,
    rewriting only the bullets it adds."""
    monkeypatch.setattr(config, "MAX_GROW_ATTEMPTS", 0)
    calls: list[list[str]] = []

    def fake_rewrite(bullets, requirements, **kwargs):
        calls.append([b.id for b in bullets])
        return _identity_rewrite(bullets, requirements, **kwargs)

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    first: dict[str, int] = {}

    def pages_for(texts):
        # Two lines short of the target on the first draft, one line per bullet after.
        first.setdefault("n", len(texts))
        lines = _target_lines() - 2 + (len(texts) - first["n"])
        return (1 if lines <= config.LINES_PER_PAGE else 2, lines)

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for)
    # A small first draft leaves bullets the caps allow off the page.
    result = fit_mod.fit(
        _test_resume(), _requirements(), target_pages=1, merge_bullets=False,
        max_bullets_per_entry=3, initial_bullet_share=0.5,
    )

    assert len(calls) == 2
    assert len(calls[1]) == 2
    assert result.topped_up == calls[1]
    assert set(calls[1]) <= set(result.bullets)
    assert [s["step"] for s in result.trace] == ["draft", "topup-A"]
    assert not any("full (target" in w for w in result.warnings)


def test_top_up_keeps_one_bullet_past_the_cap_when_that_reaches_the_target(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(config, "MAX_GROW_ATTEMPTS", 0)
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    n = _capped_first_draft()
    # One line short: a single extra bullet in an entry already on the page fills it.
    base = _target_lines() - 1 - n - 2 * n
    _stub_render(monkeypatch, tmp_path, pages_for=_lines_with_headers(base))

    result = fit_mod.fit(
        _test_resume(), _requirements(), target_pages=1, merge_bullets=False,
        max_bullets_per_entry=1,
    )

    assert [s["step"] for s in result.trace] == ["draft", "topup-B"]
    assert len(result.topped_up) == 1
    assert len(result.bullets) == n + 1
    assert not any("full (target" in w for w in result.warnings)


def test_top_up_swaps_a_short_extra_bullet_for_a_new_entry(monkeypatch, tmp_path):
    """Bullet 2 of an entry leaves the page short, so it is taken back out and the
    next-best entry is added instead — which reaches the target."""
    monkeypatch.setattr(config, "MAX_GROW_ATTEMPTS", 0)
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    resume, requirements = _test_resume(), _requirements()
    n = _capped_first_draft()
    base = _target_lines() - 3 - n - 2 * n
    _stub_render(monkeypatch, tmp_path, pages_for=_lines_with_headers(base))

    result = fit_mod.fit(
        resume, requirements, target_pages=1, merge_bullets=False, max_bullets_per_entry=1,
    )

    assert [s["step"] for s in result.trace] == ["draft", "topup-B", "revert", "topup-C"]
    extra = next(s for s in result.trace if s["step"] == "topup-B")["added"][0]
    assert extra not in result.bullets
    chosen = {
        _entry_key(b.id) for e in fit_mod.choose_entries(resume, requirements)
        for b in e.bullets
    }
    new = [bid for bid in result.topped_up if _entry_key(bid) not in chosen]
    assert len(new) == 1 and new[0] in result.bullets
    assert not any("full (target" in w for w in result.warnings)


def test_top_up_restores_the_extra_bullet_when_no_new_entry_fits(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_GROW_ATTEMPTS", 0)
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    resume, requirements = _test_resume(), _requirements()
    chosen = {
        _entry_key(b.id) for e in fit_mod.choose_entries(resume, requirements)
        for b in e.bullets
    }
    n = _capped_first_draft()
    inner = _lines_with_headers(_target_lines() - 3 - n - 2 * n)

    def pages_for(texts):
        pages, lines = inner(texts)
        if any(_entry_key(bid) not in chosen for bid in texts):
            return 2, lines + config.LINES_PER_PAGE  # any new entry overflows
        return pages, lines

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for)
    result = fit_mod.fit(
        resume, requirements, target_pages=1, merge_bullets=False, max_bullets_per_entry=1,
    )

    steps = [s["step"] for s in result.trace]
    assert steps == ["draft", "topup-B", "revert", "topup-C", "revert", "restore"]
    extra = next(s for s in result.trace if s["step"] == "topup-B")["added"][0]
    assert extra in result.bullets
    assert result.topped_up == [extra]
    assert any("overflowed the page" in w for w in result.warnings)


def test_top_up_never_adds_an_entry_from_a_section_the_template_cannot_render(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(config, "MAX_GROW_ATTEMPTS", 0)
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(
        fit_mod, "active_layout", lambda: {"enabled": {"projects": False, "experience": True}}
    )
    _stub_render(monkeypatch, tmp_path, pages_for=lambda texts: (1, _SPARSE_LINES))

    result = fit_mod.fit(
        _test_resume(), _requirements(), target_pages=1, merge_bullets=False,
        max_bullets_per_entry=1,
    )

    assert not any(bid.startswith("proj") for bid in result.bullets)


def test_top_up_repairs_widows_in_the_bullets_it_adds_even_on_reaching_the_target(
    monkeypatch, tmp_path
):
    """Added bullets arrive after the main widow pass; reaching the fill target must not
    skip their own measured pass, and the reported count must cover them."""
    monkeypatch.setattr(config, "MAX_GROW_ATTEMPTS", 0)
    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    first: dict[str, set[str]] = {}

    def pages_for(texts):
        first.setdefault("ids", set(texts))
        lines = _target_lines() - 2 + (len(texts) - len(first["ids"]))
        return (1 if lines <= config.LINES_PER_PAGE else 2, lines)

    def layout_for(texts):
        return {
            bid: fit_mod.render.LineFit(2, 0.2, 100)
            if bid not in first["ids"] and not text.endswith(" fixed")
            else fit_mod.render.LineFit(1, 1.0, 100)
            for bid, text in texts.items()
        }

    _stub_render(monkeypatch, tmp_path, pages_for=pages_for, layout_for=layout_for)
    polished: list[set[str]] = []

    def fake_polish(texts, sources, requirements, **kwargs):
        polished.append(set(kwargs["targets"]))
        return {**texts, **{b: texts[b] + " fixed" for b in kwargs["targets"]}}, 1, 0, {}

    monkeypatch.setattr(fit_mod, "_polish", fake_polish)
    result = fit_mod.fit(
        _test_resume(), _requirements(), target_pages=1, merge_bullets=False,
        max_bullets_per_entry=3, initial_bullet_share=0.5,
    )

    assert result.topped_up
    assert polished == [set(result.topped_up)]
    assert all(result.bullets[b].endswith(" fixed") for b in result.topped_up)
    assert result.widows_remaining == 0


def test_extend_target_also_accepts_a_draft_that_saves_the_last_line():
    targets = {"b": (133, 195), "a": (0, 95)}
    layout = {
        "a": fit_mod.render.LineFit(2, 0.20, 100),
        "b": fit_mod.render.LineFit(2, 0.42, 100),
    }
    assert fit_mod._line_saving_ceilings(targets, layout) == {"b": 95}
