"""The application packet's models and its inputs digest."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.content.data import MasterResume


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
    master_skills: list[str] = Field(default_factory=list)
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
