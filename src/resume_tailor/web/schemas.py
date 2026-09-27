"""Request and response models for the web API.

Kept separate from the FastAPI routes so the same shapes can be asserted in tests without
standing up an ASGI client for every check.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .. import config
from ..apply.eligibility import EligibilitySettings
from ..apply.profile import ApplicantProfile
from ..apply.screen import ScreenResult, ScreenSettings
from ..apply.store import ApplicationStatus, AtsKind, FillResult, StatusChange
from ..include import IncludeOptions

#: Every `source_sha256` request field below is interpolated straight into a filesystem
#: path in `web/template_ops.py` (`_upload_cache_dir() / f"{sha}.docx"`, etc.). Since
#: these arrive in a JSON body rather than a path param, nothing else stops a value
#: like `"../../../etc/passwd"` from reaching `pathlib`, which does not normalise `..`.
#: A real sha256 hex digest can never contain `/`; enforcing the shape here rejects a
#: traversal attempt at the schema boundary, before any path is built.
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

#: Heading kinds the template wizard's remap step may force — `template_analyze`'s
#: alias targets plus `"list"`. Mirrors the SPA's `TemplateHeadingKind`.
HeadingKind = Literal["experience", "education", "projects", "skills", "list"]


class CoverAnglesIn(BaseModel):
    """Optional per-application cover-letter angle inputs.

    Nested on `JobSettings` with defaults so an existing `settings.json` loads
    unchanged. Separate from regeneration `instruction` — see `coverletter.CoverAngles`.
    """

    why_company: str = Field(default="", max_length=1000)
    problem: str = Field(default="", max_length=1000)
    approach: str = Field(default="", max_length=1000)
    tone: Literal["", "formal", "direct", "conversational", "mirror"] = ""


class BoardConfig(BaseModel):
    """One company job board on a watchlist source (`apply/boards.py`)."""

    ats: Literal["greenhouse", "lever", "ashby", "smartrecruiters", "workday"]
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    #: The name shown in the UI and used for postings; the slug when empty.
    company: str = ""

    @model_validator(mode="after")
    def check_slug(self) -> BoardConfig:
        from ..apply import boards

        if not boards.valid_slug(self.slug, self.ats):
            raise ValueError("Invalid job board slug")
        return self


class SourceConfig(BaseModel):
    """One discovery source for the daily apply funnel.

    ``simplify_html`` and ``pipe_table`` read a README at ``url`` and keep the rows under
    ``categories``. ``ats_board`` (plan P4-D2) reads each board in ``boards`` and keeps
    the postings whose title matches ``include`` (any word, or everything when empty)
    and none of ``exclude``, and whose location matches ``locations`` (any, or
    everywhere when empty). ``max_age_days`` widens the funnel-wide age limit for this
    source (the longer of the two wins); watchlists default to 7 days, since finance
    recruiting opens months ahead and a board posting stays relevant for longer than a
    README row.
    """

    id: str
    kind: Literal["simplify_html", "pipe_table", "ats_board", "job_search"]
    url: str = ""
    categories: list[str] = Field(default_factory=list)
    enabled: bool = True
    boards: list[BoardConfig] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    max_age_days: int | None = Field(default=None, ge=0, le=365)
    provider: Literal["adzuna", "usajobs"] | None = None
    query: str = ""
    location: str = ""
    country: str = "us"

    @model_validator(mode="after")
    def _check_kind(self) -> SourceConfig:
        if self.kind == "job_search":
            if not self.provider:
                raise ValueError(f"source {self.id!r} needs a provider")
            if not self.query.strip():
                raise ValueError(f"source {self.id!r} needs a query")
            if self.max_age_days is None:
                self.max_age_days = 14
        elif self.kind == "ats_board":
            if self.max_age_days is None:
                self.max_age_days = 7
        else:
            if not self.url.strip():
                raise ValueError(f"source {self.id!r} needs a url")
        return self


def _default_apply_sources() -> list[SourceConfig]:
    """Built-in sources: Simplify internships, Simplify new-grad, and speedyapply."""
    return [
        SourceConfig(
            id="simplify-internships",
            kind="simplify_html",
            url=(
                "https://raw.githubusercontent.com/SimplifyJobs/"
                "Summer2027-Internships/dev/README.md"
            ),
            categories=[
                "Software Engineering Internship Roles",
                "Data Science, AI & Machine Learning Internship Roles",
            ],
        ),
        SourceConfig(
            id="simplify-newgrad",
            kind="simplify_html",
            url=("https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"),
            categories=[
                "Software Engineering New Grad Roles",
                "Data Science, AI & Machine Learning New Grad Roles",
            ],
        ),
        SourceConfig(
            id="speedyapply",
            kind="pipe_table",
            url=(
                "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md"
            ),
            categories=[
                "2027 USA SWE Internships",
                "USA Positions",
            ],
            enabled=True,
        ),
    ]


class ApplySettings(BaseModel):
    """Daily apply-funnel knobs nested on ``JobSettings`` so they persist with settings."""

    enabled: bool = False
    schedule_time: str = "02:00"
    #: Legacy single-source fields — kept so existing settings.json still loads.
    #: When ``sources`` is empty the validator synthesizes one entry from these.
    readme_url: str = (
        "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"
    )
    categories: list[str] = Field(
        default_factory=lambda: [
            "Software Engineering Internship Roles",
            "Data Science, AI & Machine Learning Internship Roles",
        ]
    )
    sources: list[SourceConfig] = Field(default_factory=_default_apply_sources)
    max_age_days: int = 1
    exclude_advanced_degree: bool = True
    exclude_citizenship_required: bool = True
    exclude_no_sponsorship: bool = False
    max_new_per_day: int = 40
    screen: ScreenSettings = Field(default_factory=ScreenSettings)
    eligibility: EligibilitySettings = Field(default_factory=EligibilitySettings)
    auto_submit_ats: list[str] = Field(default_factory=list)
    #: Cap on how many `ready` applications the unattended batch-submit stage
    #: (`daily._run_batch_submit`) will fill+submit per `run_daily` invocation. `0`
    #: (default) disables the stage entirely — existing workspaces see no behavior
    #: change until this is explicitly raised. Only ever considers ATSes already
    #: listed in `auto_submit_ats`; Workday is excluded in code regardless (see
    #: `fill.decide_submit_action`).
    auto_submit_max_per_run: int = Field(default=0, ge=0)
    max_parallel_fills: int = Field(default=2, ge=1, le=4)
    auto_submit_enabled: bool = False
    #: Rolling 24-hour limits on automatic submits (`apply.submit_guard`). A form that
    #: would go over is left for review with the note "Daily cap reached". `0` means no
    #: automatic submits, never "no limit".
    auto_submit_max_per_day: int = Field(default=25, ge=0)
    auto_submit_max_per_company_per_day: int = Field(default=2, ge=0)
    blocker_mode: Literal["pause", "continue"] = "continue"
    reuse_threshold: float = 0.72
    cover_letter: bool = True
    #: Provider + model for Fill's own LLM calls only — written-answer drafting and
    #: choice/blocker resolution (the "Autofill model" on the Apply page). Prepare's
    #: tailoring and its screening JD extraction use the Tailor tab's routing instead
    #: (`JobSettings.model` & co., via `web.jobs.model_routing`), so they run exactly like
    #: a Tailor-tab run. Fill's calls run outside the job queue, so without this explicit
    #: pin they would fall through to `config.backend_for`'s hardcoded Claude default
    #: whenever `_ACTIVE` is empty (e.g. right after a fresh restart) — see CLAUDE.md.
    model_provider: Literal["ollama", "ollama-cloud", "lmstudio", "gemini", "anthropic"] = "ollama"
    model_name: str = "nemotron-3-super:cloud"

    @property
    def model_spec(self) -> str:
        """``provider:model`` spec for `config.pinned`, covering Fill's autofill calls.

        ``ollama-cloud`` is not a provider word `config.parse_spec` knows: it is Ollama
        pinned to Ollama Cloud's API, so it becomes ``ollama:<tag>@<cloud URL>``.
        """
        if self.model_provider == "ollama-cloud":
            return f"ollama:{self.model_name}@{config.OLLAMA_CLOUD_BASE_URL}"
        return f"{self.model_provider}:{self.model_name}"

    @model_validator(mode="after")
    def _ensure_sources(self) -> ApplySettings:
        """Synthesize a simplify_html source from legacy fields when ``sources`` is empty."""
        if self.sources:
            return self
        self.sources = [
            SourceConfig(
                id="simplify-internships",
                kind="simplify_html",
                url=self.readme_url,
                categories=list(self.categories),
            )
        ]
        return self


class JobSettings(BaseModel):
    """Per-run knobs, mirroring the CLI flags in `tailor.py`."""

    pages: int = Field(default=1, ge=1, le=5)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=4)
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
    skills_model: str | None = None
    cover_model: str | None = None
    #: Override for the opt-in hiring-manager review stage (`--review` / CLI only today).
    review_model: str | None = None
    #: Override for application-form free-text answers (`apply.answer`).
    answer_model: str | None = None
    effort: Literal["low", "medium", "high"] | None = None
    no_semantic: bool = False
    no_widow_repair: bool = False
    no_verb_repair: bool = False
    merge: bool = False
    no_cache: bool = False
    #: How many independent JD extractions to vote over (`jd.extract_consensus`);
    #: 0 = automatic (`config.extract_runs`: 1 on Anthropic/Gemini, 3 on local models).
    extract_runs: int = Field(default=0, ge=0, le=10)
    no_expand: bool = False
    #: Skips the tailored skills-list stage. Defaults off (the stage runs): unlike
    #: `suggest_vocabulary`, this is read-only advisory output and is the point of the
    #: feature, not a workspace mutation the user must opt into.
    no_skills: bool = False
    #: Opt-in: draft and render a cover letter after the tailored resume succeeds.
    cover_letter: bool = False
    no_cover_letter: bool = False
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
    #: Editable style block for resume bullet rewriting; ``None`` uses the shipped default.
    rewrite_style: str | None = Field(default=None, max_length=4000)
    #: Editable style block for application-form experience expansion; ``None`` uses default.
    expand_style: str | None = Field(default=None, max_length=4000)
    #: Editable style block for cover-letter drafting; ``None`` uses default.
    cover_style: str | None = Field(default=None, max_length=4000)
    #: Optional cover-letter angle inputs (why this company, problem, approach, tone).
    cover_angles: CoverAnglesIn = Field(default_factory=CoverAnglesIn)
    #: One blanket model override applied to every stage of the selected profile.
    model_name: str | None = None
    #: Daily discover/screen/fill funnel settings (persisted with profile defaults).
    apply: ApplySettings = Field(default_factory=ApplySettings)


class RunMetadata(BaseModel):
    """Optional posting provenance attached to a tailor job for the apply funnel."""

    posting_url: str = ""
    company: str = ""
    role: str = ""
    source: str = ""
    source_job_id: str = ""
    ats: str = "unknown"


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

    # 50,000 chars comfortably covers any real posting (a few KB at most, even a
    # verbose one with full benefits/legal boilerplate) while bounding what reaches
    # `jd.extract_consensus` — which sends this text to the model up to 3 times.
    jd_text: str = Field(min_length=1, max_length=50_000)
    settings: JobSettings | None = None
    metadata: RunMetadata | None = None


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
    #: Score-neutral posting weight; defaulted so a run.json written before this
    #: field existed still validates.
    band: str = "meaningful"
    #: Where the band came from (`jd.Keyword.evidence`). Named `evidence_tier` to
    #: avoid colliding with the diagnostic `evidence` list above.
    evidence_tier: str = "inferred"


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
    #: Why coverage is unmeasurable; None when the ratio is real. See `jd.extraction_diagnosis`.
    extraction_diagnosis: str | None = None
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
    #: See `report.RunReport.calibration_rejection` — non-None only when a calibration
    #: file existed but was rejected as implausible, not simply absent.
    calibration_rejection: str | None = None


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


class SkillSuggestionOut(BaseModel):
    """One skill to enter, for the "Skills to list" copy-paste tile."""

    skill: str = ""
    pool_label: str = ""
    tier: Literal["required", "preferred", "additional"] = "additional"
    jd_phrase: str = ""
    sources: list[str] = Field(default_factory=list)
    reason: str = ""


class SkillsPlanOut(BaseModel):
    """Tailored skills-list artifact for one tailoring run.

    Independent of `RunReportOut` and `ExpansionOut`: skills selection can succeed, fail,
    or be skipped without changing the tailored resume outcome. Carries no gaps field —
    the "you can't claim this" half of the tile reads `RunReportOut.gaps`, already computed
    once by `report.diagnose_gaps`.
    """

    skills: list[SkillSuggestionOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str = ""
    pool_size: int = 0


class CoverLetterOut(BaseModel):
    """Cover-letter artifact for one tailoring run."""

    company: str = ""
    company_location: str = ""
    addressee: str = ""
    paragraphs: list[str] = Field(default_factory=list)
    salutation: str = ""
    closing: str = ""
    signature: str = ""
    inside_address: list[str] = Field(default_factory=list)
    date: str = ""
    warnings: list[str] = Field(default_factory=list)
    model: str = ""
    word_count: int = 0
    has_docx: bool = False
    has_pdf: bool = False


class CoverLetterRegenerateRequest(BaseModel):
    """Optional one-off instruction and angles for cover-letter regeneration."""

    instruction: str = ""
    cover_angles: CoverAnglesIn | None = None


class VerifyClaimRequest(BaseModel):
    """Body for `POST /api/verify-claim`: check free-text against a finished run."""

    job_id: str | None = Field(default=None, max_length=64)
    #: Application-answer or similar prose. Bounded so a runaway paste cannot flood
    #: the fabrication tokeniser; 10k covers any real form field.
    text: str = Field(min_length=1, max_length=10_000)


class VerifyClaimResponse(BaseModel):
    """Whether ``text`` is supported by the run's tailored bullets and JD numbers."""

    ok: bool
    unsupported_terms: list[str] = Field(default_factory=list)
    unsupported_numbers: list[str] = Field(default_factory=list)


