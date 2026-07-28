"""Request and response models for the web API.

Kept separate from the FastAPI routes so the same shapes can be asserted in tests without
standing up an ASGI client for every check.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class JobSettings(BaseModel):
    """Per-run knobs, mirroring the CLI flags in `tailor.py`."""

    pages: int = Field(default=1, ge=1, le=5)
    experience: int | None = Field(default=None, ge=1, le=10)
    projects: int | None = Field(default=None, ge=1, le=10)
    model: str = "claude"
    rewrite_model: str | None = None
    effort: Literal["low", "medium", "high"] | None = None
    no_semantic: bool = False
    no_widow_repair: bool = False
    no_verb_repair: bool = False
    merge: bool = False
    no_cache: bool = False


class CreateJobRequest(BaseModel):
    """Start a tailoring run from a pasted or uploaded job description."""

    jd_text: str = Field(min_length=1)
    settings: JobSettings = Field(default_factory=JobSettings)


class CreateJobResponse(BaseModel):
    """Handle returned immediately; the run itself is asynchronous."""

    job_id: str
    queue_position: int


class ProgressEventOut(BaseModel):
    """One stage event as the browser receives it over SSE."""

    stage: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class SectionSummaryOut(BaseModel):
    """How much of one experience/project entry survived into the final document."""

    label: str
    kept: int
    total: int
    rewritten: int


class RunReportOut(BaseModel):
    """Structured end-of-run summary for the results panel."""

    title: str
    seniority: str
    coverage_matched: int
    coverage_total: int
    missing_must_haves: list[str]
    unmatched_canonicals: list[list[str]]
    model: str
    semantic_used: bool
    bullets_selected: int
    bullets_total: int
    experience: list[SectionSummaryOut]
    projects: list[SectionSummaryOut]
    dropped: list[str]
    pages: int
    pages_are_estimated: bool
    iterations: int
    widows_repaired: int
    widows_remaining: int
    verbs_diversified: int
    verb_collisions_remaining: int
    warnings: list[str]
    out_path: str
    pdf_backend: str
    calibration_source: str


class JobStatusResponse(BaseModel):
    """Current state of one queued or finished run."""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    queue_position: int | None = None
    error: str | None = None
    report: RunReportOut | None = None
    events: list[ProgressEventOut] = Field(default_factory=list)


class ConfigResponse(BaseModel):
    """Defaults and vocabulary the UI needs before a run starts."""

    pages: int
    experience: int
    projects: int
    model_profiles: list[str]
    effort_options: list[str]
    pdf_backend: str
    calibration_source: str
    chars_per_line: int
    lines_per_page: int
    tag_vocabulary: list[str]
    contact_name: str | None = None


class ValidateResponse(BaseModel):
    """Result of a dry-run master-resume validation."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    summary: dict[str, Any] | None = None
