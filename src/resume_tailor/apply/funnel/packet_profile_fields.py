"""Where each canonical form field's answer lives on the Profile page, and which blanks are gaps."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel

from resume_tailor.apply.answers import form_facts
from resume_tailor.apply.answers.profile import ApplicantProfile

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
    #: Often legitimately blank (no middle name, no apartment): a blank one is never a
    #: profile gap, and a form's *optional* question for it is skipped silently. A form
    #: that marks it required still stops for review through ``required_empty``.
    optional: bool = False

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
    "middle_name": ProfileFieldInfo(label="Middle name", section=_CONTACT, optional=True),
    "last_name": ProfileFieldInfo(label="Legal last name", section=_CONTACT, common=True),
    "full_name": ProfileFieldInfo(label="Legal first and last name", section=_CONTACT),
    "preferred_name": ProfileFieldInfo(label="Preferred name", section=_CONTACT),
    "email": ProfileFieldInfo(label="Email", section=_CONTACT, common=True),
    "phone": ProfileFieldInfo(label="Phone", section=_CONTACT, common=True),
    "linkedin_url": ProfileFieldInfo(label="LinkedIn URL", section=_CONTACT),
    "github_url": ProfileFieldInfo(label="GitHub URL", section=_CONTACT),
    "address_line1": ProfileFieldInfo(label="Address line 1", section=_ADDRESS, common=True),
    "address_line2": ProfileFieldInfo(label="Address line 2", section=_ADDRESS, optional=True),
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
    "us_citizen": ProfileFieldInfo(label="Work authorization", section=_WORK_AUTH),
    "us_person_status": ProfileFieldInfo(label="Work authorization", section=_WORK_AUTH),
    "citizenship": ProfileFieldInfo(label="Country of citizenship", section=_WORK_AUTH),
    "government_employee": ProfileFieldInfo(
        label="Current or former government employee", section=_WORK_AUTH,
    ),
    "conflict_of_interest": ProfileFieldInfo(label="Conflict of interest", section=_SAVED),
    "earliest_start": ProfileFieldInfo(label="Earliest start", section=_AVAILABILITY, common=True),
    "notice_period": ProfileFieldInfo(label="Notice period", section=_AVAILABILITY),
    "willing_to_relocate": ProfileFieldInfo(label="Willing to relocate", section=_AVAILABILITY),
    "location_preference": ProfileFieldInfo(
        label="Location preference", section=_AVAILABILITY
    ),
    "school": ProfileFieldInfo(label="School", section=_EDUCATION, common=True),
    "gpa": ProfileFieldInfo(label="GPA", section=_EDUCATION),
    "degree_level": ProfileFieldInfo(label="Degree level", section=_EDUCATION, common=True),
    "highest_education_obtained": ProfileFieldInfo(
        label="Highest education completed", section=_EDUCATION,
    ),
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
    "sexual_orientation": ProfileFieldInfo(label="Sexual orientation", section=_VOLUNTARY),
    "over_18": ProfileFieldInfo(label="Over 18", section=_VOLUNTARY, common=True),
    "languages": ProfileFieldInfo(label="Languages", section="Languages"),
    "how_heard": ProfileFieldInfo(label="How heard", section=_SAVED, common=True),
    "how_heard_detail": ProfileFieldInfo(label="How heard", section=_SAVED),
    "portfolio_url": ProfileFieldInfo(label="Portfolio URL", section=_SAVED),
    "visa_status": ProfileFieldInfo(label="Visa status", section=_WORK_AUTH),
    "class_year": ProfileFieldInfo(label="Class standing", section=_EDUCATION),
    "high_school_graduation_year": ProfileFieldInfo(
        label="High-school graduation year", section=_EDUCATION,
    ),
    "relatives_at_company": ProfileFieldInfo(label="Relatives at the company", section=_VOLUNTARY),
    "auto_accept_notices": ProfileFieldInfo(label="Agree to required notices", section=_SAVED),
    "auto_accept_agreements": ProfileFieldInfo(
        label="Agree to terms, certifications and signatures", section=_SAVED,
    ),
    "consider_other_positions": ProfileFieldInfo(label="Consider me for other positions", section="Answering questions"),
    "minimum_qualifications": ProfileFieldInfo(label="General minimum qualifications", section="Answering questions"),
    "experience_years": ProfileFieldInfo(label="Years of experience", section="Experience"),
    "school_email": ProfileFieldInfo(label="School email", section=_EDUCATION),
    "security_clearance": ProfileFieldInfo(label="Security clearance", section=_AVAILABILITY),
    "drivers_license": ProfileFieldInfo(label="Driver's license", section=_AVAILABILITY),
    "hours_per_week": ProfileFieldInfo(label="Hours per week available", section=_AVAILABILITY),
    "noncompete": ProfileFieldInfo(
        label="Subject to a non-compete", section=_AVAILABILITY, common=True
    ),
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
_PROFILE_EDUCATION_KEYS = frozenset({
    "class_year", "school_email", "highest_education_obtained", "high_school_graduation_year",
})

_CONSENT_KEYS = frozenset({"auto_accept_notices", "auto_accept_agreements"})


def profile_path(section: str, key: str = "") -> str:
    """The page (a Profile tab, or Resume) that holds ``section`` (or, for education, ``key``)."""
    if section == "Answering questions" or key in _CONSENT_KEYS:
        return "/apply"
    if section == _EDUCATION and key not in _PROFILE_EDUCATION_KEYS:
        return "/resume"
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
    "taiwan": "Taiwan", "south korea": "South Korea", "korea": "South Korea",
    "hong kong": "Hong Kong", "new zealand": "New Zealand", "belgium": "Belgium",
    "denmark": "Denmark", "norway": "Norway", "finland": "Finland", "austria": "Austria",
    "czech republic": "Czech Republic", "czechia": "Czech Republic", "hungary": "Hungary",
    "argentina": "Argentina", "colombia": "Colombia", "chile": "Chile", "egypt": "Egypt",
    "south africa": "South Africa", "nigeria": "Nigeria", "kenya": "Kenya",
    "united arab emirates": "United Arab Emirates", "uae": "United Arab Emirates",
    "saudi arabia": "Saudi Arabia", "malaysia": "Malaysia", "indonesia": "Indonesia",
    "thailand": "Thailand", "pakistan": "Pakistan", "bangladesh": "Bangladesh",
    "turkey": "Turkey", "greece": "Greece", "ukraine": "Ukraine", "serbia": "Serbia",
    "estonia": "Estonia", "lithuania": "Lithuania", "luxembourg": "Luxembourg",
    "northern ireland": "United Kingdom", "wales": "United Kingdom",
    # The country, not the U.S. state (which a bare "Georgia" stays).
    "tbilisi": "Georgia",
}

#: Canadian provinces and territories, by name and by postal code ("Vancouver, BC").
_CA_PROVINCES = frozenset({
    "ontario", "quebec", "british columbia", "alberta", "manitoba", "saskatchewan",
    "nova scotia", "new brunswick", "newfoundland and labrador", "newfoundland",
    "prince edward island", "yukon", "northwest territories", "nunavut",
})
_CA_PROVINCE_CODES = frozenset({
    "ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU",
})


def _part_country(raw: str) -> set[str]:
    """Countries one comma-separated part of a location names."""
    text = raw.casefold()
    if raw in _US_STATE_CODES or text in _US_STATES:
        return {"United States"}
    if raw in _CA_PROVINCE_CODES or text in _CA_PROVINCES:
        return {"Canada"}
    found: set[str] = set()
    for alias, country in _COUNTRY_ALIASES.items():
        if len(alias) <= 4:
            # Short aliases ("us", "uk") only as the whole part or after "in"/"remote"
            # ("Remote in USA"): "us" is a word too.
            pattern = rf"(?:^|\b(?:in|remote)\s+){re.escape(alias)}$"
        else:
            pattern = rf"\b{re.escape(alias)}\b"
        if re.search(pattern, text):
            found.add(country)
    return found


def location_countries(location: str) -> list[set[str]]:
    """The countries each " | "-separated place of a posting names, in order."""
    places = []
    for place in re.split(r"\s*\|\s*|\s*;\s*", location or ""):
        found: set[str] = set()
        for part in re.split(r"[,/()\-–—]+|\s+(?:or|and|&)\s+", place):
            if part.strip():
                found |= _part_country(part.strip())
        # "Tbilisi, Georgia": the bare "Georgia" was read as the U.S. state.
        if {"Georgia", "United States"} <= found and not re.search(
            r"united states|\busa?\b|\bu\.s\.", place, re.I
        ):
            found.discard("United States")
        if place.strip():
            places.append(found)
    return places


def job_country(location: str) -> str | None:
    """The one country a location names ("Plymouth, Minnesota, United States" -> United
    States), or None when it names none or several. US states count as United States,
    Canadian provinces as Canada."""
    found = set().union(*location_countries(location)) if location else set()
    return found.pop() if len(found) == 1 else None


def authorized_countries(profile: ApplicantProfile) -> set[str]:
    """Every country the profile may work in (its home country when none is listed)."""
    named = profile.authorization_countries or [profile.country]
    known = set(_COUNTRY_ALIASES.values())
    # A listed country is taken as named ("Georgia" the country, not the U.S. state).
    found = (name if name in known else job_country(name) for name in named)
    return {country for country in found if country}


def authorization_mismatch(profile: ApplicantProfile, location: str) -> tuple[str, str] | None:
    """``(job country, authorised countries)`` when the posting is clearly elsewhere.

    The profile's "Authorized to work" answer is for its authorization countries (or its
    home country); a posting in another country must not reuse it.
    """
    job = job_country(location)
    authorised = authorized_countries(profile)
    if job and authorised and job not in authorised:
        return job, " or ".join(sorted(authorised))
    return None

def field_info(key: str) -> ProfileFieldInfo:
    """Profile-page wording for ``key``; an unregistered key gets its own name."""
    return PROFILE_FIELDS.get(key) or ProfileFieldInfo(
        label=key.replace("_", " ").capitalize(), section="Application details"
    )

def profile_gaps(fields: dict[str, str]) -> list[str]:
    """Common profile-backed keys ``fields`` has no answer for, in registry order."""
    return [key for key, info in PROFILE_FIELDS.items() if info.common and not fields.get(key)]

def is_optional(key: str) -> bool:
    """Whether a blank ``key`` is normal (see ``ProfileFieldInfo.optional``)."""
    info = PROFILE_FIELDS.get(key)
    return bool(info and info.optional)

def visible_missing_profile(entries: list) -> list:
    """Stored ``missing_profile`` minus optional fields no form required.

    Fills recorded before ``optional`` existed kept a blank middle name as a gap; this
    hides those without rewriting stored rows.
    """
    return [
        entry for entry in entries
        if not (isinstance(entry, dict) and is_optional(str(entry.get("key") or ""))
                and not entry.get("required"))
    ]

#: filler.js's leftover reason for a recognised question whose profile fact is blank.
BLANK_PROFILE_REASON = "Profile field is blank"

def missing_profile(blank: list[dict], filled_labels: set[str]) -> list[dict]:
    """Group recognised-but-blank questions by profile fact for ``FillResult``.

    ``answered`` is true when every such question was filled anyway (a saved answer or
    the Autofill model): it still belongs to the profile, so the next fill is certain.
    An ``optional`` field (middle name, address line 2) is listed only when the form
    marked its question required.
    """
    grouped: dict[str, list[str]] = {}
    required: set[str] = set()
    for item in blank:
        key = str(item.get("key") or "")
        if key == "routine_acknowledgement":
            label = str(item.get("label") or "")
            key = "auto_accept_agreements" if form_facts.agreement(label) else "auto_accept_notices"
        if key not in PROFILE_FIELDS:
            # Not a profile field: the preferred-name tick, resume-derived employer, ...
            continue
        if PROFILE_FIELDS[key].optional and not item.get("required"):
            continue
        if item.get("required"):
            required.add(key)
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
            "required": key in required,
        })
    return entries
