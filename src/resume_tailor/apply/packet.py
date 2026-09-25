"""Application packet assembly from a completed tailoring run.

Pure function of disk artifacts, the master resume, and the applicant profile — no LLM.
``build_packet`` reads ``run.json``, optional expansion/skills/cover/bullets JSON, and
paths to rendered documents; ``write_packet`` persists ``packet.json`` beside them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from resume_tailor import config, edu_dates
from resume_tailor.apply import ats_hints, field_matcher
from resume_tailor.apply import phone as phone_mod
from resume_tailor.apply import profile as profile_mod
from resume_tailor.apply.profile import ApplicantProfile
from resume_tailor.data import MasterResume, load
from resume_tailor.expand import Expansion, ExpandedEntry
from resume_tailor.render import parse_range


class PacketEducation(BaseModel):
    """One education row for paste-heavy ATS forms."""

    school: str = ""
    degree: str = ""
    major: str = ""
    start: str = ""
    end: str = ""
    gpa: str = ""
    entry_key: str = ""
    degree_level: str = ""
    degree_name: str = ""
    source: str = ""


class PacketExperience(BaseModel):
    """One experience row with optional expansion text."""

    employer: str = ""
    title: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    current: bool = False
    description: str = ""
    char_count: int = 0
    entry_key: str = ""
    source_entry_id: str = ""
    bullets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PreparedArtifact(BaseModel):
    purpose: str
    path: str
    filename: str
    mime_type: str
    sha256: str


class PreparationManifest(BaseModel):
    schema_version: int = 1
    preparation_id: str = ""
    job_id: str = ""
    prepared_at: str = ""
    source_revision: str = ""
    expansion_status: str = "missing"
    expansion_hash: str = ""
    artifacts: list[PreparedArtifact] = Field(default_factory=list)
    preparation_warnings: list[str] = Field(default_factory=list)


class PacketLanguage(BaseModel):
    """One profile language for Workday's Languages rows."""

    language: str
    fluent: bool = False
    levels: dict[str, str] = Field(default_factory=dict)


class Packet(BaseModel):
    """Everything the deterministic filler needs for one tailoring run."""

    job_id: str
    built_at: str
    posting_url: str = ""
    company: str = ""
    role: str = ""
    ats: str = "unknown"
    fields: dict[str, str] = Field(default_factory=dict)
    education: list[PacketEducation] = Field(default_factory=list)
    experience: list[PacketExperience] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[PacketLanguage] = Field(default_factory=list)
    cover_letter: str = ""
    artifacts: dict[str, str] = Field(default_factory=dict)
    field_hints: dict[str, str] = Field(default_factory=dict)
    gaps: list[dict] = Field(default_factory=list)
    preparation: PreparationManifest = Field(default_factory=PreparationManifest)
    #: `inputs_digest` of the applicant profile and master resume this was built from.
    #: Fill always rebuilds in memory; this tells a reader of ``packet.json`` whether
    #: the saved copy is out of date.
    inputs_digest: str = ""


