"""`content.dates`: read typed or legacy dates into ISO, leave non-dates alone."""

import pytest

from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.content import dates


@pytest.mark.parametrize(
    ("text", "precision", "expected"),
    [("June 14, 2027", "day", "2027-06-14"), ("6/14/2027", "day", "2027-06-14"),
     ("2027-06-14", "month", "2027-06"), ("Jun 2027", "month", "2027-06"),
     ("2027-06", "day", "2027-06"), ("ASAP", "day", "ASAP"), ("Present", "month", "Present"),
     ("Feb 30, 2027", "day", "Feb 30, 2027")],
)
def test_normalize(text, precision, expected):
    assert dates.normalize(text, precision) == expected


def test_profile_normalizes_legacy_dates():
    profile = ApplicantProfile.model_validate(
        {"earliest_start": "June 14, 2027", "graduation_date": "June 2027"}
    )
    assert (profile.earliest_start, profile.graduation_date) == ("2027-06-14", "2027-06")


def test_experience_months_are_read_into_iso_and_free_text_is_kept():
    from resume_tailor.content.data import Experience

    job = Experience(company="Acme", title="Intern", start="Jan 2023", end="Present")
    assert (job.start, job.end) == ("2023-01", "Present")
    assert Experience(company="A", title="T", start="Fall 2022", end="2023-05").start == "Fall 2022"
