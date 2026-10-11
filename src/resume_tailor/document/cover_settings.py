"""Cover-letter layout settings: which letterhead lines and letter blocks print.

Stored per profile beside the cover template (`config.COVER_SETTINGS_PATH`), because they
describe the letter's layout, not one run. Applied at render time through the letter's
Jinja context (`render.build_letter_context`): the cover template always carries every
block behind a `{%p if blocks[...] %}` guard, so changing a setting never rebuilds it.
No LLM reads these — the subject line is filled by code from the posting's title.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import config
from .template_profile import ContactField

CONTACT_FIELDS: tuple[ContactField, ...] = ("location", "email", "phone", "linkedin", "github")
CUSTOM_PREFIX = "custom:"
BLOCK_NAMES = ("date", "recipient", "subject", "salutation", "closing", "signature")


class CoverBlocks(BaseModel):
    """Which letter blocks print. The body always does. Defaults match the letter as it
    printed before these settings existed (no subject line)."""

    model_config = ConfigDict(extra="forbid")

    date: bool = True
    recipient: bool = True
    subject: bool = False
    salutation: bool = True
    closing: bool = True
    signature: bool = True


class CoverSettings(BaseModel):
    """One profile's cover-letter layout choices."""

    model_config = ConfigDict(extra="forbid")

    #: `same_as_resume`: the letterhead shows what the resume header shows (the template's
    #: contact fields and every custom line). `custom`: only `letterhead_fields`.
    letterhead: Literal["same_as_resume", "custom"] = "same_as_resume"
    #: Contact field names and `custom:<key>` entries; read only when `letterhead` is custom.
    letterhead_fields: list[str] = Field(default_factory=list, max_length=40)
    blocks: CoverBlocks = Field(default_factory=CoverBlocks)
    #: `{job_title}` and `{company}` are filled from the posting; anything else is literal.
    subject_format: str = Field(default="Application for {job_title}", max_length=200)
    closing_text: str = Field(default="Sincerely,", max_length=80)

    @field_validator("letterhead_fields")
    @classmethod
    def _known_fields(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            if item not in CONTACT_FIELDS and not item.startswith(CUSTOM_PREFIX):
                raise ValueError(f"unknown letterhead field: {item!r}")
            if item not in out:
                out.append(item)
        return out

    def contact_fields(self, layout: dict) -> list[ContactField] | None:
        """Contact fields for the letterhead: `None` (the template's own order) when the
        same as the resume, else the chosen fields in the template's order, any chosen
        field the template line lacks appended in canonical order."""
        if self.letterhead == "same_as_resume":
            return None
        chosen = [f for f in self.letterhead_fields if f in CONTACT_FIELDS]
        template_order = [f for f in layout.get("contact_field_order") or [] if f in chosen]
        rest = [f for f in CONTACT_FIELDS if f in chosen and f not in template_order]
        return template_order + rest

    def custom_shown(self, key: str) -> bool:
        """Whether custom line `key` prints in the letterhead."""
        if self.letterhead == "same_as_resume":
            return True
        return f"{CUSTOM_PREFIX}{key}" in self.letterhead_fields

    def subject(self, *, job_title: str, company: str) -> str:
        """The subject line, or "" when its block is off or it would name nothing."""
        if not self.blocks.subject:
            return ""
        text = self.subject_format
        for name, value in (("{job_title}", job_title.strip()), ("{company}", company.strip())):
            if name in text and not value:
                return ""  # "Application for " names nothing — leave the line out
            text = text.replace(name, value)
        return " ".join(text.split())


def load() -> CoverSettings:
    """The active profile's settings; defaults when the file is missing or unreadable."""
    path = config.COVER_SETTINGS_PATH
    try:
        return CoverSettings.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return CoverSettings()


def save(settings: CoverSettings) -> None:
    """Write the active profile's settings."""
    path = config.COVER_SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
