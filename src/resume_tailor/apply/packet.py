"""Application packet assembly from a completed tailoring run.

Pure function of disk artifacts, the master resume, and the applicant profile — no LLM.
``build_packet`` reads ``run.json``, optional expansion/skills/cover/bullets JSON, and
paths to rendered documents; ``write_packet`` persists ``packet.json`` beside them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply import ats_hints, profile as profile_mod
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
    cover_letter: str = ""
    artifacts: dict[str, str] = Field(default_factory=dict)
    field_hints: dict[str, str] = Field(default_factory=dict)
    gaps: list[dict] = Field(default_factory=list)


_WORK_AUTH_LABELS: dict[str, str] = {
    "citizen": "U.S. Citizen",
    "permanent_resident": "Permanent Resident",
    "visa_holder": "Authorized to work in the U.S. with visa sponsorship",
    "other": "Other",
}


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
    """Omit EEO answers left at ``decline`` or blank."""
    if not raw or raw.strip().lower() == "decline":
        return None
    return raw.strip()


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
    _maybe_set(fields, "last_name", last_name or None)
    _maybe_set(fields, "full_name", full_name or None)
    _maybe_set(fields, "preferred_name", profile.preferred_name or None)
    _maybe_set(fields, "email", _pick(profile.email, contact.email) or None)
    _maybe_set(fields, "phone", _pick(profile.phone, contact.phone) or None)
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
    _maybe_set(fields, "requires_sponsorship", _yes_no(profile.requires_sponsorship_now))
    _maybe_set(
        fields,
        "requires_sponsorship_future",
        _yes_no(profile.requires_sponsorship_future),
    )
    _maybe_set(fields, "f1_opt_eligible", _yes_no(profile.f1_opt_eligible))
    _maybe_set(fields, "earliest_start", profile.earliest_start or None)
    _maybe_set(fields, "graduation_month", profile.graduation_month or None)
    _maybe_set(fields, "degree_level", profile.degree_level or None)
    _maybe_set(fields, "major", profile.major or None)
    _maybe_set(fields, "school", profile.school or None)
    _maybe_set(fields, "gpa", profile.gpa or None)
    _maybe_set(fields, "salary_expectation", profile.salary_expectation or None)
    _maybe_set(fields, "willing_to_relocate", _yes_no(profile.willing_to_relocate))
    _maybe_set(fields, "how_heard", profile.how_heard or None)
    _maybe_set(fields, "gender", _eeo_value(profile.eeo.gender))
    _maybe_set(fields, "race", _eeo_value(profile.eeo.race))
    _maybe_set(fields, "veteran_status", _eeo_value(profile.eeo.veteran))
    _maybe_set(fields, "disability_status", _eeo_value(profile.eeo.disability))
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
            profile.graduation_month,
        )
    ):
        return None
    return PacketEducation(
        school=profile.school,
        degree=profile.degree_level,
        major=profile.major,
        end=profile.graduation_month,
        gpa=profile.gpa,
    )


def _education_from_resume(resume: MasterResume) -> list[PacketEducation]:
    """Convert resume education entries into packet rows."""
    rows: list[PacketEducation] = []
    for edu in resume.education:
        start, end = parse_range(edu.dates)
        rows.append(
            PacketEducation(
                school=edu.school,
                degree=edu.degree,
                start=start,
                end=end,
                gpa=edu.gpa if edu.gpa else "",
            )
        )
    return rows


def _build_education(profile: ApplicantProfile, resume: MasterResume) -> list[PacketEducation]:
    """Merge profile-first education with resume entries."""
    rows: list[PacketEducation] = []
    profile_row = _education_from_profile(profile)
    if profile_row is not None:
        rows.append(profile_row)
    seen_schools = {row.school.lower() for row in rows if row.school}
    for row in _education_from_resume(resume):
        key = row.school.lower()
        if key and key in seen_schools:
            continue
        rows.append(row)
        if key:
            seen_schools.add(key)
    return rows


def _experience_from_expansion(entries: list[ExpandedEntry]) -> list[PacketExperience]:
    """Map expansion artifact entries to packet experience rows."""
    rows: list[PacketExperience] = []
    for entry in entries:
        description = "\n".join(entry.bullets)
        rows.append(
            PacketExperience(
                employer=entry.company,
                title=entry.title,
                location=entry.location,
                start=entry.start,
                end=entry.end,
                current=entry.end.lower() in {"present", "current"},
                description=description,
                char_count=entry.char_count or len(description),
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


def build_packet(job_id: str, *, out_dir: Path | None = None) -> Packet:
    """Assemble a packet from job artifacts, profile, and master resume."""
    job_dir = out_dir if out_dir is not None else config.OUTPUT_DIR / "jobs" / job_id
    run_path = job_dir / "run.json"
    if not run_path.is_file():
        raise FileNotFoundError(f"run.json not found for job {job_id!r} at {run_path}")

    run = json.loads(run_path.read_text(encoding="utf-8"))
    metadata = run.get("metadata") or {}
    report = run.get("report") or {}

    applicant_profile, _seeded = profile_mod.load_profile()
    resume = load()

    expansion = _load_expansion(job_dir / "expansion.json")
    experience = (
        _experience_from_expansion(expansion.entries)
        if expansion is not None and expansion.entries
        else _experience_from_resume(resume)
    )

    ats = str(metadata.get("ats") or "unknown")
    return Packet(
        job_id=job_id,
        built_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        posting_url=str(metadata.get("posting_url") or ""),
        company=str(metadata.get("company") or ""),
        role=str(metadata.get("role") or report.get("title") or ""),
        ats=ats,
        fields=build_fields(applicant_profile, resume),
        education=_build_education(applicant_profile, resume),
        experience=experience,
        skills=_load_skills(job_dir / "skills.json"),
        cover_letter=_load_cover_letter(job_dir / "cover.json"),
        artifacts=_artifact_paths(job_dir),
        field_hints=ats_hints.hints_for(ats),
        gaps=list(report.get("gaps") or []),
    )


def write_packet(job_id: str) -> Packet:
    """Build and persist ``packet.json`` for ``job_id``."""
    packet = build_packet(job_id)
    job_dir = config.OUTPUT_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "packet.json"
    path.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return packet
