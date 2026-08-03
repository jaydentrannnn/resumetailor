"""FastAPI application: JSON API for the SPA, plus static-file serving in production.

Run locally with:

    uvicorn resume_tailor.web.app:app --reload --app-dir src

Or from Docker Compose, which is the intended production path.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from resume_tailor import config, data, report, workspace
from resume_tailor.data import MasterResume
from resume_tailor.events import ProgressEvent
from resume_tailor.template_profile import TemplateProfile
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import (
    ConfigResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobSettings,
    JobStatusResponse,
    ProgressEventOut,
    SettingsResponse,
    SettingsUpdateRequest,
    TemplateAnalyzeResponse,
    TemplateBuildResponse,
    TemplateInfoResponse,
    TemplateLibraryRenameRequest,
    TemplateLibraryResponse,
    ValidateResponse,
    WorkspaceActivateResponse,
    WorkspaceCreateRequest,
    WorkspaceEntryOut,
    WorkspaceListResponse,
    WorkspaceRenameRequest,
)
from resume_tailor.web.template_ops import TemplateBuildError, TemplateValidationError

#: Set by `lifespan` on startup — True only the first time the legacy single-slot
#: layout was migrated into a "Default" workspace. Surfaced once by `GET /api/config`
#: so the UI can tell the user where their files went.
_migrated_from_legacy = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Resolve the active workspace (migrating the legacy layout on first boot)."""
    global _migrated_from_legacy
    result = workspace.bootstrap()
    if result is not None:
        _migrated_from_legacy = result.migrated
    yield


app = FastAPI(title="ResumeTailor", version="0.1.0", lifespan=lifespan)

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


def _config_response(*, consume_migrated: bool = True) -> ConfigResponse:
    """Build the `GET /api/config` payload; also reused by `activate_workspace`.

    `consume_migrated` clears `_migrated_from_legacy` after reporting it once — the
    banner is a one-time notice, not a persistent status field. Both call sites want
    that (an activation response is exactly as good a place to surface it as a config
    fetch would have been).
    """
    global _migrated_from_legacy
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

    active_id = config.active_workspace_id()
    active_label: str | None = None
    if active_id is not None:
        try:
            active_label = workspace.resolve(active_id).label
        except workspace.WorkspaceError:
            pass

    migrated = _migrated_from_legacy
    if consume_migrated:
        _migrated_from_legacy = False

    return ConfigResponse(
        pages=config.DEFAULT_PAGE_TARGET,
        experience=config.MAX_EXPERIENCE_ENTRIES,
        projects=config.MAX_PROJECT_ENTRIES,
        model_profiles=sorted(config.MODEL_PROFILES),
        ollama_model=config.OLLAMA_MODEL,
        ollama_base_url=config.OLLAMA_BASE_URL,
        ollama_profiles=sorted(
            p for p in config.MODEL_PROFILES if config.provider_stages(p, "ollama")
        ),
        gemini_model=config.GEMINI_MODEL,
        gemini_base_url=config.GEMINI_BASE_URL,
        gemini_profiles=sorted(
            p for p in config.MODEL_PROFILES if config.provider_stages(p, "gemini")
        ),
        # Direct env check, not `credential_gaps` — that takes a *profile* name, and an
        # origin word coinciding with one (as "gemini" does today) would be a coincidence
        # to depend on, not a guarantee.
        provider_keys={
            origin: any(os.environ.get(name) for name in config.api_key_env_for(origin))
            for origin in config.PROVIDERS_REQUIRING_KEY
        },
        effort_options=["low", "medium", "high"],
        pdf_backend=config.PDF_BACKEND,
        calibration_source=config.CALIBRATION_SOURCE,
        chars_per_line=config.CHARS_PER_LINE,
        lines_per_page=config.LINES_PER_PAGE,
        tag_vocabulary=tags,
        contact_name=contact_name,
        fill_target=config.UNDERFLOW_THRESHOLD,
        initial_bullet_share=config.INITIAL_BULLET_SHARE,
        active_workspace_id=active_id,
        active_workspace_label=active_label,
        migrated_from_legacy=migrated,
    )


def _workspace_entry_out(entry: workspace.WorkspaceEntry) -> WorkspaceEntryOut:
    """Map a core `WorkspaceEntry` dataclass onto its wire shape."""
    return WorkspaceEntryOut(
        id=entry.id,
        label=entry.label,
        created_at=entry.created_at,
        is_active=entry.is_active,
        has_master_resume=entry.has_master_resume,
        has_template=entry.has_template,
    )


