"""A queued tailoring job: its status, record and cancellation signal."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from resume_tailor.content import industries
from resume_tailor.pipeline.events import ProgressEvent
from resume_tailor.web.schemas import (
    CoverLetterOut,
    ExpansionOut,
    JobSettings,
    RunMetadata,
    RunReportOut,
    SkillsPlanOut,
)

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]

class JobCancelled(Exception):
    """Raised internally to unwind `JobQueue._execute` once a user cancels a running
    job. Never escapes `_run_loop` — caught there and translated into the terminal
    "cancelled" status, same as `FabricationError`/`FitError` are translated into
    "failed"."""

@dataclass
class Job:
    """One queued or finished tailoring run, held in memory for the life of the process."""

    job_id: str
    jd_text: str
    settings: JobSettings
    status: JobStatus = "queued"
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    #: Profile that owned this run when it was submitted — needed so `GET /api/jobs`
    #: after a profile switch does not list another workspace's in-memory jobs.
    workspace_id: str | None = None
    #: Optional posting provenance for the apply funnel (URL, company, Simplify id).
    metadata: RunMetadata | None = None
    error: str | None = None
    report: RunReportOut | None = None
    expansion: ExpansionOut | None = None
    skills: SkillsPlanOut | None = None
    cover_letter: CoverLetterOut | None = None
    events: list[ProgressEvent] = field(default_factory=list)
    #: Signalled whenever a new event lands, so the SSE endpoint can wake up.
    event_notify: threading.Event = field(default_factory=threading.Event)
    #: Set by `JobQueue.cancel` on a running job; `_execute` polls it at checkpoints
    #: between pipeline stages (never mid-LLM-call) via `check_cancelled`.
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    out_dir: Path | None = None
    guidance: industries.GuidanceSnapshot | None = None

    def emit(self, event: ProgressEvent) -> None:
        """Append a progress event and wake any SSE listeners."""
        self.events.append(event)
        self.event_notify.set()

    def check_cancelled(self) -> None:
        """Raise `JobCancelled` if this job's cancellation was requested."""
        if self.cancel_requested.is_set():
            raise JobCancelled()