class JobStatusResponse(BaseModel):
    """Current state of one queued or finished run."""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    queue_position: int | None = None
    error: str | None = None
    report: RunReportOut | None = None
    expansion: ExpansionOut | None = None
    skills: SkillsPlanOut | None = None
    cover_letter: CoverLetterOut | None = None
    events: list[ProgressEventOut] = Field(default_factory=list)
    #: ISO timestamp when the run was submitted — present for disk-backed history rows.
    created_at: str | None = None
    #: Short title for history list rows (report title, or JD first line).
    title: str | None = None
    #: Optional posting provenance for the apply funnel.
    metadata: RunMetadata | None = None


class RunHistoryEntryOut(BaseModel):
    """One row in the Tailor tab's recent-runs list."""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    created_at: str
    finished_at: str | None = None
    title: str
    #: From the run's posting metadata (apply funnel, JD fetched from a link); "" if unknown.
    company: str = ""
    error: str | None = None
    pages: int | None = None
    coverage_matched: int | None = None
    coverage_total: int | None = None
    has_pdf: bool = False
    has_docx: bool = False


class RunHistoryResponse(BaseModel):
    """Newest-first recent runs for the active profile."""

    runs: list[RunHistoryEntryOut] = Field(default_factory=list)


class DeleteRunHistoryRequest(BaseModel):
    """Remove one or more finished runs from disk-backed history."""

    job_ids: list[str] = Field(min_length=1)


