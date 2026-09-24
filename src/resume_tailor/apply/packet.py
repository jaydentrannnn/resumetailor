"""Application packet assembly from a completed tailoring run.

Pure function of disk artifacts, the master resume, and the applicant profile — no LLM.
``build_packet`` reads ``run.json``, optional expansion/skills/cover/bullets JSON, and
paths to rendered documents; ``write_packet`` persists ``packet.json`` beside them.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply import ats_hints, field_matcher, profile as profile_mod
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
}

#: Harmless facts with an answer that is right for almost everyone, used only when the
#: profile leaves them blank. Never a legal or self-identification answer.
DEFAULTS: dict[str, str] = {"phone_device_type": "Mobile"}


def profile_path(section: str) -> str:
    """The Profile page tab that holds ``section``."""
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
            "path": profile_path(info.section), "questions": questions,
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
    _maybe_set(fields, "phone", _pick(profile.phone, contact.phone) or None)
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
    _maybe_set(fields, "requires_sponsorship", _yes_no(profile.requires_sponsorship_now))
    _maybe_set(
        fields,
        "requires_sponsorship_future",
        _yes_no(profile.requires_sponsorship_future),
    )
    _maybe_set(fields, "f1_opt_eligible", _yes_no(profile.f1_opt_eligible))
    _maybe_set(fields, "over_18", _yes_no(profile.over_18))
    _maybe_set(fields, "earliest_start", profile.earliest_start or None)
    _maybe_set(fields, "notice_period", profile.notice_period or None)
    if profile.requires_sponsorship_now is True or profile.requires_sponsorship_future is True:
        fields["requires_sponsorship_any"] = "Yes"
    elif profile.requires_sponsorship_now is False and profile.requires_sponsorship_future is False:
        fields["requires_sponsorship_any"] = "No"
    _maybe_set(fields, "education_start_month", profile.education_start_month or None)
    _maybe_set(fields, "graduation_month", profile.graduation_month or None)
    _maybe_set(fields, "degree_level", profile.degree_level or None)
    _maybe_set(fields, "major", profile.major or None)
    _maybe_set(fields, "school", profile.school or None)
    _maybe_set(fields, "gpa", profile.gpa or None)
    # Salary depends on the posting (`apply/salary.py`); the fill runner adds it.
    _maybe_set(fields, "willing_to_relocate", _yes_no(profile.willing_to_relocate))
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


def _education_from_profile(profile: ApplicantProfile) -> PacketEducation | None:
    """Build one education row when any profile education field is set."""
    if not any(
        (
            profile.school,
            profile.degree_level,
            profile.major,
            profile.gpa,
            profile.education_start_month,
            profile.graduation_month,
        )
    ):
        return None
    return PacketEducation(
        school=profile.school,
        degree=profile.degree_level,
        major=profile.major,
        start=profile.education_start_month,
        end=profile.graduation_month,
        gpa=profile.gpa,
        entry_key="profile:education",
        degree_level=profile.degree_level,
        degree_name=profile.degree_level,
        source="profile",
    )


def _education_from_resume(resume: MasterResume) -> list[PacketEducation]:
    """Convert resume education entries into packet rows."""
    rows: list[PacketEducation] = []
    for index, edu in enumerate(resume.education):
        start, end = parse_range(edu.dates)
        rows.append(
            PacketEducation(
                school=edu.school,
                degree=edu.degree,
                start=start,
                end=end,
                gpa=edu.gpa if edu.gpa else "",
                entry_key=f"resume:education:{index}",
                degree_name=edu.degree,
                source="resume",
            )
        )
    return rows


def _build_education(profile: ApplicantProfile, resume: MasterResume) -> list[PacketEducation]:
    """Merge profile-first education with resume entries."""
    rows: list[PacketEducation] = []
    profile_row = _education_from_profile(profile)
    if profile_row is not None:
        rows.append(profile_row)
    def school_key(value: str) -> str:
        normalized = " ".join(value.casefold().replace("-", " ").replace(",", " ").split())
        if normalized in {"university of california irvine", "uc irvine", "uci"}:
            return "university of california irvine"
        return normalized

    resume_rows = _education_from_resume(resume)
    for row in resume_rows:
        def same_degree(existing: PacketEducation, candidate: PacketEducation) -> bool:
            left = existing.degree.casefold().strip()
            right = candidate.degree.casefold().strip()
            generic_bachelor = {"bachelor", "bachelors", "bachelor's", "bachelors degree"}
            specific_bachelor = lambda value: value.startswith(("bachelor of ", "bs ", "ba "))
            return (
                left == right or not left or not right
                or (existing.source == "profile" and left in generic_bachelor and specific_bachelor(right))
            )

        matches = [
            existing for existing in rows
            if school_key(existing.school) and school_key(existing.school) == school_key(row.school)
            and same_degree(existing, row)
            and (not existing.end or not row.end or existing.end[:4] == row.end[:4])
        ]
        if len(matches) != 1:
            rows.append(row)
        else:
            match = matches[0]
            # A single matching resume entry can supply a missing profile date.
            # Multiple entries for the same school/degree do not establish one date.
            candidates = [candidate for candidate in resume_rows
                          if school_key(candidate.school) == school_key(row.school)
                          and same_degree(match, candidate)
                          and (not match.end or not candidate.end or match.end[:4] == candidate.end[:4])]
            if len(candidates) == 1:
                match.start = match.start or row.start
                match.end = match.end or row.end
            match.gpa = match.gpa or row.gpa
            if match.source == "profile" and match.degree.casefold().strip() in {
                "bachelor", "bachelors", "bachelor's", "bachelors degree",
            } and row.degree_name.casefold().startswith(("bachelor of ", "bs ", "ba ")):
                match.degree_name = row.degree_name
    return rows


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
    education = _build_education(applicant_profile, resume)
    fields = build_fields(applicant_profile, resume)
    if not fields.get("education_start_month"):
        matching = [row for row in education if row.start and row.school
                    and row.school.casefold().replace(",", "").replace("-", " ").split()
                    == applicant_profile.school.casefold().replace(",", "").replace("-", " ").split()]
        if len(matching) == 1:
            fields["education_start_month"] = matching[0].start
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
    )


def write_packet(job_id: str) -> Packet:
    """Build and persist ``packet.json`` for ``job_id``."""
    packet = build_packet(job_id)
    job_dir = config.OUTPUT_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "packet.json"
    path.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return packet
