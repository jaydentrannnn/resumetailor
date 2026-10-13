"""Regression questions use explicit application preferences and dated profile facts."""

from datetime import date

import pytest
from pydantic import ValidationError

from resume_tailor.apply.answers import education_status, experience, form_facts
from resume_tailor.apply.answers import questions as q
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.funnel import packet_fields
from resume_tailor.content.data import Contact, Education, EducationSection, MasterResume

TODAY = date(2026, 10, 12)
OTHER_POSITIONS = (
    "Although we encourage you to apply to all positions in which you have an interest, "
    "P&G Recruiters have the ability to consider your application for other positions to "
    "which you have not applied. Would you like to be considered for other positions "
    "for which you may be qualified?"
)
INFORMATION_SOURCES = (
    "What source(s) of information influenced your decision to apply for a P&G position?"
)
QUALIFICATIONS = (
    "Do you meet the minimum qualification requirements for this role as stated in "
    "the job description?"
)
RECENT_STUDENT = "Have you either graduated within the past 6 months, or are you an active student?"
ADVERTISING = (
    "I would like P&G to share my personal information with its advertising partners "
    "to show me, and others like me, news and updates about P&G careers and roles "
    "through online channels such as LinkedIn, Instagram, Meta, Facebook, Google, "
    "TikTok, and YouTube. Your decision to opt-in or opt-out will not disqualify you "
    "from participating in P&G’s recruitment process and you may opt-out at any time."
)


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    monkeypatch.setattr(education_status, "date", _FixedDate)
    monkeypatch.setattr(experience, "date", _FixedDate)


def _resume(*education):
    return MasterResume(
        contact=Contact(name="Test Applicant", email="test@example.test"),
        sections=[EducationSection(id="education", title="Education", entries=list(education))],
    )


def _edu(start="2023-09", end="2027-06", **fields):
    return Education(
        school="Synthetic University",
        degree="B.S. in Computing",
        dates="",
        start=start,
        end=end,
        **fields,
    )


def _facts(profile=None, resume=None):
    fields = packet_fields.build_fields(profile or ApplicantProfile(), resume or _resume(_edu()))
    return q.facts_for(fields, today=TODAY)


def _answer(text, facts, options=("Yes", "No"), kind="choice", **kwargs):
    question = q.Question(text, kind=kind, options=options, **kwargs)
    match = q.classify(question)
    answers = q.answers(match, question, facts)
    value = (
        q.choose(question, match.key, answers)
        if match and options
        else (answers[0] if answers else None)
    )
    return match.key if match else None, value


@pytest.mark.parametrize(
    ("text", "key", "options", "expected"),
    [
        (OTHER_POSITIONS, "consider_other_positions", ("Yes", "No"), "Yes"),
        (INFORMATION_SOURCES, "how_heard", ("LinkedIn", "Careers website", "Other"), "LinkedIn"),
        (QUALIFICATIONS, "minimum_qualifications", ("Yes", "No"), "Yes"),
        (RECENT_STUDENT, "recent_graduate_or_student", ("Yes", "No"), "Yes"),
        (ADVERTISING, "advertising_consent", ("Yes", "No"), "No"),
    ],
)
def test_all_five_exact_pg_questions(text, key, options, expected):
    profile = ApplicantProfile(
        consider_other_positions=True,
        minimum_qualifications_answer=True,
        how_heard="LinkedIn",
        auto_accept_routine_acknowledgements=True,
    )
    assert _answer(text, _facts(profile), options) == (key, expected)


@pytest.mark.parametrize("text", [
    "Do you have experience building SMS messaging systems?",
    "Do you have marketing experience?",
    "How many years of experience do you have developing newsletter software?",
    "Have you worked on promotional campaigns?",
    "Do you have experience implementing SMS consent flows?",
])
def test_optional_topics_do_not_turn_factual_experience_into_declined_consent(text):
    facts = _facts(ApplicantProfile(auto_accept_routine_acknowledgements=True))
    assert form_facts.acknowledgement(text) != "optional"
    assert _answer(text, facts)[0] != form_facts.ACKNOWLEDGEMENT


@pytest.mark.parametrize("text", [
    "I agree to receive marketing emails about future events",
    "I consent to text messages",
    "Would you like to receive SMS updates?",
    "Do you want to subscribe to our newsletter?",
    "Email me job alerts",
    "Sign up for promotional messages",
    "Join the talent community",
    "SMS opt-in",
])
def test_actual_optional_communications_remain_declined(text):
    facts = _facts(ApplicantProfile(auto_accept_routine_acknowledgements=True))
    assert form_facts.acknowledgement(text) == "optional"
    assert _answer(text, facts)[1] == "No"


def test_required_privacy_consent_still_uses_explicit_notice_preference():
    text = "I consent to the processing of my personal data for this application"
    assert form_facts.acknowledgement(text) == "routine"
    assert _answer(text, _facts(ApplicantProfile(auto_accept_routine_acknowledgements=True))) == (
        form_facts.ACKNOWLEDGEMENT, "Yes",
    )


@pytest.mark.parametrize(
    ("text", "key"),
    [(OTHER_POSITIONS, "consider_other_positions"), (QUALIFICATIONS, "minimum_qualifications")],
)
def test_missing_preference_never_follows_notice_consent_or_education(text, key):
    facts = _facts(ApplicantProfile(auto_accept_routine_acknowledgements=True))
    assert key not in facts.fields
    assert _answer(text, facts) == (key, None)


