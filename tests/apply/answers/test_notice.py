"""Notice period: parsing, unit conversion, option matching, profile sync."""

import pytest

from resume_tailor.apply.answers import notice
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.forms.field_matcher import match_option
from resume_tailor.apply.forms.field_types import ObservedOption

OPTIONS = ["Immediately", "Less than 2 weeks", "2 weeks", "2-4 weeks", "1 month", "More than 1 month", "3+ months"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Two weeks", (2, "week")), ("30 days", (30, "day")), ("immediately", (0, "day")),
     ("1 month", (1, "month")), ("negotiable", None), ("", None)],
)
def test_parse(text, expected):
    assert notice.parse(text) == expected


@pytest.mark.parametrize(
    ("value", "unit", "picked"),
    [(0, "day", "Immediately"), (1, "week", "Less than 2 weeks"), (2, "week", "2 weeks"),
     (3, "week", "2-4 weeks"), (1, "month", "1 month"), (6, "week", "More than 1 month"),
     (3, "month", "3+ months")],
)
def test_pick_option_converts_units(value, unit, picked):
    assert OPTIONS[notice.pick_option(OPTIONS, value, unit)] == picked


def test_pick_option_without_a_fit_is_none():
    assert notice.pick_option(["Remote", "Hybrid"], 2, "week") is None


def test_for_label_uses_the_unit_the_question_names():
    assert notice.for_label("Notice period (in days)", 2, "week") == "14"
    assert notice.for_label("Weeks of notice", 14, "day") == "2"
    assert notice.for_label("Notice period", 2, "week") == "2 weeks"


def test_match_option_converts_through_the_matcher():
    options = [ObservedOption(option_id=str(i), label=label, value=label) for i, label in enumerate(OPTIONS)]
    result = match_option(options, "3 weeks", key="notice_period")
    assert (result.status, options[int(result.option_id)].label) == ("matched", "2-4 weeks")


def test_profile_parses_legacy_text_and_prefers_the_number():
    legacy = ApplicantProfile.model_validate({"notice_period": "Two weeks"})
    assert (legacy.notice_period_value, legacy.notice_period_unit, legacy.notice_period) == (2, "week", "2 weeks")
    structured = ApplicantProfile.model_validate(
        {"notice_period_value": 3, "notice_period_unit": "day", "notice_period": "stale"}
    )
    assert structured.notice_period == "3 days"
    vague = ApplicantProfile.model_validate({"notice_period": "negotiable"})
    assert (vague.notice_period_value, vague.notice_period) == (None, "negotiable")
