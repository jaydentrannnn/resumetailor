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
the page again (`daily_rows._captured_jd`).

Batch capture (``capture-stubs``) saves LinkedIn/Indeed search-result cards as
``capture_stub`` rows with no description. Nothing here or in the daily funnel ever
fetches those boards: a stub is completed by an ordinary ``capture`` of the same job,
which the extension sends when the user opens it. Capturing an employer's ATS page
whose company and role match a board row that has no apply URL yet attaches that URL
to the board row (``merged``) instead of tracking the job twice.
"""

from __future__ import annotations

import hashlib
from typing import Literal, get_args
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from resume_tailor import config, workspace
from resume_tailor.apply.discovery import fetch_jd, identity
from resume_tailor.apply.forms import fill_buttons, submit_guard
from resume_tailor.apply.funnel import daily_rows, store, store_models, store_views
from resume_tailor.apply.funnel import operations as apply_operations
from resume_tailor.pipeline import jd_input
from resume_tailor.web import extension
from resume_tailor.web.routes.diagnostics import _version
from resume_tailor.web.schemas import (
    ApplyOperationRequest,
    ApplyOperationResponse,
    ApplySettings,
    JobSettings,
)

router = APIRouter()

_ATS_KINDS = frozenset(get_args(store_models.AtsKind))


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
    apply_kind: store_models.ApplyKind = "unknown"
    capture_stub: bool = False
    #: Where the job was captured (the board page for a LinkedIn/Indeed row).
    posting_url: str = ""
    #: The employer's application page, when known (differs from ``posting_url``).
    apply_url: str = ""
    #: The id for ``/applications/<id>`` links: the source id, which has no ``:``
    #: (a canonical key in a path breaks the SPA's static-file lookup on Windows).
    link_id: str = ""


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
    #: How the LinkedIn/Indeed page applies; ignored on other sites.
    apply_kind: store_models.ApplyKind = "unknown"


class CaptureResponse(BaseModel):
    #: ``completed``: a saved card got its description; ``merged``: this ATS page was
    #: attached to the board row already tracking the job.
    result: Literal["created", "exists", "completed", "merged"]
    application: TrackedApplication
    warnings: list[str] = Field(default_factory=list)


#: Cards per ``lookup-batch`` / ``capture-stubs`` request: one screen of search results.
MAX_BATCH = 50

_BOARDS = frozenset({"linkedin", "indeed"})


class LookupBatchRequest(BaseModel):
    urls: list[str] = Field(max_length=MAX_BATCH)


class LookupBatchItem(BaseModel):
    url: str
    exists: bool
    id: str = ""
    status: str = ""
    stub: bool = False


class LookupBatchResponse(BaseModel):
    results: list[LookupBatchItem]


class StubCard(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    job_id: str = Field(default="", max_length=100)
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=300)
    site: Literal["linkedin", "indeed"]


class CaptureStubsRequest(BaseModel):
    cards: list[StubCard] = Field(min_length=1, max_length=MAX_BATCH)


class StubResult(BaseModel):
    url: str
    result: Literal["created", "exists", "invalid"]
    application: TrackedApplication | None = None
    error: str = ""


class CaptureStubsResponse(BaseModel):
    results: list[StubResult]


class CapturedItem(BaseModel):
    """One row the extension captured, for the app's Applications page."""

    id: str
    #: See `TrackedApplication.link_id`.
    link_id: str
    company: str
    role: str
    location: str = ""
    status: str
    site: str
    posting_url: str
    capture_stub: bool
    apply_kind: store_models.ApplyKind
    discovered_at: str = ""


def _app_id(app: store_models.Application) -> str:
    return app.canonical_key or app.source_job_id


def _apply_url(app: store_models.Application) -> str:
    """The employer's apply page when it differs from where the job was captured."""
    final = app.final_url or ""
    return final if final and final != app.posting_url else ""


