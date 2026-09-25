"""The browser extension's API (plan P4-X: X1 pairing, X2 capture, X4 popup).

Two groups of routes:

- ``/api/extension/*`` is called by the extension itself. The request gate
  (`web/security.py`) lets these through only with a paired token, from an extension
  origin; ``pair/complete`` is the one open path.
- ``/api/extension-pairings*`` is called by the app's own Settings page (normal
  session auth) to show a pairing code, list the paired browsers and revoke one.

Capture turns the page the student is looking at into a tracked application: the
extension extracts the description text in the tab (so LinkedIn and Handshake, which
need a login to read, work), and Prepare later reuses that text instead of fetching
the page again (`daily._captured_jd`).
"""

from __future__ import annotations

import hashlib
from typing import Literal, get_args

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from resume_tailor import config, jd_input, workspace
from resume_tailor.apply import daily as apply_daily
from resume_tailor.apply import fetch_jd, fill, identity, store, submit_guard
from resume_tailor.apply import operations as apply_operations
from resume_tailor.web import extension
from resume_tailor.web.routes.diagnostics import _version
from resume_tailor.web.schemas import (
    ApplyOperationRequest,
    ApplyOperationResponse,
    ApplySettings,
    JobSettings,
)

router = APIRouter()

_ATS_KINDS = frozenset(get_args(store.AtsKind))


class PairCompleteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    label: str = Field(default="", max_length=80)


class PairCompleteResponse(BaseModel):
    id: str
    token: str


class PairingCode(BaseModel):
    code: str
    expires_in: int


class Pairing(BaseModel):
    id: str
    label: str
    created_at: str
    last_seen: str


class TrackedApplication(BaseModel):
    id: str
    company: str
    role: str
    status: str
    ats: str
    archived: bool = False
    needs_you: str = ""
    screen_reasons: list[str] = Field(default_factory=list)


class OperationSummary(BaseModel):
    action: str
    state: str
    message: str = ""
    current_label: str = ""
    processed: int = 0
    total: int = 0


class ExtensionStatus(BaseModel):
    app: str = "resumetailor"
    version: str
    workspace: str = ""
    paused: bool
    needs_you: int
    operation: OperationSummary | None = None


class LookupResponse(BaseModel):
    ats: str
    assist_only: bool
    application: TrackedApplication | None = None


class CaptureRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    final_url: str = Field(default="", max_length=4000)
    apply_url: str = Field(default="", max_length=4000)
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=300)
    jd_text: str = Field(max_length=200_000)
    ats_guess: str = Field(default="", max_length=40)


class CaptureResponse(BaseModel):
    result: Literal["created", "exists"]
    application: TrackedApplication
    warnings: list[str] = Field(default_factory=list)


def _tracked(app: store.Application) -> TrackedApplication:
    return TrackedApplication(
        id=app.canonical_key or app.source_job_id,
        company=app.company,
        role=app.role,
        status=app.status,
        ats=app.ats,
        archived=bool(app.archived_at),
        needs_you=store.review_summary(app) or "",
        screen_reasons=list(app.screen.reasons) if app.screen else [],
    )


def _find(*urls: str) -> store.Application | None:
    for url in dict.fromkeys(u for u in urls if u):
        found = store.get(identity.canonical_key(url))
        if found is not None:
            return found
    return None


def _apply_settings() -> ApplySettings:
    return JobSettings.model_validate(workspace.load_settings()["defaults"]).apply


# --- pairing (app side) -------------------------------------------------------------


@router.post("/api/extension-pairings/code", response_model=PairingCode)
def new_pairing_code() -> PairingCode:
    return PairingCode(**extension.start_pairing())


@router.get("/api/extension-pairings", response_model=list[Pairing])
def list_pairings() -> list[Pairing]:
    return [Pairing(**row) for row in extension.list_pairings()]


@router.delete("/api/extension-pairings/{pairing_id}", status_code=204)
def revoke_pairing(pairing_id: str) -> None:
    if not extension.revoke(pairing_id):
        raise HTTPException(status_code=404, detail="No such paired browser.")


# --- the extension's own routes -----------------------------------------------------


@router.post("/api/extension/pair/complete", response_model=PairCompleteResponse)
def complete_pairing(body: PairCompleteRequest) -> PairCompleteResponse:
    try:
        pairing_id, token = extension.complete_pairing(body.code, body.label)
    except extension.PairingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PairCompleteResponse(id=pairing_id, token=token)


