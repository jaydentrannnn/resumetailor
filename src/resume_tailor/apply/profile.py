"""Applicant form-filling profile — work auth, address, EEO, canned Q&A.

Lives beside ``settings.json`` as ``applicant_profile.json`` so
``PUT /api/settings`` cannot silently drop it. Never part of ``MasterResume``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from resume_tailor import config

_log = logging.getLogger(__name__)

WorkAuthorization = Literal["", "citizen", "permanent_resident", "visa_holder", "other"]


class EEOAnswers(BaseModel):
    """Voluntary self-identification answers; "decline" picks the form's decline option."""

    gender: str = "decline"
    race: str = "decline"
    race_detail: str = ""
    hispanic_latino: bool | None = None
    veteran: str = "decline"
    disability: str = "decline"


#: Proficiency categories and levels a language row may carry; forms word their own
#: options, matched by rank (`field_matcher.level_option`).
LANGUAGE_CATEGORIES = ("Overall", "Reading", "Speaking", "Writing", "Comprehension")
LANGUAGE_LEVELS = ("Beginner", "Intermediate", "Advanced", "Fluent", "Native")


class LanguageEntry(BaseModel):
    """One spoken language: fluency flag and a level per category (blank = not asked)."""

    language: str = ""
    fluent: bool = False
    levels: dict[str, str] = Field(default_factory=dict)


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
    #: Free-text answer; school, major, degree, GPA and dates come from the master
    #: resume's education entries (`packet._build_education`).
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
    languages: list[LanguageEntry] = Field(default_factory=list)
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


#: Education facts a profile held before the master resume became their only source.
_LEGACY_EDUCATION = ("school", "degree_level", "major", "gpa", "education_start_month", "graduation_month")


def _backup(path: Path) -> None:
    """Timestamped ``.bak.json`` sibling, the naming the master-resume saves use."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path.with_suffix(f".{stamp}.bak.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _migrate_education(path: Path, raw: dict[str, Any]) -> None:
    """Move a legacy profile's major and GPA into its master-resume entry, once.

    Only blanks on the resume entry whose school matches are filled; both files are backed
    up first, and the profile is rewritten without the legacy keys. When the resume cannot
    be read, nothing is touched and the next load tries again.
    """
    from resume_tailor import data
    from resume_tailor.apply import field_matcher

    try:
        resume = data.load()
    except Exception:  # noqa: BLE001 - no readable resume yet: retry on a later load
        return
    school = str(raw.get("school") or "").strip()
    schools = [edu.school for edu in resume.education]
    match = field_matcher.closest_option(schools, school, key="school") if school else None
    entries = [edu for edu in resume.education if match is not None and edu.school == match]
    if len(entries) == 1:
        entry = entries[0]
        major, gpa = str(raw.get("major") or "").strip(), str(raw.get("gpa") or "").strip()
        if (major and not entry.major) or (gpa and not entry.gpa):
            entry.major = entry.major or major
            entry.gpa = entry.gpa or gpa
            resume_path = config.MASTER_RESUME_PATH
            _backup(resume_path)
            resume_path.write_text(
                json.dumps(resume.model_dump(by_alias=True), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    elif school:
        _log.warning("profile education for %r matched no single resume entry; not migrated", school)
    _backup(path)
    save_profile(ApplicantProfile.model_validate(raw))


def load_profile() -> tuple[ApplicantProfile, bool]:
    """Load the profile; return ``(profile, seeded)`` where seeded means file was missing."""
    path = _path()
    if not path.is_file():
        return ApplicantProfile(), True
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and any(key in raw for key in _LEGACY_EDUCATION):
        _migrate_education(path, raw)
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