@pytest.mark.parametrize(
    ("text", "key"),
    [(OTHER_POSITIONS, "consider_other_positions"), (QUALIFICATIONS, "minimum_qualifications")],
)
def test_explicit_no_wins_over_notice_consent(text, key):
    facts = _facts(
        ApplicantProfile(
            consider_other_positions=False,
            minimum_qualifications_answer=False,
            auto_accept_routine_acknowledgements=True,
        )
    )
    assert _answer(text, facts) == (key, "No")


def test_information_source_matches_equivalent_saved_source_and_not_unrelated_board():
    facts = _facts(ApplicantProfile(how_heard="LinkedIn"))
    assert _answer(INFORMATION_SOURCES, facts, ("Indeed", "LinkedIn.com", "Other")) == (
        "how_heard",
        "LinkedIn.com",
    )
    assert _answer(INFORMATION_SOURCES, facts, ("Indeed", "Company Website", "Other")) == (
        "how_heard",
        "Other",
    )
    assert facts.fields["how_heard_detail"] == "LinkedIn"
    assert _answer(INFORMATION_SOURCES, facts, ("Indeed", "Company Website")) == ("how_heard", None)


@pytest.mark.parametrize(
    "question",
    [
        "How many years of hands on experience have you had?",
        "How many years of professional experience do you have?",
    ],
)
def test_magnite_and_professional_experience_use_same_custom_preference(question):
    facts = _facts(ApplicantProfile(experience_basis="custom", experience_years_custom=1.5))
    assert _answer(question, facts, ("0-1 years", "1-2 years", "2+ years")) == (
        "experience_years",
        "1-2 years",
    )
    assert _answer(question, facts, (), "text") == ("experience_years", "1.5")


def test_years_without_dated_evidence_remain_unanswered():
    facts = _facts(resume=_resume())
    assert "experience_years" not in facts.fields
    assert _answer("How many years of work experience do you have?", facts, ("0-1", "1-2")) == (
        "experience_years",
        None,
    )


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_custom_experience_cannot_enter_profile(value):
    with pytest.raises(ValidationError):
        ApplicantProfile(experience_basis="custom", experience_years_custom=value)


@pytest.mark.parametrize(
    ("start", "end", "student", "compound"),
    [
        ("2027-01", "2028-01", "No", "No"),
        ("2023-09", "2026-10", "Yes", "Yes"),
        ("2026-10", "2027-06", "Yes", "Yes"),
        ("2026-10-13", "2027-06-01", "No", "No"),
        ("2023-09-01", "2026-10-12", "Yes", "Yes"),
        ("2023-09-01", "2026-10-11", "No", "Yes"),
        ("2023-09", "2026-04-12", "No", "Yes"),
        ("2023-09", "2026-04-11", "No", "No"),
        ("2023-09", "2026-04", "No", "Yes"),
        ("2023-09", "2026-03", "No", "No"),
    ],
)
def test_student_and_six_calendar_month_boundaries_in_packet(start, end, student, compound):
    facts = _facts(resume=_resume(_edu(start, end)))
    assert _answer("Are you an active student?", facts) == ("currently_enrolled", student)
    assert _answer(RECENT_STUDENT, facts) == ("recent_graduate_or_student", compound)


def test_any_current_education_entry_establishes_student_status():
    facts = _facts(resume=_resume(_edu("2027-01", "2028-01"), _edu("2023-09", "2027-06")))
    assert _answer(RECENT_STUDENT, facts) == ("recent_graduate_or_student", "Yes")


def test_expected_graduation_without_start_does_not_establish_current_student():
    facts = _facts(resume=_resume(_edu("", "2027-06")))
    assert _answer("Are you an active student?", facts) == ("currently_enrolled", None)
    assert _answer(RECENT_STUDENT, facts) == ("recent_graduate_or_student", None)


@pytest.mark.parametrize(
    ("part", "expected_start", "expected_end"),
    [("day", "17", "9"), ("month", "September", "June"), ("year", "2023", "2027")],
)
def test_packet_preserves_full_education_dates_and_split_answers(
    part, expected_start, expected_end
):
    resume = _resume(_edu("2023-09-17", "2027-06-09"))
    facts = _facts(resume=resume)
    rows = packet_fields._build_education(resume)
    assert rows[0].start == "2023-09-17" and rows[0].end == "2027-06-09"
    assert facts.fields["education_start_date"] == "2023-09-17"
    assert facts.fields["graduation_date"] == "2027-06-09"
    assert facts.fields["education_start_month"] == "2023-09"
    assert facts.fields["graduation_month"] == "2027-06"
    assert _answer(part.title(), facts, (), "text", part=part, section="Education Start Date") == (
        "education_start_month",
        expected_start,
    )
    assert _answer(part.title(), facts, (), "text", part=part, section="Education End Date") == (
        "graduation_month",
        expected_end,
    )


def test_month_only_education_does_not_invent_day_for_date_control():
    facts = _facts(resume=_resume(_edu()))
    assert q.answers(q.Match("graduation_month"), q.Question("Day", part="day"), facts) == []
    assert q.date_text("2027-06", input_type="date") == ""
    result = q.plan_for(
        [
            {
                "qid": "graduation",
                "label": "Graduation Date",
                "attr_key": "graduation_month",
                "kind": "date",
                "input_type": "date",
            }
        ],
        facts,
    )
    assert result["graduation"]["value"] in {"", None}


def test_full_date_plan_uses_day_fact_instead_of_month_projection():
    facts = _facts(resume=_resume(_edu("2023-09-17", "2027-06-09")))
    result = q.plan_for(
        [
            {
                "qid": "graduation",
                "label": "Graduation Date",
                "attr_key": "graduation_month",
                "kind": "date",
                "input_type": "date",
            }
        ],
        facts,
    )
    assert result["graduation"] == {"key": "graduation_month", "value": "2027-06-09"}
