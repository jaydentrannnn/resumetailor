"""Tests for the allowlisted applicant facts shown to the answer model."""

from __future__ import annotations

from resume_tailor.apply.answers import answer_facts
from resume_tailor.apply.answers.profile import ApplicantProfile
from tests.fixtures import synthetic_resume


def test_profile_facts_include_only_allowlisted_filled_fields():
    """Contact, salary and credentials never appear; blank and None fields are skipped."""
    profile = ApplicantProfile(
        city="Irvine", state="CA", email="me@example.com", phone="555-0100",
        salary_expectation="$50/hr", linkedin_url="https://linkedin.com/in/me",
        requires_sponsorship_now=False, authorized_to_work=True,
        earliest_start="June 2027",
    )
    facts = answer_facts.profile_facts(profile)
    assert "City: Irvine" in facts
    assert "Requires sponsorship now: no" in facts
    assert "Authorized to work: yes" in facts
    assert "Earliest start: June 2027" in facts
    joined = " ".join(facts)
    for private in ("me@example.com", "555-0100", "$50/hr", "linkedin"):
        assert private not in joined
    assert not any(line.startswith("Notice period") for line in facts)


def test_all_bullets_covers_the_whole_resume():
    """Every master bullet id is present with its text."""
    resume = synthetic_resume()
    bullets = answer_facts.all_bullets(resume)
    assert set(bullets) == {b.id for b in resume.all_bullets()}
