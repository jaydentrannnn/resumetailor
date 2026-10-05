"""Live progress, summary and busy state of a nightly apply run."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from resume_tailor.apply.funnel import attention as attention_mod
from resume_tailor.apply.funnel import store_models


class FindProgress(BaseModel):
    """Measured work within either stage of a Find jobs operation."""

    phase: Literal["discovering", "processing"]
    processed: int = 0
    total: int = 0
    current: str = ""


ProgressCallback = Callable[[FindProgress], None]

_DAILY_LOCK = threading.Lock()

#: Guards `_LIVE` only. Never held across IO — a reader must not block a run.
_PROGRESS_LOCK = threading.Lock()

class DailyBusyError(RuntimeError):
    """Raised when a daily run is already in progress."""

class DailySummary(BaseModel):
    """Aggregate outcome of one ``run_daily`` invocation."""

    already_running: bool = False
    skipped: bool = False
    reason: str = ""
    date: str = ""
    total_candidates: int = 0
    new_rows: int = 0
    processed: int = 0
    discovered: int = 0
    jd_fetched: int = 0
    needs_browser: int = 0
    screened_out: int = 0
    screened_in: int = 0
    tailored: int = 0
    tailor_failed: int = 0
    reused: int = 0
    ready: int = 0
    skipped_count: int = 0
    fetch_failed: int = 0
    already_known: int = 0
    grouped: int = 0
    prefiltered_out: int = 0
    #: Populated by the unattended batch-submit stage (`_run_batch_submit`), which
    #: only runs when `ApplySettings.auto_submit_max_per_run > 0`.
    submit_attempted: int = 0
    submitted: int = 0
    submit_failed: int = 0
    submit_skipped_no_browser: bool = False
    errors: list[str] = Field(default_factory=list)
    attention: list[attention_mod.AttentionItem] = Field(default_factory=list)
    log_path: str = ""

class DailyProgress(BaseModel):
    """Live view of the in-flight (or last finished) daily pass.

    Polled by the Apply page; every field is a plain scalar so a reader never
    needs the run's own objects. ``phase`` walks
    ``idle -> discovering -> processing -> done``.
    """

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
    summary: DailySummary | None = None

#: Mutable backing store for `daily_status`, swapped field-by-field under
#: `_PROGRESS_LOCK`. Holds a reference to the run's live `DailySummary` so
#: counters read through without copying on every poll.
_LIVE = DailyProgress()

def daily_busy() -> bool:
    """True when a daily run holds ``_DAILY_LOCK``."""
    return _DAILY_LOCK.locked()

def _progress_set(**fields: Any) -> None:
    """Patch the live progress record under `_PROGRESS_LOCK`."""
    with _PROGRESS_LOCK:
        for key, value in fields.items():
            setattr(_LIVE, key, value)

def _bump(summary: DailySummary, field: str) -> None:
    """Keep counters and live progress snapshots consistent across row workers."""
    with _PROGRESS_LOCK:
        setattr(summary, field, getattr(summary, field) + 1)

def _row_error(
    summary: DailySummary, message: str, app: store_models.Application | None = None
) -> None:
    with _PROGRESS_LOCK:
        summary.errors.append(message)
        if app is not None:
            attention_mod.record(summary.attention, app.canonical_key or app.source_job_id, f"{app.company} — {app.role}", "failed", message)

def _row_attention(
    summary: DailySummary,
    app: store_models.Application,
    kind: attention_mod.AttentionKind,
    message: str,
) -> None:
    with _PROGRESS_LOCK:
        attention_mod.record(summary.attention, app.canonical_key or app.source_job_id, f"{app.company} — {app.role}", kind, message)

def daily_status() -> DailyProgress:
    """Return a snapshot of daily-run progress, safe to serialise.

    The snapshot is a deep copy: `summary` is mutated in place by a running
    pass, so handing out the live object would let counters change mid-response.
    """
    with _PROGRESS_LOCK:
        snapshot = _LIVE.model_copy(deep=True)
    # `running` is authoritative from the lock, not from a field a crashed run
    # might have left set.
    snapshot.running = daily_busy()
    return snapshot
