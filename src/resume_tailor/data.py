"""Schema, loader, and validator for the master resume store.

`data/master_resume.json` is the single source of truth for every fact that can appear in
a tailored resume. Nothing downstream may introduce content that is not traceable to this
file — `rewrite.py` enforces that mechanically.

Validation is strict and happens at load time so that a malformed store fails with a
field-level message up front, rather than as a `KeyError` halfway through a paid API call.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import config

#: The four legacy top-level keys a pre-`sections` master resume file used. Order matters:
#: it is the order `_migrate_legacy_sections` rebuilds them in, which is also today's
#: `all_bullets()` order — preserving it keeps `rewrite._score_cache_path` stable across
#: the migration, so an upgraded file does not silently invalidate every cached score.
_LEGACY_SECTION_KEYS: tuple[tuple[str, str], ...] = (
    ("education", "education"),
    ("experience", "experience"),
    ("projects", "project"),
    ("skills", "skills"),
)


class _Strict(BaseModel):
    """Base that rejects unknown keys.

    A typo'd field name in hand-maintained JSON should be an error, not a silently
    ignored key that makes a bullet mysteriously invisible to the matcher.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Bullet(_Strict):
    """One achievement line, the atomic unit of selection and rewriting."""

    #: Stable identifier, unique across the whole file. Used to map rewritten text back
    #: onto its source, so it must never be reused or renumbered casually.
    id: str
    text: str = Field(min_length=1)

    #: Skills/tools this bullet demonstrates. Doubles as the fabrication guard's
    #: whitelist, so it must name every technology mentioned in `text`.
    #: Stored as a JSON array but set-valued: duplicates (incl. aliases) collapse on load.
    tags: list[str] = Field(min_length=1)

    #: Whether the bullet carries a concrete number. Nudges selection ordering.
    metric: bool = False

    @field_validator("tags")
    @classmethod
    def _normalise_tags(cls, tags: list[str]) -> list[str]:
        """Collapse to a sorted set of canonical tags (no case/alias duplicates)."""
        return sorted({config.canonical_tag(t) for t in tags if t.strip()})


class Contact(_Strict):
    name: str
    email: str
    phone: str = ""
    location: str = ""
    #: Profile URLs rendered as labelled hyperlinks on the contact line.
    linkedin: str = ""
    github: str = ""
    #: Legacy free-form list; unused by render. Kept so older JSON still loads.
    links: list[str] = Field(default_factory=list)


class SummaryVariant(_Strict):
    """An alternative framing of the same career, e.g. IC vs lead."""

    id: str
    text: str
    tags: list[str] = Field(default_factory=list)


class Experience(_Strict):
    #: Stable identifier, unique across `experience`. Addresses the entry for per-run
    #: exclusion, so it must never be reused or renumbered casually — same contract as
    #: `Bullet.id` and `Project.id`. Auto-filled from a company slug when absent so files
    #: written before this field existed still load; see `MasterResume._fill_experience_ids`.
    id: str = ""
    company: str
    title: str
    location: str = ""
    start: str
    end: str
    bullets: list[Bullet] = Field(default_factory=list)


class Education(_Strict):
    school: str
    degree: str
    dates: str
    #: Shown after the school on the header line (`School | Location`).
    location: str = ""
    #: Courses rendered as one "Relevant Coursework: …" bullet when non-empty.
    coursework: list[str] = Field(default_factory=list)
    gpa: str = ""
    #: When true and `gpa` is set, append ` | GPA: …` to the degree line.
    show_gpa: bool = False
    #: Extra education bullets (not coursework). Coursework has its own field.
    details: list[str] = Field(default_factory=list)


class Project(_Strict):
    id: str
    name: str
    #: Technologies as shown in the resume's project header line.
    tech: list[str] = Field(default_factory=list)
    date: str = ""
    #: Link label as it appears in the resume, e.g. "Github". Empty means no link shown.
    link: str = ""
    #: Target of that label. Each project has its own — rendering them all with a single
    #: shared URL was a live bug in the first template draft.
    url: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class SkillGroup(_Strict):
    """A labelled skills line, e.g. "AI/ML" or "Tools & Languages"."""

    label: str
    items: list[str]


class ListItem(_Strict):
    """One line in a plain bulleted section with no entry header — a certification, an
    award, a language. Never rewritten by the LLM and never resized by the fit loop; it
    renders in full, the same way a skills item or a coursework title does."""

    id: str
    text: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _normalise_tags(cls, tags: list[str]) -> list[str]:
        return sorted({config.canonical_tag(t) for t in tags if t.strip()})


class _SectionBase(_Strict):
    """Shared shape of one entry in `MasterResume.sections`."""

    #: Stable identifier, unique across `sections`. Addresses the section for per-run
    #: exclusion and for the editor's reorder/rename controls.
    id: str
    #: User-facing heading text, e.g. "LEADERSHIP EXPERIENCE". Rendered verbatim.
    title: str


class ExperienceSection(_SectionBase):
    """A section of job/role-shaped entries: org, title, location, dates, bullets."""

    kind: Literal["experience"] = "experience"
    entries: list[Experience] = Field(default_factory=list)


