"""Applicant profile, packets, browser status and the apply funnel routes."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from resume_tailor import config, workspace
from resume_tailor.apply.answers import profile as apply_profile
from resume_tailor.apply.answers.answer import answer_question
from resume_tailor.apply.driver import browser as apply_browser
from resume_tailor.apply.funnel import (
    daily_progress,
    daily_retry,
    packet_fields,
    packet_profile_fields,
    store_models,
    store_views,
)
from resume_tailor.apply.funnel import operations as apply_operations
from resume_tailor.apply.funnel import packet as apply_packet
from resume_tailor.apply.funnel import scheduler as apply_scheduler
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.content import data
from resume_tailor.content.data import MasterResume
from resume_tailor.pipeline import jd
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.routes.jobs import _resolve_run
from resume_tailor.web.schemas import (
    AnswerRequest,
    AnswerResponse,
    ApplicantProfileResponse,
    ApplicantProfileUpdateRequest,
    ApplicationDetailResponse,
    ApplicationNotesRequest,
    ApplicationOut,
    ApplicationsListResponse,
    ApplicationStatusRequest,
    ApplyOperationControlRequest,
    ApplyOperationRequest,
    ApplyOperationResponse,
    ArchiveApplicationsRequest,
    ArchiveApplicationsResponse,
    BrowserStatusResponse,
    DailyStatusResponse,
    JobSettings,
    ProfileGap,
    ReviewCorrectionRequest,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def _application_out(
    app: store_models.Application,
    *,
    group_size: int = 1,
) -> ApplicationOut:
    """Convert a store row into the API response model with computed fields."""
    payload = app.model_dump()
    if isinstance(payload.get("fill"), dict) and payload["fill"].get("missing_profile"):
        payload["fill"]["missing_profile"] = packet_profile_fields.visible_missing_profile(
            payload["fill"]["missing_profile"]
        )
    payload["sources"] = (
        [ref.source for ref in app.source_refs] if app.source_refs else [app.source]
    )
    payload["group_size"] = group_size
    payload["posted_at"], payload["posted_known"] = store_models.posted_date(app)
    payload["status_at"] = apply_store.status_at(app)
    from resume_tailor.apply.funnel import preparation

    apply_settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
    eligible = preparation.check(app, require_cover=apply_settings.cover_letter)
    payload["preparation_eligible"] = eligible.eligible
    payload["preparation_reasons"] = eligible.reasons
    payload["retry_kind"] = daily_retry.retry_kind(app)
    if app.status == "screened_out" and app.screen is not None:
        from resume_tailor.apply.funnel.screen import screen_label

        payload["screen_label"] = screen_label(app.screen.reasons)
    payload["review_summary"] = store_views.review_summary(app)
    return ApplicationOut.model_validate(payload)


def _profile_gaps(profile: apply_profile.ApplicantProfile) -> list[ProfileGap]:
    """Blank profile fields forms ask for: the common ones, plus any a stored fill met.

    Resume-contact fallbacks and ``packet.DEFAULTS`` count as answered, exactly as the
    fill sees them. Most-often-met first, then Profile page order.
    """
    try:
        fields = packet_fields.build_fields(profile, data.load())
    except Exception:  # noqa: BLE001 - no resume yet: the profile alone decides
        fields = packet_fields.build_fields(
            profile, MasterResume.model_construct(contact=data.Contact.model_construct(name="", email="", phone="")),
        )
    seen: dict[str, int] = {}
    with suppress(Exception):
        for application in apply_store.load_all().values():
            fill = application.fill
            entries = (fill.get("missing_profile") if isinstance(fill, dict) else getattr(fill, "missing_profile", None)) or []
            for key in {
                str(entry.get("key") or "")
                for entry in packet_profile_fields.visible_missing_profile(entries)
                if isinstance(entry, dict)
            }:
                seen[key] = seen.get(key, 0) + 1
    keys = list(packet_profile_fields.profile_gaps(fields))
    keys += [
        key
        for key in seen
        if key in packet_profile_fields.PROFILE_FIELDS and key not in keys and not fields.get(key)
    ]
    order = list(packet_profile_fields.PROFILE_FIELDS)
    keys.sort(key=lambda key: (-seen.get(key, 0), order.index(key)))
    gaps = []
    for key in keys:
        info = packet_profile_fields.field_info(key)
        gaps.append(ProfileGap(
            key=key, label=info.label, section=info.section,
            path=packet_profile_fields.profile_path(info.section, key), seen_in=seen.get(key, 0),
        ))
    return gaps


def _profile_response(profile: apply_profile.ApplicantProfile, *, seeded: bool, password_set: bool) -> ApplicantProfileResponse:
    return ApplicantProfileResponse(
        workspace_id=config.active_workspace_id(),
        profile=profile.model_copy(update={"workday_password": ""}),
        seeded=seeded,
        workday_password_set=password_set,
        gaps=_profile_gaps(profile),
        defaults=dict(packet_profile_fields.DEFAULTS),
    )


@router.get("/api/applicant-profile", response_model=ApplicantProfileResponse)
def get_applicant_profile() -> ApplicantProfileResponse:
    """Return the active workspace's form-filling profile."""
    profile, seeded = apply_profile.load_profile()
    return _profile_response(profile, seeded=seeded, password_set=bool(profile.workday_password))


