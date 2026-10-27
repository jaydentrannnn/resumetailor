"""The application registry's models: statuses, fill results and `Application`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, PrivateAttr

from resume_tailor.apply.funnel.screen import ScreenResult
from resume_tailor.pipeline.posting_guard import GuardFindings

ApplicationStatus = Literal[
    "discovered",
    "jd_fetched",
    "needs_browser",
    "screened_out",
    "screened_in",
    "tailoring",
    "tailor_failed",
    "ready",
    "filling",
    "awaiting_otp",
    "fill_failed",
    "awaiting_review",
    "submitted",
    "submit_unconfirmed",
    "interview",
    "rejected",
    "ghosted",
    "skipped",
]

AtsKind = Literal[
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "icims",
    "smartrecruiters",
    "taleo",
    "successfactors",
    "oracle",
    "jobvite",
    "bamboohr",
    "linkedin",
    "indeed",
    "handshake",
    "other",
    "unknown",
]

#: How a LinkedIn/Indeed posting is applied to: on the board itself ("Easy Apply",
#: "Apply now" — Fill cannot drive it), on the employer's own site, or not yet known.
ApplyKind = Literal["easy_apply", "external", "unknown"]

#: Statuses that close the funnel — must not revert to pre-ready states. The only
#: definition: `preparation.check` reports these as `terminal_application`, which is
#: what the SPA reads rather than keeping its own copy.
TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"submitted", "interview", "rejected", "ghosted", "skipped"}
)

#: Discovery/screen/tailor stages before a packet is ``ready``.
PRE_READY_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        "discovered",
        "jd_fetched",
        "needs_browser",
        "screened_out",
        "screened_in",
        "tailoring",
        "tailor_failed",
    }
)

#: Filled applications waiting on the applicant: the Applications page's top table.
REVIEW_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"awaiting_review", "awaiting_otp", "fill_failed", "submit_unconfirmed"}
)

#: A task is running on the row; it stays in the table it was in until the task ends.
RUNNING_STATUSES: frozenset[ApplicationStatus] = frozenset({"filling", "tailoring"})

#: Pipeline order, for sorting by status (not alphabetical by internal name).
_STATUS_RANK: dict[str, int] = {status: rank for rank, status in enumerate(get_args(ApplicationStatus))}

SCHEMA_VERSION = 5

class StatusChange(BaseModel):
    """One entry in an application's status timeline."""

    status: ApplicationStatus
    at: str
    note: str = ""

class FillResult(BaseModel):
    """Form-fill outcome persisted on ``Application.fill``."""

    filled: list[Any] = Field(default_factory=list)
    leftovers: list[Any] = Field(default_factory=list)
    long_text_answers: dict[str, str] = Field(default_factory=dict)
    uploads: list[dict[str, Any]] = Field(default_factory=list)
    required_empty: list[str] = Field(default_factory=list)
    ready_to_submit: bool = False
    submit_action: str = ""
    confirmation: str = ""
    confirmation_evidence: dict[str, str] = Field(default_factory=dict)
    screenshot_path: str | None = None
    error: str | None = None
    status: str = ""
    browser_target_id: str = ""
    browser_url: str = ""
    handoff_reason: str = ""
    final_step_reached: bool = False
    field_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    current_step_id: str = ""
    review_snapshot_id: str = ""
    review_fields: list[dict[str, Any]] = Field(default_factory=list)
    #: Questions recognised as a profile fact the profile leaves blank, one entry per
    #: key: {key, field_label, section, path, questions, answered}.
    missing_profile: list[dict[str, Any]] = Field(default_factory=list)
    #: How this fill went, for telling an old failure from a current one (never values):
    #: {app_version, platform: {posting, landed}, end_category, elapsed_s, model_calls,
    #: corrections: [{label, key}]} (`forms.fill_diagnostics`, `answer_harvest`).
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    #: What happened to this application's tab, newest last (`tab_events`):
    #: {at, event: closed|kept|gone|replaced, reason, host}.
    tab_history: list[dict[str, str]] = Field(default_factory=list)
    #: File names the applicant attached or changed in the tab themselves
    #: (`answer_harvest`); a Continue fill never replaces those (`upload_replace`).
    user_touched_uploads: list[str] = Field(default_factory=list)

#: What happened after an application went out. Hiring progress is derived from these
#: (`outcomes.hiring_progress`); the row's operational ``status`` stays ``submitted``.
OutcomeType = Literal[
    "assessment",
    "interview_invited",
    "interview_scheduled",
    "interview_completed",
    "offer",
    "hired",
    "offer_declined",
    "rejected",
    "withdrawn",
    "ghosted",
    "employer_timeline",
    "followup_drafted",
    "followup_sent",
]


class OutcomeEvent(BaseModel):
    """One recorded fact about a sent application. Never deleted: a correction adds a
    new event naming the one it ``replaces``, and both a corrected and a voided event
    keep their text with ``voided_at`` set."""

    id: str
    type: OutcomeType
    #: The date it happened (ISO date), when the student knows it.
    occurred_on: str | None = None
    recorded_at: str
    source: Literal["manual", "mcp", "monitor"] = "manual"
    note: str = ""
    replaces: str | None = None
    voided_at: str | None = None


