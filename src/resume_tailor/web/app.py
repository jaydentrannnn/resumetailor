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

from resume_tailor import config, data, include, jd, libraries, propose, report, workspace
from resume_tailor.data import MasterResume
from resume_tailor.events import ProgressEvent
from resume_tailor.llm import LLMError
from resume_tailor.template_profile import active_layout, TemplateProfile
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import (
    ConfigResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobSettings,
    JobStatusResponse,
    LibraryAliasImpactOut,
    LibraryEffectiveOut,
    LibraryImpactRequest,
    LibraryImpactResponse,
    LibraryOverridesOut,
    LibraryPackOut,
    LibraryPackSummaryOut,
    LibraryPackWriteRequest,
    LibraryProposalOut,
    LibrarySelectionRequest,
    LibraryStateResponse,
    ProgressEventOut,
    ProposalApproveRequest,
    ProposalGenerateRequest,
    ProposalRejectRequest,
    ResumeOutlineEntryOut,
    ResumeOutlineResponse,
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
        experience_bullet_share=config.EXPERIENCE_BULLET_SHARE,
        max_bullets_per_entry=config.MAX_BULLETS_PER_ENTRY,
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


def _seed_include_gpa_if_missing(defaults: dict, settings: JobSettings) -> None:
    """A settings.json predating `include` has no saved opinion on GPA visibility.

    Pydantic fills the missing key with `IncludeOptions()`'s default (`gpa=True`)
    regardless of what the resume's `Education.show_gpa` actually says — for a profile
    that had deliberately hidden its GPA, that would silently reveal it on the very
    next run. Falling back to the resume's current `show_gpa` instead means upgrading
    to this feature changes nothing about a run's output until the user explicitly
    touches the new tile. A no-op once `include` has ever been saved once (`"include"
    in defaults`), since a value the user actually set must never be overridden.
    """
    if "include" in defaults:
        return
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError):
        return
    settings.include.gpa = any(edu.show_gpa and edu.gpa.strip() for edu in resume.education)


@app.get("/api/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """The active profile's saved run defaults, seeded from `JobSettings()` if unset."""
    raw = workspace.load_settings()
    settings = JobSettings.model_validate(raw["defaults"])
    _seed_include_gpa_if_missing(raw["defaults"], settings)
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
        )
        if v
    }
    gaps = config.credential_gaps(settings.model, overrides=overrides or None)
    if gaps:
        raise HTTPException(status_code=400, detail="; ".join(gaps))
    # Same reasoning as the credential check above: a resume where every entry is
    # excluded is a broken run, and catching it here means the job never reaches the
    # worker to fail several minutes and several LLM calls later.
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    problems = include.validate(resume, settings.include)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))
    job, position = get_queue().submit(body.jd_text.strip(), settings)
    return CreateJobResponse(job_id=job.job_id, queue_position=position)


@app.get("/api/resume-outline", response_model=ResumeOutlineResponse)
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
        sections_enabled=dict(layout.get("enabled") or {}),
    )


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


def _backup_master_resume(path: Path) -> None:
    """Copy `path` to a timestamped `.bak.json` sibling if it exists. Shared by
    `put_master_resume` (every save) and `approve_library_proposals` (only when
    approving would rewrite an existing tag) so both use the identical naming."""
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_suffix(f".{stamp}.bak.json")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


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
    _backup_master_resume(path)

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