class ProjectSection(_SectionBase):
    """A section of project-shaped entries: name, tech, link, date, bullets."""

    kind: Literal["project"] = "project"
    entries: list[Project] = Field(default_factory=list)


class ListSection(_SectionBase):
    """A section of plain bullet lines with no entry header."""

    kind: Literal["list"] = "list"
    entries: list[ListItem] = Field(default_factory=list)


class EducationSection(_SectionBase):
    kind: Literal["education"] = "education"
    entries: list[Education] = Field(default_factory=list)


class SkillsSection(_SectionBase):
    kind: Literal["skills"] = "skills"
    entries: list[SkillGroup] = Field(default_factory=list)


#: Discriminated union of every section kind. `kind` is the discriminator, so a malformed
#: or misspelled kind fails validation with a clear message rather than silently matching
#: the wrong branch.
Section = Annotated[
    Union[
        ExperienceSection,
        ProjectSection,
        ListSection,
        EducationSection,
        SkillsSection,
    ],
    Field(discriminator="kind"),
]

#: Section kinds whose entries carry `bullets` and participate in relevance
#: scoring/selection/rewriting — as opposed to `education`/`skills`/`list`, which are
#: fixed overhead the fit loop never trims.
_ENTRY_SECTION_KINDS = frozenset({"experience", "project"})


class MasterResume(_Strict):
    #: Free-text note for whoever maintains this file by hand. Ignored by the pipeline.
    comment: str | None = Field(default=None, alias="_comment")

    contact: Contact
    summary_variants: list[SummaryVariant] = Field(default_factory=list)
    #: Ordered resume sections — the render order, the editor order, and (for
    #: `experience`/`project` kinds) the selection pools. See `data.py` module docs and
    #: CLAUDE.md's "Arbitrary, renameable, reorderable resume sections" design notes.
    sections: list[Section] = Field(default_factory=list)
    #: Shared tag options for the editor and a hint for TAG_ALIASES coverage.
    #: Canonicalised at load; removing an option in the UI also strips it from bullets.
    tag_vocabulary: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_sections(cls, data: Any) -> Any:
        """Fold a pre-`sections` file's four top-level lists into `sections`.

        Only fires when `sections` is absent and at least one legacy key is present —
        a brand-new resume with neither is left alone (`sections` defaults to `[]`). The
        four sections are always built in the fixed `_LEGACY_SECTION_KEYS` order with
        stable ids equal to the legacy key name, which is what keeps `all_bullets()`'s
        order — and therefore `rewrite._score_cache_path`'s cache key — identical to
        pre-migration output for every existing file.
        """
        if not isinstance(data, dict):
            return data
        if "sections" in data:
            return data
        if not any(key in data for key, _kind in _LEGACY_SECTION_KEYS):
            return data
        sections = []
        for key, kind in _LEGACY_SECTION_KEYS:
            entries = data.pop(key, None) or []
            sections.append(
                {
                    "id": key,
                    "kind": kind,
                    "title": config.DEFAULT_SECTION_TITLES[key],
                    "entries": entries,
                }
            )
        data["sections"] = sections
        return data

    @field_validator("tag_vocabulary")
    @classmethod
    def _normalise_vocabulary(cls, tags: list[str]) -> list[str]:
        """Collapse vocabulary to a sorted set of canonical tags."""
        return sorted({config.canonical_tag(t) for t in tags if t.strip()})

    @model_validator(mode="after")
    def _fill_entry_ids(self) -> "MasterResume":
        """Auto-fill blank `Experience.id`s from a company slug, deterministically.

        Runs before `_ids_unique` so a file predating this field (every id blank) still
        validates instead of failing on an all-empty duplicate check. A collision (two
        entries at the same company, or two blanks slugging to the same base) gets a
        `-2`, `-3`, … suffix, walked in section-then-entry document order across every
        experience-kind section — not just one.
        """
        taken = {e.id for e in self.experience if e.id.strip()}
        for section in self.sections:
            if section.kind != "experience":
                continue
            for entry in section.entries:
                if entry.id.strip():
                    continue
                base = config.slugify(entry.company) or "role"
                candidate = base
                suffix = 2
                while candidate in taken:
                    candidate = f"{base}-{suffix}"
                    suffix += 1
                entry.id = candidate
                taken.add(candidate)
        return self

    @model_validator(mode="after")
    def _ids_unique(self) -> "MasterResume":
        """Bullet/entry/section ids address rewrites and exclusions; a duplicate would
        silently overwrite or misapply one."""
        ids = [b.id for b in self.all_bullets()]
        dupes = [i for i, n in Counter(ids).items() if n > 1]
        if dupes:
            raise ValueError(f"duplicate bullet id(s): {', '.join(sorted(dupes))}")

        entry_ids = [
            entry.id
            for section in self.sections
            if section.kind in _ENTRY_SECTION_KINDS
            for entry in section.entries
        ]
        entry_dupes = [i for i, n in Counter(entry_ids).items() if n > 1]
        if entry_dupes:
            raise ValueError(f"duplicate entry id(s): {', '.join(sorted(entry_dupes))}")

        section_ids = [s.id for s in self.sections]
        section_dupes = [i for i, n in Counter(section_ids).items() if n > 1]
        if section_dupes:
            raise ValueError(f"duplicate section id(s): {', '.join(sorted(section_dupes))}")
        return self

    # ------------------------------------------------------------------------------
    # Flattened views — read-only. Every pre-`sections` call site reads the resume
    # through these, unchanged. Never `@computed_field`: that would put these keys
    # back into `model_dump`, and a saved file would carry both `sections` and the
    # legacy keys as two sources of truth that can silently diverge.
    # ------------------------------------------------------------------------------

    @property
    def education(self) -> list[Education]:
        return [e for s in self.sections if isinstance(s, EducationSection) for e in s.entries]

    @property
    def experience(self) -> list[Experience]:
        return [e for s in self.sections if isinstance(s, ExperienceSection) for e in s.entries]

    @property
    def projects(self) -> list[Project]:
        return [e for s in self.sections if isinstance(s, ProjectSection) for e in s.entries]

    @property
    def skills(self) -> list[SkillGroup]:
        return [e for s in self.sections if isinstance(s, SkillsSection) for e in s.entries]

    @property
    def entry_sections(self) -> list[ExperienceSection | ProjectSection]:
        """Sections whose entries carry bullets: `experience` and `project` kinds."""
        return [s for s in self.sections if s.kind in _ENTRY_SECTION_KINDS]

    def all_bullets(self) -> list[Bullet]:
        """Every bullet in the file, across every experience/project section, in
        section-then-entry document order."""
        out: list[Bullet] = []
        for section in self.entry_sections:
            for entry in section.entries:
                out.extend(entry.bullets)
        return out

    def bullet_by_id(self, bullet_id: str) -> Bullet | None:
        return next((b for b in self.all_bullets() if b.id == bullet_id), None)


