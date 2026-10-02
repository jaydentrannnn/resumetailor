"""Tailoring job routes: submit, status, events, artifacts, cover letters."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from resume_tailor import config, workspace
from resume_tailor.content import data
from resume_tailor.document import rerender
from resume_tailor.document.template_profile import active_layout
from resume_tailor.pipeline import estimate, include
from resume_tailor.web import job_routing, template_ops
from resume_tailor.web.job_followups import regenerate_cover_letter, verify_claim
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.routes.config import _event_out, _seed_include_gpa_if_missing
from resume_tailor.web.schemas import (
    CoverLetterOut,
    CoverLetterRegenerateRequest,
    CreateJobRequest,
    CreateJobResponse,
    DeleteRunHistoryRequest,
    DeleteRunHistoryResponse,
    JobSettings,
    JobStatusResponse,
    ResumeOutlineEntryOut,
    ResumeOutlineResponse,
    ResumeOutlineSectionOut,
    RunHistoryResponse,
    VerifyClaimRequest,
    VerifyClaimResponse,
)

from . import run_lookup

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
    profile, overrides, effort = job_routing.model_routing(settings)
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


@router.get("/api/jobs", response_model=RunHistoryResponse)
def list_jobs() -> RunHistoryResponse:
    """Newest-first recent runs for the active profile (disk + in-memory)."""
    return RunHistoryResponse(runs=run_lookup._scan_run_history())


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
    resolved = run_lookup._resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    return run_lookup._resolved_status_response(resolved)


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
    return run_lookup._job_status_response(job)


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


class RerenderRequest(BaseModel):
    """Edits relative to the AI version; an empty request restores it."""

    edits: dict[str, str] = Field(default_factory=dict, max_length=500)
    reverted: list[str] = Field(default_factory=list, max_length=500)
    removed: list[str] = Field(default_factory=list, max_length=500)
    #: Flagged bullets the student confirmed as accurate.
    confirmed: list[str] = Field(default_factory=list, max_length=500)


@router.get("/api/jobs/{job_id}/bullets")
def get_job_bullets(job_id: str) -> dict:
    """The run's bullets beside their master-resume source, for review and editing."""
    out_dir = run_lookup._finished_run_dir(job_id)
    try:
        return {"bullets": rerender.bullet_rows(out_dir)}
    except rerender.NoSnapshot as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/jobs/{job_id}/rerender")
def rerender_job(job_id: str, body: RerenderRequest) -> dict:
    """Render the edited bullets with the run's own template. No model call."""
    out_dir = run_lookup._finished_run_dir(job_id)
    # Held like a profile switch: the render reads config's per-profile fit constants.
    with template_ops.LOCK:
        try:
            result = rerender.rerender(
                out_dir,
                edits=body.edits,
                reverted=body.reverted,
                removed=body.removed,
                confirmed=body.confirmed,
            )
        except rerender.NoSnapshot as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except rerender.RerenderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result["status"] == "saved" and (out_dir / "packet.json").is_file():
        # The application kit records each file's hash; rebuild it so the next fill
        # uploads the edited resume.
        try:
            from resume_tailor.apply.funnel import packet as apply_packet

            apply_packet.write_packet(job_id)
        except Exception as exc:  # noqa: BLE001 - the edit is saved either way
            _log.warning("Packet rebuild after re-render failed for %s: %s", job_id, exc)
            result.setdefault("warnings", []).append(
                "The application kit could not be refreshed; rebuild it before filling."
            )
    return result


@router.get("/api/jobs/{job_id}/preview.pdf")
def preview_pdf(job_id: str) -> FileResponse:
    """Inline PDF for embedding. Must not use attachment disposition — that forces a
    download every time an iframe remounts (e.g. switching Tailor ↔ Master resume).
    """
    path = run_lookup._job_artifact(job_id, ".pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=run_lookup._export_download_name(job_id, suffix=".pdf"),
        content_disposition_type="inline",
    )


@router.get("/api/jobs/{job_id}/download.pdf")
def download_pdf(job_id: str) -> FileResponse:
    """Download the tailored PDF (attachment disposition for Save As / auto-download)."""
    path = run_lookup._job_artifact(job_id, ".pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=run_lookup._export_download_name(job_id, suffix=".pdf"),
        content_disposition_type="attachment",
    )


@router.get("/api/jobs/{job_id}/download.docx")
def download_docx(job_id: str) -> FileResponse:
    """Download the tailored `.docx`."""
    path = run_lookup._job_artifact(job_id, ".docx")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=run_lookup._export_download_name(job_id, suffix=".docx"),
    )


@router.get("/api/jobs/{job_id}/expansion.md")
def download_expansion(job_id: str) -> FileResponse:
    """Plain-text expanded experience descriptions for a single copy-all paste."""
    resolved = run_lookup._resolve_run(job_id)
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
        filename=run_lookup._export_download_name(job_id, suffix=".expansion.md"),
    )


@router.get("/api/jobs/{job_id}/skills.md")
def download_skills(job_id: str) -> FileResponse:
    """Plain-text tailored skills list for a single copy-all paste."""
    resolved = run_lookup._resolve_run(job_id)
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
        filename=run_lookup._export_download_name(job_id, suffix=".skills.md"),
    )


@router.get("/api/jobs/{job_id}/cover-letter.md")
def download_cover_letter_md(job_id: str) -> FileResponse:
    """Plain-text cover letter for a single copy-all paste."""
    resolved = run_lookup._resolve_run(job_id)
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
        filename=run_lookup._export_download_name(job_id, suffix=".cover.md"),
    )


@router.get("/api/jobs/{job_id}/cover-letter.docx")
def download_cover_letter_docx(job_id: str) -> FileResponse:
    """Download the rendered cover-letter ``.docx``."""
    resolved = run_lookup._resolve_run(job_id)
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
        filename=run_lookup._export_download_name(job_id, suffix=" Cover Letter.docx"),
    )


@router.get("/api/jobs/{job_id}/cover-letter.pdf")
def download_cover_letter_pdf(job_id: str) -> FileResponse:
    """Download the rendered cover-letter PDF."""
    resolved = run_lookup._resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "cover.pdf"
    run_lookup._rebuild_missing_pdf(path)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Cover letter PDF was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=run_lookup._export_download_name(job_id, suffix=" Cover Letter.pdf"),
        content_disposition_type="attachment",
    )


@router.get("/api/jobs/{job_id}/cover-letter/preview.pdf")
def preview_cover_letter_pdf(job_id: str) -> FileResponse:
    """Inline cover-letter PDF for embedding in the results card."""
    resolved = run_lookup._resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {resolved.status}, not ready for download."
        )
    path = resolved.out_dir / "cover.pdf"
    run_lookup._rebuild_missing_pdf(path)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Cover letter PDF was not produced for this job.",
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=run_lookup._export_download_name(job_id, suffix=" Cover Letter.pdf"),
        content_disposition_type="inline",
    )


@router.post("/api/jobs/{job_id}/cover-letter", response_model=CoverLetterOut)
def regenerate_job_cover_letter(
    job_id: str,
    body: CoverLetterRegenerateRequest,
) -> CoverLetterOut:
    """Re-draft and overwrite this job's cover letter using saved run inputs."""
    resolved = run_lookup._resolve_run(job_id)
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