def _tracked(app: store_models.Application) -> TrackedApplication:
    return TrackedApplication(
        id=_app_id(app),
        company=app.company,
        role=app.role,
        status=app.status,
        ats=app.ats,
        archived=bool(app.archived_at),
        needs_you=store_views.review_summary(app) or "",
        screen_reasons=list(app.screen.reasons) if app.screen else [],
        apply_kind=app.apply_kind,
        capture_stub=app.capture_stub,
        posting_url=app.posting_url,
        apply_url=_apply_url(app),
        link_id=app.source_job_id,
    )


def _find(*urls: str) -> store_models.Application | None:
    for url in dict.fromkeys(u for u in urls if u):
        found = store.get(identity.canonical_key(url))
        if found is not None:
            return found
    return None


def _board_of(key: str) -> str:
    """``linkedin``/``indeed`` for a board job key, else ''."""
    board = key.split(":", 1)[0]
    return board if board in _BOARDS and key.startswith(f"{board}:jobs:") else ""


def _board_url(board: str, job_id: str, host: str) -> str:
    """The one URL a board job is stored under, whatever page it was seen on."""
    if board == "linkedin":
        return f"https://www.linkedin.com/jobs/view/{job_id}/"
    return f"https://{host}/viewjob?jk={job_id}"


def _is_captured(app: store_models.Application) -> bool:
    return app.source == "extension" or any(ref.source == "extension" for ref in app.source_refs)


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


@router.get("/api/extension-captures", response_model=list[CapturedItem])
def list_captures(stubs_only: bool = False) -> list[CapturedItem]:
    """Rows the extension captured (not archived), newest first, for the app's own pages.

    ``stubs_only`` lists the "Needs description" cards: each links to its board page,
    where opening it lets the extension complete it.
    """
    rows = [
        app
        for app in store.load_all().values()
        if _is_captured(app) and not app.archived_at and (app.capture_stub or not stubs_only)
    ]
    rows.sort(key=lambda app: app.discovered_at, reverse=True)
    return [
        CapturedItem(
            id=_app_id(app),
            link_id=app.source_job_id,
            company=app.company,
            role=app.role,
            location=app.location,
            status=app.status,
            site=_board_of(app.canonical_key) or app.ats,
            posting_url=app.posting_url,
            capture_stub=app.capture_stub,
            apply_kind=app.apply_kind,
            discovered_at=app.discovered_at,
        )
        for app in rows
    ]


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
        if app.status in store_models.REVIEW_STATUSES and not app.archived_at
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
        assist_only=ats in fill_buttons.ASSIST_ONLY_ATS,
        application=_tracked(app) if app is not None else None,
    )


def _source_job_id(key: str) -> str:
    return "ext-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _clean_description(jd_text: str) -> jd_input.JdText:
    try:
        return jd_input.from_text(jd_text, "extension")
    except jd_input.JdInputError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{exc} Select the job description on the page and use "
                "“Send selection to ResumeTailor”."
            ),
        ) from exc


def _settings_or_none() -> ApplySettings | None:
    try:
        return _apply_settings()
    except Exception:  # noqa: BLE001 - a capture must never fail on broken settings
        return None


def _screen(app: store_models.Application, text: str, settings: ApplySettings | None) -> None:
    """The no-LLM prefilter every capture runs, exactly as the daily funnel does."""
    if settings is None:
        return
    screen = daily_rows.prefilter_screen(text, app.role, settings)
    app.eligibility_flags = list(screen.flags)
    if not screen.passed:
        app.screen = screen
        store.set_status(app, "screened_out", note="prefilter: " + "; ".join(screen.reasons))


def _attach_apply_url(app: store_models.Application, target: str, now: str) -> None:
    """Point a board row at the employer's application page (its key is unchanged).

    The ATS page's own key is added as a source ref, so a later lookup or capture of
    that page finds this row (`store._locate` matches source ids).
    """
    app.final_url = target
    app.ats = fetch_jd.detect_ats(target)
    app.apply_kind = "external"
    store.add_source_ref(
        app,
        store_models.SourceRef(
            source="extension",
            source_job_id=identity.canonical_key(target),
            url=target,
            first_seen=now,
        ),
    )