def inputs_digest(profile: ApplicantProfile, resume: MasterResume) -> str:
    """Hash of everything outside the job folder that a packet's fields come from."""
    payload = {
        "profile": profile.model_dump(mode="json", exclude={"workday_password"}),
        "resume": resume.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def current_inputs_digest() -> str:
    profile, _seeded = profile_mod.load_profile()
    return inputs_digest(profile, load())


_WORK_AUTH_LABELS: dict[str, str] = {
    "citizen": "U.S. Citizen",
    "permanent_resident": "Permanent Resident",
    "visa_holder": "Authorized to work in the U.S. with visa sponsorship",
    "other": "Other",
}


class ProfileFieldInfo(BaseModel):
    """Where a canonical field's answer lives on the Profile page."""

    label: str
    section: str
    common: bool = False


_CONTACT = "Application contact"
_ADDRESS = "Address and phone details"
_WORK_AUTH = "Work authorization and sponsorship"
_AVAILABILITY = "Availability and location preferences"
_EDUCATION = "Education"
_VOLUNTARY = "Voluntary information"
_SAVED = "Saved answers and other preferences"

#: Canonical keys with a profile source, keyed as ``build_fields`` emits them. ``common``
#: marks the facts application forms routinely ask for: a blank one is a known skip.
PROFILE_FIELDS: dict[str, ProfileFieldInfo] = {
    "first_name": ProfileFieldInfo(label="Legal first name", section=_CONTACT, common=True),
    "middle_name": ProfileFieldInfo(label="Middle name", section=_CONTACT),
    "last_name": ProfileFieldInfo(label="Legal last name", section=_CONTACT, common=True),
    "full_name": ProfileFieldInfo(label="Legal first and last name", section=_CONTACT),
    "preferred_name": ProfileFieldInfo(label="Preferred name", section=_CONTACT),
    "email": ProfileFieldInfo(label="Email", section=_CONTACT, common=True),
    "phone": ProfileFieldInfo(label="Phone", section=_CONTACT, common=True),
    "linkedin_url": ProfileFieldInfo(label="LinkedIn URL", section=_CONTACT),
    "github_url": ProfileFieldInfo(label="GitHub URL", section=_CONTACT),
    "address_line1": ProfileFieldInfo(label="Address line 1", section=_ADDRESS, common=True),
    "address_line2": ProfileFieldInfo(label="Address line 2", section=_ADDRESS),
    "city": ProfileFieldInfo(label="City", section=_ADDRESS, common=True),
    "state": ProfileFieldInfo(label="State or province", section=_ADDRESS, common=True),
    "postal_code": ProfileFieldInfo(label="Postal code", section=_ADDRESS, common=True),
    "country": ProfileFieldInfo(label="Country", section=_ADDRESS, common=True),
    "phone_country_code": ProfileFieldInfo(label="Phone country code", section=_ADDRESS),
    "phone_country_region": ProfileFieldInfo(label="Phone country or region", section=_ADDRESS),
    "phone_device_type": ProfileFieldInfo(label="Phone device type", section=_ADDRESS, common=True),
    "work_authorization": ProfileFieldInfo(label="Work authorization", section=_WORK_AUTH),
    "authorization_country": ProfileFieldInfo(label="Authorization country", section=_WORK_AUTH),
    "authorized_to_work": ProfileFieldInfo(
        label="Authorized to work", section=_WORK_AUTH, common=True
    ),
    "requires_sponsorship": ProfileFieldInfo(
        label="Requires sponsorship now", section=_WORK_AUTH, common=True
    ),
    "requires_sponsorship_future": ProfileFieldInfo(
        label="Requires sponsorship future", section=_WORK_AUTH, common=True
    ),
    "requires_sponsorship_any": ProfileFieldInfo(
        label="Requires sponsorship now and future", section=_WORK_AUTH
    ),
    "f1_opt_eligible": ProfileFieldInfo(label="F1 opt eligible", section=_WORK_AUTH),
    "earliest_start": ProfileFieldInfo(label="Earliest start", section=_AVAILABILITY, common=True),
    "notice_period": ProfileFieldInfo(label="Notice period", section=_AVAILABILITY),
    "willing_to_relocate": ProfileFieldInfo(label="Willing to relocate", section=_AVAILABILITY),
    "location_preference": ProfileFieldInfo(
        label="Location preference", section=_AVAILABILITY
    ),
    "school": ProfileFieldInfo(label="School", section=_EDUCATION, common=True),
    "gpa": ProfileFieldInfo(label="GPA", section=_EDUCATION),
    "degree_level": ProfileFieldInfo(label="Degree level", section=_EDUCATION, common=True),
    "major": ProfileFieldInfo(label="Major", section=_EDUCATION, common=True),
    "education_start_month": ProfileFieldInfo(label="Education start month", section=_EDUCATION),
    "graduation_month": ProfileFieldInfo(label="Graduation month", section=_EDUCATION, common=True),
    "gender": ProfileFieldInfo(label="Gender", section=_VOLUNTARY, common=True),
    "race": ProfileFieldInfo(label="Race", section=_VOLUNTARY, common=True),
    "hispanic_latino": ProfileFieldInfo(
        label="Hispanic or Latino", section=_VOLUNTARY, common=True
    ),
    "veteran_status": ProfileFieldInfo(label="Veteran", section=_VOLUNTARY, common=True),
    "disability_status": ProfileFieldInfo(label="Disability", section=_VOLUNTARY, common=True),
    "over_18": ProfileFieldInfo(label="Over 18", section=_VOLUNTARY, common=True),
    "languages": ProfileFieldInfo(label="Languages", section="Languages"),
    "how_heard": ProfileFieldInfo(label="How heard", section=_SAVED, common=True),
    "how_heard_detail": ProfileFieldInfo(label="How heard", section=_SAVED),
    "portfolio_url": ProfileFieldInfo(label="Portfolio URL", section=_SAVED),
    "visa_status": ProfileFieldInfo(label="Visa status", section=_WORK_AUTH),
    "class_year": ProfileFieldInfo(label="Class standing", section=_EDUCATION),
    "school_email": ProfileFieldInfo(label="School email", section=_EDUCATION),
    "security_clearance": ProfileFieldInfo(label="Security clearance", section=_AVAILABILITY),
    "drivers_license": ProfileFieldInfo(label="Driver's license", section=_AVAILABILITY),
    "hours_per_week": ProfileFieldInfo(label="Hours per week available", section=_AVAILABILITY),
}

_CLEARANCE_LABELS: dict[str, str] = {
    "none": "None",
    "eligible": "Eligible to obtain a clearance",
    "secret": "Secret",
    "top_secret": "Top Secret",
}


def class_year_for(graduation: str, degree_level: str, today: date | None = None) -> str | None:
    """Class standing ("Senior") from a "YYYY-MM" graduation month; "Graduate" for grad degrees.

    Counted in academic years to graduation (a May 2027 graduate is a Senior from
    June 2026). None when the month is unknown or already past.
    """
    if re.search(r"master|mba|ph\.?d|doctor|graduate", degree_level or "", re.I):
        return "Graduate"
    match = re.fullmatch(r"(\d{4})-(\d{2})", (graduation or "").strip())
    if not match:
        return None
    today = today or date.today()
    months = (int(match[1]) - today.year) * 12 + int(match[2]) - today.month
    if months < 0:
        return None
    years = months // 12
    return ("Senior", "Junior", "Sophomore", "Freshman")[min(years, 3)]


#: Harmless facts with an answer that is right for almost everyone, used only when the
#: profile leaves them blank. Never a legal or self-identification answer.
DEFAULTS: dict[str, str] = {"phone_device_type": "Mobile"}


#: Education facts the applicant profile holds itself (the rest live on the resume).
_PROFILE_EDUCATION_KEYS = frozenset({"class_year", "school_email"})


def profile_path(section: str, key: str = "") -> str:
    """The Profile page tab that holds ``section`` (or, for education, ``key``)."""
    if section == _EDUCATION and key not in _PROFILE_EDUCATION_KEYS:
        return "/profile/resume"  # education lives on the resume, not the profile
    return "/profile/personal" if section == _CONTACT else "/profile/application"


_US_STATES = frozenset({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
})
_US_STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
})
#: Countries a posting location names outright (alias -> name). Deliberately short: an
#: unrecognised location is "unknown", and unknown trusts the profile as before.
_COUNTRY_ALIASES: dict[str, str] = {
    "united states of america": "United States", "united states": "United States",
    "usa": "United States", "u.s.": "United States", "us": "United States",
    "canada": "Canada", "united kingdom": "United Kingdom", "uk": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "india": "India",
    "germany": "Germany", "mexico": "Mexico", "france": "France", "ireland": "Ireland",
    "netherlands": "Netherlands", "poland": "Poland", "spain": "Spain", "italy": "Italy",
    "singapore": "Singapore", "japan": "Japan", "china": "China", "australia": "Australia",
    "brazil": "Brazil", "israel": "Israel", "philippines": "Philippines",
    "vietnam": "Vietnam", "costa rica": "Costa Rica", "romania": "Romania",
    "switzerland": "Switzerland", "sweden": "Sweden", "portugal": "Portugal",
}


