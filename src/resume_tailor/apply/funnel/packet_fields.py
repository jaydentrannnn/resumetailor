"""Canonical form-field values built from the applicant profile and master resume (deterministic)."""

from __future__ import annotations

from resume_tailor.apply.answers import education_status
from resume_tailor.apply.answers import experience as experience_years
from resume_tailor.apply.answers import phone as phone_mod
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.forms import field_matcher
from resume_tailor.content import dates, degree_line, edu_dates
from resume_tailor.content.data import MajorEntry, MasterResume
from resume_tailor.document.render import parse_range

from . import packet_models, packet_profile_fields


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
    return packet_profile_fields._WORK_AUTH_LABELS.get(code, code.replace("_", " ").title())

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

    from resume_tailor.apply.answers import education as education_answers  # noqa: PLC0415

    fields: dict[str, str] = {}
    education_answers.refresh_fields(fields, profile.highest_education_obtained)
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
    _maybe_set(
        fields,
        "phone_device_type",
        profile.phone_device_type or packet_profile_fields.DEFAULTS["phone_device_type"],
    )
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
    # "Are you a U.S. citizen?" and "...citizen, permanent resident, asylee or refugee?"
    # (U.S. person, for export control) follow from the work-authorization category.
    status = profile.work_authorization
    if status:
        fields["us_citizen"] = "Yes" if status == "citizen" else "No"
        if status != "other":
            us_person = status in {"citizen", "permanent_resident"}
            fields["us_person_status"] = "Yes" if us_person else "No"
    _maybe_set(fields, "citizenship", profile.citizenship or None)
    fields["government_employee"] = _yes_no(profile.government_employee)
    fields["conflict_of_interest"] = _yes_no(profile.conflict_of_interest)
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
    _maybe_set(fields, "relatives_at_company", _yes_no(profile.relatives_at_company))
    fields["auto_accept_routine_acknowledgements"] = (
        _yes_no(profile.auto_accept_routine_acknowledgements)
    )
    _maybe_set(fields, "consider_other_positions", _yes_no(profile.consider_other_positions))
    _maybe_set(fields, "minimum_qualifications", _yes_no(profile.minimum_qualifications_answer))
    total = experience_years.calculate(resume, profile.experience_basis, profile.experience_years_custom)
    if total["years"] is not None:
        fields["experience_years"] = str(total["years"])
    _maybe_set(fields, "noncompete", _yes_no(profile.subject_to_noncompete))
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
    from resume_tailor.apply.answers import form_facts

    _maybe_set(
        fields, form_facts.HIGH_SCHOOL,
        profile.high_school_graduation_year or form_facts.high_school_year(education) or None,
    )
    if education:
        primary = current_education(education)
        _maybe_set(fields, "education_start_month", primary.start or None)
        _maybe_set(fields, "graduation_month", primary.end or None)
        _maybe_set(fields, "education_start_date", primary.start or None)
        _maybe_set(fields, "graduation_date", primary.end or None)
        _maybe_set(fields, "degree_level", primary.degree_level or None)
        _maybe_set(fields, "major", primary.major or None)
        _maybe_set(fields, "minor", primary.minor or None)
        _maybe_set(fields, "school", primary.school or None)
        _maybe_set(fields, "gpa", primary.gpa or None)
    # Profile overrides for what the resume states differently or not at all.
    _maybe_set(fields, "graduation_month", profile.graduation_date or None)
    if profile.graduation_date:
        # A legacy month override for the same month must not erase a newly supplied day.
        source_date = fields.get("graduation_date", "")
        if not (len(profile.graduation_date) == 7 and source_date[:7] == profile.graduation_date):
            fields["graduation_date"] = profile.graduation_date
    for key in ("education_start_month", "graduation_month"):
        if key in fields:
            fields[key] = fields[key][:7]
    status_education = [row.model_copy() for row in education]
    if status_education and profile.graduation_date:
        for row in status_education:
            if row.entry_key == primary.entry_key:
                row.end = fields.get("graduation_date", profile.graduation_date)
    fields.update(education_status.facts(status_education))
    _maybe_set(fields, "gpa", profile.gpa_display or None)
    class_year = (
        profile.class_year.capitalize()
        if profile.class_year
        else packet_profile_fields.class_year_for(
            fields.get("graduation_month", ""), fields.get("degree_level", "")
        )
    )
    _maybe_set(fields, "class_year", class_year)
    email = fields.get("email", "")
    _maybe_set(
        fields,
        "school_email",
        profile.school_email or (email if email.lower().endswith(".edu") else None),
    )
    _maybe_set(
        fields,
        "security_clearance",
        packet_profile_fields._CLEARANCE_LABELS.get(profile.security_clearance),
    )
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
    # A category ("not_veteran"), matched to each form's wording by `field_matcher.VETERAN_TIERS`.
    _maybe_set(fields, "veteran_status", profile.eeo.veteran or None)
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

