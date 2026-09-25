"""Tailoring job routes: submit, status, events, artifacts, cover letters."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from resume_tailor import (
    config,
    data,
    estimate,
    include,
    report,
    workspace,
)
from resume_tailor.events import ProgressEvent
from resume_tailor.template_profile import active_layout
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import Job, get_queue, regenerate_cover_letter, verify_claim
from resume_tailor.web.routes.config import _event_out, _seed_include_gpa_if_missing
from resume_tailor.web.schemas import (
    CoverLetterOut,
    CoverLetterRegenerateRequest,
    CreateJobRequest,
    CreateJobResponse,
    DeleteRunHistoryRequest,
    DeleteRunHistoryResponse,
    ExpansionOut,
    JobSettings,
    JobStatusResponse,
    ResumeOutlineEntryOut,
    ResumeOutlineResponse,
    ResumeOutlineSectionOut,
    RunHistoryEntryOut,
    RunHistoryResponse,
    RunMetadata,
    RunReportOut,
    SkillsPlanOut,
    VerifyClaimRequest,
    VerifyClaimResponse,
)

router = APIRouter()
_log = logging.getLogger(__name__)


@router.post("/api/jobs", response_model=CreateJobResponse)
def create_job(body: CreateJobRequest) -> CreateJobResponse:
    """Enqueue a tailoring run. Returns immediately with a job id.

    Validates against — and submits against — the active workspace atomically under
    `template_ops.LOCK`, the same lock `activate_workspace` holds while switching. Without
    this, a job could be validated against workspace A, then executed by the worker
    against workspace B if a switch landed in between: `submit()` only enqueues, so the
    job's actual `data.load()`/path resolution happens later, on the worker thread,
    against whatever `config` points to *then* — not what it pointed to when this route
    ran. `activate_workspace`'s own `busy()` check has to run *inside* this same lock for
    the same reason: checked-then-acquired, a job submitted in the gap would still slip
    through to the worker under the new workspace.
    """
    if not body.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description is empty.")
    settings = body.settings
    if settings is None:
        # No per-run override: fall back to the active profile's saved defaults so a
        # bare `POST /api/jobs {"jd_text": ...}` behaves like the UI.
        raw_defaults = workspace.load_settings()["defaults"]
        settings = JobSettings.model_validate(raw_defaults)
        _seed_include_gpa_if_missing(raw_defaults, settings)
    # A missing key otherwise only surfaces as an async `job.status == "failed"` once the
    # worker gets to it. `credential_gaps` is pure (never touches `_ACTIVE`), so this check
    # is safe to run on the request thread even while another job is mid-run.
    overrides = {
        k: v
        for k, v in (
            ("rewrite", settings.rewrite_model),
            ("expand", settings.expand_model),
            ("skills", settings.skills_model),
        )
        if v
    }
    gaps = config.credential_gaps(settings.model, overrides=overrides or None)
    if gaps:
        raise HTTPException(status_code=400, detail="; ".join(gaps))
    with template_ops.LOCK:
        # Same reasoning as the credential check above: a resume where every entry is
        # excluded is a broken run, and catching it here means the job never reaches
        # the worker to fail several minutes and several LLM calls later.
        try:
            resume = data.load()
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        problems = include.validate(resume, settings.include)
        if problems:
            raise HTTPException(status_code=400, detail="; ".join(problems))
        job, position = get_queue().submit(
            body.jd_text.strip(), settings, metadata=body.metadata
        )
    return CreateJobResponse(job_id=job.job_id, queue_position=position)


@router.post("/api/jobs/estimate")
def estimate_job(body: CreateJobRequest) -> dict[str, Any]:
    """Estimated calls, tokens and cost of a run with these settings (`estimate.py`).

    No model call. Resolved under the run's own routing, like the job itself, and under
    `template_ops.LOCK` so the resume read is the active workspace's.
    """
    settings = body.settings
    if settings is None:
        settings = JobSettings.model_validate(workspace.load_settings()["defaults"])
    profile, overrides, effort = jobs_mod.model_routing(settings)
    with template_ops.LOCK:
        try:
            resume = data.load()
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        with config.pinned(profile, overrides=overrides, effort=effort):
            return estimate.estimate_run(
                body.jd_text,
                resume,
                extract_runs=config.extract_runs(settings.extract_runs),
                facets=not settings.no_facets,
                expand=not settings.no_expand,
                skills=not settings.no_skills,
                cover_letter=settings.cover_letter and not settings.no_cover_letter,
                vocabulary=settings.suggest_vocabulary,
            )
    except ValueError as exc:  # an unparseable model spec in the settings
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/resume-outline", response_model=ResumeOutlineResponse)
def get_resume_outline() -> ResumeOutlineResponse:
    """Master-resume shape the include tile needs — refetched every Tailor tab visit.

    Deliberately its own endpoint rather than fields on `/api/config`: `RunProvider`
    fetches config once and holds it for the profile's whole mount, while an edit made on
    the Master resume tab (adding a job, clearing coursework) must show up here the next
    time the Tailor tab is visited.
    """
    try:
        resume = data.load()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # A malformed master_resume.json (failed Pydantic validation) is bad user
        # data, not a server fault — 400, matching `create_job`'s identical catch on
        # the identical `data.load()` call. 500 is precisely where the editor most
        # needs the real error surfaced, not hidden behind a generic failure.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    contact = resume.contact
    field_values = {
        "location": contact.location,
        "email": contact.email,
        "phone": contact.phone,
        "linkedin": contact.linkedin,
        "github": contact.github,
    }
    available_contact_fields = [k for k, v in field_values.items() if v.strip()]

    layout = active_layout()
    has_coursework = any(edu.coursework for edu in resume.education)
    has_gpa = any(edu.gpa.strip() for edu in resume.education)
    gpa_currently_shown = any(edu.show_gpa and edu.gpa.strip() for edu in resume.education)

    return ResumeOutlineResponse(
        available_contact_fields=available_contact_fields,
        default_contact_order=list(layout.get("contact_field_order") or []),
        has_gpa=has_gpa,
        gpa_currently_shown=gpa_currently_shown,
        has_coursework=has_coursework,
        experience=[
            ResumeOutlineEntryOut(
                id=e.id, label=f"{e.company} — {e.title}", bullets=len(e.bullets)
            )
            for e in resume.experience
        ],
        projects=[
            ResumeOutlineEntryOut(id=p.id, label=p.name, bullets=len(p.bullets))
            for p in resume.projects
        ],
        sections=[
            ResumeOutlineSectionOut(
                id=section.id,
                title=section.title,
                kind=section.kind,
                entries=(
                    [
                        ResumeOutlineEntryOut(
                            id=entry.id,
                            label=(
                                f"{entry.company} — {entry.title}"
                                if section.kind == "experience"
                                else entry.name
                            ),
                            bullets=len(entry.bullets),
                        )
                        for entry in section.entries
                    ]
                    if section.kind in ("experience", "project")
                    else []
                ),
            )
            # Every section, not just entry sections — education/skills/list sections are
            # orderable from the include tile too, even though they have no per-entry
            # excludes and so contribute an empty `entries` list here.
            for section in resume.sections
        ],
        sections_enabled=dict(layout.get("enabled") or {}),
        section_mode=str(layout.get("section_mode") or "fixed"),
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
        report=job.report,
        expansion=job.expansion,
        skills=job.skills,
        cover_letter=job.cover_letter,
        events=[_event_out(e) for e in job.events],
        created_at=job.created_at,
        title=title,
        metadata=job.metadata,
    )


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
        report=resolved.report,
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
            error=job.error,
            pages=job.report.pages if job.report else None,
            coverage_matched=job.report.coverage_matched if job.report else None,
            coverage_total=job.report.coverage_total if job.report else None,
            has_pdf=(out_dir / "tailored.pdf").exists(),
            has_docx=(out_dir / "tailored.docx").exists(),
        )

    runs = sorted(by_id.values(), key=lambda r: r.created_at, reverse=True)
    return runs[:_HISTORY_LIMIT]


@router.get("/api/jobs", response_model=RunHistoryResponse)
def list_jobs() -> RunHistoryResponse:
    """Newest-first recent runs for the active profile (disk + in-memory)."""
    return RunHistoryResponse(runs=_scan_run_history())


@router.post("/api/jobs/history/delete", response_model=DeleteRunHistoryResponse)
def delete_run_history(body: DeleteRunHistoryRequest) -> DeleteRunHistoryResponse:
    """Remove finished runs from disk-backed history.

    Queued and running jobs are rejected per id — use ``DELETE /api/jobs/{id}`` to
    cancel those instead.
    """
    deleted: list[str] = []
    errors: dict[str, str] = {}
    for job_id in body.job_ids:
        reason = get_queue().remove_from_history(job_id)
        if reason is None:
            deleted.append(job_id)
        else:
            errors[job_id] = reason
    return DeleteRunHistoryResponse(deleted=deleted, errors=errors)


@router.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    """Current state of one queued or finished run (live or disk-backed)."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    return _resolved_status_response(resolved)


