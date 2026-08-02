"""FastAPI application: JSON API for the SPA, plus static-file serving in production.

Run locally with:

    uvicorn resume_tailor.web.app:app --reload --app-dir src

Or from Docker Compose, which is the intended production path.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from resume_tailor import config, data, report
from resume_tailor.data import MasterResume
from resume_tailor.events import ProgressEvent
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import (
    ConfigResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobStatusResponse,
    ProgressEventOut,
    TemplateBuildResponse,
    TemplateInfoResponse,
    ValidateResponse,
)
from resume_tailor.web.template_ops import TemplateBuildError, TemplateValidationError

app = FastAPI(title="ResumeTailor", version="0.1.0")

# The Vite dev server runs on a different origin; production serves the SPA from this
# same process, so CORS is only needed in development. Allowing * is fine for a
# single-user local tool.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _event_out(event: ProgressEvent) -> ProgressEventOut:
    """Map an internal progress event onto the wire shape."""
    return ProgressEventOut(stage=event.stage, message=event.message, detail=event.detail)


@app.get("/api/config", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    """Defaults and vocabulary the UI needs before a run starts."""
    contact_name: str | None = None
    tags: list[str] = []
    try:
        resume = data.load()
        contact_name = resume.contact.name
        tags = list(resume.tag_vocabulary) or sorted(
            {t for b in resume.all_bullets() for t in b.tags}
        )
    except (FileNotFoundError, ValueError):
        # A missing or malformed master resume still lets the UI load; the editor and
        # the run page will surface the real error when the user tries to use them.
        pass

    return ConfigResponse(
        pages=config.DEFAULT_PAGE_TARGET,
        experience=config.MAX_EXPERIENCE_ENTRIES,
        projects=config.MAX_PROJECT_ENTRIES,
        model_profiles=sorted(config.MODEL_PROFILES),
        effort_options=["low", "medium", "high"],
        pdf_backend=config.PDF_BACKEND,
        calibration_source=config.CALIBRATION_SOURCE,
        chars_per_line=config.CHARS_PER_LINE,
        lines_per_page=config.LINES_PER_PAGE,
        tag_vocabulary=tags,
        contact_name=contact_name,
        fill_target=config.UNDERFLOW_THRESHOLD,
    )


@app.post("/api/jobs", response_model=CreateJobResponse)
def create_job(body: CreateJobRequest) -> CreateJobResponse:
    """Enqueue a tailoring run. Returns immediately with a job id."""
    if not body.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description is empty.")
    job, position = get_queue().submit(body.jd_text.strip(), body.settings)
    return CreateJobResponse(job_id=job.job_id, queue_position=position)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    """Current state of one queued or finished run."""
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    position = get_queue().queue_position(job_id) or None
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        queue_position=position if job.status == "queued" else None,
        error=job.error,
        report=job.report,
        expansion=job.expansion,
        events=[_event_out(e) for e in job.events],
    )


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    """Server-sent events stream of stage progress for one job."""
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")

    async def generate():
        """Yield SSE frames as new events arrive, until the job finishes."""
        sent = 0
        while True:
            while sent < len(job.events):
                event = job.events[sent]
                sent += 1
                payload = _event_out(event).model_dump()
                yield f"data: {json.dumps(payload)}\n\n"

            if job.status in ("succeeded", "failed"):
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
            if sent < len(job.events) or job.status in ("succeeded", "failed"):
                continue
            await asyncio.get_event_loop().run_in_executor(None, job.event_notify.wait, 1.0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _job_artifact(job_id: str, suffix: str) -> Path:
    """Resolve a finished job's deliverable, or raise 404."""
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if job.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {job.status}, not ready for download."
        )
    path = (job.out_dir or config.OUTPUT_DIR / "jobs" / job_id) / f"tailored{suffix}"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} was not produced.")
    return path


def _export_download_name(job_id: str, *, suffix: str) -> str:
    """User-facing download name from contact + JD title, with a safe fallback."""
    job = get_queue().get(job_id)
    title = (job.report.title if job and job.report else None) or "Resume"
    try:
        name = data.load().contact.name
    except (FileNotFoundError, ValueError):
        name = "Resume"
    return report.export_filename(name, title, suffix=suffix)


@app.get("/api/jobs/{job_id}/preview.pdf")
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


