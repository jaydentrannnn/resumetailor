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
    expand_model: str | None = None
    effort: Literal["low", "medium", "high"] | None = None
    no_semantic: bool = False
    no_widow_repair: bool = False
    no_verb_repair: bool = False
    merge: bool = False
    no_cache: bool = False
    no_expand: bool = False
    no_facets: bool = False
    no_project_links: bool = False
    #: Fraction of page capacity below which the fit loop grows (0.80–0.95).
    fill_target: float | None = Field(default=None, ge=0.8, le=0.95)


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


class ExpandedEntryOut(BaseModel):
    """One experience entry for the application-form copy-paste tile."""

    entry_key: str
    title: str
    company: str
    location: str
    start: str
    end: str
    bullets: list[str] = Field(default_factory=list)
    char_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    on_resume: bool = False


class ExpansionOut(BaseModel):
    """Expanded experience descriptions for application-form paste fields.

    Independent of `RunReportOut`: expansion can succeed, fail, or be skipped without
    changing the tailored resume outcome.
    """

    entries: list[ExpandedEntryOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str = ""
    char_limit: int = 0


class JobStatusResponse(BaseModel):
    """Current state of one queued or finished run."""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    queue_position: int | None = None
    error: str | None = None
    report: RunReportOut | None = None
    expansion: ExpansionOut | None = None
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
    #: Default page-fill target (UNDERFLOW_THRESHOLD) for the settings slider.
    fill_target: float = 0.93


class ValidateResponse(BaseModel):
    """Result of a dry-run master-resume validation."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    summary: dict[str, Any] | None = None


class TemplateFileInfo(BaseModel):
    """Existence and metadata for one template .docx on disk."""

    exists: bool
    path: str
    size_bytes: int | None = None
    modified_at: str | None = None


class CalibrationInfo(BaseModel):
    """Whether fit constants are still valid for the current tagged template."""

    source: str
    chars_per_line: int
    lines_per_page: int
    #: True when main_template.docx is newer than the calibration file (or there is none).
    stale: bool
    message: str | None = None


class TemplateProfileSummary(BaseModel):
    """Active template-profile metadata shown on the Template tab."""

    exists: bool = False
    schema_version: int | None = None
    enabled: dict[str, bool] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    contact_separator: str | None = None


class TemplateInfoResponse(BaseModel):
    """Current baseline + tagged template state for the Template tab."""

    baseline: TemplateFileInfo
    tagged: TemplateFileInfo
    experience_entries: int = 0
    project_entries: int = 0
    bullets: int = 0
    calibration: CalibrationInfo
    preview_available: bool = False
    profile: TemplateProfileSummary = Field(default_factory=TemplateProfileSummary)
    #: Active named-library entry, when the live slot was installed/activated from the library.
    active_library_id: str | None = None
    active_label: str | None = None


class TemplateBuildResponse(BaseModel):
    """Outcome of uploading a new baseline and regenerating the tagged template."""

    ok: bool
    log: str = ""
    info: TemplateInfoResponse | None = None


class TemplateLibraryEntry(BaseModel):
    """One saved template in the named library."""

    id: str
    label: str
    created_at: str
    source_filename: str | None = None
    size_bytes: int | None = None
    has_profile: bool = False
    is_active: bool = False


class TemplateLibraryResponse(BaseModel):
    """List of named templates plus which one is currently live."""

    entries: list[TemplateLibraryEntry] = Field(default_factory=list)
    active_id: str | None = None


class TemplateLibraryRenameRequest(BaseModel):
    """Rename a library entry."""

    label: str


class TemplateIssueOut(BaseModel):
    """One analyzer finding (blocking or advisory)."""

    code: str
    message: str
    blocking: bool = False


class TemplateParagraphOut(BaseModel):
    """Paragraph preview for the mapping wizard."""

    id: int
    text: str
    is_bullet: bool = False
    is_heading_candidate: bool = False
    has_tab: bool = False
    has_hyperlink: bool = False
    run_count: int = 0
    preview: str = ""


class TemplateSectionOut(BaseModel):
    """Detected section heading candidate."""

    key: str
    heading_paragraph_id: int
    heading_text: str
    body_start: int
    body_end: int
    entry_count: int = 0
    bullet_count: int = 0
    confidence: float = 0.0
    aliases_matched: str = ""


class TemplateAnalyzeResponse(BaseModel):
    """Preflight analysis for an uploaded baseline (no disk writes)."""

    source_sha256: str
    paragraphs: list[TemplateParagraphOut]
    sections: list[TemplateSectionOut]
    suggested_profile: dict[str, Any] | None = None
    issues: list[TemplateIssueOut] = Field(default_factory=list)
    ready: bool = False
