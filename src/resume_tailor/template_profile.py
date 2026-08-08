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

SCHEMA_VERSION = 2

SectionKey = Literal["education", "experience", "projects", "skills"]
ContactField = Literal["location", "email", "phone", "linkedin", "github"]
DateAlignment = Literal["tab", "inline", "separate_paragraph"]

#: `data.MasterResume` section kinds a generic-mode template can render. Matches
#: `data.Section`'s discriminator values, except `"projects"`/`"skills"` there are
#: `"project"`/`"skills"` — kept distinct from `SectionKey` (the fixed-mode, legacy-named
#: set) rather than merged with it, since the two sets diverge on purpose: fixed mode has
#: no `"list"` kind, and its plural `"projects"`/`"education"` names predate sections.
GenericSectionKind = Literal["experience", "project", "list", "education", "skills"]


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


class ContactSlot(_Strict):
    """One physical paragraph carrying part of a contact block that a table layout
    spreads across several cells (name in one, address in another, email/phone in a
    third and fourth). Each slot renders as its own `RichText`, so the layout survives
    instead of collapsing onto one joined line the way `ContactMapping` alone would."""

    paragraph_id: int
    fields: list[ContactField]
    separator: str = " • "


class ContactMapping(_Strict):
    """How the contact line is rebuilt from master-resume fields."""

    paragraph_id: int
    #: Order of non-empty fields on the rendered contact line.
    field_order: list[ContactField] = Field(
        default_factory=lambda: ["location", "email", "phone", "linkedin", "github"]
    )
    #: Empty (the default) is today's exact behaviour: one joined line at
    #: `paragraph_id`, using `field_order`/`separator` below. Non-empty replaces that
    #: entirely — `paragraph_id` then names slot 0's own paragraph, so
    #: `validate_profile_against_doc`'s `bad_contact` existence check still means
    #: something. Table layout only; every existing profile has `slots == []` and
    #: renders byte-identically.
    slots: list[ContactSlot] = Field(default_factory=list)
    #: Literal separator between contact parts (e.g. " • " or " | ").
    separator: str = " \u2022 "

    @model_validator(mode="after")
    def _slots_consistent(self) -> ContactMapping:
        """A non-empty `slots` must agree with `paragraph_id` and never double-map a
        field — two slots both claiming the same field would make rendering ambiguous
        about which paragraph is authoritative."""
        if not self.slots:
            return self
        if self.slots[0].paragraph_id != self.paragraph_id:
            raise ValueError("contact.paragraph_id must equal slots[0].paragraph_id")
        seen: list[ContactField] = [f for s in self.slots for f in s.fields]
        if len(seen) != len(set(seen)):
            raise ValueError(f"a contact field appears in more than one slot: {seen}")
        return self


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


class ListMapping(_Strict):
    """Plain-bullet section prototype mapping: a heading plus one bullet loop, no entry
    header at all — certifications, awards, languages. The simplest of the five kinds."""

    heading_paragraph_id: int
    heading_text: str
    bullet_paragraph_id: int


class HeadingPrototype(_Strict):
    """Which paragraph's formatting (font, size, spacing, style) every generic-mode
    section heading clones. Its text is fully replaced with `{{ section.title }}`, so
    only the paragraph identity — not its original wording — matters. Generic-mode only."""

    paragraph_id: int


class DetectedSection(_Strict):
    """One resume-shaped section as detected (or hand-mapped) in document order.
    Generic-mode only — drives the outer `{%p for section in sections %}` loop's shape,
    while the per-kind prototype mappings above (`experience`, `projects`, `education`,
    `skills`, `list_section`) still supply the tagging for whichever kinds are enabled."""

    id: str
    title: str
    kind: GenericSectionKind
    heading_paragraph_id: int