@app.get("/api/config", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    """Defaults and vocabulary the UI needs before a run starts."""
    return _config_response()


@app.get("/api/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """The active profile's saved run defaults, seeded from `JobSettings()` if unset."""
    raw = workspace.load_settings()
    settings = JobSettings.model_validate(raw["defaults"])
    return SettingsResponse(
        workspace_id=config.active_workspace_id(),
        settings=settings,
        seeded=not raw["defaults"],
    )


@app.put("/api/settings", response_model=SettingsResponse)
def put_settings(body: SettingsUpdateRequest) -> SettingsResponse:
    """Persist new run defaults for the active profile."""
    workspace.save_settings(body.settings.model_dump())
    return SettingsResponse(
        workspace_id=config.active_workspace_id(),
        settings=body.settings,
        seeded=False,
    )


@app.post("/api/jobs", response_model=CreateJobResponse)
def create_job(body: CreateJobRequest) -> CreateJobResponse:
    """Enqueue a tailoring run. Returns immediately with a job id."""
    if not body.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description is empty.")
    settings = body.settings
    if settings is None:
        # No per-run override: fall back to the active profile's saved defaults so a
        # bare `POST /api/jobs {"jd_text": ...}` behaves like the UI.
        settings = JobSettings.model_validate(workspace.load_settings()["defaults"])
    # A missing key otherwise only surfaces as an async `job.status == "failed"` once the
    # worker gets to it. `credential_gaps` is pure (never touches `_ACTIVE`), so this check
    # is safe to run on the request thread even while another job is mid-run.
    overrides = {
        k: v
        for k, v in (
            ("rewrite", settings.rewrite_model),
            ("expand", settings.expand_model),
        )
        if v
    }
    gaps = config.credential_gaps(settings.model, overrides=overrides or None)
    if gaps:
        raise HTTPException(status_code=400, detail="; ".join(gaps))
    job, position = get_queue().submit(body.jd_text.strip(), settings)
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


@app.post("/api/template/analyze", response_model=TemplateAnalyzeResponse)
async def analyze_template(file: UploadFile = File(...)) -> TemplateAnalyzeResponse:
    """Preflight an uploaded baseline without writing under templates/."""
    raw = await file.read()
    filename = file.filename or "upload.docx"
    try:
        return template_ops.analyze_upload(raw, filename)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/template", response_model=TemplateBuildResponse)
async def upload_template(
    file: UploadFile = File(...),
    profile: str | None = Form(None),
    calibrate: str | None = Form(None),
    label: str | None = Form(None),
) -> TemplateBuildResponse:
    """Replace the baseline export and regenerate the tagged template.

    Optional multipart field `profile` is a JSON TemplateProfile. When omitted, the
    legacy hard-coded heading build runs (backward compatible).

    Optional multipart field `calibrate` (truthy: ``1``/``true``/``yes``) measures fit
    constants after a successful install and hot-reloads them in-process.

    Optional multipart field `label` names the library snapshot (default: filename stem).

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
    parsed_profile = None
    if profile:
        try:
            parsed_profile = TemplateProfile.model_validate_json(profile)
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid template profile: {exc}",
            ) from exc
    do_calibrate = (calibrate or "").strip().lower() in ("1", "true", "yes", "on")
    try:
        return template_ops.install_baseline(
            raw,
            filename,
            profile=parsed_profile,
            do_calibrate=do_calibrate,
            label=label,
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateBuildError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "log": exc.log},
        ) from exc


@app.get("/api/template/library", response_model=TemplateLibraryResponse)
def get_template_library() -> TemplateLibraryResponse:
    """List named template snapshots; seeds Default from live when the library is empty."""
    return template_ops.list_library()


@app.post("/api/template/library/{entry_id}/activate", response_model=TemplateBuildResponse)
async def activate_template_library_entry(
    entry_id: str,
    calibrate: str | None = None,
) -> TemplateBuildResponse:
    """Copy a library snapshot into the live template slot.

    Optional query `calibrate=true` measures fit constants after activation.
    Refuses while a tailoring job is busy.
    """
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish before "
            "switching templates.",
        )
    do_calibrate = (calibrate or "").strip().lower() in ("1", "true", "yes", "on")
    try:
        return template_ops.activate_library_entry(
            entry_id, do_calibrate=do_calibrate
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateBuildError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "log": exc.log},
        ) from exc


@app.patch("/api/template/library/{entry_id}", response_model=TemplateLibraryResponse)
def rename_template_library_entry(
    entry_id: str,
    body: TemplateLibraryRenameRequest,
) -> TemplateLibraryResponse:
    """Rename a saved template; labels must be unique (case-insensitive)."""
    try:
        return template_ops.rename_library_entry(entry_id, body.label)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/template/library/{entry_id}", response_model=TemplateLibraryResponse)
def delete_template_library_entry(entry_id: str) -> TemplateLibraryResponse:
    """Delete a non-active library entry."""
    try:
        return template_ops.delete_library_entry(entry_id)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _workspace_list_response() -> WorkspaceListResponse:
    """Current registry contents, mapped onto the wire shape."""
    entries = workspace.list_workspaces()
    active_id = next((e.id for e in entries if e.is_active), None)
    return WorkspaceListResponse(
        entries=[_workspace_entry_out(e) for e in entries], active_id=active_id
    )


def _busy_conflict(action: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"A tailoring job is in progress; wait for it to finish before {action}.",
    )


@app.get("/api/workspaces", response_model=WorkspaceListResponse)
def get_workspaces() -> WorkspaceListResponse:
    """Every registered profile and which one is active."""
    return _workspace_list_response()


@app.post("/api/workspaces", response_model=WorkspaceListResponse)
def create_workspace(body: WorkspaceCreateRequest) -> WorkspaceListResponse:
    """Register a new, empty profile — or, with `copy_from` set, a duplicate of it.

    Duplicating reads another profile's live template files, so (like every other
    template-tab mutation) it refuses while a tailoring job is busy.
    """
    if body.copy_from is not None:
        if get_queue().busy():
            raise _busy_conflict("duplicating a profile")
        with template_ops.LOCK:
            try:
                workspace.create(body.label, copy_from=body.copy_from)
            except workspace.WorkspaceError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        try:
            workspace.create(body.label)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _workspace_list_response()


@app.post("/api/workspaces/{workspace_id}/activate", response_model=WorkspaceActivateResponse)
def activate_workspace(workspace_id: str) -> WorkspaceActivateResponse:
    """Switch the active profile — master resume, template, calibration, and settings.

    Refuses while a tailoring job is busy: rebinding paths mid-job would silently mix
    one profile's content with another's paths instead of failing loudly.
    """
    if get_queue().busy():
        raise _busy_conflict("switching profiles")

    with template_ops.LOCK:
        try:
            workspace.activate(workspace_id)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        entries = workspace.list_workspaces()
        return WorkspaceActivateResponse(
            active_id=workspace_id,
            entries=[_workspace_entry_out(e) for e in entries],
            config=_config_response(),
            settings=JobSettings.model_validate(workspace.load_settings()["defaults"]),
            template=template_ops.info(),
        )


@app.patch("/api/workspaces/{workspace_id}", response_model=WorkspaceListResponse)
def rename_workspace(workspace_id: str, body: WorkspaceRenameRequest) -> WorkspaceListResponse:
    """Rename a profile. Its on-disk directory (named from the id) never moves."""
    try:
        workspace.rename(workspace_id, body.label)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _workspace_list_response()


@app.delete("/api/workspaces/{workspace_id}", response_model=WorkspaceListResponse)
def delete_workspace(workspace_id: str) -> WorkspaceListResponse:
    """Delete a profile. Refuses the active profile and the last remaining one."""
    if get_queue().busy():
        raise _busy_conflict("deleting a profile")
    with template_ops.LOCK:
        try:
            workspace.delete(workspace_id)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _workspace_list_response()


class _SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html on a 404.

    React Router uses real URL paths (BrowserRouter), so a hard refresh on
    /editor or /template is a direct GET for a path that has no file on disk.
    Plain StaticFiles(html=True) only serves index.html for the directory
    root, so those requests 404 before React Router ever loads. Falling back
    to index.html hands the route to the client-side router instead.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            first_segment = path.split(os.sep, 1)[0]
            if exc.status_code != 404 or first_segment == "api":
                raise
            return await super().get_response("index.html", scope)


# Serve the built SPA when it exists (production / Docker). The Vite dev server handles
# this in development, so a missing frontend/dist is not an error here.
_FRONTEND_DIST = config.PROJECT_ROOT / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", _SPAStaticFiles(directory=str(_FRONTEND_DIST), html=True), name="spa")