@router.put("/api/applicant-profile", response_model=ApplicantProfileResponse)
def put_applicant_profile(body: ApplicantProfileUpdateRequest) -> ApplicantProfileResponse:
    """Persist ``applicant_profile.json`` for the active workspace."""
    with template_ops.LOCK:
        current, _seeded = apply_profile.load_profile()
        profile = body.profile
        if not profile.workday_password and current.workday_password:
            profile = profile.model_copy(
                update={"workday_password": current.workday_password}
            )
        # Server-owned: only the upload route sets it, so a client can never point a
        # fill's file upload at an arbitrary path on this machine.
        profile = profile.model_copy(
            update={key: getattr(current, key) for key in _DOCUMENT_KEYS}
        )
        saved = apply_profile.save_profile(profile)
    return _profile_response(saved, seeded=False, password_set=bool(saved.workday_password))


DOCUMENT_MAX_BYTES = 10 * 1024 * 1024
#: Uploaded PDFs a fill attaches by purpose; each lives at ``files/<kind>.pdf`` and is
#: recorded in the profile's server-owned ``<kind>_path``.
_DOCUMENT_KEYS = ("transcript_path", "portfolio_path")


def _document_file(kind: str) -> Path:
    return config.APPLICANT_PROFILE_PATH.parent / "files" / f"{kind}.pdf"


