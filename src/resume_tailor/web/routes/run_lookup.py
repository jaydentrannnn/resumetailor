"""Finding a run (live job or `run.json` on disk) and its artifacts for the job routes.

Helpers only, no router: `routes/jobs.py` and `routes/applications.py` share them.
"""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import convert
from resume_tailor.pipeline import report, resume_quality
from resume_tailor.pipeline.events import ProgressEvent
from resume_tailor.web.job_types import Job
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.routes.config import _event_out
from resume_tailor.web.schemas import (
    CoverLetterOut,
    ExpansionOut,
    JobStatusResponse,
    RunHistoryEntryOut,
    RunMetadata,
    RunReportOut,
    SkillsPlanOut,
)


def _job_status_response(job: Job) -> JobStatusResponse:
    """Build the wire shape shared by `get_job` and `cancel_job`."""
    position = get_queue().queue_position(job.job_id) or None
    title = job.report.title if job.report else None
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        queue_position=position if job.status == "queued" else None,
        error=job.error,
        report=_quality_report(job.report, job.out_dir),
        expansion=job.expansion,
        skills=job.skills,
        cover_letter=job.cover_letter,
        events=[_event_out(e) for e in job.events],
        created_at=job.created_at,
        title=title,
        metadata=job.metadata,
    )


def _quality_report(value: RunReportOut | None, out_dir: Path | None) -> RunReportOut | None:
    if value is None or out_dir is None or not (out_dir / "quality.json").exists():
        return value
    return value.model_copy(update={"quality": resume_quality.read(out_dir).model_dump()})

@dataclass
class _ResolvedRun:
    """Live job or disk-backed `run.json` — enough for status + artifact routes."""

    job_id: str
    status: str
    out_dir: Path
    error: str | None = None
    report: RunReportOut | None = None
    expansion: ExpansionOut | None = None
    skills: SkillsPlanOut | None = None
    cover_letter: CoverLetterOut | None = None
    events: list[ProgressEvent] = field(default_factory=list)
    created_at: str | None = None
    title: str | None = None
    #: Present only for in-memory jobs — cancel/SSE still need the live object.
    live: Job | None = None
    metadata: RunMetadata | None = None

def _load_run_json(job_id: str) -> dict[str, Any] | None:
    """Parse `output/.../jobs/<id>/run.json` if it exists, else None."""
    path = config.OUTPUT_DIR / "jobs" / job_id / "run.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None

def _resolve_run(job_id: str) -> _ResolvedRun | None:
    """Prefer the in-memory job; fall back to a persisted `run.json` on disk.

    Download and preview routes used to 404 the moment the process restarted even
    though `tailored.pdf` was still on disk — this is what makes history usable.
    """
    live = get_queue().get(job_id)
    if live is not None:
        out_dir = live.out_dir or (config.OUTPUT_DIR / "jobs" / job_id)
        return _ResolvedRun(
            job_id=live.job_id,
            status=live.status,
            out_dir=out_dir,
            error=live.error,
            report=live.report,
            expansion=live.expansion,
            skills=live.skills,
            cover_letter=live.cover_letter,
            events=list(live.events),
            created_at=live.created_at,
            title=live.report.title if live.report else None,
            live=live,
            metadata=live.metadata,
        )
    raw = _load_run_json(job_id)
    if raw is None:
        return None
    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    report_out: RunReportOut | None = None
    if raw.get("report"):
        with suppress(ValidationError):
            report_out = RunReportOut.model_validate(raw["report"])
    expansion_out: ExpansionOut | None = None
    expansion_path = out_dir / "expansion.json"
    if expansion_path.exists():
        with suppress(OSError, ValidationError, json.JSONDecodeError):
            expansion_out = ExpansionOut.model_validate(
                json.loads(expansion_path.read_text(encoding="utf-8"))
            )
    skills_out: SkillsPlanOut | None = None
    skills_path = out_dir / "skills.json"
    if skills_path.exists():
        with suppress(OSError, ValidationError, json.JSONDecodeError):
            skills_out = SkillsPlanOut.model_validate(
                json.loads(skills_path.read_text(encoding="utf-8"))
            )
    cover_out: CoverLetterOut | None = None
    cover_path = out_dir / "cover.json"
    if cover_path.exists():
        with suppress(OSError, ValidationError, json.JSONDecodeError):
            cover_out = CoverLetterOut.model_validate(
                json.loads(cover_path.read_text(encoding="utf-8"))
            )
    meta_out: RunMetadata | None = None
    if raw.get("metadata"):
        with suppress(ValidationError):
            meta_out = RunMetadata.model_validate(raw["metadata"])
    return _ResolvedRun(
        job_id=str(raw.get("job_id") or job_id),
        status=str(raw.get("status") or "failed"),
        out_dir=out_dir,
        error=raw.get("error"),
        report=report_out,
        expansion=expansion_out,
        skills=skills_out,
        cover_letter=cover_out,
        created_at=raw.get("created_at"),
        title=raw.get("title") or (report_out.title if report_out else None),
        metadata=meta_out,
    )

