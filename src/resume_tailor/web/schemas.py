"""Request and response models for the web API.

Kept separate from the FastAPI routes so the same shapes can be asserted in tests without
standing up an ASGI client for every check.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import config
from ..include import IncludeOptions


class JobSettings(BaseModel):
    """Per-run knobs, mirroring the CLI flags in `tailor.py`."""

    pages: int = Field(default=1, ge=1, le=5)
    experience: int | None = Field(default=None, ge=1, le=10)
    projects: int | None = Field(default=None, ge=1, le=10)
    #: Defaults to `ollama` rather than `claude` so a fresh install runs without an
    #: Anthropic key — the Ollama free tier is what makes bulk applying affordable.
    model: str = "ollama"
    #: Ollama tag for *every* Ollama-routed stage of the chosen profile, overriding the
    #: `OLLAMA_MODEL` env default without an edit-and-restart. Under `hybrid` this leaves
    #: the Anthropic rewrite stage alone (see `config.ollama_stages`). The two per-stage
    #: overrides below still win where they are set.
    ollama_model: str | None = None
    #: Same idea, for the `gemini` profile's stages (`config.provider_stages(model,
    #: "gemini")`). A separate field rather than reusing `ollama_model` under a generic
    #: name — a `hybrid`-style profile mixing Ollama and Gemini stages needs both tags
    #: distinguishable, and this is additive so existing `settings.json` files keep loading.
    gemini_model: str | None = None
    rewrite_model: str | None = None
    expand_model: str | None = None
    effort: Literal["low", "medium", "high"] | None = None
    no_semantic: bool = False
    no_widow_repair: bool = False
    no_verb_repair: bool = False
    merge: bool = False
    no_cache: bool = False
    #: How many independent JD extractions to vote over — see `jd.extract_consensus`.
    #: 1 restores a single call.
    extract_runs: int = Field(default_factory=lambda: config.EXTRACT_CONSENSUS_RUNS, ge=1, le=10)
    no_expand: bool = False
    no_facets: bool = False
    no_project_links: bool = False
    #: Fraction of page capacity below which the fit loop grows (0.80–0.95).
    fill_target: float | None = Field(default=None, ge=0.8, le=0.95)
    #: Fraction of the chosen entries' bullets the first selection may claim (0.30–1.00).
    #: Bounds only the first draft — see `fit.fit`'s docstring for the `fill_target` pairing.
    initial_bullet_share: float | None = Field(default=None, ge=0.3, le=1.0)
    #: Fraction of the *overall* selected bullets given to experience, budgeted separately
    #: from projects (0.00–1.00). `None` is one flat pool ranked by relevance, which lets a
    #: keyword-dense project out-rank every job for the shared discretionary budget.
    experience_bullet_share: float | None = Field(default=None, ge=0.0, le=1.0)
    #: Ceiling on how many bullets any single job or project may take. `None` is uncapped.
    max_bullets_per_entry: int | None = Field(default=None, ge=1, le=10)
    #: What to leave out — contact fields/order, GPA, coursework, whole entries. See
    #: `include.py`. Nested rather than flattened so the "what to include" tile's state
    #: has one field to read/write, and an old settings.json without this key just gets
    #: `IncludeOptions()` defaults.
    include: IncludeOptions = Field(default_factory=IncludeOptions)
    #: Opt-in: after a successful run, opportunistically draft vocabulary-library
    #: proposals from this run's near-miss keyword gaps and unclassified opening verbs
    #: (`propose.py`). Defaults off — an always-on extra call would silently add a call
    #: to every run's budget for a feature most runs have no use for, and would break
    #: every test whose fake LLM client is queued with a fixed number of replies.
    suggest_vocabulary: bool = False


class WorkspaceSettings(BaseModel):
    """The on-disk shape of one profile's `settings.json`.

    Wraps `JobSettings` rather than forking its fields, so the run-knob list has one
    definition — adding a knob to `JobSettings` is the only edit needed for it to be
    persistable. `schema_version` exists because this file is user data that outlives
    a release.
    """

    schema_version: int = 1
    defaults: JobSettings = Field(default_factory=JobSettings)


class SettingsResponse(BaseModel):
    """Response for `GET /api/settings` and `PUT /api/settings`."""

    workspace_id: str | None = None
    settings: JobSettings
    #: True when settings.json did not exist and JobSettings() defaults were served.
    seeded: bool = False


class SettingsUpdateRequest(BaseModel):
    """Body for `PUT /api/settings`."""

    settings: JobSettings


class CreateJobRequest(BaseModel):
    """Start a tailoring run from a pasted or uploaded job description.

    `settings` is optional: when omitted, the run falls back to the active profile's
    saved defaults (`GET /api/settings`) rather than `JobSettings()` — this is what
    lets a bare `POST /api/jobs {"jd_text": "..."}` behave like the UI, whose settings
    panel always shows and sends the profile's current defaults explicitly.
    """

    jd_text: str = Field(min_length=1)
    settings: JobSettings | None = None


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


class KeywordGapOut(BaseModel):
    """Why one unmatched must-have missed — see `report.KeywordGap`."""

    canonical: str
    phrase: str
    importance: str
    reason: Literal["no_evidence", "untagged_evidence", "near_miss"]
    evidence: list[str]


class RunReportOut(BaseModel):
    """Structured end-of-run summary for the results panel."""

    title: str
    seniority: str
    coverage_matched: int
    coverage_total: int
    missing_must_haves: list[str]
    unmatched_canonicals: list[list[str]]
    #: Defaulted so a job payload cached before this field existed still validates.
    gaps: list[KeywordGapOut] = Field(default_factory=list)
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
    #: The `OLLAMA_MODEL` / `OLLAMA_BASE_URL` env defaults, so the settings panel can show
    #: what an `ollama`/`hybrid` profile actually resolves to instead of leaving it
    #: invisible in `.env`.
    ollama_model: str = ""
    ollama_base_url: str = ""
    #: Profiles with at least one Ollama-routed stage, so the UI knows when the tag field
    #: applies without hardcoding `["ollama", "hybrid"]` against `config.MODEL_PROFILES`.
    ollama_profiles: list[str] = Field(default_factory=list)
    #: The `GEMINI_MODEL` / `GEMINI_BASE_URL` env defaults, mirroring the Ollama pair above.
    gemini_model: str = ""
    gemini_base_url: str = ""
    #: Profiles with at least one Gemini-routed stage — mirrors `ollama_profiles`.
    gemini_profiles: list[str] = Field(default_factory=list)
    #: Whether a credential is present for each origin that requires one
    #: (`config.PROVIDERS_REQUIRING_KEY`), so the settings panel can warn the moment a
    #: profile is picked rather than only after a run fails deep in the job queue. Booleans
    #: only — never the key value itself.
    provider_keys: dict[str, bool] = Field(default_factory=dict)
    effort_options: list[str]
    pdf_backend: str
    calibration_source: str
    chars_per_line: int
    lines_per_page: int
    tag_vocabulary: list[str]
    contact_name: str | None = None
    #: Default page-fill target (UNDERFLOW_THRESHOLD) for the settings slider.
    fill_target: float = 0.93
    #: Default first-draft bullet-share ceiling (INITIAL_BULLET_SHARE) for the settings slider.
    initial_bullet_share: float = 1.0
    #: Default experience-vs-projects share (EXPERIENCE_BULLET_SHARE); `None` means
    #: unweighted, matching the config default.
    experience_bullet_share: float | None = None
    #: Default per-entry bullet cap (MAX_BULLETS_PER_ENTRY); `None` means uncapped.
    max_bullets_per_entry: int | None = None
    active_workspace_id: str | None = None
    active_workspace_label: str | None = None
    #: True on the first response after the legacy single-slot layout was migrated
    #: into a "Default" profile. The UI shows a one-time banner and never sets it again.
    migrated_from_legacy: bool = False


class ResumeOutlineEntryOut(BaseModel):
    """One experience/project entry as the include tile lists it."""

    id: str
    label: str
    bullets: int


class ResumeOutlineResponse(BaseModel):
    """Master-resume shape the include tile needs: what exists, so it knows what to offer.

    Served from its own endpoint (not folded into `ConfigResponse`) because `RunProvider`
    fetches config once and holds it for the life of a profile mount, while this needs to
    be fresh every time the Tailor tab is visited — the master resume may have changed on
    the Editor tab in between.
    """

    #: Which of location/email/phone/linkedin/github are non-empty in the master resume.
    available_contact_fields: list[str] = Field(default_factory=list)
    #: The active template profile's order, used when `include.contact_fields` is null.
    default_contact_order: list[str] = Field(default_factory=list)
    has_gpa: bool = False
    #: Whether `Education.show_gpa` is currently on for any entry — lets a profile
    #: upgrading to this feature seed the tile from its existing behaviour instead of
    #: silently flipping GPA visibility on the next run.
    gpa_currently_shown: bool = False
    has_coursework: bool = False
    experience: list[ResumeOutlineEntryOut] = Field(default_factory=list)
    projects: list[ResumeOutlineEntryOut] = Field(default_factory=list)
    #: From `template_profile.active_layout()["enabled"]` — a template with no Projects
    #: section should not offer project checkboxes or the link toggle.
    sections_enabled: dict[str, bool] = Field(default_factory=dict)


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


class WorkspaceEntryOut(BaseModel):
    """One profile in the switcher's list."""

    id: str
    label: str
    created_at: str
    is_active: bool = False
    has_master_resume: bool = False
    has_template: bool = False


