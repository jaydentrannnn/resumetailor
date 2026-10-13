"""User-selected aggregate experience is deterministic and never double counted."""

from datetime import date

import pytest

from resume_tailor.apply.answers import experience
from resume_tailor.content.data import Contact, Experience, ExperienceSection, MasterResume

TODAY = date(2026, 10, 12)
YEAR_DAYS = 365.2425


def _resume(**sections):
    return {"sections": [{"kind": kind, "entries": entries} for kind, entries in sections.items()]}


def _entry(start="2024-01", end="2024-12", **fields):
    return {"start": start, "end": end, **fields}


def test_full_master_resume_sections_include_multiple_experience_sections():
    resume = MasterResume(
        contact=Contact(name="Test Person", email="test@example.test"),
        sections=[
            ExperienceSection(
                id="work",
                title="Work",
                entries=[
                    Experience(
                        company="Company A", title="Developer", start="2024-01", end="2024-08"
                    )
                ],
            ),
            ExperienceSection(
                id="leadership",
                title="Leadership",
                entries=[
                    Experience(company="Club", title="President", start="2024-06", end="2024-12")
                ],
            ),
        ],
    )
    result = experience.calculate(resume, "experience", today=TODAY)
    assert result == {"years": 366 / YEAR_DAYS, "as_of": "2026-10-12", "excluded_entries": []}


def test_bases_union_overlapping_work_projects_and_education():
    resume = _resume(
        experience=[_entry("2024-01", "2024-06")],
        project=[_entry("2024-04", "2024-09")],
        education=[_entry("2024-08", "2024-12"), _entry("2024-08", "2024-12")],
        list=[_entry("2020-01", "2023-12")],
    )
    values = experience.summaries(resume, today=TODAY)
    assert values["experience"]["years"] == 182 / YEAR_DAYS
    assert values["experience_projects"]["years"] == 274 / YEAR_DAYS
    assert values["experience_projects_education"]["years"] == 366 / YEAR_DAYS
    assert all(value["as_of"] == TODAY.isoformat() for value in values.values())


def test_exact_dates_preserve_days_and_do_not_round_years():
    resume = _resume(education=[_entry("2024-02-28", "2024-03-01")])
    result = experience.calculate(resume, "experience_projects_education", today=TODAY)
    assert result["years"] == 3 / YEAR_DAYS


@pytest.mark.parametrize(("start", "expected_days"), [("2024-02", 29), ("2024-02-15", 1)])
def test_project_without_end_is_single_source_period(start, expected_days):
    result = experience.calculate(
        _resume(project=[_entry(start, "")]), "experience_projects", today=TODAY
    )
    assert result["years"] == expected_days / YEAR_DAYS


def test_education_falls_back_to_printed_dates_without_mutation():
    entry = _entry("", "", dates="September 2023 – May 2024")
    resume = _resume(education=[entry])
    result = experience.calculate(resume, "experience_projects_education", today=TODAY)
    assert result["years"] == (date(2024, 6, 1) - date(2023, 9, 1)).days / YEAR_DAYS
    assert entry["start"] == entry["end"] == ""


@pytest.mark.parametrize("end", ["Present", "current", "2027-05", "2027-05-05"])
def test_ongoing_or_future_end_clamps_to_today(end):
    result = experience.calculate(
        _resume(experience=[_entry("2026-10-10", end)]), "experience", today=TODAY
    )
    assert result["years"] == 3 / YEAR_DAYS


@pytest.mark.parametrize("end", ["Present", "2028-01"])
def test_future_dated_entry_is_zero_not_missing(end):
    result = experience.calculate(
        _resume(experience=[_entry("2027-01", end)]), "experience", today=TODAY
    )
    assert result["years"] == 0
    assert result["excluded_entries"] == []


