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

from resume_tailor import config, secret_store

_log = logging.getLogger(__name__)

WorkAuthorization = Literal["", "citizen", "permanent_resident", "visa_holder", "other"]
VisaStatus = Literal[
    "", "none", "f1", "f1_opt", "f1_stem_opt", "f1_cpt", "h1b", "h4_ead", "other"
]
ClassYear = Literal["", "freshman", "sophomore", "junior", "senior", "graduate"]
SecurityClearance = Literal["", "none", "eligible", "secret", "top_secret"]

VISA_LABELS: dict[str, str] = {
    "none": "No visa needed (citizen or permanent resident)",
    "f1": "F-1 student",
    "f1_opt": "F-1 (OPT)",
    "f1_stem_opt": "F-1 (STEM OPT)",
    "f1_cpt": "F-1 (CPT)",
    "h1b": "H-1B",
    "h4_ead": "H-4 EAD",
    "other": "Other",
}


def sponsorship_from_visa(visa: str) -> tuple[bool, bool] | None:
    """``(sponsorship now, sponsorship in future)`` a visa status implies, else None.

    Only a default: an explicit Yes/No on the profile always wins. F-1 students (CPT,
    OPT, STEM OPT) and H-4 EAD holders can work now but need sponsorship later; an H-1B
    holder needs a transfer now. "Other" implies nothing.
    """
    return {
        "none": (False, False),
        "f1": (False, True),
        "f1_cpt": (False, True),
        "f1_opt": (False, True),
        "f1_stem_opt": (False, True),
        "h4_ead": (False, True),
        "h1b": (True, True),
    }.get(visa)


#: Veteran self-identification is four answers, not Yes/No: forms tell "not a veteran"
#: from "a veteran, just not a protected one" (CACI, 2026-09), and a Yes/No profile could
#: not say which applied. Blank skips the question. Matching: `field_matcher.VETERAN_TIERS`.
VeteranStatus = Literal["", "protected", "veteran_not_protected", "not_veteran", "decline"]
VETERAN_CHOICES: tuple[str, ...] = ("", "protected", "veteran_not_protected", "not_veteran", "decline")
VETERAN_LABELS: dict[str, str] = {
    "protected": "I am a protected veteran",
    "veteran_not_protected": "I am a veteran, but not a protected veteran",
    "not_veteran": "I am not a veteran",
    "decline": "Decline to self-identify",
}


class EEOAnswers(BaseModel):
    """Voluntary self-identification answers; "decline" picks the form's decline option."""

    gender: str = "decline"
    race: str = "decline"
    race_detail: str = ""
    hispanic_latino: bool | None = None
    veteran: VeteranStatus = "decline"
    #: The free-text answer an older profile held ("No") when it was converted to a
    #: ``veteran`` category; the Profile page asks the applicant to confirm the
    #: conversion and clears this once they have.
    veteran_legacy: str = ""
    disability: str = "decline"

    @model_validator(mode="before")
    @classmethod
    def _migrate_veteran(cls, data: Any) -> Any:
        """Read a pre-category ``veteran`` answer ("No", "Yes", a long-form sentence)."""
        if not isinstance(data, dict):
            return data
        raw = data.get("veteran")
        if not isinstance(raw, str) or raw in VETERAN_CHOICES:
            return data
        from resume_tailor.apply.field_matcher import veteran_category  # noqa: PLC0415

        text = raw.strip()
        category = "" if not text else veteran_category(text) or "decline"
        migrated = {**data, "veteran": category}
        if text and text.casefold() != "decline":
            # "No" could mean "not a veteran" or "not a *protected* veteran": asked, not assumed.
            migrated["veteran_legacy"] = migrated.get("veteran_legacy") or text
        return migrated


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
    #: Drives sponsorship defaults (`sponsorship_from_visa`) and "Visa status" questions.
    visa_status: VisaStatus = ""
    #: "YYYY-MM"; overrides the resume's education end date on forms. Blank = resume.
    graduation_date: str = ""
    #: Blank = derived from the graduation date (`packet.class_year_for`).
    class_year: ClassYear = ""
    #: Overrides the resume's GPA on forms ("3.7/4.0"). Blank = resume.
    gpa_display: str = ""
    #: Uploaded transcript (PDF) in the workspace's files folder, for transcript uploads.
    transcript_path: str = ""
    #: Uploaded portfolio / work sample (PDF), for "Portfolio" upload fields.
    portfolio_path: str = ""
    security_clearance: SecurityClearance = ""
    drivers_license: bool | None = None
    hours_per_week_available: int | None = Field(default=None, ge=0, le=80)
    #: A school (.edu) address for forms that ask for one; blank = the email when .edu.
    school_email: str = ""
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


#: Secret-store key of the profile's Workday password (see `secret_store.profile_name`).
_PASSWORD_SECRET = "workday_password"


def _stored_password() -> str:
    try:
        return secret_store.get(secret_store.profile_name(_PASSWORD_SECRET)) or ""
    except secret_store.SecretStoreError as exc:
        _log.warning("could not read the saved Workday password: %s", exc)
        return ""


def load_profile() -> tuple[ApplicantProfile, bool]:
    """Load the profile; return ``(profile, seeded)`` where seeded means file was missing.

    ``workday_password`` is filled from the secret store; the JSON file holds it only
    when the store could not take it (see `save_profile`). A plaintext password found
    in the file is moved into the store once, after a backup.
    """
    path = _path()
    if not path.is_file():
        return ApplicantProfile(), True
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and any(key in raw for key in _LEGACY_EDUCATION):
        _migrate_education(path, raw)
    profile = ApplicantProfile.model_validate(raw)
    if profile.workday_password:
        _backup(path)
        save_profile(profile)
    else:
        profile.workday_password = _stored_password()
    return profile, False


def save_profile(profile: ApplicantProfile) -> ApplicantProfile:
    """Write ``applicant_profile.json`` atomically and return the saved model.

    The Workday password goes to the secret store and the file gets an empty string.
    An empty password leaves the stored one alone (`clear_workday_password` removes
    it), so code that rebuilds a profile from the file cannot wipe it by accident. If
    the store refuses the password (a locked keychain), it stays in the file rather
    than being lost, and a warning is logged.
    """
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    on_disk = profile.model_dump()
    if profile.workday_password:
        try:
            secret_store.set(
                secret_store.profile_name(_PASSWORD_SECRET), profile.workday_password
            )
            on_disk["workday_password"] = ""
        except secret_store.SecretStoreError as exc:
            _log.warning("Workday password kept in applicant_profile.json: %s", exc)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(on_disk, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return profile


def clear_workday_password() -> None:
    """Forget the active profile's saved Workday password."""
    secret_store.delete(secret_store.profile_name(_PASSWORD_SECRET))
