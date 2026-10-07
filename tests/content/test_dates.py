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