@router.delete("/api/jobs/{job_id}", response_model=JobStatusResponse)
def cancel_job(job_id: str) -> JobStatusResponse:
    """Cancel a queued or running run.

    A queued job stops immediately. A running job only has its cancellation flag
    set — the worker notices at the next checkpoint between pipeline stages
    (`Job.check_cancelled`, threaded through `JobQueue._execute`), not mid-LLM-call,
    so the returned status may still read "running" for a moment; poll or watch the
    SSE stream for the eventual "cancelled" terminal state. 409s when the job is
    already terminal — nothing left to cancel.
    """
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if get_queue().cancel(job_id) is None:
        raise HTTPException(status_code=409, detail=f"Job {job_id} is already {job.status}.")
    return _job_status_response(job)


@router.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    """Server-sent events stream of stage progress for one job."""
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")

    async def generate():
        """Yield SSE frames as new events arrive, until the job finishes.

        A comment frame goes out on any silent stretch >20s so a reverse proxy that
        kills idle responses (e.g. Cloudflare's 100s cutoff) doesn't drop the stream
        mid-stage — `EventSource` ignores comment frames, so this needs no frontend
        change.
        """
        sent = 0
        last_frame = time.monotonic()
        while True:
            while sent < len(job.events):
                event = job.events[sent]
                sent += 1
                payload = _event_out(event).model_dump()
                yield f"data: {json.dumps(payload)}\n\n"
                last_frame = time.monotonic()

            if job.status in ("succeeded", "failed", "cancelled"):
                # Flush any final events that landed between the check and now.
                while sent < len(job.events):
                    event = job.events[sent]
                    sent += 1
                    payload = _event_out(event).model_dump()
                    yield f"data: {json.dumps(payload)}\n\n"
                yield f"event: done\ndata: {json.dumps({'status': job.status})}\n\n"
                return

            # Wait for the worker to signal a new event without busy-polling.
            job.event_notify.clear()
            # Re-check after clearing: an event may have landed between the len() check
            # and clear(), which would leave us waiting forever for a signal already past.
            if sent < len(job.events) or job.status in ("succeeded", "failed", "cancelled"):
                continue
            await asyncio.get_running_loop().run_in_executor(None, job.event_notify.wait, 1.0)
            if time.monotonic() - last_frame > 20:
                yield ": keepalive\n\n"
                last_frame = time.monotonic()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} was not produced.")
    return path


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