def _library_pack_summary_out(pack: libraries.PackMeta) -> LibraryPackSummaryOut:
    return LibraryPackSummaryOut(
        id=pack.id,
        label=pack.label,
        description=pack.description,
        builtin=pack.builtin,
        tag_alias_count=pack.tag_alias_count,
        verb_count=pack.verb_count,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


def _library_proposal_out(p: libraries.LibraryProposal) -> LibraryProposalOut:
    return LibraryProposalOut(
        id=p.id,
        kind=p.kind,
        alias=p.alias,
        canonical=p.canonical,
        verb=p.verb,
        family=p.family,
        rationale=p.rationale,
        source=p.source,
        created_at=p.created_at,
    )


def _library_state_response(*, warning: str | None = None) -> LibraryStateResponse:
    """Current pack list, active profile's selection/overrides/proposals, and the
    composed table's summary — the one payload every library route returns, so the
    Settings tab can re-render from a mutation's response instead of issuing a second
    fetch."""
    state = libraries.read_workspace_state()
    effective = libraries.resolve_effective()
    return LibraryStateResponse(
        packs=[_library_pack_summary_out(p) for p in libraries.list_packs()],
        enabled_packs=state.enabled_packs,
        overrides=LibraryOverridesOut(**state.overrides.model_dump()),
        effective=LibraryEffectiveOut(
            tag_alias_count=len(effective.tag_aliases),
            verb_count=len(effective.verb_index),
            fingerprint=libraries.effective_fingerprint(effective),
        ),
        diagnostics=effective.diagnostics,
        proposals=[_library_proposal_out(p) for p in state.proposals],
        warning=warning,
    )


def _library_pack_out(pack: libraries.Pack) -> LibraryPackOut:
    return LibraryPackOut(
        id=pack.id,
        label=pack.label,
        description=pack.description,
        builtin=libraries.is_builtin_pack(pack.id),
        tag_aliases=pack.tag_aliases,
        verb_families=pack.verb_families,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


@app.get("/api/libraries", response_model=LibraryStateResponse)
def get_libraries() -> LibraryStateResponse:
    """Every pack (built-in and user-authored), the active profile's selection and
    overrides, and the composed table's summary."""
    return _library_state_response()


@app.get("/api/libraries/packs/{pack_id}", response_model=LibraryPackOut)
def get_library_pack(pack_id: str) -> LibraryPackOut:
    """One pack's full contents, for the pack editor."""
    try:
        pack = libraries.read_pack(pack_id)
    except libraries.LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _library_pack_out(pack)


def _library_write_conflict() -> HTTPException:
    return _busy_conflict("editing vocabulary packs")


@app.post("/api/libraries/packs", response_model=LibraryStateResponse)
def create_library_pack(body: LibraryPackWriteRequest) -> LibraryStateResponse:
    """Create a new user-authored pack. The id is derived from the label."""
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        existing_ids = {p.id for p in libraries.list_packs()}
        pack_id = libraries.new_pack_id(body.label, existing=existing_ids)
        pack = libraries.Pack(
            id=pack_id,
            label=body.label,
            description=body.description,
            tag_aliases=body.tag_aliases,
            verb_families=body.verb_families,
        )
        try:
            libraries.write_pack(pack, force=body.force)
        except libraries.LibraryValidationError as exc:
            raise HTTPException(
                status_code=400, detail={"message": str(exc), "errors": exc.errors}
            ) from exc
        except libraries.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.reload()
        return _library_state_response()


@app.put("/api/libraries/packs/{pack_id}", response_model=LibraryStateResponse)
def update_library_pack(pack_id: str, body: LibraryPackWriteRequest) -> LibraryStateResponse:
    """Update a user-authored pack's contents. Refuses a built-in id."""
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        pack = libraries.Pack(
            id=pack_id,
            label=body.label,
            description=body.description,
            tag_aliases=body.tag_aliases,
            verb_families=body.verb_families,
        )
        try:
            libraries.write_pack(pack, force=body.force)
        except libraries.LibraryValidationError as exc:
            raise HTTPException(
                status_code=400, detail={"message": str(exc), "errors": exc.errors}
            ) from exc
        except libraries.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.reload()
        return _library_state_response()


@app.delete("/api/libraries/packs/{pack_id}", response_model=LibraryStateResponse)
def delete_library_pack(pack_id: str) -> LibraryStateResponse:
    """Delete a user-authored pack. Refuses a built-in id.

    A profile that still has `pack_id` in its selection is left as-is —
    `libraries.resolve_effective` skips a missing pack with a diagnostic rather than
    erroring, so this cannot brick a profile that had it enabled.
    """
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        try:
            libraries.delete_pack(pack_id)
        except libraries.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.reload()
        return _library_state_response()


@app.put("/api/libraries/selection", response_model=LibraryStateResponse)
def put_library_selection(body: LibrarySelectionRequest) -> LibraryStateResponse:
    """Set the active profile's enabled packs and overrides."""
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        state = libraries.read_workspace_state()
        state.enabled_packs = body.enabled_packs
        state.overrides = libraries.LibraryOverrides(**body.overrides.model_dump())
        libraries.write_workspace_state(state)
        libraries.reload()
        return _library_state_response()


@app.post("/api/libraries/impact", response_model=LibraryImpactResponse)
def preview_library_impact(body: LibraryImpactRequest) -> LibraryImpactResponse:
    """What approving each of `tag_aliases` would rewrite in the current master
    resume, if anything — the confirmation step before a destructive alias write."""
    impacts = libraries.alias_impact(body.tag_aliases)
    return LibraryImpactResponse(
        impacts=[
            LibraryAliasImpactOut(
                alias=i.alias,
                canonical=i.canonical,
                affected_tags=i.affected_tags,
                affected_bullets=i.affected_bullets,
            )
            for i in impacts
        ]
    )


@app.post("/api/libraries/proposals", response_model=LibraryStateResponse)
def generate_library_proposals(body: ProposalGenerateRequest) -> LibraryStateResponse:
    """Draft new vocabulary-library proposals from the master resume's own near-miss
    keyword gaps (against an optional pasted JD) and unclassified opening verbs.

    Does not check `busy()` — generating a draft changes nothing effective, so a
    tailoring job may run alongside it. The LLM call itself runs unlocked (it can take
    a while and must not freeze the Template tab); the active workspace id is captured
    first and re-checked once `template_ops.LOCK` is held for the write, so a profile
    switch mid-call cannot land a draft in the wrong profile's queue.
    """
    workspace_id_at_start = config.active_workspace_id()
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})
    jd_text = body.jd_text.strip()

    unmatched: list[tuple[str, str]] = []
    if jd_text:
        try:
            requirements = jd.extract(jd_text, known_tags=known_tags)
            unmatched = propose.near_miss_alias_candidates(requirements, resume)
        except (LLMError, RuntimeError, ValueError) as exc:
            return _library_state_response(
                warning=f"Could not read the pasted job description: {exc}"
            )

    unknown_verbs = propose.unclassified_opening_verbs(resume)
    effective = libraries.resolve_effective()

    filtered: list[libraries.LibraryProposal] = []
    warning: str | None = None
    if unmatched or unknown_verbs:
        try:
            raw = propose.propose_vocabulary(
                known_tags=known_tags,
                unmatched=unmatched,
                unknown_verbs=unknown_verbs,
                families=effective.verb_families,
                jd_text=jd_text,
            )
        except (LLMError, RuntimeError) as exc:
            return _library_state_response(warning=f"Could not draft suggestions: {exc}")

        rejected = libraries.read_workspace_state().rejected
        filtered = propose.filter_proposals(
            raw,
            known_tags=known_tags,
            effective=effective,
            rejected=rejected,
            source="run" if jd_text else "manual",
        )
        if not filtered:
            warning = "The model did not find any new suggestions worth proposing."

    with template_ops.LOCK:
        if config.active_workspace_id() != workspace_id_at_start:
            raise _busy_conflict("saving suggestions")
        state = libraries.read_workspace_state()
        existing_ids = {p.id for p in state.proposals}
        new_ones = [p for p in filtered if p.id not in existing_ids]
        if new_ones:
            state.proposals = [*state.proposals, *new_ones]
            libraries.write_workspace_state(state)
            libraries.reload()
        return _library_state_response(warning=warning)