def _build_education(resume: MasterResume) -> list[packet_models.PacketEducation]:
    """One packet row per resume education entry: the resume is the only education source."""
    rows: list[packet_models.PacketEducation] = []
    for index, edu in enumerate(resume.education):
        # Structured dates retain supplied days; older files only have printed dates.
        parsed_start, parsed_end = edu_dates.months(edu.dates)
        start = edu.start or parsed_start
        end = edu.end or parsed_end
        if not (start or end):
            start, end = parse_range(edu.dates)
        first_major = next((entry for entry in edu.major_entries if entry.name), None)
        if first_major and any(entry.degree_type for entry in edu.major_entries):
            kind = first_major.degree_type
        else:
            kind = edu.degree_type or edu.degree
        rows.append(
            packet_models.PacketEducation(
                school=edu.school,
                degree=edu.degree,
                major=edu.major,
                majors=list(edu.majors),
                major_entries=[entry.model_copy() for entry in edu.major_entries],
                minor=edu.minors[0] if edu.minors else "",
                minors=list(edu.minors),
                start=start,
                end=end,
                gpa=edu.gpa,
                entry_key=f"resume:education:{index}",
                degree_level=_degree_label(kind),
                degree_name=kind,
                source="resume",
            )
        )
    return rows

def education_rows(
    education: list[packet_models.PacketEducation],
) -> list[packet_models.PacketEducation]:
    """One form row per major, retaining that major's degree and the school's dates.

    Old packets without structured credentials keep their existing degree facts.
    """
    rows: list[packet_models.PacketEducation] = []
    for row in education:
        entries = [entry for entry in row.major_entries if entry.name]
        if not entries and len(row.majors) < 2:
            rows.append(row)
            continue
        entries = entries or [MajorEntry(name=major) for major in row.majors]
        has_types = any(entry.degree_type for entry in row.major_entries)
        for index, entry in enumerate(entries):
            update = {
                "major": entry.name,
                "majors": [entry.name],
                "major_entries": [entry.model_copy()] if row.major_entries else [],
                "entry_key": f"{row.entry_key}:{index}" if len(entries) > 1 else row.entry_key,
            }
            if has_types:
                # A sibling's credential never supplies a missing type for this major.
                kind = entry.degree_type
                update.update(
                    degree_level=_degree_label(kind), degree_name=kind,
                    degree=degree_line.compose(kind, [entry.name], []) if kind else "",
                )
            rows.append(row.model_copy(update=update))
    return rows


def current_education(
    education: list[packet_models.PacketEducation],
) -> packet_models.PacketEducation:
    """The row a single "School"/"Graduation date" question means: the latest ``end``
    month, ties and undated rows falling back to resume order."""
    dated = [
        (row, parsed) for row in education
        if (parsed := dates.parse(row.end)) and parsed[1]
    ]
    if not dated:
        return education[0]
    return max(
        dated, key=lambda item: (item[1][0], item[1][1] or 1, item[1][2] or 31)
    )[0]

def degree_name(education: list[packet_models.PacketEducation], level: str) -> str:
    """The one named degree at the profile's level ("Bachelor of Science" from "Bachelor
    of Science in Computer Science & Minor in ..."), so a choice list of "BS"/"BA" is
    answered without the model; "" when the rows disagree or name none."""
    wanted = field_matcher.degree_of(level) if level else None
    names: set[str] = set()
    for row in education:
        types = [entry.degree_type for entry in row.major_entries if entry.degree_type]
        if types and any(entry.name and not entry.degree_type for entry in row.major_entries):
            return ""
        for value in types or [row.degree_name or row.degree]:
            degree = field_matcher.degree_of(value)
            if degree and degree[1] and (wanted is None or degree[0] == wanted[0]):
                names.add(degree[1])
    if len(names) != 1:
        return ""
    words = names.pop().split()
    return " ".join(word if word in {"of", "in"} else word.capitalize() for word in words)