async def _store_document(kind: str, file: UploadFile) -> ApplicantProfileResponse:
    raw = await file.read(DOCUMENT_MAX_BYTES + 1)
    if len(raw) > DOCUMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"The {kind} is over 10 MB.")
    if not raw.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail=f"Upload the {kind} as a PDF.")
    target = _document_file(kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{kind}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(raw)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    with template_ops.LOCK:
        current, _seeded = apply_profile.load_profile()
        saved = apply_profile.save_profile(
            current.model_copy(update={f"{kind}_path": str(target)})
        )
    return _profile_response(saved, seeded=False, password_set=bool(saved.workday_password))


def _forget_document(kind: str) -> ApplicantProfileResponse:
    _document_file(kind).unlink(missing_ok=True)
    with template_ops.LOCK:
        current, _seeded = apply_profile.load_profile()
        saved = apply_profile.save_profile(current.model_copy(update={f"{kind}_path": ""}))
    return _profile_response(saved, seeded=False, password_set=bool(saved.workday_password))


@router.post("/api/applicant-profile/transcript", response_model=ApplicantProfileResponse)
async def upload_transcript(file: UploadFile = File(...)) -> ApplicantProfileResponse:
    """Store the transcript PDF that fills attach to "Transcript" upload fields."""
    return await _store_document("transcript", file)


@router.delete("/api/applicant-profile/transcript", response_model=ApplicantProfileResponse)
def delete_transcript() -> ApplicantProfileResponse:
    """Forget the transcript; later fills leave transcript uploads for review."""
    return _forget_document("transcript")


@router.post("/api/applicant-profile/portfolio", response_model=ApplicantProfileResponse)
async def upload_portfolio(file: UploadFile = File(...)) -> ApplicantProfileResponse:
    """Store the portfolio / work-sample PDF fills attach to "Portfolio" upload fields."""
    return await _store_document("portfolio", file)


@router.delete("/api/applicant-profile/portfolio", response_model=ApplicantProfileResponse)
def delete_portfolio() -> ApplicantProfileResponse:
    """Forget the portfolio PDF; later fills leave portfolio uploads for review."""
    return _forget_document("portfolio")


@router.get("/api/jobs/{job_id}/packet.json", response_model=None)
def get_job_packet(job_id: str) -> JSONResponse:
    """Return ``packet.json`` for a finished tailoring run.

    A saved packet built from an older applicant profile or master resume is rebuilt
    first, so what the page (or the MCP server) shows matches what a fill would use.
    """
    path = config.OUTPUT_DIR / "jobs" / job_id / "packet.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No packet for job {job_id!r}.")
    content = json.loads(path.read_text(encoding="utf-8"))
    with suppress(Exception):  # a rebuild failure still serves the saved packet
        if content.get("inputs_digest") != apply_packet.current_inputs_digest():
            content = json.loads(apply_packet.write_packet(job_id).model_dump_json())
    return JSONResponse(content=content)


