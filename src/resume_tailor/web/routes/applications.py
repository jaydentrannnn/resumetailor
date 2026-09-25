"""Applicant profile, packets, browser status and the apply funnel routes."""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from resume_tailor import (
    config,
    data,
    jd,
    workspace,
)
from resume_tailor.apply import browser as apply_browser
from resume_tailor.apply import daily as apply_daily
from resume_tailor.apply import operations as apply_operations
from resume_tailor.apply import packet as apply_packet
from resume_tailor.apply import profile as apply_profile
from resume_tailor.apply import store as apply_store
from resume_tailor.apply.answer import answer_question
from resume_tailor.data import MasterResume
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.routes.jobs import _resolve_run
from resume_tailor.web.schemas import (
    AnswerRequest,
    AnswerResponse,
    ApplicantProfileResponse,
    ApplicantProfileUpdateRequest,
    ApplicationDetailResponse,
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
    app: apply_store.Application,
    *,
    group_size: int = 1,
) -> ApplicationOut:
    """Convert a store row into the API response model with computed fields."""
    payload = app.model_dump()
    payload["sources"] = (
        [ref.source for ref in app.source_refs] if app.source_refs else [app.source]
    )
    payload["group_size"] = group_size
    from resume_tailor.apply import preparation

    apply_settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
    eligible = preparation.check(app, require_cover=apply_settings.cover_letter)
    payload["preparation_eligible"] = eligible.eligible
    payload["preparation_reasons"] = eligible.reasons
    payload["retry_kind"] = apply_daily.retry_kind(app)
    if app.status == "screened_out" and app.screen is not None:
        from resume_tailor.apply.screen import screen_label

        payload["screen_label"] = screen_label(app.screen.reasons)
    payload["review_summary"] = apply_store.review_summary(app)
    return ApplicationOut.model_validate(payload)


def _profile_gaps(profile: apply_profile.ApplicantProfile) -> list[ProfileGap]:
    """Blank profile fields forms ask for: the common ones, plus any a stored fill met.

    Resume-contact fallbacks and ``packet.DEFAULTS`` count as answered, exactly as the
    fill sees them. Most-often-met first, then Profile page order.
    """
    try:
        fields = apply_packet.build_fields(profile, data.load())
    except Exception:  # noqa: BLE001 - no resume yet: the profile alone decides
        fields = apply_packet.build_fields(
            profile, MasterResume.model_construct(contact=data.Contact.model_construct(name="", email="", phone="")),
        )
    seen: dict[str, int] = {}
    with suppress(Exception):
        for application in apply_store.load_all().values():
            fill = application.fill
            entries = (fill.get("missing_profile") if isinstance(fill, dict) else getattr(fill, "missing_profile", None)) or []
            for key in {str(entry.get("key") or "") for entry in entries if isinstance(entry, dict)}:
                seen[key] = seen.get(key, 0) + 1
    keys = list(apply_packet.profile_gaps(fields))
    keys += [key for key in seen if key in apply_packet.PROFILE_FIELDS and key not in keys and not fields.get(key)]
    order = list(apply_packet.PROFILE_FIELDS)
    keys.sort(key=lambda key: (-seen.get(key, 0), order.index(key)))
    gaps = []
    for key in keys:
        info = apply_packet.field_info(key)
        gaps.append(ProfileGap(
            key=key, label=info.label, section=info.section,
            path=apply_packet.profile_path(info.section), seen_in=seen.get(key, 0),
        ))
    return gaps


def _profile_response(profile: apply_profile.ApplicantProfile, *, seeded: bool, password_set: bool) -> ApplicantProfileResponse:
    return ApplicantProfileResponse(
        workspace_id=config.active_workspace_id(),
        profile=profile.model_copy(update={"workday_password": ""}),
        seeded=seeded,
        workday_password_set=password_set,
        gaps=_profile_gaps(profile),
        defaults=dict(apply_packet.DEFAULTS),
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
        saved = apply_profile.save_profile(profile)
    return _profile_response(saved, seeded=False, password_set=bool(saved.workday_password))


@router.get("/api/jobs/{job_id}/packet.json", response_model=None)
def get_job_packet(job_id: str) -> JSONResponse:
    """Return ``packet.json`` for a finished tailoring run."""
    path = config.OUTPUT_DIR / "jobs" / job_id / "packet.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No packet for job {job_id!r}.")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


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
    status: apply_store.ApplicationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    q: str = "",
    archive: Literal["active", "archived", "all"] = "all",
    sort: Literal["discovered_at", "archived_at", "company", "role", "location", "status", "coverage", "salary", "ats", "sources"] = "discovered_at",
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
    matched = apply_store.filtered_applications(q=q, archive=archive, applications=list(all_apps.values()))
    if group is not None:
        matched = [row for row in matched if (row.status in apply_store.REVIEW_STATUSES) == (group == "review")]
    counts: dict[str, int] = {}
    for item in matched:
        counts[item.status] = counts.get(item.status, 0) + 1
    rows = apply_store.list_applications(
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
    return ApplicationsListResponse(
        applications=outs,
        counts=counts,
        total=counts.get(status, 0) if status else sum(counts.values()),
    )


@router.post("/api/applications/archive", response_model=ArchiveApplicationsResponse)
def archive_applications(body: ArchiveApplicationsRequest) -> ArchiveApplicationsResponse:
    """Move records between the working and archived tables without changing status."""
    try:
        with apply_operations.registry_edit_idle():
            with template_ops.LOCK:
                if get_queue().busy():
                    raise HTTPException(status_code=409, detail="Tailoring is running; try again when it finishes")
                updated, errors = apply_store.set_archived(body.application_ids, body.archived)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ArchiveApplicationsResponse(updated=updated, errors=errors)


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
    previous = apply_store.FillResult.model_validate(app.fill) if app.fill else None
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
    progress = apply_daily.daily_status()
    return DailyStatusResponse(
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


@router.get("/api/applications/export.csv")
def export_applications_csv() -> StreamingResponse:
    """Download the application tracker as CSV."""
    csv_text = apply_store.export_csv()
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


@router.post("/api/applications/{source_job_id}/retry", response_model=ApplicationOut)
def retry_application_route(source_job_id: str) -> ApplicationOut:
    """Re-run the failed fetch, prefilter, or tailor step for one application."""
    # A fetch retry may drive the host browser, which an Apply operation or a daily
    # pass owns while it runs.
    if apply_operations.active() is not None or apply_daily.daily_busy():
        raise HTTPException(status_code=409, detail="Another Apply workflow is running; retry when it finishes.")
    try:
        app = apply_daily.retry_application(source_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _application_out(app)
