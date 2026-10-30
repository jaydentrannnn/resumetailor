"""Intuitive's screening step (live 2026-10-30): the citizenship list its export question
reveals, and "available to work during the work period" (a profile setting, never guessed)."""

from __future__ import annotations

from datetime import date

import pytest

from resume_tailor.apply.answers import questions as q
from resume_tailor.apply.answers.questions import Question

_LISTED = (
    "Do you hold Citizenship or Permanent Residency status from any of the following "
    "countries or administrative regions? Please select one."
)
_COUNTRIES = (
    "Afghanistan", "China (PRC, including Hong Kong and Macau)", "Crimea, Ukraine",
    "Donetsk, Ukraine", "Vietnam", "None of these",
)
_PERIOD = (
    "Are you available to work during the work period specified in the eligibility section "
    "of the job posting?"
)


def _pick(question: Question, fields: dict[str, str]) -> tuple[str | None, str | None]:
    match = q.classify(question)
    found = q.answers(match, question, q.facts_for(fields, today=date(2026, 10, 30)))
    key = match.key if match else None
    return key, (q.choose(question, key or "", found) if found else None)


@pytest.mark.parametrize(
    ("fields", "picked"),
    [
        ({"country": "United States", "us_citizen": "Yes"}, "None of these"),
        ({"country": "United States", "citizenship": "United States"}, "None of these"),
        # Living in the U.S. on a visa: the citizenship is unknown (Intuitive, 2026-10-30).
        ({"country": "United States", "us_citizen": "No"}, None),
        ({"country": "United States"}, None),
        ({"country": "United States", "citizenship": "Viet Nam"}, "Vietnam"),
        ({"citizenship": "China"}, "China (PRC, including Hong Kong and Macau)"),
        # Three Ukrainian regions: unclear, so the applicant picks.
        ({"citizenship": "Ukraine"}, None),
        # Not on the list, yet never "None of these": the list may spell it differently.
        ({"citizenship": "France"}, None),
        ({}, None),
    ],
)
def test_the_listed_country_comes_from_citizenship_and_home_country(fields, picked):
    question = Question(_LISTED, kind="choice", options=_COUNTRIES)
    assert _pick(question, fields) == ("listed_country", picked)


def test_a_country_list_read_before_its_options_load_is_still_the_list():
    # SmartRecruiters' select loads its options only once opened.
    question = Question(_LISTED, kind="typeahead")
    assert q.classify(question).key == "listed_country"
    facts = q.facts_for({"country": "United States", "us_citizen": "Yes"})
    found = q.answers(q.classify(question), question, facts)
    assert found[0] == "None of these"


def test_a_yes_no_list_question_stays_the_export_question():
    question = Question(
        "Are you a citizen, national or resident of any of the following countries: Iran, "
        "Cuba, North Korea, Syria?", kind="choice", options=("Yes", "No"),
    )
    assert _pick(question, {"country": "United States"}) == ("export_control_country", "No")


@pytest.mark.parametrize(("value", "picked"), [("Yes", "Yes"), ("No", "No"), ("", None)])
def test_the_work_period_question_follows_the_setting(value, picked):
    question = Question(_PERIOD, kind="choice", options=("Yes", "No"))
    fields = {"available_for_work_period": value} if value else {}
    assert _pick(question, fields) == ("available_for_work_period", picked)


@pytest.mark.parametrize(
    "text", ["Availability", "When can you start?", "What is your availability to start?"]
)
def test_start_date_questions_are_not_the_work_period(text):
    assert q.classify(Question(text, kind="text")).key == "earliest_start"
