"""Applicant form-filling profile — work auth, address, EEO, canned Q&A.

Lives beside ``settings.json`` as ``applicant_profile.json`` so
``PUT /api/settings`` cannot silently drop it. Never part of ``MasterResume``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from resume_tailor import config

WorkAuthorization = Literal["", "citizen", "permanent_resident", "visa_holder", "other"]


class EEOAnswers(BaseModel):
    """Voluntary self-identification answers; blank/"decline" leave the field empty."""

    gender: str = "decline"
    race: str = "decline"
    race_detail: str = ""
    hispanic_latino: bool | None = None
    veteran: str = "decline"
    disability: str = "decline"


class ApplicantProfile(BaseModel):
    """Flat answers reused across ATS forms; not resume content."""

    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    preferred_name: str = ""
    pronouns: str = ""
    email: str = ""
    phone: str = ""
    phone_device_type: str = ""
    phone_country_code: str = "+1"
    phone_country_region: str = ""
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = "United States"
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    #: When True, filler only fills ``portfolio_url`` into labels that explicitly
    #: mention portfolio/personal site/website — never a generic "URL" field.
    portfolio_only_when_asked: bool = True
    work_authorization: WorkAuthorization = ""
    authorized_to_work: bool | None = None
    authorization_country: str = ""
    requires_sponsorship_now: bool | None = None
    requires_sponsorship_future: bool | None = None
    f1_opt_eligible: bool | None = None
    earliest_start: str = ""
    notice_period: str = ""
    education_start_month: str = ""
    graduation_month: str = ""
    degree_level: str = ""
    major: str = ""
    school: str = ""
    gpa: str = ""
    highest_education_obtained: str = ""
    salary_expectation: str = ""
    #: Structured range behind salary answers (`apply/salary.py`); seeded once from
    #: ``salary_expectation`` when all four are empty.
    salary_hourly_min: float | None = None
    salary_hourly_max: float | None = None
    salary_yearly_min: float | None = None
    salary_yearly_max: float | None = None
    willing_to_relocate: bool | None = None
    location_preference: str = ""
    over_18: bool | None = None
    relatives_at_company: bool | None = None
    referred_by: str = ""
    how_heard: str = "Found through a job postings aggregator."
    workday_email: str = ""
    workday_password: str = ""
    eeo: EEOAnswers = Field(default_factory=EEOAnswers)
    custom_answers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _seed_salary_range(cls, data: Any) -> Any:
        """Seed the structured range from the free-text expectation, once.

        Only a profile saved before the range existed (none of its keys present) is
        seeded; a range the applicant later cleared stays cleared.
        """
        keys = ("salary_hourly_min", "salary_hourly_max", "salary_yearly_min", "salary_yearly_max")
        if not isinstance(data, dict) or any(key in data for key in keys) or not data.get("salary_expectation"):
            return data
        from resume_tailor.apply.salary import profile_ranges

        ranges = profile_ranges(str(data["salary_expectation"]))
        seeded = dict(data)
        if "hour" in ranges:
            seeded["salary_hourly_min"], seeded["salary_hourly_max"] = ranges["hour"]
        if "year" in ranges:
            seeded["salary_yearly_min"], seeded["salary_yearly_max"] = ranges["year"]
        return seeded
        from resume_tailor.apply.salary import profile_ranges

        ranges = profile_ranges(self.salary_expectation)
        if "hour" in ranges:
            self.salary_hourly_min, self.salary_hourly_max = ranges["hour"]
        if "year" in ranges:
            self.salary_yearly_min, self.salary_yearly_max = ranges["year"]
        return self


def _path() -> Path:
    """Active workspace's applicant-profile path."""
    return config.APPLICANT_PROFILE_PATH


def load_profile() -> tuple[ApplicantProfile, bool]:
    """Load the profile; return ``(profile, seeded)`` where seeded means file was missing."""
    path = _path()
    if not path.is_file():
        return ApplicantProfile(), True
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ApplicantProfile.model_validate(raw), False


def save_profile(profile: ApplicantProfile) -> ApplicantProfile:
    """Write ``applicant_profile.json`` atomically and return the saved model."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(profile.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return profile


def seed_default_profile(path: Path | None = None) -> ApplicantProfile:
    """Write the owner's seeded answers from application-answers.md if missing.

    Only creates the file when absent — never overwrites a user edit.
    """
    target = path if path is not None else _path()
    if target.is_file():
        return ApplicantProfile.model_validate_json(target.read_text(encoding="utf-8"))
    seeded = ApplicantProfile(
        first_name="Alex Jordan Lee",
        last_name="Tran",
        preferred_name="Jayden",
        pronouns="He/Him",
        email="alex@example.com",
        phone="555 010 0000",
        phone_country_code="+1",
        address_line1="123 Main St",
        city="Springfield",
        state="California",
        postal_code="12345",
        country="United States",
        linkedin_url="https://www.linkedin.com/in/alex-jordan-lee-doe/",
        github_url="https://github.com/jaydentrannnn",
        portfolio_url="https://jaydentrannnn.github.io/jaydentran-portfolio/",
        portfolio_only_when_asked=True,
        work_authorization="visa_holder",
        requires_sponsorship_now=False,
        requires_sponsorship_future=False,
        f1_opt_eligible=True,
        earliest_start="2027-06-14",
        graduation_month="2027-06",
        degree_level="Bachelors",
        major="Computer Science",
        school="University of California - Irvine",
        gpa="3.643",
        highest_education_obtained=(
            "High school diploma; currently pursuing a Bachelor of Science degree."
        ),
        salary_expectation=(
            "Open to discussing; otherwise $60k-80k/yr or $40-$45/hour depending on the role."
        ),
        willing_to_relocate=True,
        location_preference=(
            "Open to any location; if forced to pick, Orange County/LA or the Bay Area."
        ),
        over_18=True,
        relatives_at_company=False,
        how_heard="Found through a job postings aggregator.",
        eeo=EEOAnswers(gender="Male", race="Asian", race_detail="Southeast Asian", hispanic_latino=False, veteran="No", disability="No"),
        custom_answers={
            "are you at least 18 years of age": "Yes",
            "what is the highest level of education you have obtained": (
                "High school diploma; currently pursuing a Bachelor of Science degree."
            ),
            "do you have relatives employed at": "No",
            "were you referred": "No",
            "how did you hear about us": "Found through a job postings aggregator.",
            "availability": "June 14, 2027",
            "start date": "June 14, 2027",
            "expected graduation": "June 11, 2027",
        },
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(seeded.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return seeded