@router.get("/api/jobs/{job_id}/preview.pdf")
def preview_pdf(job_id: str) -> FileResponse:
    """Inline PDF for embedding. Must not use attachment disposition — that forces a
    download every time an iframe remounts (e.g. switching Tailor ↔ Master resume).
    """
    path = _job_artifact(job_id, ".pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=_export_download_name(job_id, suffix=".pdf"),
        content_disposition_type="inline",
    )


@router.get("/api/jobs/{job_id}/download.pdf")
def download_pdf(job_id: str) -> FileResponse:
    """Download the tailored PDF (attachment disposition for Save As / auto-download)."""
    path = _job_artifact(job_id, ".pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=_export_download_name(job_id, suffix=".pdf"),
        content_disposition_type="attachment",
    )


@router.get("/api/jobs/{job_id}/download.docx")
def download_docx(job_id: str) -> FileResponse:
    """Download the tailored `.docx`."""
    path = _job_artifact(job_id, ".docx")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=_export_download_name(job_id, suffix=".docx"),
    )


@router.get("/api/jobs/{job_id}/expansion.md")
def download_expansion(job_id: str) -> FileResponse:
    """Plain-text expanded experience descriptions for a single copy-all paste."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "expansion.md"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Experience expansion was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=_export_download_name(job_id, suffix=".expansion.md"),
    )


@router.get("/api/jobs/{job_id}/skills.md")
def download_skills(job_id: str) -> FileResponse:
    """Plain-text tailored skills list for a single copy-all paste."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "skills.md"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Skills selection was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=_export_download_name(job_id, suffix=".skills.md"),
    )


