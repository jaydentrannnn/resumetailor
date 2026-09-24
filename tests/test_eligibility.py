"""Hermetic tests for bachelor-only eligibility prefilter."""

from __future__ import annotations

from resume_tailor.apply import eligibility


def test_inclusive_degree_wording_passes():
    result = eligibility.check_text(
        "Bachelor's, Master's, or PhD in Computer Science"
    )
    assert result.passed
    assert result.flags == []


def test_phd_only_rejects():
    result = eligibility.check_text("Currently pursuing a PhD in ML")
    assert not result.passed
    assert "advanced_degree_without_bachelor" in result.reasons


def test_ms_or_phd_required_rejects():
    result = eligibility.check_text("MS or PhD required")
    assert not result.passed
    assert "advanced_degree_without_bachelor" in result.reasons


def test_baccalaureate_counts_as_a_bachelor_path():
    # AmFam intern posting wording (2026-09).
    result = eligibility.check_text(
        "Must be currently seeking a baccalaureate, masters, or doctoral degree and be "
        "enrolled in an accredited college or university on a full-time basis."
    )
    assert result.passed


def test_bs_ms_passes():
    result = eligibility.check_text("BS/MS in CS or equivalent")
    assert result.passed


def test_ms_office_not_advanced_degree():
    result = eligibility.check_text("Proficient in MS Office")
    assert result.passed
    assert result.reasons == []


def test_five_plus_years_rejects():
    result = eligibility.check_text("5+ years of professional experience")
    assert not result.passed
    assert "requires_5_years" in result.reasons


def test_two_to_three_years_preferred_flags():
    result = eligibility.check_text("2-3 years experience preferred")
    assert result.passed
    assert any(f.startswith("years_") for f in result.flags)


def test_company_history_number_does_not_read_as_years_requirement():
    """Regression: "over 175 years" (company history boilerplate) once misparsed as a
    17-year floor because the years regex's `\\d{1,2}` group could start mid-number."""
    result = eligibility.check_text(
        "We have a deep tradition of respecting individual differences. Doing so has "
        "been core to our success for over 175 years."
    )
    assert result.passed
    assert result.reasons == []


def test_title_phd_research_intern_rejects():
    result = eligibility.check_title("PhD Research Intern")
    assert not result.passed
    assert "title_advanced_degree" in result.reasons


def test_title_level_ii_flags_only():
    result = eligibility.check_title("Software Engineer II")
    assert result.passed
    assert "title_level_token" in result.flags


def test_title_senior_rejects():
    result = eligibility.check_title("Senior Software Engineer")
    assert not result.passed
    assert "title_senior" in result.reasons


def test_title_intern_passes():
    result = eligibility.check_title("Software Engineer Intern - Summer 2027")
    assert result.passed
    assert result.reasons == []


def test_company_age_boilerplate_is_not_a_years_requirement():
    """Regression (CAI, Workday R8551): "over 40 years of excellence" is company
    history, not an experience floor — it once hard-rejected an internship."""
    result = eligibility.check_text(
        "We have over 40 years of excellence in uniting talent and technology to "
        "power the possible for our clients, colleagues, and communities."
    )
    assert result.passed
    assert result.reasons == []
    assert result.flags == []


def test_years_without_experience_nearby_are_ignored():
    result = eligibility.check_text("Our team has grown for 3 years straight.")
    assert result.passed
    assert result.flags == []


def test_years_above_plausible_ceiling_are_ignored():
    """Intern/new-grad boards never really ask for more than 5 years."""
    result = eligibility.check_text("8+ years of professional experience required")
    assert result.passed
    assert result.reasons == []


def test_intern_title_downgrades_years_floor_to_flag():
    text = "5+ years of professional experience"
    assert not eligibility.check_text(text, role="Data Analyst").passed
    result = eligibility.check_text(text, role="Data Analyst Intern")
    assert result.passed
    assert "years_5" in result.flags