def _resolved_status_response(resolved: _ResolvedRun) -> JobStatusResponse:
    """Wire shape for a live or disk-backed run."""
    if resolved.live is not None:
        return _job_status_response(resolved.live)
    return JobStatusResponse(
        job_id=resolved.job_id,
        status=resolved.status,  # type: ignore[arg-type]
        error=resolved.error,
        report=_quality_report(resolved.report, resolved.out_dir),
        expansion=resolved.expansion,
        skills=resolved.skills,
        cover_letter=resolved.cover_letter,
        events=[_event_out(e) for e in resolved.events],
        created_at=resolved.created_at,
        title=resolved.title,
        metadata=resolved.metadata,
    )

#: Cap on how many history rows `GET /api/jobs` returns.
_HISTORY_LIMIT = 30

def _scan_run_history() -> list[RunHistoryEntryOut]:
    """Newest-first history for the active workspace from disk + in-memory overlay."""
    active_ws = config.active_workspace_id()
    jobs_root = config.OUTPUT_DIR / "jobs"
    by_id: dict[str, RunHistoryEntryOut] = {}

    if jobs_root.is_dir():
        for child in jobs_root.iterdir():
            if not child.is_dir():
                continue
            raw = _load_run_json(child.name)
            if raw is None:
                continue
            # Skip runs that belong to a different profile (or legacy runs with no
            # workspace_id when we *do* have an active one — those predate this field).
            record_ws = raw.get("workspace_id")
            if active_ws is not None and record_ws is not None and record_ws != active_ws:
                continue
            if active_ws is not None and record_ws is None:
                # Pre-history runs: only show them when their directory sits under the
                # active workspace's output root (workspace-scoped OUTPUT_DIR already).
                pass
            report = raw.get("report") or {}
            by_id[child.name] = RunHistoryEntryOut(
                job_id=child.name,
                status=raw.get("status") or "failed",
                created_at=str(raw.get("created_at") or ""),
                finished_at=raw.get("finished_at"),
                title=str(raw.get("title") or "Untitled run"),
                company=str((raw.get("metadata") or {}).get("company") or ""),
                error=raw.get("error"),
                pages=report.get("pages"),
                coverage_matched=report.get("coverage_matched"),
                coverage_total=report.get("coverage_total"),
                has_pdf=(child / "tailored.pdf").exists(),
                has_docx=(child / "tailored.docx").exists(),
            )

    # Overlay live jobs for this workspace (queued/running may have no run.json yet).
    for job in get_queue().iter_jobs():
        if active_ws is not None and job.workspace_id not in (None, active_ws):
            continue
        out_dir = job.out_dir or (jobs_root / job.job_id)
        title = (
            job.report.title
            if job.report
            else (
                job.jd_text.splitlines()[0].strip()[:80]
                if job.jd_text.strip()
                else "Untitled run"
            )
        )
        by_id[job.job_id] = RunHistoryEntryOut(
            job_id=job.job_id,
            status=job.status,
            created_at=job.created_at,
            finished_at=None,
            title=title or "Untitled run",
            company=job.metadata.company if job.metadata else "",
            error=job.error,
            pages=job.report.pages if job.report else None,
            coverage_matched=job.report.coverage_matched if job.report else None,
            coverage_total=job.report.coverage_total if job.report else None,
            has_pdf=(out_dir / "tailored.pdf").exists(),
            has_docx=(out_dir / "tailored.docx").exists(),
        )

    runs = sorted(by_id.values(), key=lambda r: r.created_at, reverse=True)
    return runs[:_HISTORY_LIMIT]

def _job_artifact(job_id: str, suffix: str) -> Path:
    """Resolve a finished job's deliverable, or raise 404."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / f"tailored{suffix}"
    if suffix == ".pdf":
        _rebuild_missing_pdf(path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} was not produced.")
    return path

def _rebuild_missing_pdf(pdf: Path) -> None:
    """Convert a finished run's `.docx` when its PDF is missing, or raise 404.

    A run whose PDF step failed (e.g. Word refusing a conversion) still has a good
    `.docx`, so the PDF is rebuilt on first request instead of leaving a dead link.
    """
    docx = pdf.with_suffix(".docx")
    if pdf.exists() or not docx.exists():
        return
    try:
        convert.convert(docx, pdf)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=404, detail=f"{pdf.name} was not produced, and rebuilding it failed: {exc}"
        ) from exc

def _export_download_name(job_id: str, *, suffix: str) -> str:
    """User-facing download name from contact + JD title, with a safe fallback."""
    resolved = _resolve_run(job_id)
    title = (
        (resolved.report.title if resolved and resolved.report else None)
        or (resolved.title if resolved else None)
        or "Resume"
    )
    try:
        name = data.load().contact.name
    except (FileNotFoundError, ValueError):
        name = "Resume"
    return report.export_filename(name, title, suffix=suffix)

def _finished_run_dir(job_id: str) -> Path:
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(status_code=409, detail="Only a finished run can be edited.")
    return resolved.out_dir