def job_country(location: str) -> str | None:
    """The one country a location names ("Plymouth, Minnesota, United States" -> United
    States), or None when it names none or several. US states count as United States."""
    found: set[str] = set()
    for part in re.split(r"[,;/|()\-–—]+|\s+(?:or|and|&)\s+", location or ""):
        raw = part.strip()
        text = raw.casefold()
        if not text:
            continue
        if raw in _US_STATE_CODES or text in _US_STATES:
            found.add("United States")
            continue
        for alias, country in _COUNTRY_ALIASES.items():
            # Two-letter aliases ("us", "uk") only as the whole part: "us" is a word too.
            if (text == alias) if len(alias) <= 4 else re.search(rf"\b{re.escape(alias)}\b", text):
                found.add(country)
    return found.pop() if len(found) == 1 else None


def authorization_mismatch(profile: ApplicantProfile, location: str) -> tuple[str, str] | None:
    """``(job country, authorised country)`` when the posting is clearly elsewhere.

    The profile's "Authorized to work" answer is for its authorization country (or its
    home country); a posting in another country must not reuse it.
    """
    job = job_country(location)
    authorised = job_country(profile.authorization_country or profile.country)
    if job and authorised and job != authorised:
        return job, authorised
    return None


def field_info(key: str) -> ProfileFieldInfo:
    """Profile-page wording for ``key``; an unregistered key gets its own name."""
    return PROFILE_FIELDS.get(key) or ProfileFieldInfo(
        label=key.replace("_", " ").capitalize(), section="Application details"
    )