@router.get("/api/extension/status", response_model=ExtensionStatus)
def extension_status() -> ExtensionStatus:
    needs_you = sum(
        1
        for app in store.load_all().values()
        if app.status in store.REVIEW_STATUSES and not app.archived_at
    )
    current = apply_operations.active()
    operation = (
        OperationSummary(**current.model_dump(include=set(OperationSummary.model_fields)))
        if current is not None
        else None
    )
    return ExtensionStatus(
        version=_version(),
        workspace=config.active_workspace_id() or "",
        paused=submit_guard.is_paused(),
        needs_you=needs_you,
        operation=operation,
    )


@router.get("/api/extension/lookup", response_model=LookupResponse)
def lookup(url: str = Query(min_length=1, max_length=4000)) -> LookupResponse:
    ats = fetch_jd.detect_ats(url)
    app = _find(url)
    return LookupResponse(
        ats=ats,
        assist_only=ats in fill.ASSIST_ONLY_ATS,
        application=_tracked(app) if app is not None else None,
    )


@router.post("/api/extension/capture", response_model=CaptureResponse)
def capture(body: CaptureRequest) -> CaptureResponse:
    page_url = (body.final_url or body.url).strip()
    target = identity.resolve_final_url(body.apply_url.strip()) if body.apply_url else ""
    target = target or page_url

    existing = _find(target, page_url, body.url)
    if existing is not None:
        return CaptureResponse(result="exists", application=_tracked(existing))

    try:
        cleaned = jd_input.from_text(body.jd_text, "extension")
    except jd_input.JdInputError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{exc} Select the job description on the page and use "
                "“Send selection to ResumeTailor”."
            ),
        ) from exc

    ats: str = fetch_jd.detect_ats(target)
    if ats in {"other", "unknown"} and body.ats_guess.lower() in _ATS_KINDS:
        ats = body.ats_guess.lower()
    key = identity.canonical_key(target)
    source_job_id = "ext-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    group = identity.group_key(body.company, body.role)
    now = apply_daily._now_iso()

    warnings = list(cleaned.warnings)
    index = store.build_index()
    for other_key in index.by_group.get(group, []) if body.company and body.role else []:
        other = index.by_canonical.get(other_key)
        if other is not None:
            warnings.append(f"You already track {other.company} · {other.role} ({other.status}).")
            break

    app = store.Application(
        source="extension",
        source_job_id=source_job_id,
        company=body.company.strip() or "Unknown company",
        role=body.role.strip() or "Unknown role",
        location=body.location.strip(),
        posting_url=target,
        final_url=target,
        ats=ats,
        discovered_at=now,
        canonical_key=key,
        group_key=group,
        source_refs=[
            store.SourceRef(
                source="extension", source_job_id=source_job_id, url=body.url, first_seen=now
            )
        ],
    )
    app.jd_text_path = apply_daily._save_jd(source_job_id, cleaned.text)
    store.set_status(app, "jd_fetched", note="captured by the browser extension")

    try:
        settings = _apply_settings()
    except Exception:  # noqa: BLE001 - a capture must never fail on broken settings
        settings = None
    if settings is not None:
        screen = apply_daily.prefilter_screen(cleaned.text, app.role, settings)
        app.eligibility_flags = list(screen.flags)
        if not screen.passed:
            app.screen = screen
            store.set_status(app, "screened_out", note="prefilter: " + "; ".join(screen.reasons))
    store.upsert(app)
    return CaptureResponse(result="created", application=_tracked(app), warnings=warnings)


def _start(application_id: str, action: Literal["prepare", "fill"]) -> ApplyOperationResponse:
    app = store.get(application_id)
    if app is None:
        raise HTTPException(status_code=404, detail="That page is not tracked yet.")
    settings = _apply_settings()
    request = ApplyOperationRequest(
        action=action,
        application_ids=[app.canonical_key or app.source_job_id],
        # The student is at the tab; the extension never starts an automatic submit.
        auto_submit=False,
        model_provider=settings.model_provider,
        model_name=settings.model_name,
    )
    try:
        operation = apply_operations.start(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApplyOperationResponse.model_validate(operation.model_dump())


@router.post(
    "/api/extension/applications/{application_id}/prepare",
    response_model=ApplyOperationResponse,
    status_code=202,
)
def prepare(application_id: str) -> ApplyOperationResponse:
    return _start(application_id, "prepare")


@router.post(
    "/api/extension/applications/{application_id}/fill",
    response_model=ApplyOperationResponse,
    status_code=202,
)
def fill_application(application_id: str) -> ApplyOperationResponse:
    return _start(application_id, "fill")