class SubmissionAttempt(BaseModel):
    """What was sent: an immutable copy of the files at the moment the row became
    submitted (`attempts.record`). ``confirmed`` is True only when the app itself
    uploaded and sent these files; a manual mark records the prepared files, whose
    upload is unconfirmed."""

    id: str
    number: int
    submitted_at: str
    method: Literal["auto", "manual", "monitor"]
    confirmed: bool = False
    snapshot_dir: str = ""
    #: File name in ``snapshot_dir`` -> SHA-256.
    files: dict[str, str] = Field(default_factory=dict)
    #: The names in ``files`` the app itself attached to the form (``attached/...``,
    #: copied from the fill's pinned files) -> SHA-256. Empty: the prepared files only.
    attached: dict[str, str] = Field(default_factory=dict)
    packet_digest: str = ""
    jd_sha256: str = ""
    voided_at: str | None = None
    #: Why the copy is incomplete, when it is (the status change still stands).
    error: str = ""


class SourceRef(BaseModel):
    """One discovery sighting of a posting (Simplify UUID, speedyapply hash, …)."""

    source: str
    source_job_id: str
    url: str = ""
    first_seen: str = ""

class Application(BaseModel):
    """One tracked posting from discovery through submit."""

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
    jd_text_path: str | None = None
    screen: ScreenResult | None = None
    job_id: str | None = None
    reused_from_job_id: str | None = None
    fill: FillResult | dict[str, Any] | None = None
    error: str | None = None
    canonical_key: str = ""
    group_key: str = ""
    source_refs: list[SourceRef] = Field(default_factory=list)
    age_days: int | None = None
    #: The posting's own publication date (ISO date) when its source states one;
    #: otherwise `posted_date` derives it from ``discovered_at`` and ``age_days``.
    posted_at: str = ""
    salary: str = ""
    duplicate_of: str | None = None
    eligibility_flags: list[str] = Field(default_factory=list)
    otp_prompt: str | None = None
    archived_at: str | None = None
    #: Set by the browser extension on a LinkedIn/Indeed capture (see `ApplyKind`).
    apply_kind: ApplyKind = "unknown"
    #: A card saved from a search page without its description (status ``discovered``).
    #: Nothing fetches it server-side: the extension completes it when the user opens
    #: the job, and the daily funnel and Prepare skip it until then.
    capture_stub: bool = False
    #: Bumped on every write of this row; lets a client tell that a row changed.
    revision: int = 0
    # Additive JSON-column fields: old SQLite/legacy rows load with empty defaults.
    resume_ack_revision: str = ""
    resume_ack_at: str = ""
    #: What `posting_guard` removed from or flagged in the saved JD (`daily_rows.save_jd`);
    #: None for a row saved before the guard, which `submit_guard` scans on demand.
    posting_guard: GuardFindings | None = None
    outcome_events: list[OutcomeEvent] = Field(default_factory=list)
    attempts: list[SubmissionAttempt] = Field(default_factory=list)

    #: The stored version this object was read from (never mutated), or None for a
    #: row built in memory. `upsert` diffs against it; see the module docstring.
    _base: Application | None = PrivateAttr(default=None)
    #: Set by `store.undo_terminal` until the next write: the one change allowed to
    #: take a terminal row back to a working status (`store._merge_into`).
    _undoing_terminal: bool = PrivateAttr(default=False)

@dataclass
class Index:
    """In-memory lookup tables over the applications registry."""

    by_canonical: dict[str, Application] = field(default_factory=dict)
    by_source_ref: dict[tuple[str, str], str] = field(default_factory=dict)
    by_group: dict[str, list[str]] = field(default_factory=dict)

def list_group(app: Application) -> Literal["review", "working"]:
    """Which Applications table lists ``app``: ``review`` (Needs you) or ``working``.

    A row with a task running keeps the table of the status it ran from, so Retry on a
    "Needs you" row does not bounce it to In progress and back; it moves when the task
    ends. With no earlier status on record it counts as working.
    """
    status = app.status
    if status in RUNNING_STATUSES:
        status = next(
            (
                change.status
                for change in reversed(app.status_history)
                if change.status not in RUNNING_STATUSES
            ),
            status,
        )
    return "review" if status in REVIEW_STATUSES else "working"

def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()

def _registry_key(app: Application) -> str:
    """Primary dict key: canonical_key when set, else legacy source_job_id."""
    return app.canonical_key or app.source_job_id

def posted_date(app: Application) -> tuple[str, bool]:
    """The date ``app`` was posted (ISO date) and whether it is known.

    A source that states a date wins. Otherwise the posting's age on the day it was
    found dates it, unless the source gave no age (flag ``age_unknown``). With neither,
    the date found stands in, reported as unknown: a posting is never newer than that.
    """
    if app.posted_at:
        return app.posted_at[:10], True
    try:
        found = datetime.fromisoformat(app.discovered_at.replace("Z", "+00:00"))
    except ValueError:
        return "", False
    if app.age_days is not None and "age_unknown" not in app.eligibility_flags:
        return (found.date() - timedelta(days=max(0, app.age_days))).isoformat(), True
    return found.date().isoformat(), False
