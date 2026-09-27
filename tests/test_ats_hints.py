"""Tests for ATS selector hints and synonym routing."""

from __future__ import annotations

import re

import pytest

from resume_tailor.apply import ats_hints, workday_flow


def test_canonical_field_keys_match_plan():
    """Every documented flat field key is present."""
    expected = {
            "first_name",
            "middle_name",
        "last_name",
        "full_name",
        "preferred_name",
        "has_preferred_name",
        "email",
        "phone",
        "phone_country_code",
            "phone_country_region",
            "phone_device_type",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        "website",
            "work_authorization",
            "authorized_to_work",
            "authorization_country",
            "requires_sponsorship",
            "requires_sponsorship_future",
            "requires_sponsorship_any",
        "f1_opt_eligible",
            "earliest_start",
            "notice_period",
        "education_start_month",
        "graduation_month",
        "degree_level",
        "major",
        "school",
        "gpa",
        "salary_expectation",
        "salary_expectation_number",
        "salary_hourly",
        "salary_hourly_number",
        "salary_yearly",
        "salary_yearly_number",
        "willing_to_relocate",
        "how_heard",
        "how_heard_detail",
        "gender",
        "race",
        "race_detail",
        "hispanic_latino",
        "veteran_status",
        "disability_status",
        "current_company",
        "current_title",
        "languages",
        "over_18",
        "noncompete",
        # Profile fields added for students (plan PR3).
        "visa_status",
        "class_year",
        "school_email",
        "security_clearance",
        "drivers_license",
        "hours_per_week",
    }
    assert expected == ats_hints.CANONICAL_FIELD_KEYS


def test_ats_hint_selectors_look_like_css():
    """Hint keys resemble CSS selectors or reserved pseudo-keys."""
    for ats, hints in ats_hints.ATS_HINTS.items():
        for selector in hints:
            assert ats_hints.looks_like_css_selector(selector), (
                f"{ats} hint key {selector!r} does not look like CSS"
            )


def test_ats_hint_values_are_known_keys():
    """Every hint row maps selectors to canonical or reserved fill-runner keys."""
    for hints in ats_hints.ATS_HINTS.values():
        for selector, value in hints.items():
            assert ats_hints.is_valid_hint_entry(selector, value)


def test_f1_opt_synonym_precedes_sponsorship():
    """F-1/OPT/CPT labels route to ``f1_opt_eligible`` before sponsorship."""
    sponsorship_idx = next(
        i for i, (_, key) in enumerate(ats_hints.SYNONYMS) if key == "requires_sponsorship"
    )
    f1_idx = next(
        i for i, (_, key) in enumerate(ats_hints.SYNONYMS) if key == "f1_opt_eligible"
    )
    assert f1_idx < sponsorship_idx
    f1_pattern = ats_hints.SYNONYMS[f1_idx][0]
    assert re.search(f1_pattern, "Are you eligible for OPT/CPT?", re.IGNORECASE)


@pytest.mark.parametrize(
    ("label", "key"),
    [
        # A live Workday step (2026-09): the third appears after the second is answered Yes.
        ("Are you over the age of 18?", "over_18"),
        ("Are you legally permitted to work in the country where this job is located?", "authorized_to_work"),
        ("If hired, can you provide proof of eligibility?", "authorized_to_work"),
        ("Are you eligible to work in the US?", "authorized_to_work"),
        ("Can you provide documentation of your employment eligibility?", "authorized_to_work"),
        ("Are you legally authorized to work in the United States?", "authorized_to_work"),
        ("Are you at least 18 years old?", "over_18"),
        ("Are you 18 years of age or older?", "over_18"),
        ("Are you currently subject to a non-compete agreement?", "noncompete"),
        ("To your knowledge are you currently subject to any non-compete or non-solicitation restrictions?", "noncompete"),
        ("Are you bound by a noncompete or restrictive covenant?", "noncompete"),
        # Neighbours that must keep their own meaning.
        ("Which country do you live in?", "country"),
        ("Country", "country"),
        ("Will you now or in the future require sponsorship?", "requires_sponsorship_any"),
        ("Are you eligible for OPT/CPT?", "f1_opt_eligible"),
    ],
)
def test_eligibility_questions_map_to_profile_facts(label, key):
    assert workday_flow.key_for_label(label, ats_hints.SYNONYMS) == key


@pytest.mark.parametrize(
    "label",
    [
        "Are you under 18?",  # the inverse of the profile answer
        "If you are under the age of 18, please list a guardian",
        "Can you provide proof of degree completion?",
        "Can you provide proof of veteran status?",
        "Are you able to work weekends?",
        "Do you hold a security clearance eligibility?",
    ],
)
def test_lookalike_questions_do_not_borrow_eligibility_answers(label):
    assert workday_flow.key_for_label(label, ats_hints.SYNONYMS) not in {"over_18", "authorized_to_work"}


def test_eligibility_patterns_span_label_line_breaks():
    """Workday legends can wrap: the keyword may sit on the label's second line."""
    label = "Legal eligibility\nAre you legally permitted to work in this country?"
    assert workday_flow.key_for_label(label, ats_hints.SYNONYMS) == "authorized_to_work"


def test_hints_for_known_ats():
    """``hints_for`` returns a copy of the configured hint map."""
    hints = ats_hints.hints_for("greenhouse")
    assert hints["#email"] == "email"
    hints["#email"] = "mutated"
    assert ats_hints.ATS_HINTS["greenhouse"]["#email"] == "email"