class WorkspaceListResponse(BaseModel):
    """Response for `GET /api/workspaces` and the CRUD mutations that return a list."""

    entries: list[WorkspaceEntryOut] = Field(default_factory=list)
    active_id: str | None = None


class WorkspaceCreateRequest(BaseModel):
    """Body for `POST /api/workspaces`."""

    label: str
    #: When set, the new profile starts as a duplicate of this one's resume, template,
    #: template library, and calibration (never its LLM caches — those regenerate).
    copy_from: str | None = None


class WorkspaceRenameRequest(BaseModel):
    """Body for `PATCH /api/workspaces/{id}`."""

    label: str


class WorkspaceActivateResponse(BaseModel):
    """Everything the SPA needs to re-seed itself after a profile switch, in one call."""

    ok: bool = True
    active_id: str
    entries: list[WorkspaceEntryOut] = Field(default_factory=list)
    config: ConfigResponse
    settings: JobSettings
    template: TemplateInfoResponse


class LibraryOverridesOut(BaseModel):
    """A workspace's own additions and removals, layered on top of its enabled packs.
    Wire shape of `libraries.LibraryOverrides`."""

    tag_aliases: dict[str, str] = Field(default_factory=dict)
    tag_aliases_removed: list[str] = Field(default_factory=list)
    #: verb -> family. One family per overridden verb, not a pack's family -> [verbs].
    verb_families: dict[str, str] = Field(default_factory=dict)
    verb_families_removed: list[str] = Field(default_factory=list)


