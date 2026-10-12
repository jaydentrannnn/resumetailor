"""Option matching for tenant-specific wording: language scales and phone device types."""

from __future__ import annotations

import pytest

from resume_tailor.apply.forms.field_matcher import match_option
from resume_tailor.apply.forms.field_types import ObservedOption


def _options(*labels: str) -> list[ObservedOption]:
    return [ObservedOption(option_id=str(i), label=label) for i, label in enumerate(labels)]


def _picked(labels: tuple[str, ...], target: str, key: str) -> str | None:
    options = _options(*labels)
    result = match_option(options, target, key=key)
    if result.status != "matched":
        return None
    return next(o.label for o in options if o.option_id == result.option_id)


@pytest.mark.parametrize(("labels", "target", "picked"), [
    (("Poor", "Fair", "Good", "Excellent"), "Fluent", "Excellent"),
    (("Low", "Medium", "High"), "Fluent", "High"),
    (("Poor", "Fair", "Good", "Very Good", "Excellent"), "Native", "Excellent"),
    (("Beginner", "Intermediate", "Advanced", "Proficient"), "Proficient", "Proficient"),
    (("Basic", "Intermediate", "Advanced", "Fluent"), "Native", "Fluent"),
])
def test_language_scales_by_rank(labels, target, picked):
    assert _picked(labels, target, "language_level") == picked


def test_language_level_never_rounds_up():
    assert _picked(("Native", "Bilingual"), "Fluent", "language_level") is None


@pytest.mark.parametrize(("labels", "picked"), [
    (("Home", "Personal Cell", "Work"), "Personal Cell"),
    (("Landline", "Mobile - Personal", "Mobile - Work"), "Mobile - Personal"),
    (("Home", "Cellular"), "Cellular"),
    (("Home", "Work Mobile"), "Work Mobile"),
])
def test_phone_device_type_finds_the_mobile_option(labels, picked):
    assert _picked(labels, "Mobile", "phone_device_type") == picked


def test_phone_device_type_does_not_guess_between_two_personal_mobiles():
    assert _picked(("Personal Cell", "Mobile Phone 2"), "Mobile", "phone_device_type") is None