@router.post("/api/jobs/{job_id}/packet/rebuild", response_model=None)
def rebuild_job_packet(job_id: str) -> JSONResponse:
    """Rebuild and persist ``packet.json`` from on-disk run artifacts."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is {resolved.status}, not ready for packet rebuild.",
        )
    try:
        packet = apply_packet.write_packet(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(content=json.loads(packet.model_dump_json()))


@router.post("/api/jobs/{job_id}/answer", response_model=AnswerResponse)
def answer_job_question(job_id: str, body: AnswerRequest) -> AnswerResponse:
    """Draft a guarded free-text ATS answer using saved run artifacts."""
    resolved = _resolve_run(job_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}.")
    if resolved.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is {resolved.status}, not ready for answers.",
        )

    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    bullets_path = out_dir / "bullets.json"
    if not bullets_path.is_file():
        raise HTTPException(status_code=404, detail="This job has no saved tailored bullets.")
    requirements_path = out_dir / "requirements.json"
    if not requirements_path.is_file():
        raise HTTPException(status_code=404, detail="This job has no saved requirements.")
    jd_path = out_dir / "jd.txt"
    if not jd_path.is_file():
        raise HTTPException(status_code=404, detail="This job has no saved job description.")

    bullets = json.loads(bullets_path.read_text(encoding="utf-8"))
    requirements = jd.JobRequirements.model_validate_json(
        requirements_path.read_text(encoding="utf-8")
    )
    jd_text = jd_path.read_text(encoding="utf-8")
    resume = data.load()
    profile, _seeded = apply_profile.load_profile()

    backends_path = out_dir / "backends.json"
    if backends_path.is_file():
        backend_specs = json.loads(backends_path.read_text(encoding="utf-8"))
        with config.pinned_specs(backend_specs, effort=None):
            result = answer_question(
                body.question,
                resume=resume,
                bullets=bullets,
                requirements=requirements,
                profile=profile,
                max_chars=body.max_chars,
                jd_text=jd_text,
            )
    else:
        result = answer_question(
            body.question,
            resume=resume,
            bullets=bullets,
            requirements=requirements,
            profile=profile,
            max_chars=body.max_chars,
            jd_text=jd_text,
        )

    return AnswerResponse(
        answer=result.answer,
        offenders=list(result.offenders),
        warnings=list(result.warnings),
        source=result.source,
        model=result.model,
    )


@router.get("/api/browser/status", response_model=BrowserStatusResponse)
def get_browser_status() -> BrowserStatusResponse:
    """Probe host browser CDP reachability for JD fetch and form fill."""
    status = apply_browser.browser_status()
    return BrowserStatusResponse(
        reachable=status.reachable,
        browser=status.browser,
        user_agent=status.user_agent,
        error=status.error,
        cdp_url=status.cdp_url,
    )


@router.get("/api/applications/open-tabs")
def get_open_application_tabs() -> dict[str, Any]:
    """List the browser's open tab ids so the UI offers Continue only for live tabs.

    Read-only and lock-free (one CDP HTTP call); ``reachable: false`` means the
    tab state is unknown, not that every tab is closed.
    """
    ids = apply_browser.open_target_ids()
    return {"reachable": ids is not None, "target_ids": sorted(ids or ())}


@router.get("/api/applications", response_model=ApplicationsListResponse)
def list_applications(
    request: Request,
    status: store_models.ApplicationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    q: str = "",
    archive: Literal["active", "archived", "all"] = "all",
    sort: Literal["posted_at", "status_at", "discovered_at", "archived_at", "company", "role", "location", "status", "coverage", "salary", "ats", "sources"] = "discovered_at",
    direction: Literal["asc", "desc"] = "desc",
    group: Literal["review", "working"] | None = None,
) -> ApplicationsListResponse:
    """Search, sort, and page applications within one archive scope.

    ``group`` splits the working list into the rows waiting on the applicant
    (``review``) and everything else (``working``); counts cover the chosen group.
    """
    q = q.strip()
    if len(q) > 200:
        raise HTTPException(status_code=422, detail="Search must be at most 200 characters")
    all_apps = apply_store.load_all()
    matched = store_views.filtered_applications(
        q=q, archive=archive, applications=list(all_apps.values())
    )
    if group is not None:
        matched = [
            row
            for row in matched
            if (row.status in store_models.REVIEW_STATUSES) == (group == "review")
        ]
    counts: dict[str, int] = {}
    for item in matched:
        counts[item.status] = counts.get(item.status, 0) + 1
    rows = store_views.list_applications(
        status=status,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
        q=q,
        archive=archive,
        sort=sort,
        direction=direction,
        applications=matched,
    )
    index = apply_store.build_index(all_apps)
    outs: list[ApplicationOut] = []
    for row in rows:
        gkey = row.group_key
        group_size = len(index.by_group.get(gkey, [])) if gkey else 1
        outs.append(_application_out(row, group_size=max(1, group_size)))
    body = ApplicationsListResponse(
        applications=outs,
        counts=counts,
        total=counts.get(status, 0) if status else sum(counts.values()),
    ).model_dump_json().encode("utf-8")
    # The Apply page polls this every few seconds; an unchanged page answers 304 so the
    # client keeps its rows (and React skips the re-render). Hashing the body rather than
    # a store counter: rows also carry fields computed from job files and settings.
    etag = f'W/"{hashlib.sha1(body, usedforsecurity=False).hexdigest()}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.post("/api/applications/archive", response_model=ArchiveApplicationsResponse)
def archive_applications(body: ArchiveApplicationsRequest) -> ArchiveApplicationsResponse:
    """Move records between tables; restoring undoes submitted/skipped marks."""
    try:
        with apply_operations.registry_edit_idle():
            with template_ops.LOCK:
                if get_queue().busy():
                    raise HTTPException(status_code=409, detail="Tailoring is running; try again when it finishes")
                updated, errors = apply_store.set_archived(body.application_ids, body.archived)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ArchiveApplicationsResponse(updated=updated, errors=errors)


@router.post("/api/applications/{source_job_id}/undo-submitted", response_model=ApplicationOut)
def undo_submitted(source_job_id: str) -> ApplicationOut:
    """Correct a mistaken submitted/skipped mark on a restored application."""
    try:
        with apply_operations.registry_edit_idle():
            with template_ops.LOCK:
                if get_queue().busy():
                    raise HTTPException(status_code=409, detail="Tailoring is running; try again when it finishes")
                app = apply_store.get(source_job_id)
                if app is None:
                    raise HTTPException(status_code=404, detail="Unknown application")
                if app.archived_at:
                    raise HTTPException(status_code=409, detail="Restore it first")
                if not apply_store.undo_terminal(app, "Submitted mark undone by user"):
                    raise HTTPException(status_code=409, detail="Application is not submitted or skipped")
                return _application_out(apply_store.upsert(app))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _operation_out(operation: apply_operations.ApplyOperation) -> ApplyOperationResponse:
    return ApplyOperationResponse.model_validate(operation.model_dump())


@router.post("/api/applications/operations", response_model=ApplyOperationResponse, status_code=202)
def start_apply_operation(body: ApplyOperationRequest) -> ApplyOperationResponse:
    """Start an explicit Find, Prepare, or Fill operation."""
    try:
        return _operation_out(apply_operations.start(body))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/applications/operations", response_model=list[ApplyOperationResponse])
def list_apply_operations() -> list[ApplyOperationResponse]:
    """Return recent Apply operations, newest first."""
    return [_operation_out(operation) for operation in apply_operations.list_recent()]


@router.get("/api/applications/operations/{operation_id}", response_model=ApplyOperationResponse)
def get_apply_operation(operation_id: str) -> ApplyOperationResponse:
    operation = apply_operations.get(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Unknown Apply operation")
    return _operation_out(operation)


@router.post(
    "/api/applications/operations/{operation_id}/control",
    response_model=ApplyOperationResponse,
)
def control_apply_operation(
    operation_id: str,
    body: ApplyOperationControlRequest,
) -> ApplyOperationResponse:
    try:
        return _operation_out(apply_operations.control(operation_id, body.action))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown Apply operation") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/applications/{source_job_id}/review-tab")
def focus_application_review_tab(source_job_id: str) -> dict[str, str]:
    """Focus the exact browser tab retained for human review."""
    app = apply_store.get(source_job_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Unknown application")
    if app.archived_at:
        raise HTTPException(status_code=409, detail="Restore this application before using its browser tab")
    previous = store_models.FillResult.model_validate(app.fill) if app.fill else None
    if previous is None or not previous.browser_target_id:
        raise HTTPException(status_code=409, detail="No review tab was recorded for this application")
    try:
        url = apply_browser.focus_target(previous.browser_target_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"url": url}


@router.post(
    "/api/applications/{source_job_id}/review/refresh",
    response_model=ApplyOperationResponse, status_code=202,
)
def refresh_application_review(source_job_id: str) -> ApplyOperationResponse:
    """Inspect the existing tab under Apply worker ownership without filling it."""
    try:
        return _operation_out(apply_operations.start_review_action(source_job_id, action="inspect"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/applications/{source_job_id}/corrections",
    response_model=ApplyOperationResponse, status_code=202,
)
def correct_application_field(
    source_job_id: str, body: ReviewCorrectionRequest,
) -> ApplyOperationResponse:
    """Apply one explicit, stale-safe correction in the recorded tab."""
    try:
        return _operation_out(apply_operations.start_review_action(
            source_job_id, action="correct", correction=body.model_dump(),
        ))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


#: Declared before `/api/applications/{source_job_id}` — a literal path must be
#: registered ahead of the parameterised one or Starlette matches "daily-status"
#: as an application id and 404s.
@router.get("/api/applications/daily-status", response_model=DailyStatusResponse)
def get_daily_status() -> DailyStatusResponse:
    """Return live progress for the in-flight (or last finished) daily pass."""
    progress = daily_progress.daily_status()
    try:
        apply_settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
        scheduler = apply_scheduler.status(
            enabled=apply_settings.enabled, schedule_time=apply_settings.schedule_time
        )
    except Exception:  # noqa: BLE001 - progress must still render with bad settings
        scheduler = None
    return DailyStatusResponse(
        scheduler=scheduler,
        running=progress.running,
        phase=progress.phase,
        source_id=progress.source_id,
        current=progress.current,
        processed=progress.processed,
        total=progress.total,
        dry_run=progress.dry_run,
        fetch_only=progress.fetch_only,
        started_at=progress.started_at,
        finished_at=progress.finished_at,
        date=progress.date,
        summary=progress.summary.model_dump() if progress.summary else None,
    )


@router.post("/api/applications/daily-run", response_model=DailyStatusResponse, status_code=202)
def run_daily_now() -> DailyStatusResponse:
    """Start the nightly discover/screen/tailor pass now (Apply settings → Run now)."""
    from resume_tailor.web import app as web_app  # the scheduler's own busy/start pair

    apply_settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
    started = apply_scheduler.run_now(
        schedule_time=apply_settings.schedule_time,
        busy=web_app._apply_busy,
        start=web_app._start_daily_run,
    )
    if not started:
        raise HTTPException(
            status_code=409, detail="Another Apply task is running. Try again when it finishes."
        )
    return get_daily_status()


@router.get("/api/applications/export.csv")
def export_applications_csv() -> StreamingResponse:
    """Download the application tracker as CSV."""
    csv_text = store_views.export_csv()
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="applications.csv"'},
    )


@router.get("/api/applications/{source_job_id}", response_model=ApplicationDetailResponse)
def get_application(source_job_id: str) -> ApplicationDetailResponse:
    """Return one application plus packet and JD text when available."""
    app = apply_store.get(source_job_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"Unknown application {source_job_id!r}.")

    packet: dict[str, Any] | None = None
    if app.job_id:
        packet_path = config.OUTPUT_DIR / "jobs" / app.job_id / "packet.json"
        if packet_path.is_file():
            packet = json.loads(packet_path.read_text(encoding="utf-8"))

    jd_text: str | None = None
    if app.jd_text_path and Path(app.jd_text_path).is_file():
        jd_text = Path(app.jd_text_path).read_text(encoding="utf-8")

    return ApplicationDetailResponse(
        application=_application_out(app),
        packet=packet,
        jd_text=jd_text,
    )


@router.post("/api/applications/{source_job_id}/status", response_model=ApplicationOut)
def set_application_status(
    source_job_id: str,
    body: ApplicationStatusRequest,
) -> ApplicationOut:
    """Update one application's status and append a timeline entry."""
    app = apply_store.get(source_job_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"Unknown application {source_job_id!r}.")
    if app.archived_at:
        raise HTTPException(status_code=409, detail="Restore this application before changing its status")
    try:
        apply_store.set_status(app, body.status, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _application_out(apply_store.upsert(app))


@router.put("/api/applications/{source_job_id}/notes", response_model=ApplicationOut)
def set_application_notes(source_job_id: str, body: ApplicationNotesRequest) -> ApplicationOut:
    """Save the applicant's own notes; only that field changes (merge-on-write)."""
    try:
        app = apply_store.patch(source_job_id, notes=body.notes)
    except apply_store.StaleApplication as exc:
        detail = f"Unknown application {source_job_id!r}."
        raise HTTPException(status_code=404, detail=detail) from exc
    return _application_out(app)


@router.post("/api/applications/{source_job_id}/retry", response_model=ApplicationOut)
def retry_application_route(source_job_id: str) -> ApplicationOut:
    """Re-run the failed fetch, prefilter, or tailor step for one application."""
    # A fetch retry may drive the host browser, which an Apply operation or a daily
    # pass owns while it runs.
    if apply_operations.active() is not None or daily_progress.daily_busy():
        raise HTTPException(status_code=409, detail="Another Apply workflow is running; retry when it finishes.")
    try:
        app = daily_retry.retry_application(source_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _application_out(app)