class LibraryPackSummaryOut(BaseModel):
    """One pack's summary row for the Settings tab's pack list — no alias/verb bodies,
    since a workspace may have several packs enabled and the list view doesn't need
    every one's full contents."""

    id: str
    label: str
    description: str = ""
    builtin: bool = False
    tag_alias_count: int = 0
    verb_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class LibraryPackOut(BaseModel):
    """One pack's full contents, for `GET /api/libraries/packs/{id}` (the edit form)."""

    id: str
    label: str
    description: str = ""
    builtin: bool = False
    tag_aliases: dict[str, str] = Field(default_factory=dict)
    verb_families: dict[str, list[str]] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class LibraryPackWriteRequest(BaseModel):
    """Body for `POST /api/libraries/packs` and `PUT /api/libraries/packs/{id}`.

    `label` is required for both; create derives a fresh id from it, update takes the
    id from the path and uses this field only to change the label itself.
    """

    label: str
    description: str = ""
    tag_aliases: dict[str, str] = Field(default_factory=dict)
    verb_families: dict[str, list[str]] = Field(default_factory=dict)
    #: Allow overwriting a target another pack already claims — see
    #: `libraries.validate_pack`. Without this, a genuine conflict is a 400.
    force: bool = False


class LibraryEffectiveOut(BaseModel):
    """Summary of the composed table. Per-pack contents already sit in `packs`, so this
    is counts and a fingerprint, not the tables themselves."""

    tag_alias_count: int = 0
    verb_count: int = 0
    fingerprint: str = ""