def _describe(
    app: store_models.Application,
    body: CaptureRequest,
    text: str,
    settings: ApplySettings | None,
    *,
    note: str,
) -> None:
    """Give a saved card its description: it becomes an ordinary ``jd_fetched`` row."""
    app.capture_stub = False
    app.company = body.company.strip() or app.company
    app.role = body.role.strip() or app.role
    app.location = body.location.strip() or app.location
    app.group_key = identity.group_key(app.company, app.role)
    app.jd_text_path = daily_rows._save_jd(app.source_job_id, text)
    store.set_status(app, "jd_fetched", note=note)
    _screen(app, text, settings)


def _merge_candidate(group: str, index: store_models.Index) -> store_models.Application | None:
    """A LinkedIn/Indeed row for the same job that has no employer apply URL yet."""
    for key in index.by_group.get(group, []):
        other = index.by_canonical.get(key)
        if (
            other is not None
            and _board_of(other.canonical_key)
            and not _apply_url(other)
            and not other.archived_at
            and other.status not in store_models.TERMINAL_STATUSES
        ):
            return other
    return None


@router.post("/api/extension/capture", response_model=CaptureResponse)
def capture(body: CaptureRequest) -> CaptureResponse:
    page_url = (body.final_url or body.url).strip()
    target = identity.resolve_final_url(body.apply_url.strip()) if body.apply_url else ""
    target = target or page_url
    page_key = identity.canonical_key(page_url)
    board = _board_of(page_key)
    now = daily_rows._now_iso()

    existing = _find(target, page_url, body.url)
    if existing is not None and not existing.capture_stub:
        return CaptureResponse(result="exists", application=_tracked(existing))

    cleaned = _clean_description(body.jd_text)
    settings = _settings_or_none()

    if existing is not None:  # a saved search card, now opened: complete it
        def complete(app: store_models.Application) -> None:
            if target != page_url and not _apply_url(app):
                _attach_apply_url(app, target, now)
            elif board and body.apply_kind != "unknown":
                app.apply_kind = body.apply_kind
            _describe(app, body, cleaned.text, settings, note="description captured when the job was opened")

        done = store.update(_app_id(existing), complete)
        return CaptureResponse(
            result="completed", application=_tracked(done), warnings=list(cleaned.warnings)
        )

    ats: str = fetch_jd.detect_ats(target)
    if ats in {"other", "unknown"} and body.ats_guess.lower() in _ATS_KINDS:
        ats = body.ats_guess.lower()
    key = identity.canonical_key(target)
    source_job_id = _source_job_id(key)
    group = identity.group_key(body.company, body.role)
    index = store.build_index()

    # An employer's page for a job already tracked from LinkedIn/Indeed: clicking Apply
    # on the board and capturing the ATS tab links the two instead of tracking it twice.
    candidate = (
        _merge_candidate(group, index)
        if body.company and body.role and not _board_of(key) and ats != "handshake"
        else None
    )
    if candidate is not None:
        def merge(app: store_models.Application) -> None:
            _attach_apply_url(app, target, now)
            if app.capture_stub:
                _describe(app, body, cleaned.text, settings, note="description captured from the employer's page")

        merged = store.update(_app_id(candidate), merge)
        return CaptureResponse(
            result="merged",
            application=_tracked(merged),
            warnings=[f"Linked to {merged.company} · {merged.role}, already tracked from {candidate.ats.title()}."],
        )

    warnings = list(cleaned.warnings)
    for other_key in index.by_group.get(group, []) if body.company and body.role else []:
        other = index.by_canonical.get(other_key)
        if other is not None:
            warnings.append(f"You already track {other.company} · {other.role} ({other.status}).")
            break

    apply_kind: store_models.ApplyKind = "unknown"
    if board:
        apply_kind = "external" if target != page_url else body.apply_kind
    app = store_models.Application(
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
        apply_kind=apply_kind,
        source_refs=[
            store_models.SourceRef(
                source="extension", source_job_id=source_job_id, url=body.url, first_seen=now
            )
        ],
    )
    app.jd_text_path = daily_rows._save_jd(source_job_id, cleaned.text)
    store.set_status(app, "jd_fetched", note="captured by the browser extension")
    _screen(app, cleaned.text, settings)
    store.upsert(app)
    return CaptureResponse(result="created", application=_tracked(app), warnings=warnings)