@app.post("/api/libraries/proposals/approve", response_model=LibraryStateResponse)
def approve_library_proposals(body: ProposalApproveRequest) -> LibraryStateResponse:
    """Fold selected pending proposals into an existing user-authored pack.

    `Bullet._normalise_tags` re-canonicalises every tag on every master-resume save, so
    approving an alias whose key is already used as a literal bullet tag would silently
    rewrite it the next time the resume is saved. Refuses with 409 and the exact impact
    list unless `acknowledge_rewrites` is set, and takes a timestamped backup of the
    current master resume before writing whenever it is.
    """
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        if libraries.is_builtin_pack(body.target_pack_id):
            raise HTTPException(
                status_code=400,
                detail=f"{body.target_pack_id!r} is a built-in pack and cannot be a target.",
            )

        state = libraries.read_workspace_state()
        wanted_ids = set(body.proposal_ids)
        selected = [p for p in state.proposals if p.id in wanted_ids]
        if not selected:
            raise HTTPException(status_code=404, detail="No matching pending proposals.")

        alias_map = {p.alias: p.canonical for p in selected if p.kind == "tag_alias" and p.alias}
        impacts = libraries.alias_impact(alias_map) if alias_map else []
        rewriting = [i for i in impacts if i.affected_tags]
        if rewriting and not body.acknowledge_rewrites:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        f"Approving this rewrites {len(rewriting)} tag(s) already used "
                        f"in your master resume the next time it is saved."
                    ),
                    "impact": [
                        {
                            "alias": i.alias,
                            "canonical": i.canonical,
                            "affected_tags": i.affected_tags,
                            "affected_bullets": i.affected_bullets,
                        }
                        for i in rewriting
                    ],
                },
            )

        try:
            pack = libraries.read_pack(body.target_pack_id)
        except libraries.LibraryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if rewriting:
            _backup_master_resume(config.MASTER_RESUME_PATH)

        tag_aliases = dict(pack.tag_aliases)
        verb_families = {family: list(verbs) for family, verbs in pack.verb_families.items()}
        for p in selected:
            if p.kind == "tag_alias" and p.alias and p.canonical:
                tag_aliases[p.alias] = p.canonical
            elif p.kind == "verb_family" and p.verb and p.family:
                verbs = verb_families.setdefault(p.family, [])
                if p.verb not in verbs:
                    verbs.append(p.verb)

        updated = pack.model_copy(
            update={"tag_aliases": tag_aliases, "verb_families": verb_families}
        )
        try:
            libraries.write_pack(updated)
        except libraries.LibraryValidationError as exc:
            raise HTTPException(
                status_code=400, detail={"message": str(exc), "errors": exc.errors}
            ) from exc
        except libraries.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        state.proposals = [p for p in state.proposals if p.id not in wanted_ids]
        libraries.write_workspace_state(state)
        libraries.reload()
        return _library_state_response()