@router.get("/api/jobs/{job_id}/cover-letter.md")
def download_cover_letter_md(job_id: str) -> FileResponse:
    """Plain-text cover letter for a single copy-all paste."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "cover.md"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Cover letter was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=_export_download_name(job_id, suffix=".cover.md"),
    )


@router.get("/api/jobs/{job_id}/cover-letter.docx")
def download_cover_letter_docx(job_id: str) -> FileResponse:
    """Download the rendered cover-letter ``.docx``."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "cover.docx"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Cover letter was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=_export_download_name(job_id, suffix=" Cover Letter.docx"),
    )


@router.get("/api/jobs/{job_id}/cover-letter.pdf")
def download_cover_letter_pdf(job_id: str) -> FileResponse:
    """Download the rendered cover-letter PDF."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "cover.pdf"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Cover letter PDF was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=_export_download_name(job_id, suffix=" Cover Letter.pdf"),
        content_disposition_type="attachment",
    )


@router.get("/api/jobs/{job_id}/cover-letter/preview.pdf")
def preview_cover_letter_pdf(job_id: str) -> FileResponse:
    """Inline cover-letter PDF for embedding in the results card."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "cover.pdf"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Cover letter PDF was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=_export_download_name(job_id, suffix=" Cover Letter.pdf"),
        content_disposition_type="inline",
    )


@router.post("/api/jobs/{job_id}/cover-letter", response_model=CoverLetterOut)
def regenerate_job_cover_letter(
    job_id: str,
    body: CoverLetterRegenerateRequest,
) -> CoverLetterOut:
    """Re-draft and overwrite this job's cover letter using saved run inputs."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready to regenerate."
        )
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="Cannot regenerate while another tailoring run is in progress.",
        )
    try:
        out = regenerate_cover_letter(
            job_id,
            instruction=body.instruction,
            cover_angles=body.cover_angles,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if resolved.live is not None:
        resolved.live.cover_letter = out
    return out


@router.post("/api/verify-claim", response_model=VerifyClaimResponse)
def post_verify_claim(body: VerifyClaimRequest) -> VerifyClaimResponse:
    """Check free-text application prose against tailored or master-resume bullets.

    Pure and read-only — deliberately does not check ``busy()``, so an agent can
    verify draft answers while another job is running. When ``job_id`` is omitted,
    every master-resume bullet is used as the evidence set.
    """
    try:
        result = verify_claim(body.job_id, body.text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return VerifyClaimResponse(
        ok=result.ok,
        unsupported_terms=list(result.unsupported_terms),
        unsupported_numbers=list(result.unsupported_numbers),
    )