def profile_gaps(fields: dict[str, str]) -> list[str]:
    """Common profile-backed keys ``fields`` has no answer for, in registry order."""
    return [key for key, info in PROFILE_FIELDS.items() if info.common and not fields.get(key)]


#: filler.js's leftover reason for a recognised question whose profile fact is blank.
BLANK_PROFILE_REASON = "Profile field is blank"


def missing_profile(blank: list[dict], filled_labels: set[str]) -> list[dict]:
    """Group recognised-but-blank questions by profile fact for ``FillResult``.

    ``answered`` is true when every such question was filled anyway (a saved answer or
    the Autofill model): it still belongs to the profile, so the next fill is certain.
    """
    grouped: dict[str, list[str]] = {}
    for item in blank:
        key = str(item.get("key") or "")
        if key not in PROFILE_FIELDS:
            # Not a profile field: the preferred-name tick, resume-derived employer, ...
            continue
        labels = grouped.setdefault(key, [])
        label = str(item.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    entries = []
    for key, questions in grouped.items():
        info = field_info(key)
        entries.append({
            "key": key, "field_label": info.label, "section": info.section,
            "path": profile_path(info.section, key), "questions": questions,
            "answered": bool(questions) and all(q in filled_labels for q in questions),
        })
    return entries


def _yes_no(value: bool | None) -> str | None:
    """Serialise a tri-state boolean for ATS Yes/No controls."""
    if value is None:
        return None
    return "Yes" if value else "No"


def _split_contact_name(full_name: str) -> tuple[str, str]:
    """Split a display name into first and last for fallback filling."""
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _pick(*values: str) -> str:
    """Return the first non-empty string."""
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _eeo_value(raw: str) -> str | None:
    """A self-identification answer; ``decline`` stays the literal sentinel "decline".

    Choice controls resolve it to the form's own decline option
    (`field_matcher.eeo_pattern`: "I do not want to answer", "Decline to Self Identify");
    it is never typed into a text box. Blank omits the field.
    """
    if not raw or not raw.strip():
        return None
    return "decline" if raw.strip().lower() == "decline" else raw.strip()


def languages_text(profile: ApplicantProfile) -> str:
    """"English (Native), Vietnamese (Intermediate)" for a free-text languages question."""
    parts = []
    for entry in profile.languages:
        name = entry.language.strip()
        if not name:
            continue
        level = (entry.levels.get("Overall") or "").strip() or ("Fluent" if entry.fluent else "")
        parts.append(f"{name} ({level})" if level else name)
    return ", ".join(parts)


def _work_authorization_label(code: str) -> str | None:
    """Turn a profile work-auth code into human-readable prose."""
    if not code:
        return None
    return _WORK_AUTH_LABELS.get(code, code.replace("_", " ").title())


def _maybe_set(fields: dict[str, str], key: str, value: str | None) -> None:
    """Insert ``key`` only when ``value`` is non-empty."""
    if value is not None and str(value).strip():
        fields[key] = str(value).strip()


def build_fields(profile: ApplicantProfile, resume: MasterResume) -> dict[str, str]:
    """Build flat canonical field values from profile with resume contact fallbacks."""
    contact = resume.contact
    contact_first, contact_last = _split_contact_name(contact.name)

    first_name = _pick(profile.first_name, contact_first)
    last_name = _pick(profile.last_name, contact_last)
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()

    current_company = ""
    current_title = ""
    if resume.experience:
        current = resume.experience[0]
        current_company = current.company
        current_title = current.title

    fields: dict[str, str] = {}
    _maybe_set(fields, "first_name", first_name or None)
    _maybe_set(fields, "middle_name", profile.middle_name or None)
    _maybe_set(fields, "last_name", last_name or None)
    _maybe_set(fields, "full_name", full_name or None)
    _maybe_set(fields, "preferred_name", profile.preferred_name or None)
    if profile.preferred_name.strip() and profile.preferred_name.strip().casefold() != (first_name or "").strip().casefold():
        # Ticks Workday's "I have a preferred name" box, which reveals the inputs.
        fields["has_preferred_name"] = "Yes"
    _maybe_set(fields, "email", _pick(profile.email, contact.email) or None)
    typed_phone = _pick(profile.phone, contact.phone)
    _maybe_set(fields, "phone", typed_phone or None)
    # The two shapes forms ask for (`phone.py`); the filler picks by the input's hints.
    code = profile.phone_country_code or "+1"
    _maybe_set(fields, "phone_e164", phone_mod.e164(typed_phone, code))
    _maybe_set(fields, "phone_national", phone_mod.national(typed_phone, code))
    _maybe_set(fields, "phone_device_type", profile.phone_device_type or DEFAULTS["phone_device_type"])
    _maybe_set(fields, "phone_country_code", profile.phone_country_code or None)
    _maybe_set(fields, "phone_country_region", profile.phone_country_region or None)
    _maybe_set(fields, "address_line1", profile.address_line1 or None)
    _maybe_set(fields, "address_line2", profile.address_line2 or None)
    _maybe_set(fields, "city", profile.city or None)
    _maybe_set(fields, "state", profile.state or None)
    _maybe_set(fields, "postal_code", profile.postal_code or None)
    _maybe_set(fields, "country", profile.country or None)
    _maybe_set(
        fields,
        "linkedin_url",
        _pick(profile.linkedin_url, contact.linkedin) or None,
    )
    _maybe_set(
        fields,
        "github_url",
        _pick(profile.github_url, contact.github) or None,
    )
    _maybe_set(fields, "portfolio_url", profile.portfolio_url or None)
    if profile.portfolio_url:
        _maybe_set(fields, "website", profile.portfolio_url)
    _maybe_set(fields, "work_authorization", _work_authorization_label(profile.work_authorization))
    _maybe_set(fields, "authorized_to_work", _yes_no(profile.authorized_to_work))
    _maybe_set(fields, "authorization_country", profile.authorization_country or None)
    # An explicit Yes/No wins; otherwise the visa status implies one (`sponsorship_from_visa`).
    implied = profile_mod.sponsorship_from_visa(profile.visa_status)
    sponsor_now = profile.requires_sponsorship_now
    sponsor_future = profile.requires_sponsorship_future
    if implied is not None:
        sponsor_now = implied[0] if sponsor_now is None else sponsor_now
        sponsor_future = implied[1] if sponsor_future is None else sponsor_future
    _maybe_set(fields, "requires_sponsorship", _yes_no(sponsor_now))
    _maybe_set(fields, "requires_sponsorship_future", _yes_no(sponsor_future))
    f1_opt = profile.f1_opt_eligible
    if f1_opt is None and profile.visa_status.startswith("f1"):
        f1_opt = True
    _maybe_set(fields, "f1_opt_eligible", _yes_no(f1_opt))
    _maybe_set(fields, "visa_status", profile_mod.VISA_LABELS.get(profile.visa_status))
    _maybe_set(fields, "over_18", _yes_no(profile.over_18))
    _maybe_set(fields, "earliest_start", profile.earliest_start or None)
    _maybe_set(fields, "notice_period", profile.notice_period or None)
    if sponsor_now is True or sponsor_future is True:
        fields["requires_sponsorship_any"] = "Yes"
    elif sponsor_now is False and sponsor_future is False:
        fields["requires_sponsorship_any"] = "No"
    # Single-field forms ("School", "Major", "Graduation date") answer from the current
    # school: the entry graduating last (a transfer student's new school, the later of
    # two degrees), else the first entry.
    education = _build_education(resume)
    if education:
        primary = current_education(education)
        _maybe_set(fields, "education_start_month", primary.start or None)
        _maybe_set(fields, "graduation_month", primary.end or None)
        _maybe_set(fields, "degree_level", primary.degree_level or None)
        _maybe_set(fields, "major", primary.major or None)
        _maybe_set(fields, "school", primary.school or None)
        _maybe_set(fields, "gpa", primary.gpa or None)
    # Profile overrides for what the resume states differently or not at all.
    _maybe_set(fields, "graduation_month", profile.graduation_date or None)
    _maybe_set(fields, "gpa", profile.gpa_display or None)
    class_year = profile.class_year.capitalize() if profile.class_year else class_year_for(
        fields.get("graduation_month", ""), fields.get("degree_level", "")
    )
    _maybe_set(fields, "class_year", class_year)
    email = fields.get("email", "")
    _maybe_set(
        fields,
        "school_email",
        profile.school_email or (email if email.lower().endswith(".edu") else None),
    )
    _maybe_set(fields, "security_clearance", _CLEARANCE_LABELS.get(profile.security_clearance))
    _maybe_set(fields, "drivers_license", _yes_no(profile.drivers_license))
    if profile.hours_per_week_available is not None:
        fields["hours_per_week"] = str(profile.hours_per_week_available)
    # Salary depends on the posting (`apply/salary.py`); the fill runner adds it.
    _maybe_set(fields, "willing_to_relocate", _yes_no(profile.willing_to_relocate))
    _maybe_set(fields, "location_preference", profile.location_preference or None)
    _maybe_set(fields, "how_heard", profile.how_heard or None)
    # Typed into "If other, please specify" when the source list has no such option.
    _maybe_set(fields, "how_heard_detail", profile.how_heard or None)
    _maybe_set(fields, "gender", _eeo_value(profile.eeo.gender))
    _maybe_set(fields, "race", _eeo_value(profile.eeo.race))
    _maybe_set(fields, "race_detail", profile.eeo.race_detail or None)
    _maybe_set(fields, "hispanic_latino", _yes_no(profile.eeo.hispanic_latino))
    _maybe_set(fields, "veteran_status", _eeo_value(profile.eeo.veteran))
    _maybe_set(fields, "disability_status", _eeo_value(profile.eeo.disability))
    _maybe_set(fields, "languages", languages_text(profile) or None)
    _maybe_set(fields, "current_company", current_company or None)
    _maybe_set(fields, "current_title", current_title or None)
    return fields


def _degree_label(degree: str) -> str:
    """The named degree a resume degree line states ("Bachelor of Science" from
    "Bachelor of Science in Computer Science & Minor in ..."), else the line itself."""
    parsed = field_matcher.degree_of(degree)
    if not parsed or not parsed[1]:
        return degree.strip()
    return " ".join(word if word in {"of", "in"} else word.capitalize() for word in parsed[1].split())


def _build_education(resume: MasterResume) -> list[PacketEducation]:
    """One packet row per resume education entry: the resume is the only education source."""
    rows: list[PacketEducation] = []
    for index, edu in enumerate(resume.education):
        # The editor's structured months win; older files only have the printed dates.
        parsed_start, parsed_end = edu_dates.months(edu.dates)
        start = edu.start or parsed_start
        end = edu.end or parsed_end
        if not (start or end):
            start, end = parse_range(edu.dates)
        rows.append(
            PacketEducation(
                school=edu.school,
                degree=edu.degree,
                major=edu.major,
                start=start,
                end=end,
                gpa=edu.gpa,
                entry_key=f"resume:education:{index}",
                degree_level=_degree_label(edu.degree),
                degree_name=edu.degree,
                source="resume",
            )
        )
    return rows


def current_education(education: list[PacketEducation]) -> PacketEducation:
    """The row a single "School"/"Graduation date" question means: the latest ``end``
    month, ties and undated rows falling back to resume order."""
    dated = [row for row in education if edu_dates.MONTH_RE.match(row.end or "")]
    if not dated:
        return education[0]
    return max(dated, key=lambda row: row.end)


def degree_name(education: list[PacketEducation], level: str) -> str:
    """The one named degree at the profile's level ("Bachelor of Science" from "Bachelor
    of Science in Computer Science & Minor in ..."), so a choice list of "BS"/"BA" is
    answered without the model; "" when the rows disagree or name none."""
    wanted = field_matcher.degree_of(level) if level else None
    names = {
        degree[1] for row in education
        for degree in [field_matcher.degree_of(row.degree_name or row.degree)]
        if degree and degree[1] and (wanted is None or degree[0] == wanted[0])
    }
    if len(names) != 1:
        return ""
    words = names.pop().split()
    return " ".join(word if word in {"of", "in"} else word.capitalize() for word in words)


def _experience_from_expansion(entries: list[ExpandedEntry]) -> list[PacketExperience]:
    """Map expansion artifact entries to packet experience rows."""
    rows: list[PacketExperience] = []
    for entry in entries:
        description = "\n".join(f"• {bullet}" for bullet in entry.bullets)
        rows.append(
            PacketExperience(
                employer=entry.company,
                title=entry.title,
                location=entry.location,
                start=entry.start,
                end=entry.end,
                current=entry.end.lower() in {"present", "current"},
                description=description,
                char_count=len(description),
                entry_key=entry.entry_key,
                source_entry_id=entry.entry_key.removeprefix("exp:"),
                bullets=list(entry.bullets),
                warnings=list(entry.warnings),
            )
        )
    return rows


def _experience_from_resume(resume: MasterResume) -> list[PacketExperience]:
    """Build experience rows from the master resume with empty descriptions."""
    rows: list[PacketExperience] = []
    for entry in resume.experience:
        rows.append(
            PacketExperience(
                employer=entry.company,
                title=entry.title,
                location=entry.location,
                start=entry.start,
                end=entry.end,
                current=entry.end.lower() in {"present", "current"},
                description="",
                char_count=0,
                entry_key=f"exp:{entry.id}",
                source_entry_id=entry.id,
            )
        )
    return rows


def _load_expansion(path: Path) -> Expansion | None:
    """Parse ``expansion.json`` when present."""
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = [
        ExpandedEntry(
            entry_key=item.get("entry_key", ""),
            title=item.get("title", ""),
            company=item.get("company", ""),
            location=item.get("location", ""),
            start=item.get("start", ""),
            end=item.get("end", ""),
            bullets=list(item.get("bullets", [])),
            char_count=int(item.get("char_count", 0)),
            warnings=list(item.get("warnings", [])),
            on_resume=bool(item.get("on_resume", False)),
        )
        for item in raw.get("entries", [])
    ]
    return Expansion(
        entries=entries,
        warnings=list(raw.get("warnings", [])),
        model=str(raw.get("model", "")),
        char_limit=int(raw.get("char_limit", 0)),
    )


def _load_skills(path: Path) -> list[str]:
    """Extract skill labels from ``skills.json`` when present."""
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    skills = raw.get("skills", [])
    if not isinstance(skills, list):
        return []
    labels: list[str] = []
    for item in skills:
        if isinstance(item, dict) and item.get("skill"):
            labels.append(str(item["skill"]))
        elif isinstance(item, str):
            labels.append(item)
    return labels


def _load_cover_letter(path: Path) -> str:
    """Join cover-letter body paragraphs when ``cover.json`` exists."""
    if not path.is_file():
        return ""
    raw = json.loads(path.read_text(encoding="utf-8"))
    paragraphs = raw.get("paragraphs", [])
    if not isinstance(paragraphs, list):
        return ""
    return "\n\n".join(str(p).strip() for p in paragraphs if str(p).strip())


def _artifact_paths(job_dir: Path) -> dict[str, str]:
    """Collect absolute paths to rendered documents that exist on disk."""
    mapping = {
        "resume_pdf": job_dir / "tailored.pdf",
        "resume_docx": job_dir / "tailored.docx",
        "cover_pdf": job_dir / "cover.pdf",
        "cover_docx": job_dir / "cover.docx",
    }
    return {kind: str(path) for kind, path in mapping.items() if path.is_file()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_packet(
    job_id: str, *, out_dir: Path | None = None,
    applicant_profile: profile_mod.ApplicantProfile | None = None,
) -> Packet:
    """Assemble a packet from job artifacts, profile, and master resume."""
    job_dir = out_dir if out_dir is not None else config.OUTPUT_DIR / "jobs" / job_id
    run_path = job_dir / "run.json"
    if not run_path.is_file():
        raise FileNotFoundError(f"run.json not found for job {job_id!r} at {run_path}")

    run = json.loads(run_path.read_text(encoding="utf-8"))
    metadata = run.get("metadata") or {}
    report = run.get("report") or {}

    if applicant_profile is None:
        applicant_profile, _seeded = profile_mod.load_profile()
    resume = load()

    from resume_tailor.apply import preparation

    expansion_path = job_dir / "expansion.json"
    prepared_expansion = preparation.read_expansion(expansion_path) if expansion_path.is_file() else None
    expansion = prepared_expansion.as_expansion() if prepared_expansion is not None else None
    experience = _experience_from_expansion(expansion.entries) if expansion is not None else []
    artifacts = _artifact_paths(job_dir)
    for kind in ("transcript", "portfolio"):
        uploaded = getattr(applicant_profile, f"{kind}_path")
        if uploaded and Path(uploaded).is_file():
            artifacts[f"{kind}_pdf"] = uploaded
    manifest_artifacts = [PreparedArtifact(
        purpose=kind, path=path, filename=Path(path).name,
        mime_type="application/pdf" if kind.endswith("pdf") else
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sha256=_sha256(Path(path)),
    ) for kind, path in artifacts.items()]
    expansion_status = prepared_expansion.status if prepared_expansion is not None else "missing"
    manifest = PreparationManifest(
        preparation_id=_sha256(run_path)[:16], job_id=job_id,
        prepared_at=datetime.fromtimestamp(run_path.stat().st_mtime, timezone.utc).isoformat(),
        source_revision=_sha256(run_path), expansion_status=expansion_status,
        expansion_hash=_sha256(expansion_path) if expansion_path.is_file() else "",
        artifacts=manifest_artifacts,
        preparation_warnings=list(expansion.warnings) if expansion else [],
    )

    ats = str(metadata.get("ats") or "unknown")
    education = _build_education(resume)
    fields = build_fields(applicant_profile, resume)
    named = degree_name(education, fields.get("degree_level", ""))
    _maybe_set(fields, "degree_name", named or None)
    return Packet(
        job_id=job_id,
        built_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        posting_url=str(metadata.get("posting_url") or ""),
        company=str(metadata.get("company") or ""),
        role=str(metadata.get("role") or report.get("title") or ""),
        ats=ats,
        fields=fields,
        education=education,
        experience=experience,
        skills=_load_skills(job_dir / "skills.json"),
        languages=[
            PacketLanguage(language=entry.language.strip(), fluent=entry.fluent,
                           levels={k: v for k, v in entry.levels.items() if v.strip()})
            for entry in applicant_profile.languages if entry.language.strip()
        ],
        cover_letter=_load_cover_letter(job_dir / "cover.json"),
        artifacts=artifacts,
        field_hints=ats_hints.hints_for(ats),
        gaps=list(report.get("gaps") or []),
        preparation=manifest,
        inputs_digest=inputs_digest(applicant_profile, resume),
    )


#: One writer at a time: on Windows, two threads replacing the same ``packet.json`` at
#: once fail with "Access is denied" (the job thread and a rebuild request can race).
_WRITE_LOCK = threading.Lock()


def _replace(src: Path, dst: Path, attempts: int = 10) -> None:
    """``os.replace``, retried briefly while a reader holds ``dst`` open (Windows)."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def write_packet(job_id: str) -> Packet:
    """Build and persist ``packet.json`` for ``job_id``."""
    packet = build_packet(job_id)
    job_dir = config.OUTPUT_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "packet.json"
    # Temp file + rename: the job is already "succeeded" when this runs, so a reader
    # (the Apply page, the MCP server) can open the file mid-write. An in-place
    # write_text truncates first and was read back as empty JSON. The temp name is
    # unique because the job thread and a rebuild request can write at the same time.
    tmp = path.with_name(f"packet.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
        with _WRITE_LOCK:
            _replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return packet
