"""Pure screening rules: work-restriction blocks, seniority, and the short label."""

from __future__ import annotations

import pytest

from resume_tailor.apply.funnel import screen as screen_mod
from resume_tailor.apply.funnel.eligibility import is_early_career_title
from resume_tailor.apply.funnel.screen import (
    ScreenSettings,
    check_blocks,
    screen_label,
    seniority_reasons,
)

_RTX = (
    "Position Role Type: Onsite. Active and transferable U.S. government issued security "
    "clearance is required prior to start date. U.S. citizenship is required, as only U.S. "
    "citizens are eligible for a security clearance. Assist in real-time embedded software."
)
_CACI = (
    "Must be legally authorized to work in the United States without the need for employer "
    "sponsorship.\nMust be able to obtain and maintain applicable security clearance\n"
    "Working knowledge of AI."
)
_ASTRANIS = (
    "Base Hourly Pay $29 USD. (To comply with U.S. Government space technology export "
    "regulations, applicant must be a U.S. citizen, lawful permanent resident of the United "
    "States, or other protected individual as defined by 8 U.S.C. 1324b(a)(3)) Our mission."
)


def test_check_blocks_names_the_restriction_and_quotes_the_sentence():
    reasons, evidence = check_blocks(_RTX)
    assert reasons == ["citizenship_required", "clearance_required"]
    assert evidence[0] == (
        "U.S. citizenship is required, as only U.S. citizens are eligible for a security "
        "clearance."
    )
    assert evidence[1].startswith("Active and transferable U.S. government issued security")


def test_check_blocks_uses_line_breaks_as_sentence_ends():
    reasons, evidence = check_blocks(_CACI)
    assert reasons == ["clearance_required"]
    assert evidence == ["Must be able to obtain and maintain applicable security clearance"]


def test_long_evidence_is_trimmed_around_the_match():
    reasons, evidence = check_blocks(_ASTRANIS)
    assert reasons == ["citizenship_required"]
    assert "U.S. citizen" in evidence[0]
    assert len(evidence[0]) <= 162


def test_custom_block_pattern_keeps_the_legacy_wording():
    reasons, _ = check_blocks("Must relocate to Antarctica.", ScreenSettings(block_patterns=["antarctica"]))
    assert reasons == ["blocked by pattern 'antarctica'"]


def test_intern_title_outranks_the_models_seniority():
    assert seniority_reasons("mid", "Analytics Intern") == ([], ["seniority_mismatch"])
    assert seniority_reasons("mid", "Data Analyst")[0] == [
        "seniority 'mid' not in ['intern', 'entry']"
    ]
    assert seniority_reasons("intern", "Data Analyst") == ([], [])
    assert is_early_career_title("New Grad Software Engineer")


@pytest.mark.parametrize(
    ("reasons", "label"),
    [
        ([], None),
        (["citizenship_required"], "Citizenship required"),
        (["clearance_required"], "Clearance required"),
        (["citizenship_required", "clearance_required"], "Citizenship required +1"),
        # Legacy rows stored the regex source itself.
        (["blocked by pattern '\\\\bU\\\\.?S\\\\.? citizen'"], "Citizenship required"),
        (["blocked by pattern 'security clearance'"], "Clearance required"),
        (["seniority 'mid' not in ['intern', 'entry']"], "Too senior"),
        (["title_senior"], "Senior title"),
        (["advanced_degree_without_bachelor"], "Grad degree only"),
        (["title_advanced_degree"], "Grad degree only"),
        (["requires_5_years"], "5+ yrs experience"),
        (["must-have coverage 11% < 34%", "4 no_evidence must-haves > 3"], "Low skill match"),
        (["text_block:crypto"], "Blocked term"),
        (["blocked by pattern 'antarctica'"], "Blocked term"),
    ],
)
def test_screen_label(reasons, label):
    assert screen_label(reasons) == label


def test_default_block_patterns_all_have_names():
    """A default pattern without a name would store its regex source as the reason."""
    assert set(ScreenSettings().block_patterns) == set(screen_mod._NAMED_BLOCKS)
