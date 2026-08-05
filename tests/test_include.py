"""Tests for `include.py` — what a run leaves out, applied as a pure resume transform.

No LLM, no render, no Word — `apply` operates on a `MasterResume` in memory, same
no-network convention as the rest of the suite.
"""

from __future__ import annotations

from resume_tailor.data import load
from resume_tailor.include import IncludeOptions, apply, contact_order, validate


def _resume():
    return load()


def test_apply_with_defaults_changes_nothing_but_gpa_flag():
    """Every education entry's show_gpa is forced by the default (True), everything
    else survives untouched."""
    resume = _resume()
    result = apply(resume, IncludeOptions())
    assert len(result.experience) == len(resume.experience)
    assert len(result.projects) == len(resume.projects)
    assert all(edu.show_gpa for edu in result.education)


def test_apply_drops_named_experience_and_project_ids():
    resume = _resume()
    exp_id = resume.experience[0].id
    proj_id = resume.projects[0].id
    result = apply(
        resume,
        IncludeOptions(exclude_experience=[exp_id], exclude_projects=[proj_id]),
    )
    assert exp_id not in {e.id for e in result.experience}
    assert proj_id not in {p.id for p in result.projects}
    assert len(result.experience) == len(resume.experience) - 1
    assert len(result.projects) == len(resume.projects) - 1


def test_apply_ignores_unknown_ids():
    """A stale exclusion (entry renamed/deleted since it was saved) is a no-op, not
    an error — the entry simply renders."""
    resume = _resume()
    result = apply(
        resume,
        IncludeOptions(exclude_experience=["no-such-id"], exclude_projects=["no-such-id"]),
    )
    assert len(result.experience) == len(resume.experience)
    assert len(result.projects) == len(resume.projects)


def test_apply_forces_gpa_off():
    resume = _resume()
    result = apply(resume, IncludeOptions(gpa=False))
    assert all(not edu.show_gpa for edu in result.education)


def test_apply_clears_coursework_when_disabled():
    resume = _resume()
    assert any(edu.coursework for edu in resume.education)  # sanity: fixture has some
    result = apply(resume, IncludeOptions(coursework=False))
    assert all(not edu.coursework for edu in result.education)


def test_apply_keeps_coursework_when_enabled():
    resume = _resume()
    result = apply(resume, IncludeOptions(coursework=True))
    for original, new in zip(resume.education, result.education):
        assert new.coursework == original.coursework


def test_apply_does_not_mutate_its_input():
    resume = _resume()
    original_exp_count = len(resume.experience)
    original_gpa_flags = [edu.show_gpa for edu in resume.education]
    apply(
        resume,
        IncludeOptions(
            gpa=False, coursework=False, exclude_experience=[resume.experience[0].id]
        ),
    )
    assert len(resume.experience) == original_exp_count
    assert [edu.show_gpa for edu in resume.education] == original_gpa_flags


def test_validate_passes_when_something_remains():
    resume = _resume()
    assert validate(resume, IncludeOptions()) == []


def test_validate_catches_a_fully_excluded_resume():
    resume = _resume()
    options = IncludeOptions(
        exclude_experience=[e.id for e in resume.experience],
        exclude_projects=[p.id for p in resume.projects],
    )
    problems = validate(resume, options)
    assert problems
    assert "nothing would render" in problems[0]


def test_validate_passes_when_only_experience_excluded_but_projects_remain():
    resume = _resume()
    options = IncludeOptions(exclude_experience=[e.id for e in resume.experience])
    assert validate(resume, options) == []


def test_contact_order_prefers_explicit_option():
    layout = {"contact_field_order": ["location", "email", "phone", "linkedin", "github"]}
    options = IncludeOptions(contact_fields=["email", "linkedin"])
    assert contact_order(options, layout) == ["email", "linkedin"]


def test_contact_order_falls_back_to_layout_when_option_is_none():
    layout = {"contact_field_order": ["email", "phone"]}
    assert contact_order(IncludeOptions(), layout) == ["email", "phone"]


def test_contact_order_returns_none_when_neither_is_set():
    assert contact_order(IncludeOptions(), {}) is None


def test_section_order_none_is_a_noop():
    resume = _resume()
    result = apply(resume, IncludeOptions())
    assert [s.id for s in result.sections] == [s.id for s in resume.sections]


def test_section_order_reorders_named_sections_first():
    resume = _resume()
    ids = [s.id for s in resume.sections]
    reversed_ids = list(reversed(ids))
    result = apply(resume, IncludeOptions(section_order=reversed_ids))
    assert [s.id for s in result.sections] == reversed_ids


def test_section_order_appends_unnamed_sections_after_named_ones_in_original_order():
    resume = _resume()
    ids = [s.id for s in resume.sections]
    assert len(ids) >= 2  # sanity: fixture has more than one section
    last_id = ids[-1]
    result = apply(resume, IncludeOptions(section_order=[last_id]))
    expected = [last_id] + [i for i in ids if i != last_id]
    assert [s.id for s in result.sections] == expected


def test_section_order_ignores_unknown_ids():
    resume = _resume()
    ids = [s.id for s in resume.sections]
    result = apply(resume, IncludeOptions(section_order=["no-such-section", *ids]))
    assert [s.id for s in result.sections] == ids


def test_section_order_applies_after_section_exclusion():
    resume = _resume()
    ids = [s.id for s in resume.sections]
    assert len(ids) >= 2
    excluded, kept = ids[0], ids[1:]
    result = apply(
        resume,
        IncludeOptions(exclude_sections=[excluded], section_order=list(reversed(kept))),
    )
    assert [s.id for s in result.sections] == list(reversed(kept))