class DeleteRunHistoryResponse(BaseModel):
    """Per-id outcome of a history delete request."""

    deleted: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


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
    #: See `report.RunReport.calibration_rejection`.
    calibration_rejection: str | None = None
    chars_per_line: int
    lines_per_page: int
    #: Soft min / hard max character band the rewrite prompt advertises for a two-line
    #: bullet — same numbers `rewrite.length_band(fit.default_bullet_char_budget())`
    #: returns. Surfaced so the master-resume editor can warn before a bullet is past
    #: the cliff the fit loop will later fight.
    bullet_char_soft_min: int = 0
    bullet_char_max: int = 0
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
    #: Shipped default style blocks for the Tailor tab's prompt editors.
    rewrite_style_default: str = ""
    expand_style_default: str = ""
    cover_style_default: str = ""
    #: Locked safety rules shown read-only beside each style editor.
    rewrite_core_rules: str = ""
    expand_core_rules: str = ""
    cover_core_rules: str = ""
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


class ResumeOutlineSectionOut(BaseModel):
    """One resume section as the include tile lists it — any kind, any count, in
    resume order. The general form of the flattened `experience`/`projects` fields
    below, which stay for callers that only ever assumed exactly two sections."""

    id: str
    title: str
    kind: str
    entries: list[ResumeOutlineEntryOut] = Field(default_factory=list)


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
    #: Every entry section (any kind, any count), in resume order — lets the include
    #: tile show which section an entry belongs to instead of merging same-kind
    #: sections into one flat list.
    sections: list[ResumeOutlineSectionOut] = Field(default_factory=list)
    #: From `template_profile.active_layout()["enabled"]` — a template with no Projects
    #: section should not offer project checkboxes or the link toggle.
    sections_enabled: dict[str, bool] = Field(default_factory=dict)
    #: From `template_profile.active_layout()["section_mode"]` — `"fixed"` templates bake
    #: section order into the tagged XML, so reordering `include.section_order` has no
    #: visible effect until the template is rebuilt in generic mode. The include tile uses
    #: this to disable/annotate its section-order control rather than silently no-op.
    section_mode: str = "fixed"