@app.post("/api/libraries/proposals/reject", response_model=LibraryStateResponse)
def reject_library_proposals(body: ProposalRejectRequest) -> LibraryStateResponse:
    """Decline selected pending proposals so they are never re-proposed."""
    wanted_ids = set(body.proposal_ids)
    state = libraries.read_workspace_state()
    selected = [p for p in state.proposals if p.id in wanted_ids]
    if not selected:
        return _library_state_response()

    existing_rejected = {
        (r.kind, r.alias, r.canonical, r.verb, r.family) for r in state.rejected
    }
    for p in selected:
        key = (p.kind, p.alias, p.canonical, p.verb, p.family)
        if key not in existing_rejected:
            state.rejected.append(
                libraries.RejectedEntry(
                    kind=p.kind, alias=p.alias, canonical=p.canonical, verb=p.verb, family=p.family
                )
            )
            existing_rejected.add(key)
    state.proposals = [p for p in state.proposals if p.id not in wanted_ids]
    libraries.write_workspace_state(state)
    return _library_state_response()


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
        raw_defaults = workspace.load_settings()["defaults"]
        activated_settings = JobSettings.model_validate(raw_defaults)
        _seed_include_gpa_if_missing(raw_defaults, activated_settings)
        return WorkspaceActivateResponse(
            active_id=workspace_id,
            entries=[_workspace_entry_out(e) for e in entries],
            config=_config_response(),
            settings=activated_settings,
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
