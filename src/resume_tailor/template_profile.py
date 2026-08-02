"""Versioned mapping for the active single-column resume template.

A profile records how an uploaded baseline DOCX maps onto the render context keys
(`name`, `contact`, `experience`, …). It is produced by the analyze → confirm flow and
consumed by `template_build` — never by the LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import config

SCHEMA_VERSION = 1

SectionKey = Literal["education", "experience", "projects", "skills"]
ContactField = Literal["location", "email", "phone", "linkedin", "github"]
DateAlignment = Literal["tab", "inline", "separate_paragraph"]


class _Strict(BaseModel):
    """Reject unknown keys so a typo'd mapping field fails loudly."""

    model_config = ConfigDict(extra="forbid")


class CharSpan(_Strict):
    """Inclusive-start exclusive-end character range within one paragraph's visible text."""

    paragraph_id: int
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> CharSpan:
        """Reject inverted or empty spans."""
        if self.end < self.start:
            raise ValueError(
                f"span end ({self.end}) must be >= start ({self.start}) "
                f"on paragraph {self.paragraph_id}"
            )
        return self


class OptionalSpan(_Strict):
    """A field that may be absent from the prototype (omitted at render time)."""

    present: bool = True
    span: CharSpan | None = None

    @model_validator(mode="after")
    def _span_when_present(self) -> OptionalSpan:
        """Require a span when the field is present; forbid one when absent."""
        if self.present and self.span is None:
            raise ValueError("present field requires a span")
        if not self.present and self.span is not None:
            raise ValueError("absent field must not carry a span")
        return self


class ContactMapping(_Strict):
    """How the contact line is rebuilt from master-resume fields."""

    paragraph_id: int
    #: Order of non-empty fields on the rendered contact line.
    field_order: list[ContactField] = Field(
        default_factory=lambda: ["location", "email", "phone", "linkedin", "github"]
    )
    #: Literal separator between contact parts (e.g. " • " or " | ").
    separator: str = " \u2022 "


class HeaderFieldMapping(_Strict):
    """Mapped fields for an experience / education / project header line."""

    #: Paragraph holding the primary header (company/school/name + optional location/dates).
    header_paragraph_id: int
    fields: dict[str, OptionalSpan] = Field(default_factory=dict)
    date_alignment: DateAlignment = "tab"
    #: When dates live on their own paragraph (rare).
    date_paragraph_id: int | None = None


class ExperienceMapping(_Strict):
    """Experience section prototype mapping."""

    heading_paragraph_id: int
    heading_text: str
    prototype_entry_start: int
    header: HeaderFieldMapping
    #: Job title may share the header or sit on the next non-bullet paragraph.
    title: OptionalSpan
    title_paragraph_id: int | None = None
    bullet_paragraph_id: int


class EducationMapping(_Strict):
    """Education section prototype mapping."""

    heading_paragraph_id: int
    heading_text: str
    prototype_entry_start: int
    header: HeaderFieldMapping
    degree_paragraph_id: int
    detail_paragraph_id: int | None = None


class ProjectsMapping(_Strict):
    """Projects section prototype mapping."""

    heading_paragraph_id: int
    heading_text: str
    prototype_entry_start: int
    header: HeaderFieldMapping
    #: Character span of the baked-in link text (replaced with RichText).
    link: OptionalSpan = Field(default_factory=lambda: OptionalSpan(present=False))
    bullet_paragraph_id: int


class SkillsMapping(_Strict):
    """Skills section prototype mapping."""

    heading_paragraph_id: int
    heading_text: str
    prototype_paragraph_id: int
    label_span: CharSpan
    body_span: CharSpan
    #: Literal text between label and body in the prototype (often ": ").
    separator: str = ": "


class NormalizationFlags(_Strict):
    """Post-tag formatting passes inferred from the prototype (or forced for legacy)."""

    force_single_spacing: bool = True
    normalize_bullet_font: bool = True
    bullet_font: str = "Noto Sans Symbols"


class EnabledSections(_Strict):
    """Which canonical sections the tagged template will render."""

    education: bool = True
    experience: bool = True
    projects: bool = True
    skills: bool = True


class TemplateProfile(_Strict):
    """Confirmed mapping for the active baseline DOCX."""

    schema_version: int = SCHEMA_VERSION
    #: SHA-256 of the exact baseline bytes this mapping was confirmed against.
    source_sha256: str
    name_paragraph_id: int = 0
    contact: ContactMapping
    enabled: EnabledSections = Field(default_factory=EnabledSections)
    experience: ExperienceMapping
    education: EducationMapping | None = None
    projects: ProjectsMapping | None = None
    skills: SkillsMapping | None = None
    normalization: NormalizationFlags = Field(default_factory=NormalizationFlags)
    #: Non-blocking notes captured at confirm time (shown in the Template tab).
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _optional_consistency(self) -> TemplateProfile:
        """Enabled flags must agree with mappings; experience is always required."""
        if not self.enabled.experience:
            raise ValueError("experience section is required")
        pairs = (
            (self.enabled.education, self.education, "education"),
            (self.enabled.projects, self.projects, "projects"),
            (self.enabled.skills, self.skills, "skills"),
        )
        for enabled, mapping, name in pairs:
            if enabled and mapping is None:
                raise ValueError(f"{name} is enabled but has no mapping")
            if not enabled and mapping is not None:
                raise ValueError(f"{name} is disabled but still has a mapping")
        return self


def profile_path() -> Path:
    """Path of the active template profile JSON beside the baseline."""
    return config.TEMPLATE_PROFILE_PATH


def load_profile(path: Path | None = None) -> TemplateProfile | None:
    """Load the active profile, or None when no profile has been installed yet."""
    target = path or profile_path()
    if not target.exists():
        return None
    return TemplateProfile.model_validate_json(target.read_text(encoding="utf-8"))


def save_profile(profile: TemplateProfile, path: Path | None = None) -> Path:
    """Write the profile JSON (pretty-printed) and return the path."""
    target = path or profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def legacy_defaults() -> dict:
    """Contact/layout defaults matching the original Google Docs export.

    Used when rendering/fitting against a tagged template that has no profile file
    (CLI `--template` override, or a baseline built before profiles existed).
    """
    return {
        "contact_separator": " \u2022 ",
        "contact_field_order": ["location", "email", "phone", "linkedin", "github"],
        "enabled": {
            "education": True,
            "experience": True,
            "projects": True,
            "skills": True,
        },
    }


def active_layout(profile: TemplateProfile | None = None) -> dict:
    """Resolve contact layout and enabled sections for the current active template."""
    if profile is None:
        profile = load_profile()
    if profile is None:
        return legacy_defaults()
    return {
        "contact_separator": profile.contact.separator,
        "contact_field_order": list(profile.contact.field_order),
        "enabled": profile.enabled.model_dump(),
        "warnings": list(profile.warnings),
        "schema_version": profile.schema_version,
    }
