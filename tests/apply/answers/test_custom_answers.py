"""Custom answers that restate a built-in field are detected and merged."""

import pytest

from resume_tailor.apply.answers import custom_answers
from resume_tailor.apply.answers.profile import ApplicantProfile


def _profile(**answers: str) -> ApplicantProfile:
    return ApplicantProfile(custom_answers=answers)


def test_duplicates_name_the_field_they_restate():
    profile = _profile(**{
        "are you at least 18 years of age": "Yes",
        "what is the highest level of education you have obtained": "Bachelor's",
        "do you have relatives employed at": "No",
        "were you referred": "No",
        "why do you want this job": "Because",
    })
    assert custom_answers.duplicates(profile) == {
        "are you at least 18 years of age": "over_18",
        "what is the highest level of education you have obtained": "highest_education_obtained",
        "do you have relatives employed at": "relatives_at_company",
        "were you referred": "referred_by",
    }


def test_self_identification_questions_are_never_duplicates():
    assert custom_answers.target("What is your gender?") is None


def test_merge_fills_an_unset_field_and_drops_the_entry():
    merged = custom_answers.merge(_profile(**{"are you at least 18 years of age": "Yes"}), "are you at least 18 years of age")
    assert merged.over_18 is True
    assert merged.custom_answers == {}


def test_merge_keeps_a_value_the_applicant_already_chose():
    profile = ApplicantProfile(over_18=False, custom_answers={"are you at least 18 years of age": "Yes"})
    merged = custom_answers.merge(profile, "are you at least 18 years of age")
    assert merged.over_18 is False
    assert merged.custom_answers == {}


def test_merge_normalizes_dates_and_replaces_the_shipped_default():
    profile = ApplicantProfile(custom_answers={"start date": "June 14, 2027", "how did you hear about us": "A friend"})
    merged = custom_answers.merge(custom_answers.merge(profile, "start date"), "how did you hear about us")
    assert merged.earliest_start == "2027-06-14"
    assert merged.how_heard == "A friend"


def test_merge_rejects_an_answer_the_field_cannot_hold():
    with pytest.raises(ValueError):
        custom_answers.merge(_profile(**{"are you at least 18 years of age": "Maybe"}), "are you at least 18 years of age")
