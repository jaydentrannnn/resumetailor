"""Veteran self-identification: every profile category against real forms' option lists.

The corpus (`fixtures/eeo/veteran_options.json`) holds the wordings forms actually use;
a new wording that fails in a live run belongs there, not in a one-off regex test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor.apply.answers.profile import EEOAnswers
from resume_tailor.apply.forms.field_matcher import closest_option, eeo_patterns, veteran_category

_CORPUS = json.loads((Path(__file__).parents[2] / "fixtures" / "eeo" / "veteran_options.json").read_text(encoding="utf-8"))
_CASES = [
    (name, category, entry["options"], expected)
    for name, entry in _CORPUS["lists"].items()
    for category, expected in entry["expected"].items()
]


@pytest.mark.parametrize(("form", "category", "options", "expected"), _CASES,
                         ids=[f"{form}-{category}" for form, category, _o, _e in _CASES])
def test_each_category_picks_its_option_or_none(form, category, options, expected):
    assert closest_option(options, category, key="veteran_status") == expected


@pytest.mark.parametrize(("form", "category", "options", "expected"), _CASES,
                         ids=[f"{form}-{category}" for form, category, _o, _e in _CASES])
def test_the_order_of_options_never_changes_the_pick(form, category, options, expected):
    assert closest_option(list(reversed(options)), category, key="veteran_status") == expected


@pytest.mark.parametrize(("answer", "category"), [
    ("No", "not_veteran"), ("yes", "protected"), ("decline", "decline"),
    ("I don't wish to answer", "decline"), ("not_veteran", "not_veteran"),
    ("I identify as a veteran, just not a protected veteran", "veteran_not_protected"),
    ("I am not a veteran", "not_veteran"),
    # "not a protected veteran" could be either of two categories: not read as one.
    ("I am not a protected veteran", None), ("", None),
])
def test_older_answers_read_as_a_category(answer, category):
    assert veteran_category(answer) == category


def test_a_legacy_profile_answer_is_converted_and_flagged_for_confirmation():
    migrated = EEOAnswers.model_validate({"veteran": "No"})
    assert (migrated.veteran, migrated.veteran_legacy) == ("not_veteran", "No")
    # A decline or a blank means what it always meant: nothing to confirm.
    assert EEOAnswers.model_validate({"veteran": "Decline"}).veteran_legacy == ""
    assert EEOAnswers.model_validate({"veteran": ""}).veteran == ""
    # An answer no category names falls back to declining, and is flagged.
    unclear = EEOAnswers.model_validate({"veteran": "I am not a protected veteran"})
    assert (unclear.veteran, unclear.veteran_legacy) == ("decline", "I am not a protected veteran")
    # A converted profile saves the category, and keeps asking until confirmed.
    assert EEOAnswers.model_validate(migrated.model_dump()) == migrated


def test_filler_gets_the_same_ordered_tiers():
    tiers = eeo_patterns({"veteran_status": "not_veteran"})["veteran_status"]
    assert isinstance(tiers, list) and len(tiers) == 3
