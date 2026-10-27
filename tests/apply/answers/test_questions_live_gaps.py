"""Questions left blank in live Workday fills on 2026-10-12 (Aptiv)."""

from __future__ import annotations

from datetime import date

import pytest

from resume_tailor.apply.answers import form_facts
from resume_tailor.apply.answers import questions as q
from resume_tailor.apply.answers.questions import Question

FACTS = q.facts_for(
    {"current_company": "Age of Learning Inc.", "current_title": "AI Chatbot Engineer Intern"},
    company="Aptiv", role="Linux Software Development Intern",
    employers=["Age of Learning Inc."], experience_titles=["AI Chatbot Engineer Intern"],
    today=date(2026, 10, 12),
)


def _answer(question: Question) -> tuple[str | None, str | None]:
    match = q.classify(question)
    found = q.answers(match, question, FACTS)
    if question.options:
        return (match.key if match else None), q.choose(question, match.key if match else "", found)
    return (match.key if match else None), (found[0] if found else None)


def test_long_direct_employer_question_gets_the_current_employer():
    question = Question(
        "Who is your current or most recent employer? (Enter the legal company name)",
        kind="text",
    )
    assert _answer(question) == ("current_company", "Age of Learning Inc.")


def test_long_question_merely_mentioning_an_employer_is_not_the_employer_field():
    question = Question(
        "Have you ever been employed by a company that is a competitor of your current employer?",
        options=("Yes", "No"),
    )
    assert q.classify(question) is None or q.classify(question).key != "current_company"


@pytest.mark.parametrize("text", [
    "Do you consent for your data to be further processed for other job opportunities at Aptiv?",
    "May we keep your information on file for future job opportunities?",
    "I agree to join the talent community so recruiters can contact me about similar roles",
])
def test_talent_pool_consent_is_declined(text):
    question = Question(text, options=("Yes", "No"))
    assert _answer(question) == (form_facts.TALENT_POOL, "No")


def test_consent_to_process_this_application_is_not_a_talent_pool():
    text = "I consent to the processing of my personal data for this application"
    assert not form_facts.talent_pool(text)
    assert form_facts.semantic_key(text) == form_facts.ACKNOWLEDGEMENT


def test_required_certification_is_agreed_to():
    question = Question(
        "I certify that I have read, fully understand and accept all items of the foregoing "
        "statement.", kind="checkbox",
    )
    assert q.classify(question).key == "routine_acknowledgement"


# -- Itron / Aptiv / Workday questions from the 2026-10-12 rerun -------------------------

PROFILE_FACTS = q.Facts(
    {
        "us_person_status": "No",
        "us_citizen": "No",
        "citizenship": "Vietnam",
        "government_employee": "No",
        "conflict_of_interest": "No",
        "relatives_at_company": "No",
        "auto_accept_notices": "Yes", "auto_accept_agreements": "Yes",
        "first_name": "Ada",
        "last_name": "Lovelace",
    },
    today=date(2026, 10, 12),
)


def _live(question: Question) -> tuple[str | None, str | None]:
    match = q.classify(question)
    found = q.answers(match, question, PROFILE_FACTS) if match else []
    if question.options:
        return (match.key if match else None), q.choose(question, match.key if match else "", found)
    return (match.key if match else None), (found[0] if found else None)


@pytest.mark.parametrize(
    "text,options,expected",
    [
        (
            "Are you a US Citizen, Lawful Permanent Resident, Asylee, or Refugee?",
            ("Yes", "No"), ("us_person_status", "No"),
        ),
        (
            "Do you have any business or personal relationship that may present a conflict of "
            "interest with Itron?",
            ("Yes", "No"), ("conflict_of_interest", "No"),
        ),
        (
            "Are you currently or have you ever been employed by a government agency?",
            ("Yes", "No"), ("government_employee", "No"),
        ),
        (
            "Are you related to a current Itron employee?",
            ("Yes", "No"), ("relatives_at_company", "No"),
        ),
        (
            "Are you a citizen or national of Cuba, Iran, North Korea, Syria, or Russia?",
            ("Yes", "No"), ("export_control_country", "No"),
        ),
        (
            "I understand and agree that any offer is contingent on a background check.",
            ("Yes", "No"), ("routine_acknowledgement", "Yes"),
        ),
        (
            "Restricted Party Screening Aptiv/Windriver will be conducting restricted party screening "
            "as required by law and company policy for this position. I understand my "
            "application information will be checked against government watchlists and "
            "sanctions databases, and that this screening is mandatory for consideration. I "
            "confirm my application information is accurate and acknowledge that screening "
            "results may affect my employment eligibility.*",
            ("I acknowledge", "I do not acknowledge"),
            ("routine_acknowledgement", "I acknowledge"),
        ),
    ],
)
def test_rerun_questions_are_answered_from_facts(text, options, expected):
    assert _live(Question(text, kind="choice", options=options)) == expected


def test_country_of_citizenship_is_the_profile_citizenship():
    assert _live(Question("Country of citizenship", kind="text")) == ("citizenship", "Vietnam")


@pytest.mark.parametrize(
    "text,help_text,expected",
    [
        ("Type 'I AGREE' to accept the terms", "", "I AGREE"),
        ("Electronic signature", "Type your full legal name to sign", "Ada Lovelace"),
        ("Date", "", "10/12/2026"),
    ],
)
def test_typed_consents_are_filled(text, help_text, expected):
    question = Question(text, kind="text", help_text=help_text)
    assert _live(question)[1] == expected


def test_typed_consent_needs_the_setting_and_never_types_a_hint():
    question = Question("Type 'I AGREE' to accept the terms", kind="text")
    match = q.classify(question)
    assert q.answers(match, question, q.Facts({})) == []
    assert form_facts.typed_consent("If none, type 'N/A'") == ""


def test_optional_marketing_opt_in_is_declined():
    question = Question(
        "I agree to receive marketing emails about future events", kind="choice",
        options=("Yes", "No"),
    )
    assert _live(question)[1] == "No"


def test_government_service_is_not_previous_employment():
    question = Question(
        "Have you ever worked for the federal government?", kind="choice", options=("Yes", "No")
    )
    assert _live(question)[0] == "government_employee"