class ValidateResponse(BaseModel):
    """Result of a dry-run master-resume validation."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    summary: dict[str, Any] | None = None


class MasterResumeImportResponse(BaseModel):
    """Result of `POST /api/master-resume/import`: a draft the editor loads as unsaved
    state — nothing is written to disk here. The user reviews and saves through the
    existing `PUT /api/master-resume`, the same path a hand edit takes."""

    resume: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    untagged_bullet_count: int = 0


class MasterResumeMergeResponse(BaseModel):
    """Result of `POST /api/master-resume/merge`: unlike `import`, this one writes —
    `resume` is the merged, saved master resume. `updated`/`added`/`added_sections` are
    entry/section names, not just counts, so the caller can show exactly what changed
    (surfacing a near-miss duplicate immediately rather than burying it in a total)."""

    resume: dict[str, Any]
    updated: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    added_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    backup: str | None = None


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
    #: When this backend's calibration file was written (ISO, UTC); None when there is none.
    calibrated_at: str | None = None


class CalibrateResponse(BaseModel):
    """Result of ``POST /api/template/calibrate`` (the Template tab's "Tune page fit")."""

    ok: bool
    log: str
    warnings: list[str] = Field(default_factory=list)
    calibration: CalibrationInfo


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


class DefaultTemplateOut(BaseModel):
    """One built-in starter template (`default_templates`)."""

    name: str
    label: str
    description: str
    #: The design lists Education first; the UI offers to reorder the resume to match.
    education_first: bool = False
    #: The library entry holding this design, when it has been installed before.
    library_id: str | None = None
    is_active: bool = False


class DefaultTemplatesResponse(BaseModel):
    templates: list[DefaultTemplateOut] = Field(default_factory=list)


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


class TemplateFieldCandidateOut(BaseModel):
    """One suggested character span for a semantic field (company, dates, …), so the
    wizard can show a per-field confidence row instead of just a pass/fail section
    summary."""

    field: str
    paragraph_id: int
    start: int
    end: int
    confidence: float = 0.0
    preview: str = ""
    section_heading_paragraph_id: int | None = None


class TemplateAnalyzeResponse(BaseModel):
    """Preflight analysis for an uploaded baseline (no disk writes)."""

    source_sha256: str
    paragraphs: list[TemplateParagraphOut]
    sections: list[TemplateSectionOut]
    field_candidates: list[TemplateFieldCandidateOut] = Field(default_factory=list)
    suggested_profile: dict[str, Any] | None = None
    issues: list[TemplateIssueOut] = Field(default_factory=list)
    ready: bool = False


class TemplateRemapRequest(BaseModel):
    """Body for `POST /api/template/analyze/remap`.

    `source_sha256` must match a sha the wizard already analyzed in this process
    lifetime (see `template_ops._cache_upload`) — the remap step never re-uploads the
    file. `overrides` maps a heading paragraph id to a user-confirmed kind
    (`experience`/`education`/`projects`/`skills`/`list`), or `null` to say "this is
    not a section" regardless of what the heuristics concluded.
    """

    source_sha256: str = Field(pattern=_SHA256_HEX_PATTERN)
    overrides: dict[int, HeadingKind | None] = Field(default_factory=dict)


class TemplatePreviewDraftRequest(BaseModel):
    """Body for `POST /api/template/preview/draft`: build a staged profile into a temp
    tagged template and render the master resume through it, without touching the live
    template slot."""

    source_sha256: str = Field(pattern=_SHA256_HEX_PATTERN)
    profile: dict[str, Any]


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
    customized: bool = False
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
    customized: bool = False
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

    jd_text: str = Field(default="", max_length=50_000)


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


class ProfileGap(BaseModel):
    """One blank profile field that application forms ask for."""

    key: str
    label: str
    section: str
    path: str
    #: Stored applications whose last fill met this question with the field blank.
    seen_in: int = 0


class ApplicantProfileResponse(BaseModel):
    """Response for ``GET /api/applicant-profile``."""

    workspace_id: str | None = None
    profile: ApplicantProfile
    seeded: bool = False
    workday_password_set: bool = False
    #: Profile fields forms ask for that this profile leaves blank (`packet.profile_gaps`).
    gaps: list[ProfileGap] = Field(default_factory=list)
    #: Harmless answers used when the profile field is blank (`packet.DEFAULTS`).
    defaults: dict[str, str] = Field(default_factory=dict)


class ApplicantProfileUpdateRequest(BaseModel):
    """Body for ``PUT /api/applicant-profile``."""

    profile: ApplicantProfile


class ApplicationOut(BaseModel):
    """API view of one tracked application (``apply.store``)."""

    source: str
    source_job_id: str
    company: str
    role: str
    location: str = ""
    posting_url: str = ""
    final_url: str = ""
    ats: AtsKind = "unknown"
    sponsorship_ok: str = "Unknown"
    citizenship_required: str = "No"
    notes: str = ""
    status: ApplicationStatus = "discovered"
    status_history: list[StatusChange] = Field(default_factory=list)
    discovered_at: str = ""
    #: When the posting was published (`store.posted_date`); when ``posted_known`` is
    #: false this is the date it was found instead.
    posted_at: str = ""
    posted_known: bool = False
    jd_text_path: str | None = None
    screen: ScreenResult | None = None
    job_id: str | None = None
    reused_from_job_id: str | None = None
    fill: FillResult | dict[str, Any] | None = None
    error: str | None = None
    canonical_key: str = ""
    group_key: str = ""
    salary: str = ""
    duplicate_of: str | None = None
    eligibility_flags: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    group_size: int = 1
    otp_prompt: str | None = None
    archived_at: str | None = None
    preparation_eligible: bool = False
    preparation_reasons: list[str] = Field(default_factory=list)
    #: Which retry `POST .../retry` would run (`daily.retry_kind`), or None when the
    #: row has no retry path — the SPA shows and labels its Retry button from this.
    retry_kind: Literal["fetch", "prefilter", "tailor"] | None = None
    #: Short "why screened out" label for the Status column (`screen.screen_label`).
    screen_label: str | None = None
    #: What a row in the "Needs your review" table is waiting on (`store.review_summary`).
    review_summary: str | None = None


class ApplicationsListResponse(BaseModel):
    """Newest-first application rows plus per-status counts."""

    applications: list[ApplicationOut] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class ArchiveApplicationsRequest(BaseModel):
    application_ids: list[str] = Field(min_length=1, max_length=500)
    archived: bool


class ArchiveApplicationsResponse(BaseModel):
    updated: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


class ApplicationDetailResponse(BaseModel):
    """One application with optional packet and JD text when available."""

    application: ApplicationOut
    packet: dict[str, Any] | None = None
    jd_text: str | None = None


class ApplicationStatusRequest(BaseModel):
    """Body for ``POST /api/applications/{source_job_id}/status``."""

    status: ApplicationStatus
    note: str = ""


class ApplicationNotesRequest(BaseModel):
    """Body for ``PUT /api/applications/{source_job_id}/notes`` (the detail page's Notes tab)."""

    notes: str = Field(default="", max_length=20_000)


class AnswerRequest(BaseModel):
    """Body for ``POST /api/jobs/{job_id}/answer``."""

    question: str = Field(min_length=1, max_length=4000)
    max_chars: int = Field(default=1500, ge=50, le=10_000)


class AnswerResponse(BaseModel):
    """Guarded free-text answer for one ATS question."""

    answer: str
    offenders: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source: str
    model: str


class BrowserStatusResponse(BaseModel):
    """Reachability of the configured host browser's CDP endpoint."""

    reachable: bool
    browser: str = ""
    user_agent: str = ""
    error: str = ""
    cdp_url: str = ""


class ApplyOperationRequest(BaseModel):
    """Start one explicit Apply-page stage using a captured settings snapshot."""

    action: Literal["find", "prepare", "fill"]
    fill_mode: Literal["initial", "continue", "reopen"] = "initial"
    force_prepare: bool = False
    application_ids: list[str] = Field(default_factory=list, max_length=500)
    limit: int | None = Field(default=None, ge=1, le=500)
    #: One-off posting-age window for Find; ``None`` uses the saved ``max_age_days``.
    max_age_days: int | None = Field(default=None, ge=0, le=365)
    dry_run: bool = False
    auto_submit: bool = False
    blocker_mode: Literal["pause", "continue"] = "continue"
    model_provider: Literal["ollama", "ollama-cloud", "lmstudio", "gemini", "anthropic"]
    model_name: str = Field(min_length=1, max_length=200)


class ApplyOperationControlRequest(BaseModel):
    """Control a running or paused Apply operation."""

    action: Literal["pause", "resume", "skip", "cancel"]


class ApplyOperationResponse(BaseModel):
    """Persistent progress for one Find, Prepare, or Fill operation."""

    operation_id: str
    action: Literal["find", "prepare", "fill", "inspect", "correct"]
    state: str
    application_ids: list[str] = Field(default_factory=list)
    in_flight: list[dict[str, Any]] = Field(default_factory=list)
    current_application_id: str = ""
    current_job_id: str = ""
    current_label: str = ""
    stage: str = ""
    message: str = ""
    processed: int = 0
    total: int = 0
    completed: int = 0
    blocked: int = 0
    failed: int = 0
    submitted: int = 0
    started_at: str = ""
    updated_at: str = ""
    heartbeat_at: str = ""
    current_step: int = 0
    current_step_id: str = ""
    current_step_number: int = 0
    current_action_id: str = ""
    current_action_label: str = ""
    current_field_label: str = ""
    action_started_at: str = ""
    last_activity_at: str = ""
    application_started_at: str = ""
    application_deadline_at: str = ""
    ready_for_review: int = 0
    needs_input: int = 0
    finished_at: str = ""
    effective_model: str = ""
    auto_submit: bool = False
    blocker_mode: Literal["pause", "continue"] = "continue"
    events: list[dict[str, Any]] = Field(default_factory=list)
    excluded: dict[str, list[str]] = Field(default_factory=dict)


class ReviewCorrectionRequest(BaseModel):
    snapshot_id: str
    field_id: str
    expected_state_hash: str
    value: str | None = None
    option_ids: list[str] = Field(default_factory=list)
    idempotency_key: str


class DailyStatusResponse(BaseModel):
    """Progress snapshot for ``GET /api/applications/daily-status``."""

    running: bool = False
    phase: str = "idle"
    source_id: str = ""
    current: str = ""
    processed: int = 0
    total: int = 0
    dry_run: bool = False
    fetch_only: bool = False
    started_at: str = ""
    finished_at: str = ""
    date: str = ""
    summary: dict[str, Any] | None = None
    #: `apply.scheduler.status()`: last/next scheduled run, today's miss, bad time.
    scheduler: dict[str, Any] | None = None


class SuggestTagsRequest(BaseModel):
    """Body for ``POST /api/master-resume/suggest-tags`` (the editor's per-bullet chips).

    ``vocabulary`` is the editor's draft tag list, so tags added but not yet saved count.
    """

    text: str = Field(max_length=5_000)
    tags: list[str] = Field(default_factory=list, max_length=200)
    vocabulary: list[str] = Field(default_factory=list, max_length=5_000)