ProposalKindOut = Literal["tag_alias", "verb_family"]


class LibraryProposalOut(BaseModel):
    """One LLM-drafted addition awaiting approval."""

    id: str
    kind: ProposalKindOut
    alias: str | None = None
    canonical: str | None = None
    verb: str | None = None
    family: str | None = None
    rationale: str = ""
    source: Literal["run", "manual"] = "manual"
    created_at: str = ""


class LibraryStateResponse(BaseModel):
    """Response for `GET /api/libraries` and every mutating library route, so the
    Settings tab can always re-render from what a mutation returns rather than issuing
    a second fetch."""

    packs: list[LibraryPackSummaryOut] = Field(default_factory=list)
    enabled_packs: list[str] = Field(default_factory=list)
    overrides: LibraryOverridesOut = Field(default_factory=LibraryOverridesOut)
    effective: LibraryEffectiveOut = Field(default_factory=LibraryEffectiveOut)
    #: Human-readable notes from composition: a missing pack, a cross-pack verb
    #: collision, or a dropped alias chain. Never errors — see `libraries.py`.
    diagnostics: list[str] = Field(default_factory=list)
    proposals: list[LibraryProposalOut] = Field(default_factory=list)
    #: Set only by `POST /api/libraries/proposals` when generation partially failed
    #: (an `LLMError`) — that route still returns 200 with whatever succeeded rather
    #: than failing the whole request over an advisory feature.
    warning: str | None = None


class LibrarySelectionRequest(BaseModel):
    """Body for `PUT /api/libraries/selection`."""

    enabled_packs: list[str]
    overrides: LibraryOverridesOut = Field(default_factory=LibraryOverridesOut)


class LibraryAliasImpactOut(BaseModel):
    """What approving one alias would rewrite in the current master resume, if
    anything. Empty `affected_tags` means the alias is purely additive."""

    alias: str
    canonical: str
    affected_tags: list[str] = Field(default_factory=list)
    #: (entry label, bullet id) pairs carrying the affected tag.
    affected_bullets: list[tuple[str, str]] = Field(default_factory=list)


class LibraryImpactRequest(BaseModel):
    """Body for `POST /api/libraries/impact`."""

    tag_aliases: dict[str, str]


class LibraryImpactResponse(BaseModel):
    impacts: list[LibraryAliasImpactOut] = Field(default_factory=list)


class ProposalGenerateRequest(BaseModel):
    """Body for `POST /api/libraries/proposals`. `jd_text` is optional context — the
    request's own gaps (near-miss tags, unclassified opening verbs) drive most of the
    prompt regardless."""

    jd_text: str = ""


class ProposalApproveRequest(BaseModel):
    """Body for `POST /api/libraries/proposals/approve`."""

    proposal_ids: list[str]
    #: An existing user-authored pack to fold the approved items into. Never a built-in
    #: id — `libraries.write_pack` refuses those.
    target_pack_id: str
    #: Required (re-POST with this set) once `libraries.alias_impact` reports that an
    #: approved alias would rewrite an existing bullet tag on the next master-resume
    #: save — see `approve_library_proposals`'s 409 path.
    acknowledge_rewrites: bool = False


class ProposalRejectRequest(BaseModel):
    """Body for `POST /api/libraries/proposals/reject`. Rejected ids move to the
    workspace's `rejected` list so they are never re-proposed."""

    proposal_ids: list[str]
