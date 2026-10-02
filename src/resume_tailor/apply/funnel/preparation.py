"""Shared, read-only Fill eligibility checks for UI, API and worker."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from resume_tailor import config
from resume_tailor.apply.funnel import store_models
from resume_tailor.pipeline.expand import ExpandedEntry, Expansion


class PreparationEligibility(BaseModel):
    eligible: bool = False
    reasons: list[str] = Field(default_factory=list)


#: Every status the backend will Fill. Per-row "Continue fill" / "Reopen and fill" rely
#: on the non-`ready` ones; the SPA's bulk Fill is deliberately narrower (`ready` only)
#: so a test batch never fills every row.
_FILLABLE = {"ready", "awaiting_review", "awaiting_otp", "fill_failed"}


class _PreparedEntry(BaseModel):
    """Validate prepared expansion content without coercing malformed applicant facts."""

    model_config = ConfigDict(strict=True, extra="ignore")
    entry_key: str
    title: str
    company: str
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(min_length=1)
    char_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    on_resume: bool = False

    @field_validator("entry_key", "title", "company")
    @classmethod
    def nonempty_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prepared employment identity must not be blank")
        return value

    @field_validator("bullets")
    @classmethod
    def usable_bullets(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Prepared descriptions must contain nonblank bullet strings")
        return values


class PreparedExpansion(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    entries: list[_PreparedEntry]
    warnings: list[str] = Field(default_factory=list)
    model: str = ""
    char_limit: int = Field(default=0, ge=0)
    # Written during Prepare; a later profile edit must not change this evidence.
    source_experience_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def unique_entries(self) -> PreparedExpansion:
        keys = [entry.entry_key for entry in self.entries]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate prepared employment identities")
        if self.entries and self.source_experience_count == 0:
            raise ValueError("Prepared entries conflict with empty source employment")
        return self

    @property
    def status(self) -> str:
        if self.entries:
            return "present"
        return "not_applicable" if self.source_experience_count == 0 else "missing"

    def as_expansion(self) -> Expansion:
        return Expansion(
            entries=[ExpandedEntry(**entry.model_dump()) for entry in self.entries],
            warnings=list(self.warnings), model=self.model, char_limit=self.char_limit,
        )


def read_expansion(path: Path) -> PreparedExpansion:
    """Shared validation for eligibility and packet assembly; no fallback source."""
    return PreparedExpansion.model_validate_json(path.read_text(encoding="utf-8"))


def _usable_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def check(
    app: store_models.Application, *, require_cover: bool | None = None,
    require_acknowledgement: bool = True,
) -> PreparationEligibility:
    reasons: list[str] = []
    if app.archived_at:
        reasons.append("archived_application")
    if app.status == "submit_unconfirmed":
        reasons.append("submission_unconfirmed")
    elif app.status in store_models.TERMINAL_STATUSES:
        reasons.append("terminal_application")
    elif app.status not in _FILLABLE:
        reasons.append("not_prepared")
    if not app.job_id:
        reasons.append("missing_tailor_job")
        return PreparationEligibility(reasons=reasons)
    job_dir = config.OUTPUT_DIR / "jobs" / app.job_id
    run = job_dir / "run.json"
    raw: dict = {}
    if not run.is_file():
        reasons.append("missing_tailor_job")
    else:
        try:
            raw = json.loads(run.read_text(encoding="utf-8"))
            if raw.get("status") != "succeeded":
                reasons.append("incomplete_tailor_job")
        except (OSError, ValueError, AttributeError):
            reasons.append("invalid_tailor_job")
            raw = {}
    if require_cover is None:
        settings = raw.get("settings") or {}
        require_cover = isinstance(settings, dict) and bool(
            settings.get("cover_letter") and not settings.get("no_cover_letter")
        )
    if not any(_usable_file(job_dir / name) for name in ("tailored.pdf", "tailored.docx")):
        reasons.append("missing_resume")
    else:
        from . import resume_review

        review = resume_review.state(app)
        if not review.quality.verified:
            reasons.append("resume_quality_unverified")
        elif review.required and require_acknowledgement:
            reasons.append("resume_quality_ack_required")
    if require_cover and not any(
        _usable_file(job_dir / name) for name in ("cover.pdf", "cover.docx")
    ):
        reasons.append("missing_configured_cover_letter")
    expansion_path = job_dir / "expansion.json"
    if not expansion_path.is_file():
        reasons.append("missing_expansion")
    else:
        try:
            if read_expansion(expansion_path).status == "missing":
                reasons.append("missing_expansion")
        except (OSError, ValueError, AttributeError):
            reasons.append("invalid_expansion")
    return PreparationEligibility(eligible=not reasons, reasons=reasons)