def _index_find(index: store_models.Index, key: str) -> store_models.Application | None:
    """`store.get` against an index built once for a whole batch."""
    found = index.by_canonical.get(key)
    if found is not None:
        return found
    for (_source, source_job_id), ckey in index.by_source_ref.items():
        if source_job_id == key:
            return index.by_canonical.get(ckey)
    return None


@router.post("/api/extension/lookup-batch", response_model=LookupBatchResponse)
def lookup_batch(body: LookupBatchRequest) -> LookupBatchResponse:
    """In-queue status for each visible search-result card (read-only)."""
    index = store.build_index()
    results: list[LookupBatchItem] = []
    for url in body.urls:
        app = _index_find(index, identity.canonical_key(url[:4000]))
        if app is None:
            results.append(LookupBatchItem(url=url, exists=False))
        else:
            results.append(
                LookupBatchItem(
                    url=url, exists=True, id=_app_id(app), status=app.status, stub=app.capture_stub
                )
            )
    return LookupBatchResponse(results=results)


@router.post("/api/extension/capture-stubs", response_model=CaptureStubsResponse)
def capture_stubs(body: CaptureStubsRequest) -> CaptureStubsResponse:
    """Save search-result cards the user ticked, without their descriptions.

    Only LinkedIn/Indeed job URLs are accepted; each is stored under the job's own
    board URL so opening it from any search page later finds the same row.
    """
    now = daily_rows._now_iso()
    results: list[StubResult] = []
    for card in body.cards:
        key = identity.canonical_key(card.url)
        if _board_of(key) != card.site or (card.job_id and not key.endswith(f":{card.job_id.lower()}")):
            results.append(
                StubResult(url=card.url, result="invalid", error="Not a LinkedIn or Indeed job link.")
            )
            continue
        existing = store.get(key)
        if existing is not None:
            results.append(StubResult(url=card.url, result="exists", application=_tracked(existing)))
            continue
        job_id = key.rsplit(":", 1)[1]
        host = (urlparse(card.url).hostname or "www.indeed.com").lower()
        posting = _board_url(card.site, job_id, host)
        source_job_id = _source_job_id(key)
        app = store_models.Application(
            source="extension",
            source_job_id=source_job_id,
            company=card.company.strip() or "Unknown company",
            role=card.role.strip() or "Unknown role",
            location=card.location.strip(),
            posting_url=posting,
            final_url=posting,
            ats=card.site,
            discovered_at=now,
            canonical_key=key,
            group_key=identity.group_key(card.company, card.role),
            capture_stub=True,
            source_refs=[
                store_models.SourceRef(
                    source="extension", source_job_id=source_job_id, url=card.url, first_seen=now
                )
            ],
        )
        store.set_status(app, "discovered", note="saved from search results; opens to complete")
        store.upsert(app)
        results.append(StubResult(url=card.url, result="created", application=_tracked(app)))
    return CaptureStubsResponse(results=results)


def _start(application_id: str, action: Literal["prepare", "fill"]) -> ApplyOperationResponse:
    app = store.get(application_id)
    if app is None:
        raise HTTPException(status_code=404, detail="That page is not tracked yet.")
    if app.capture_stub:
        raise HTTPException(
            status_code=409,
            detail="This job has no description yet. Open it on the job board to capture it first.",
        )
    if action == "fill" and app.apply_kind == "easy_apply":
        board = "LinkedIn" if app.ats == "linkedin" else "Indeed"
        raise HTTPException(
            status_code=422,
            detail=f"This job uses {board}'s own apply form. Tailor it here, then apply on {board}.",
        )
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