class SpacingProfile(_Strict):
    """Separator paragraphs to reproduce in a generic-mode build. Each field is the
    contiguous *run* of chrome paragraph ids observed at that slot in the upload —
    formatting is inherited from real XML, never reconstructed, same rule every other
    prototype in this module follows.

    A run rather than a single id because real exports put more than one chrome
    paragraph at a slot: a horizontal rule followed by a blank under every heading, or
    two blank paragraphs between entries. Recording only the first would drop the rule
    entirely and mis-measure the gap.

    All-empty (the default) is today's behaviour exactly: no spacers inserted, so every
    existing profile.json loads and builds byte-identically. Generic-mode only; unused
    under `section_mode="fixed"`."""

    #: Run before each section heading (suppressed before the first — the upload's own
    #: pre-first-heading chrome sits above the tagged block and survives untouched).
    before_heading: list[int] = Field(default_factory=list)
    #: Run right after each section heading — typically rule + blank.
    after_heading: list[int] = Field(default_factory=list)
    #: Run between two entries within one section (suppressed before the first entry).
    #: Applies to experience/project/education bodies, not skills/list.
    between_entries: list[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_single_ids(cls, data):
        """Accept the pre-run shape (`int | None` per field) written by an earlier build
        of this feature, so a `template_profile.json` already on disk still loads."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for key in ("before_heading", "after_heading", "between_entries"):
            value = out.get(key)
            if value is None:
                out[key] = []
            elif isinstance(value, int):
                out[key] = [value]
        return out


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
    #: Whether the template has a `list_section` prototype. Defaults off — unlike the
    #: other four, no template has ever had this mapping before generic mode existed, so
    #: `False` (not `True`) is what keeps every pre-existing profile's `model_dump`
    #: unchanged on load.
    list_section: bool = False


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
    #: Plain-bullet section prototype (certifications, awards, …). Generic-mode only —
    #: `section_mode="fixed"` never offers this kind, matching `EnabledSections.list_section`
    #: defaulting off.
    list_section: ListMapping | None = None
    normalization: NormalizationFlags = Field(default_factory=NormalizationFlags)
    #: Non-blocking notes captured at confirm time (shown in the Template tab).
    warnings: list[str] = Field(default_factory=list)

    #: `"fixed"` (default) is today's contract: exactly one physical heading per kind,
    #: baked into the template at build time — adding a second same-kind resume section
    #: just flows more entries under that one heading, and renaming/reordering a section
    #: has no effect until the template is rebuilt. `"generic"` tags one shared
    #: `{%p for section in sections %}` block instead, so any number of sections, in any
    #: order, with any title, render correctly with no rebuild — see `template_build.
    #: build_generic`. `fit.estimate_lines` reads this to know whether same-kind sections
    #: share one heading line or each get their own.
    section_mode: Literal["fixed", "generic"] = "fixed"
    #: Every detected/confirmed section, in document order. Generic-mode only; empty
    #: under `"fixed"`.
    sections: list[DetectedSection] = Field(default_factory=list)
    #: Formatting donor for every generic-mode section heading. `None` under `"fixed"`.
    heading_prototype: HeadingPrototype | None = None
    #: Blank-line spacers to reproduce. Generic-mode only; all-`None` under `"fixed"`.
    spacing: SpacingProfile = Field(default_factory=SpacingProfile)
    #: `"paragraph"` (default) is every template before this field existed: content
    #: lives in body paragraphs. `"table"` is a resume whose content lives inside one
    #: invisible layout table (used purely to right-align dates/locations without tab
    #: stops) — see `template_build.build_generic_table`. Always implies
    #: `section_mode="generic"`: a table-layout resume needs at least two
    #: experience-shaped headings' worth of generality (this document's own
    #: WORK EXPERIENCE + LEADERSHIP) far more often than a paragraph one does, and
    #: implementing table support only for generic mode halves the build surface.
    layout: Literal["paragraph", "table"] = "paragraph"
    #: Count of `docx_text.iter_document_paragraphs(doc)` at analysis time. Optional —
    #: `None` (every profile before this field existed) skips the check. When set,
    #: `template_build.build_from_profile` verifies the baseline still enumerates to
    #: the same count before resolving any paragraph id, turning a silent off-by-one
    #: span corruption (the flattened id space and the document having drifted apart)
    #: into a named failure instead of a build that quietly tags the wrong paragraphs.
    paragraph_count: int | None = None

    @model_validator(mode="after")
    def _optional_consistency(self) -> TemplateProfile:
        """Enabled flags must agree with mappings; experience is always required."""
        if not self.enabled.experience:
            raise ValueError("experience section is required")
        pairs = (
            (self.enabled.education, self.education, "education"),
            (self.enabled.projects, self.projects, "projects"),
            (self.enabled.skills, self.skills, "skills"),
            (self.enabled.list_section, self.list_section, "list_section"),
        )
        for enabled, mapping, name in pairs:
            if enabled and mapping is None:
                raise ValueError(f"{name} is enabled but has no mapping")
            if not enabled and mapping is not None:
                raise ValueError(f"{name} is disabled but still has a mapping")
        if self.section_mode == "generic" and self.heading_prototype is None:
            raise ValueError("generic section_mode requires heading_prototype")
        if self.section_mode == "fixed" and self.sections:
            raise ValueError("fixed section_mode must not carry a sections list")
        if self.section_mode == "fixed" and self.spacing != SpacingProfile():
            raise ValueError("fixed section_mode must not carry spacing donors")
        if self.layout == "table" and self.section_mode != "generic":
            raise ValueError("table layout requires section_mode='generic'")
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
            "list_section": False,
        },
        "section_mode": "fixed",
        "layout": "paragraph",
    }


def active_layout(profile: TemplateProfile | None = None) -> dict:
    """Resolve contact layout and enabled sections for the current active template."""
    if profile is None:
        profile = load_profile()
    if profile is None:
        return legacy_defaults()
    layout = {
        "contact_separator": profile.contact.separator,
        "contact_field_order": list(profile.contact.field_order),
        "enabled": profile.enabled.model_dump(),
        "warnings": list(profile.warnings),
        "schema_version": profile.schema_version,
        "section_mode": profile.section_mode,
        "layout": profile.layout,
    }
    if profile.contact.slots:
        layout["contact_slots"] = [s.model_dump() for s in profile.contact.slots]
    if profile.section_mode == "generic":
        layout["sections"] = [s.model_dump() for s in profile.sections]
        layout["spacing"] = profile.spacing.model_dump()
    return layout
