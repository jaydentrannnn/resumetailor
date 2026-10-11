"""Per-template style choices the document itself cannot hold: separators the renderer
writes, the bullet marker the build applies, and how links look.

Quick adjustments sets these; they live on `TemplateProfile.style`, reach `render.py`
through `active_layout()["style"]`, and ride the layout skeleton's meta through a Word
edit or adjustment (the read-back rebuilds the rest of the profile from scratch). Every
default is what the renderer printed before the setting existed, so a profile without
one renders exactly as it always did. No LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import config

#: Separators offered between items and parts of a line.
SEPARATOR_CHOICES = (" | ", " • ", " · ", " – ", " — ", ", ", " / ", "; ")
#: Separators offered inside a date range (all of them `date_style` reads back).
DATE_SEPARATOR_CHOICES = (" - ", " – ", " — ", "–", " to ")
#: Bullet markers offered for lists. A dropdown, never free text: a glyph the marker
#: font lacks prints as an empty box.
BULLET_GLYPHS = ("●", "•", "◦", "▪", "■", "–", "›", "➢", "✓")
#: "keep" leaves the template's own marker; the two "none" choices drop the marker and
#: keep the text where it was (indented) or move it to the margin (flush).
BULLET_MODES = ("keep", "none_indent", "none_flush")
#: Characters a separator found in a template may contain besides spaces (a detected
#: name-to-tech gap seeds the link separator, and may be any of these).
_SEPARATOR_CHARS = set("|•·–—-,/;:●▪∙~")


def _check_separator(value: str) -> str:
    if not value or len(value) > 6 or not set(value) - {" "} <= _SEPARATOR_CHARS:
        raise ValueError(f"not a separator: {value!r}")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Separators(_Strict):
    tech_items: str = ", "
    #: Before a project's link; printed only when the project has one.
    project_link: str = " | "
    skills_items: str = ", "
    coursework: str = ", "
    #: Inside a date range; None keeps the separator read off the original resume.
    dates: str | None = None

    @field_validator("tech_items", "project_link", "skills_items", "coursework")
    @classmethod
    def _separator(cls, value: str) -> str:
        return _check_separator(value)

    @field_validator("dates")
    @classmethod
    def _date_separator(cls, value: str | None) -> str | None:
        if value is not None and value not in DATE_SEPARATOR_CHOICES:
            raise ValueError(f"not a date separator: {value!r}")
        return value


BulletChoice = str


def _check_bullet(value: str) -> str:
    if value not in BULLET_MODES and value not in BULLET_GLYPHS:
        raise ValueError(f"not a bullet choice: {value!r}")
    return value


class Bullets(_Strict):
    #: Job, project, education-detail and list bullets (they share one list).
    list: BulletChoice = "keep"
    #: Skills lines, which keep their own list.
    skills: BulletChoice = "keep"

    @field_validator("list", "skills")
    @classmethod
    def _bullet(cls, value: str) -> str:
        return _check_bullet(value)


class Links(_Strict):
    #: "blue" is the classic link colour; "text" prints links in the line's own colour.
    color: Literal["blue", "text"] = "blue"
    underline: bool = True


class TemplateStyle(_Strict):
    separators: Separators = Field(default_factory=Separators)
    bullets: Bullets = Field(default_factory=Bullets)
    links: Links = Field(default_factory=Links)


DEFAULT = TemplateStyle()


def from_layout(layout: dict | None) -> TemplateStyle:
    """The style an `active_layout()` dict carries (defaults when it has none)."""
    raw = (layout or {}).get("style")
    return TemplateStyle.model_validate(raw) if raw else DEFAULT


_ACTIVE: dict[tuple[str, int], TemplateStyle] = {}


def active() -> TemplateStyle:
    """The active template's style, for callers with no layout at hand (page-fit
    budgets). Cached on the profile file's path and mtime."""
    path = Path(config.TEMPLATE_PROFILE_PATH)
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return DEFAULT
    cached = _ACTIVE.get(key)
    if cached is None:
        from .template_profile import load_profile  # noqa: PLC0415

        try:
            profile = load_profile(path)
        except ValueError:
            profile = None
        cached = profile.style if profile is not None else DEFAULT
        _ACTIVE.clear()
        _ACTIVE[key] = cached
    return cached
