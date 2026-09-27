"""The decision layer (`apply/questions.py`) on questions real forms asked.

Each row is a question a fill got wrong or left empty (September 2026 fill reports:
AbbVie and RRS on SmartRecruiters, Quora and Ramp on Ashby, GCM on Greenhouse), with the
fact it asks for and the answer the applicant below should get.
"""

from __future__ import annotations

from datetime import date

import pytest

from resume_tailor.apply import questions as q
from resume_tailor.apply.questions import Question

YES_NO = ("Yes", "No")

FIELDS = {
    "first_name": "Alex", "last_name": "Doe", "email": "alex@example.com",
    "phone": "(555) 010-0000", "city": "Fountain Valley", "state": "California",
    "country": "United States", "school": "State University", "major": "Computer Science",
    "degree_level": "Bachelors", "degree_name": "Bachelor of Science",
    "graduation_month": "2027-06", "education_start_month": "2023-09", "gpa": "3.7/4.0",
    "authorized_to_work": "Yes", "requires_sponsorship": "No",
    "requires_sponsorship_future": "No", "requires_sponsorship_any": "No",
    "willing_to_relocate": "Yes", "noncompete": "No", "gender": "Male", "race": "Asian",
    "veteran_status": "not_veteran", "disability_status": "No",
}
FACTS = q.facts_for(
    FIELDS, company="AbbVie", role="2027 Business Technology Solutions Intern",
    employers=["Acme Corp", "Campus IT"],
    experience_titles=["AI Chatbot Engineer Intern", "Computer Support Specialist"],
    today=date(2026, 9, 27),
)


def _answer(question: Question, facts: q.Facts = FACTS) -> tuple[str | None, str | None]:
    match = q.classify(question)
    key = match.key if match else None
    found = q.answers(match, question, facts)
    if question.options:
        return key, q.choose(question, key or "", found)
    return key, found[0] if found else None


@pytest.mark.parametrize(
    ("text", "options", "key", "answer"),
    [
        # AbbVie (SmartRecruiters screening): answerable from the graduation date.
        ("Are you currently enrolled in college or university pursuing a degree?", YES_NO,
         "currently_enrolled", "Yes"),
        ("Do you expect that you will have obtained the degree you are currently pursuing by "
         "June of the upcoming year?", YES_NO, "degree_by", "Yes"),
        ("Have you completed a previous internship, co-op, or have related work experience?",
         YES_NO, "has_prior_internship", "Yes"),
        ("Will you now or in the future require sponsorship by AbbVie for employment to obtain, "
         "extend or renew your authorization?", YES_NO, "requires_sponsorship_any", "No"),
        ("Have you ever worked at AbbVie, Allergan, Cerevel Therapeutics or Immunogen "
         "(including as a contractor)?", YES_NO, "previous_worker", "No"),
        # RRS (SmartRecruiters): keyed to Major and School before.
        ("Is your current cumulative GPA (not major GPA) 3.0 or above?", YES_NO,
         "gpa_at_least", "Yes"),
        ("Have you uploaded your most recent College Transcript?", YES_NO, None, None),
        ("Will you be returning to school at the end of the internship to continue academic "
         "studies?", YES_NO, "returning_to_school", "No"),
        # GCM (Greenhouse) and Ramp (Ashby).
        ("Do you currently require employer-sponsored work authorization (e.g., employer visa "
         "sponsorship) to work in the country or location where this role is based?",
         YES_NO, "requires_sponsorship", "No"),
        ("To your knowledge are you currently subject to any non-compete or non-solicitation "
         "restrictions?", YES_NO, "noncompete", "No"),
        ("Are you currently located in, or willing to relocate to, the Greater New York City "
         "area and work from our NYC office for the duration of the internship?", YES_NO,
         "located_or_relocate", "Yes"),
        # Quora (Ashby): the group's question, with its own option wording.
        ("Degree", ("Associate Degree", "Bachelor's Degree", "Master's Degree", "Phd", "Other"),
         "degree_level", "Bachelor's Degree"),
        ("Gender", ("Male", "Female", "Non Binary", "Other", "I prefer not to say"),
         "gender", "Male"),
        ("Are you legally authorized to work in that country?", YES_NO,
         "authorized_to_work", "Yes"),
        ("Will you now or in the future require sponsorship for employment visa status?",
         YES_NO, "requires_sponsorship_any", "No"),
    ],
)
def test_questions_from_real_forms(text, options, key, answer):
    question = Question(text, kind="choice" if options else "text", options=options)
    assert _answer(question) == (key, answer)


