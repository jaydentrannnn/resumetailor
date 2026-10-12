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


def test_legal_certification_stays_the_applicants():
    question = Question(
        "I certify that I have read, fully understand and accept all items of the foregoing "
        "statement.", kind="checkbox",
    )
    assert q.classify(question) is None