def test_missing_dates_are_reported_and_do_not_discard_dated_subtotal():
    resume = _resume(
        experience=[
            _entry("2024-01", "2024-12", title="Developer", company="One"),
            _entry("2023", "2024-12", title="Assistant", company="Two"),
            _entry("2024-01", "", title="Intern", company="Three"),
        ],
        education=[_entry("2020-01", "", school="College")],
    )
    result = experience.calculate(resume, "experience_projects_education", today=TODAY)
    assert result["years"] == 366 / YEAR_DAYS
    assert result["excluded_entries"] == [
        {
            "label": "Assistant — Two",
            "kind": "experience",
            "reason": "Missing or incomplete start date",
        },
        {
            "label": "Intern — Three",
            "kind": "experience",
            "reason": "Missing or incomplete end date",
        },
        {"label": "College", "kind": "education", "reason": "Missing or incomplete end date"},
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [("", ""), ("2024", "2025"), ("2024-02-30", "2024-03"), ("2024-03", "2024-02")],
)
def test_no_usable_dates_produces_null(start, end):
    result = experience.calculate(
        _resume(experience=[_entry(start, end)]), "experience", today=TODAY
    )
    assert result["years"] is None
    assert len(result["excluded_entries"]) == 1


@pytest.mark.parametrize("value", [None, -1, float("inf"), float("nan"), True, "2"])
def test_invalid_custom_years_are_unresolved(value):
    assert experience.calculate(_resume(), "custom", value, TODAY)["years"] is None


@pytest.mark.parametrize("value", [0, 1.5, 10])
def test_custom_years_preserve_fraction(value):
    assert experience.calculate(_resume(), "custom", value, TODAY) == {
        "years": float(value),
        "as_of": TODAY.isoformat(),
        "excluded_entries": [],
    }


@pytest.mark.parametrize(
    "question",
    [
        "How many years of hands-on experience have you had?",
        "How many years of professional experience do you have?",
        "How many years of relevant work experience do you have?",
        "Total years of experience",
        "Please indicate your years of experience.",
    ],
)
def test_general_and_professional_questions_use_preference(question):
    assert experience.question_key(question) == "experience_years"


@pytest.mark.parametrize(
    "question",
    [
        "How many years of experience do you have with Python?",
        "How many years of hands-on Java experience have you had?",
        "How many years of C++ experience do you have?",
        "How many years of professional experience in cybersecurity do you have?",
        "What is your graduation year?",
    ],
)
def test_named_technology_or_domain_questions_stay_unrecognized(question):
    assert experience.question_key(question) is None


@pytest.mark.parametrize(
    ("options", "years", "expected"),
    [
        (["Select", "0-1 years", "1-2 years", "2+ years"], 1.5, "1-2 years"),
        (["0-1 years", "1-2 years"], 1, "0-1 years"),
        (["1-2 years", "0-1 years", "1 year"], 1, "1 year"),
        (["Less than 1 year", "1 or more years"], 1, "1 or more years"),
        (["Under 1 year", "Between 1 and 3 years", "3+ years"], 0.5, "Under 1 year"),
        (["1 to 2 years", "2 to 3 years"], 2, "1 to 2 years"),
        (["1 – 3 years", "3 years and above"], 4, "3 years and above"),
        (["No experience", "0-1 years"], 0, "No experience"),
        (["1", "2", "3"], 2, "2"),
        (["1.5 years of experience", "1-2 years"], 1.5, "1.5 years of experience"),
        (["Less than 1 year", "1-2 years"], 2.001, None),
        (["3+ years", "1-2 years"], 2.9, None),
        (["1 option selected", "2 years managing Python"], 1, None),
    ],
)
def test_dropdown_ranges_do_not_round_up(options, years, expected):
    assert experience.choose_year_option(options, years) == expected


def test_years_text_uses_completed_years_only_for_integer_inputs():
    assert experience.years_text(1.9999999, integer=True) == "1"
    assert experience.years_text(1.5) == "1.5"
    assert experience.years_text(0) == "0"


def test_unknown_basis_is_a_configuration_error():
    with pytest.raises(ValueError, match="Unknown experience basis"):
        experience.calculate(_resume(), "unknown", today=TODAY)