@pytest.mark.parametrize(
    "text",
    [
        # A Yes/No question is never the School, GPA, Major or Phone field.
        "Have you uploaded your most recent College Transcript?",
        "Do you have a phone number where recruiters can reach you during the day?",
        "Is Computer Science your declared major?",
    ],
)
def test_yes_no_questions_never_take_a_text_fact(text):
    match = q.classify(Question(text, kind="choice", options=YES_NO))
    assert match is None or match.key in q.YES_NO_KEYS


def test_short_fields_keep_their_labels():
    assert q.classify(Question("Phone")) == q.Match("phone")
    assert q.classify(Question("School", kind="typeahead")) == q.Match("school")
    assert q.classify(Question("Field of Study")) == q.Match("major")
    # The helper text is not the question: "School Name" is not the Degree field.
    assert q.classify(Question("School Name", kind="typeahead")) == q.Match("school")


def test_split_dates_follow_their_section():
    months = ("January", "February", "March", "June")
    years = ("2027", "2026", "2023")
    start_month = Question("Start Date", kind="choice", options=months, part="month")
    end_year = Question("End Date", kind="choice", options=years, part="year")
    assert _answer(start_month) == ("education_start_month", None)  # September not listed
    assert _answer(Question("Start Date", kind="choice", options=(*months, "September"),
                            part="month")) == ("education_start_month", "September")
    assert _answer(end_year) == ("graduation_month", "2027")
    assert q.classify(Question("Start date month", part="month")) == q.Match("education_start_month")
    assert q.classify(Question("End date year", part="year")) == q.Match("graduation_month")


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("by June of the upcoming year", (2027, 6)),
        ("by June 2026", (2026, 6)),
        ("by the end of 2027", (2027, 12)),
        ("by May", (2027, 5)),
        ("by December", (2026, 12)),
        ("by AbbVie", None),
    ],
)
def test_by_date(phrase, expected):
    assert q.by_date(phrase, date(2026, 9, 27)) == expected


def test_derived_answers_need_their_facts():
    bare = q.facts_for({}, today=date(2026, 9, 27))
    for text in (
        "Are you currently enrolled in college or university pursuing a degree?",
        "Is your current cumulative GPA (not major GPA) 3.0 or above?",
        "Are you currently located in, or willing to relocate to, the Greater New York City area?",
    ):
        question = Question(text, kind="choice", options=YES_NO)
        assert q.answers(q.classify(question), question, bare) == []


def test_located_in_the_area_answers_yes_without_relocating():
    facts = q.facts_for({"city": "Brooklyn", "state": "New York", "willing_to_relocate": "No"})
    question = Question("Are you currently located in or willing to relocate to New York, "
                        "New York?", kind="choice", options=YES_NO)
    assert _answer(question, facts) == ("located_or_relocate", "Yes")
    elsewhere = q.facts_for({"city": "Austin", "state": "Texas", "willing_to_relocate": "No"})
    assert _answer(question, elsewhere) == ("located_or_relocate", "No")


def test_worked_at_a_named_company():
    facts = q.facts_for({}, company="AbbVie", employers=["Allergan"])
    question = Question("Have you ever worked at AbbVie, Allergan, Cerevel Therapeutics or "
                        "Immunogen?", kind="choice", options=YES_NO)
    assert _answer(question, facts) == ("previous_worker", "Yes")


def test_yes_no_options_with_wording():
    options = ("Yes - I consent to receiving text messages", "No - I do not consent")
    question = Question("Are you currently enrolled in a degree program?", kind="choice",
                        options=options)
    assert _answer(question) == ("currently_enrolled", options[0])


@pytest.mark.parametrize(
    ("text", "key", "answer"),
    [
        ("What is your expected graduation year?", "graduation_month", "2027"),
        ("What is your expected graduation month?", "graduation_month", "June"),
        ("What is your hourly wage expectation?", "salary_expectation", "$40/hour"),
        ("How did you learn about Acme and this opportunity?", "how_heard", "LinkedIn"),
        ("Will you need sponsorship in the future from an employer to obtain, extend or renew "
         "your authorization?", "requires_sponsorship_future", "No"),
        ("Are you currently subject to a non-compete agreement?", "noncompete", "No"),
    ],
)
def test_screening_style_questions(text, key, answer):
    facts = q.facts_for({**FIELDS, "salary_hourly": "$40/hour", "how_heard": "LinkedIn"})
    question = Question(text)
    match = q.classify(question)
    assert match is not None and match.key == key
    assert q.answers(match, question, facts)[:1] == [answer]


def test_graduation_parts_need_the_part():
    facts = q.facts_for({"graduation_month": "May 2026"})
    question = Question("Expected graduation year")
    assert q.answers(q.classify(question), question, facts) == ["2026"]
    month_only = q.facts_for({"graduation_month": "2027"})
    question = Question("Graduation month")
    assert q.answers(q.classify(question), question, month_only) == []
