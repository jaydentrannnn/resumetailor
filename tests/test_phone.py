"""Phone shapes for application forms (`apply/phone.py`, plan P4-E E16)."""

from __future__ import annotations

import pytest

from resume_tailor.apply import phone


@pytest.mark.parametrize(
    ("typed", "code", "e164", "national"),
    [
        ("(555) 010-0000", "+1", "+15550100000", "5550100000"),
        ("555.010.0000", "", "+15550100000", "5550100000"),
        ("1-555-010-0000", "+1", "+15550100000", "5550100000"),
        ("+1 555 010 0000", "+44", "+15550100000", "5550100000"),
        ("555-010-0000 ext. 12", "+1", "+15550100000", "5550100000"),
        ("07700 900123", "+44", "+447700900123", "7700900123"),
        ("+44 7700 900123", "+1", "+447700900123", "7700900123"),
        ("0044 7700 900123", "+1", "+447700900123", "7700900123"),
        ("+84 90 123 4567", "+1", "+84901234567", "901234567"),
        ("+353 85 123 4567", "+1", "+353851234567", "851234567"),
    ],
)
def test_shapes(typed, code, e164, national):
    assert phone.e164(typed, code) == e164
    assert phone.national(typed, code) == national


@pytest.mark.parametrize("typed", ["", "555-0100", "12345", "+1 555 010", "call me"])
def test_numbers_that_do_not_parse_are_left_alone(typed):
    assert phone.e164(typed, "+1") is None
    assert phone.national(typed, "+1") is None
