"""Deterministic salary answers: parsing, the range rule, units and formats."""

from __future__ import annotations

import pytest

from resume_tailor.apply import packet, salary
from resume_tailor.apply.profile import ApplicantProfile
from resume_tailor.apply.salary import Pay
from tests.fixtures import synthetic_resume

_SENTENCE = "Open to discussing; otherwise $60k-80k/yr or $40-$45/hour depending on the role."


@pytest.mark.parametrize(
    ("text", "pays"),
    [
        ("Base Hourly Pay $29 USD. (To comply with export rules)", [Pay(29, 29, "hour")]),
        ("$70,000 – $90,000 per year", [Pay(70_000, 90_000, "year")]),
        ("$25/hr", [Pay(25, 25, "hour")]),
        ("$30-$40/hr", [Pay(30, 40, "hour")]),
        ("The pay range is $22.00 - $28.50", [Pay(22, 28.5, "hour")]),
        ("$60-80k", [Pay(60_000, 80_000, "year")]),
        ("Level I - Minimum $18.00 - Maximum $20.00", [Pay(18, 20, "hour")]),
        ("We raised $5 billion and offer a 401k match.", []),
    ],
)
def test_parse_pay(text, pays):
    assert salary.parse_pay(text) == pays


def test_profile_range_is_seeded_from_the_sentence_once():
    profile = ApplicantProfile(salary_expectation=_SENTENCE)
    assert (profile.salary_hourly_min, profile.salary_hourly_max) == (40, 45)
    assert (profile.salary_yearly_min, profile.salary_yearly_max) == (60_000, 80_000)
    edited = ApplicantProfile(salary_expectation=_SENTENCE, salary_hourly_max=50)
    assert edited.salary_hourly_max == 50
    assert edited.salary_yearly_max is None  # a user-set range is never re-seeded
    cleared = ApplicantProfile.model_validate({"salary_expectation": _SENTENCE, "salary_hourly_max": None})
    assert cleared.salary_hourly_max is None and cleared.salary_yearly_max is None
    assert ApplicantProfile.model_validate_json(profile.model_dump_json()).salary_hourly_max == 45


@pytest.mark.parametrize(
    ("posted", "answer"),
    [
        (Pay(20, 30, "hour"), 30),  # below my range: the posting's top
        (Pay(35, 50, "hour"), 45),  # overlapping: the highest number both allow
        (Pay(42, 44, "hour"), 44),  # inside: the posting's top
        (Pay(60, 70, "hour"), 45),  # above: my top
        (None, 45),  # nothing stated: my top
        (Pay(104_000, 104_000, "year"), 45),  # converted at 2080 h/yr, then capped
    ],
)
def test_answer_is_min_of_posted_top_and_my_top(posted, answer):
    assert salary.answer_value("hour", posted, {"hour": 45, "year": 80_000}) == answer


def test_a_missing_unit_is_converted_from_the_other_and_no_range_means_no_answer():
    assert salary.answer_value("year", None, {"hour": 45, "year": None}) == 45 * 2080
    assert salary.answer_value("hour", None, {"hour": None, "year": None}) is None


def test_salary_fields_default_unit_and_formats():
    intern = salary.salary_fields(role="College Intern - Records", listing_salary="", jd_text="", hourly_max=45, yearly_max=80_000)
    assert intern["salary_expectation"] == "$45/hour"
    assert intern["salary_expectation_number"] == "45"
    assert intern["salary_yearly"] == "$80,000/year"
    engineer = salary.salary_fields(role="Engineer", listing_salary="", jd_text="Pay: $90,000 - $120,000 annually", hourly_max=45, yearly_max=80_000)
    assert engineer["salary_expectation"] == "$80,000/year"
    listed = salary.salary_fields(role="Intern", listing_salary="$25/hr", jd_text="$99/hr", hourly_max=45, yearly_max=80_000)
    assert listed["salary_expectation"] == "$25/hour"
    assert salary.salary_fields(role="Intern", listing_salary="", jd_text="", hourly_max=None, yearly_max=None) == {}


def test_format_keeps_cents_only_when_needed():
    assert salary.format_value(28.5, "hour", numeric=False) == "$28.50/hour"
    assert salary.format_value(28.5, "hour", numeric=True) == "28.5"
    assert salary.format_value(80_000, "year", numeric=True) == "80000"


def test_packet_flags_a_preferred_name_that_differs_from_the_first_name():
    resume = synthetic_resume()
    fields = packet.build_fields(ApplicantProfile(first_name="Alexander", preferred_name="Alex"), resume)
    assert fields["has_preferred_name"] == "Yes"
    same = packet.build_fields(ApplicantProfile(first_name="Alex", preferred_name="alex"), resume)
    assert "has_preferred_name" not in same
    assert "salary_expectation" not in fields  # added per posting by the fill runner
