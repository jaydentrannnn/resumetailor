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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import config


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


class MasterResume(_Strict):
    #: Free-text note for whoever maintains this file by hand. Ignored by the pipeline.
    comment: str | None = Field(default=None, alias="_comment")

    contact: Contact
    education: list[Education] = Field(default_factory=list)
    summary_variants: list[SummaryVariant] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    #: Shared tag options for the editor and a hint for TAG_ALIASES coverage.
    #: Canonicalised at load; removing an option in the UI also strips it from bullets.
    tag_vocabulary: list[str] = Field(default_factory=list)

    @field_validator("tag_vocabulary")
    @classmethod
    def _normalise_vocabulary(cls, tags: list[str]) -> list[str]:
        """Collapse vocabulary to a sorted set of canonical tags."""
        return sorted({config.canonical_tag(t) for t in tags if t.strip()})

    @model_validator(mode="after")
    def _ids_unique(self) -> "MasterResume":
        """Bullet ids address rewrites; a duplicate would silently overwrite one."""
        ids = [b.id for b in self.all_bullets()]
        dupes = [i for i, n in Counter(ids).items() if n > 1]
        if dupes:
            raise ValueError(f"duplicate bullet id(s): {', '.join(sorted(dupes))}")
        return self

    def all_bullets(self) -> list[Bullet]:
        """Every bullet in the file, across experience and projects."""
        out: list[Bullet] = []
        for job in self.experience:
            out.extend(job.bullets)
        for proj in self.projects:
            out.extend(proj.bullets)
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
    """
    seen: dict[str, str] = {}
    for section in ("experience", "projects"):
        for entry in raw.get(section, []):
            for bullet in entry.get("bullets", []):
                for tag in bullet.get("tags", []):
                    cleaned = tag.strip().lower()
                    if cleaned in config.TAG_ALIASES and tag not in seen:
                        seen[tag] = config.TAG_ALIASES[cleaned]
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