def load(path: Path | None = None) -> MasterResume:
    """Load and validate the master resume.

    Raises with an actionable message if the file is missing or malformed.
    """
    path = path or config.MASTER_RESUME_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Master resume not found at {path}. See CLAUDE.md for the expected schema."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    return MasterResume.model_validate(raw)


def _alias_rewrites(raw: dict) -> list[tuple[str, str]]:
    """Every raw bullet tag `TAG_ALIASES` silently rewrote, as (original, canonical) pairs.

    `Bullet._normalise_tags` runs `config.canonical_tag` at load time with no way to see
    the transform happen — a tag typed as `"performance measurement"` becomes
    `"performance"` and the person who typed it never finds out. This exists so
    `--validate` makes that visible instead. Deliberately checks membership in
    `TAG_ALIASES` specifically, not `canonical_tag(tag) != tag`, so a pure case/whitespace
    fold ("Python" -> "python") — expected and not surprising — doesn't drown out an
    actual alias substitution in the output.

    Reads the raw dict, not the model, so it must handle both shapes: a `sections`-native
    file, and a legacy file with top-level `experience`/`projects` lists.
    """
    seen: dict[str, str] = {}

    def scan(entries: list[dict]) -> None:
        for entry in entries:
            for bullet in entry.get("bullets", []):
                for tag in bullet.get("tags", []):
                    cleaned = tag.strip().lower()
                    if cleaned in config.TAG_ALIASES and tag not in seen:
                        seen[tag] = config.TAG_ALIASES[cleaned]

    if "sections" in raw:
        for section in raw.get("sections", []):
            if section.get("kind") in ("experience", "project"):
                scan(section.get("entries", []))
    else:
        for key in ("experience", "projects"):
            scan(raw.get(key, []))
    return sorted(seen.items())


def _validate_cli() -> int:
    """Back the `--validate` entrypoint. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Validate the master resume store.")
    parser.add_argument("--validate", action="store_true", help="Validate and report.")
    parser.add_argument("--path", type=Path, default=None, help="Override the file path.")
    args = parser.parse_args()

    if not args.validate:
        parser.print_help()
        return 0

    path = args.path or config.MASTER_RESUME_PATH
    try:
        resume = load(args.path)
    except Exception as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    bullets = resume.all_bullets()
    tags = sorted({t for b in bullets for t in b.tags})
    print(f"OK  {resume.contact.name}")
    print(f"    {len(resume.sections)} sections: " + ", ".join(
        f"{s.title!r} ({s.kind}, {len(s.entries)})" for s in resume.sections
    ))
    print(f"    {len(resume.experience)} experience entries, {len(resume.projects)} projects")
    print(f"    {len(bullets)} bullets, {sum(b.metric for b in bullets)} with metrics")
    print(f"    {len(tags)} distinct tags")

    raw = json.loads(path.read_text(encoding="utf-8"))
    rewrites = _alias_rewrites(raw)
    if rewrites:
        print(f"    {len(rewrites)} tag(s) rewritten by TAG_ALIASES on load:")
        for original, canonical in rewrites:
            print(f"      {original!r} -> {canonical!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_validate_cli())