@app.get("/api/jobs/{job_id}/download.pdf")
def download_pdf(job_id: str) -> FileResponse:
    """Download the tailored PDF (attachment disposition for Save As / auto-download)."""
    path = _job_artifact(job_id, ".pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=_export_download_name(job_id, suffix=".pdf"),
        content_disposition_type="attachment",
    )


@app.get("/api/jobs/{job_id}/download.docx")
def download_docx(job_id: str) -> FileResponse:
    """Download the tailored `.docx`."""
    path = _job_artifact(job_id, ".docx")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=_export_download_name(job_id, suffix=".docx"),
    )


@app.get("/api/jobs/{job_id}/expansion.md")
def download_expansion(job_id: str) -> FileResponse:
    """Plain-text expanded experience descriptions for a single copy-all paste."""
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if job.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is {job.status}, not ready for download."
        )
    path = (job.out_dir or config.OUTPUT_DIR / "jobs" / job_id) / "expansion.md"
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


@app.get("/api/master-resume")
def get_master_resume() -> dict[str, Any]:
    """Return the current master resume as JSON for the editor."""
    try:
        resume = data.load()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return resume.model_dump(by_alias=True)


@app.put("/api/master-resume")
def put_master_resume(body: dict[str, Any]) -> ValidateResponse:
    """Validate and save a new master resume, keeping a timestamped backup of the old one."""
    try:
        resume = MasterResume.model_validate(body)
    except ValidationError as exc:
        return ValidateResponse(
            ok=False,
            errors=[f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()],
        )

    path = config.MASTER_RESUME_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_suffix(f".{stamp}.bak.json")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    # Round-trip through the model so tags are canonicalised and unknown keys stripped
    # before anything hits disk — same guarantees `data.load` enforces on the way in.
    payload = resume.model_dump(by_alias=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    bullets = resume.all_bullets()
    tags = sorted({t for b in bullets for t in b.tags})
    return ValidateResponse(
        ok=True,
        summary={
            "name": resume.contact.name,
            "experience": len(resume.experience),
            "projects": len(resume.projects),
            "bullets": len(bullets),
            "tags": len(tags),
        },
    )


@app.post("/api/master-resume/validate", response_model=ValidateResponse)
def validate_master_resume(body: dict[str, Any]) -> ValidateResponse:
    """Dry-run validation for the editor — does not write anything."""
    try:
        resume = MasterResume.model_validate(body)
    except ValidationError as exc:
        return ValidateResponse(
            ok=False,
            errors=[f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()],
        )

    bullets = resume.all_bullets()
    tags = sorted({t for b in bullets for t in b.tags})
    return ValidateResponse(
        ok=True,
        summary={
            "name": resume.contact.name,
            "experience": len(resume.experience),
            "projects": len(resume.projects),
            "bullets": len(bullets),
            "metrics": sum(1 for b in bullets if b.metric),
            "tags": len(tags),
        },
    )


@app.get("/api/template", response_model=TemplateInfoResponse)
def get_template() -> TemplateInfoResponse:
    """Current baseline and tagged template metadata for the Template tab."""
    return template_ops.info()


@app.get("/api/template/preview.pdf")
def template_preview_pdf() -> FileResponse:
    """Inline PDF of the tagged template filled with the full master resume."""
    try:
        path = template_ops.ensure_preview()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        # PDF conversion unavailable (no Word / LibreOffice).
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to render template preview: {exc}"
        ) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename="template-preview.pdf",
        content_disposition_type="inline",
    )


@app.post("/api/template", response_model=TemplateBuildResponse)
async def upload_template(file: UploadFile = File(...)) -> TemplateBuildResponse:
    """Replace the baseline export and regenerate the tagged template.

    Refuses while a tailoring job is queued or running so the fit loop never
    measures against a template that is mid-rebuild.
    """
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish before "
            "replacing the template.",
        )

    raw = await file.read()
    filename = file.filename or "upload.docx"
    try:
        return template_ops.install_baseline(raw, filename)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateBuildError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "log": exc.log},
        ) from exc


# Serve the built SPA when it exists (production / Docker). The Vite dev server handles
# this in development, so a missing frontend/dist is not an error here.
_FRONTEND_DIST = config.PROJECT_ROOT / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="spa")
