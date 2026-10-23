"""FastAPI application: JSON API for the SPA, plus static-file serving in production.

Run locally with:

    uvicorn resume_tailor.web.app:app --reload --app-dir src

Or from Docker Compose, which is the intended production path.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from resume_tailor import config, workspace
from resume_tailor.apply.funnel import daily as apply_daily
from resume_tailor.apply.funnel import daily_progress
from resume_tailor.apply.funnel import operations as apply_operations
from resume_tailor.apply.funnel import scheduler as apply_scheduler
from resume_tailor.content import data, data_transfer
from resume_tailor.infra import appearance, fake_llm, housekeeping, logs
from resume_tailor.web import (
    coverage_rescore,
    security,
    skill_refresh,
    template_migration,
    template_ops,
)
from resume_tailor.web import state as web_state
from resume_tailor.web.schemas import (
    JobSettings,
)

_log = logging.getLogger(__name__)
_scheduler_stop = threading.Event()


def _apply_busy() -> bool:
    """Another Apply workflow owns the browser; the scheduled run waits a tick."""
    return daily_progress.daily_busy() or apply_operations.active() is not None


def _start_daily_run() -> None:
    threading.Thread(
        target=apply_daily.run_daily,
        name="apply-daily-scheduled",
        daemon=True,
    ).start()


def _apply_scheduler_tick() -> None:
    raw = workspace.load_settings()
    settings = JobSettings.model_validate(raw["defaults"])
    apply_scheduler.tick(
        enabled=settings.apply.enabled,
        schedule_time=settings.apply.schedule_time,
        busy=_apply_busy,
        start=_start_daily_run,
    )


def _apply_scheduler_loop(stop: threading.Event) -> None:
    """Tick at startup (catch-up), then every `apply_scheduler.TICK_SECONDS`."""
    while True:
        try:
            _apply_scheduler_tick()
        except Exception:  # noqa: BLE001 - scheduler must never crash the process
            _log.exception("apply scheduler tick failed")
        if stop.wait(apply_scheduler.TICK_SECONDS):
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Resolve the active workspace (migrating the legacy layout on first boot)."""
    log_dir = config.log_dir_setting()
    if log_dir is not None:
        logs.setup_logging(log_dir)
    fake_llm.warn_if_enabled()
    token = security.session_token()
    if token is not None:
        security.write_token_file(token)
        # Printed, not logged: the log file must never hold the token.
        print(f"ResumeTailor: open http://127.0.0.1:<port>/?t={token} to sign in", flush=True)
    result = workspace.bootstrap()
    if result is not None:
        web_state.migrated_from_legacy = result.migrated
    # Before serving: no request may see a half-converted template. Never raises.
    template_migration.migrate_all()
    try:
        recovered = apply_daily.recover_orphaned_tailoring()
    except Exception:  # noqa: BLE001 — a bad store must not block startup
        _log.exception("could not recover orphaned tailoring rows")
    else:
        if recovered:
            _log.info("marked %d orphaned tailoring row(s) tailor_failed", recovered)
    try:
        # Before the row sync below, so Apply rows pick up the re-scored figures.
        rescored = coverage_rescore.run()
    except Exception:  # noqa: BLE001 — a display backfill must not block startup
        _log.exception("could not re-score saved runs' coverage")
    else:
        if rescored:
            _log.info("re-scored skill coverage for %d saved run(s)", rescored)
    try:
        apply_daily.sync_run_coverage()
    except Exception:  # noqa: BLE001 — a display backfill must not block startup
        _log.exception("could not sync application coverage from run reports")
    try:
        # Fill any bullet-skill inferences the cache lacks (a new model, an upgrade's key
        # migration) in the background, before a batch needs them. A no-op when warm.
        skill_refresh.schedule(data.load())
    except Exception:  # noqa: BLE001 — no resume yet, or unreadable: nothing to warm
        _log.info("skill cache warm-up skipped", exc_info=True)
    threading.Thread(target=housekeeping.run, name="housekeeping", daemon=True).start()
    _scheduler_stop.clear()
    scheduler = threading.Thread(
        target=_apply_scheduler_loop,
        args=(_scheduler_stop,),
        name="apply-scheduler",
        daemon=True,
    )
    scheduler.start()
    from resume_tailor.apply.funnel import answer_harvest  # noqa: PLC0415
    with contextlib.suppress(Exception):
        answer_harvest.restore()
    yield
    from resume_tailor.infra import vertex_oauth
    vertex_oauth.cancel_all()
    answer_harvest.stop()
    _scheduler_stop.set()
    scheduler.join(timeout=2.0)


app = FastAPI(title="ResumeTailor", version="0.1.0", lifespan=lifespan)

# No CORS middleware, deliberately: `frontend/vite.config.ts` proxies `/api` through
# the Vite dev server itself, so the browser's own request is always same-origin
# (to :5173) even in development — the :5173 -> :8000 hop is a plain server-to-server
# call that CORS (a browser-only restriction) never applies to. Production serves the
# built SPA from this same process on the same origin. An `allow_origins=["*"]`
# middleware here would do nothing for the app to work, and everything to let any page
# open in the user's browser read this app's data (master resume, real PII) or issue
# writes to it — this app has no authentication of its own.


class _RequestSizeLimitMiddleware:
    """Reject an oversized request by its declared `Content-Length`, before FastAPI's
    multipart/JSON parsing ever runs.

    Requests to ``POST /api/data/import`` may be up to ``data_transfer.MAX_IMPORT_BYTES``
    (2 GiB) plus a small multipart overhead allowance (1 MiB), allowing large profile
    imports to proceed without being read into memory. ``POST /api/desktop/save-as``
    takes up to its own ``MAX_SAVE_BYTES``. Every other path keeps the existing 10 MB
    limit (`template_ops._MAX_UPLOAD_BYTES`).

    A check inside a route handler (e.g. `len(raw) > _MAX_UPLOAD_BYTES` after
    `await file.read()`, as `template_uploads._validate_upload_bytes` does) is too late to
    bound memory use: `File(...)`/`Form(...)` dependency resolution fully consumes and
    parses the body *before* any handler code runs, so the oversized payload is already
    resident by the time a handler could reject it. This is a raw ASGI middleware
    (not `BaseHTTPMiddleware`, which buffers the body itself) so the reject path never
    touches the body at all — only the header.

    A request with no `Content-Length` (chunked transfer-encoding) isn't covered by
    this cheap check; acceptable for a local single-user tool.
    """

    #: Shared with `template_ops._MAX_UPLOAD_BYTES` (the per-file cap checked again,
    #: redundantly but harmlessly, once a request does pass this gate) rather than a
    #: separate constant, so the two limits can't quietly drift apart.
    _MAX_BYTES = template_ops._MAX_UPLOAD_BYTES
    _MULTIPART_OVERHEAD = 1024 * 1024  # 1 MiB allowance for multipart boundaries and headers

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                length = None
            if length is not None:
                path = str(scope.get("path", "")).rstrip("/")
                method = scope.get("method")
                if method == "POST" and path == "/api/data/import":
                    max_bytes = data_transfer.MAX_IMPORT_BYTES + self._MULTIPART_OVERHEAD
                elif method == "POST" and path == "/api/desktop/save-as":
                    # The route's own cap: Save as… sends the file's bytes back.
                    from resume_tailor.web.routes.desktop import MAX_SAVE_BYTES

                    max_bytes = MAX_SAVE_BYTES
                else:
                    max_bytes = self._MAX_BYTES
                if length > max_bytes:
                    response = JSONResponse(
                        {
                            "detail": (
                                f"Request body is {length} bytes; maximum is "
                                f"{max_bytes}."
                            )
                        },
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


class _NoStoreApiMiddleware:
    """``Cache-Control: no-store`` on API reads that don't choose their own caching.

    The SPA refetches state after every change (template switch, settings save). A
    browser or webview that heuristically cached a GET would show the old state until a
    hard refresh. Routes that set their own header (the ETag'd application list, the
    thumbnails, SSE) keep it.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "GET"
            or not str(scope.get("path", "")).startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        async def _send(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                if not any(name.lower() == b"cache-control" for name, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send)


app.add_middleware(_RequestSizeLimitMiddleware)
app.add_middleware(_NoStoreApiMiddleware)
# Added last, so it runs first: nothing, not even the size check, answers a foreign
# Host or a cross-site write (see `web/security.py`).
app.add_middleware(security.RequestGateMiddleware)


# Imported after `app` exists and its middleware is added, deliberately.
from resume_tailor.web.routes import (  # noqa: E402, I001
    after_send as _after_send_routes,
    answers as _answers_routes,
    applications as _applications_routes,
    automation as _automation_routes,
    company_research as _company_research_routes,
    config as _config_routes,
    cover_letter as _cover_letter_routes,
    desktop as _desktop_routes,
    diagnostics as _diagnostics_routes,
    discovery as _discovery_routes,
    extension as _extension_routes,
    jd as _jd_routes,
    jobs as _jobs_routes,
    libraries as _libraries_routes,
    mail_updates as _mail_updates_routes,
    onboarding as _onboarding_routes,
    outcomes as _outcomes_routes,
    pay as _pay_routes,
    reference as _reference_routes,
    resume as _resume_routes,
    search_presets as _search_presets_routes,
    secrets as _secrets_routes,
    setup as _setup_routes,
    system as _system_routes,
    template as _template_routes,
    template_edit as _template_edit_routes,
    update as _update_routes,
    vertex as _vertex_routes,
    workspaces as _workspaces_routes,
)

# Registration order is route-matching order: keep it the order these areas had in
# the single-file app (config, jobs, applications, resume, template, libraries, profiles).
# `after_send` precedes applications: its `/api/applications/follow-ups` is not an id.
for _router in (
    _config_routes, _jobs_routes, _after_send_routes, _applications_routes, _outcomes_routes,
    _resume_routes, _template_routes, _libraries_routes, _workspaces_routes, _diagnostics_routes,
    _secrets_routes, _setup_routes, _system_routes, _onboarding_routes,
    _jd_routes, _answers_routes, _automation_routes, _discovery_routes,
    _extension_routes, _update_routes, _reference_routes, _search_presets_routes,
    _cover_letter_routes, _template_edit_routes, _vertex_routes, _desktop_routes,
    _mail_updates_routes, _pay_routes, _company_research_routes,
):
    app.include_router(_router.router)


class _SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html on a 404.

    React Router uses real URL paths (BrowserRouter), so a hard refresh on
    /editor or /template is a direct GET for a path that has no file on disk.
    Plain StaticFiles(html=True) only serves index.html for the directory
    root, so those requests 404 before React Router ever loads. Falling back
    to index.html hands the route to the client-side router instead.
    """

    async def get_response(self, path: str, scope):
        served = path
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            first_segment = path.split(os.sep, 1)[0]
            if exc.status_code != 404 or first_segment == "api":
                raise
            served = "index.html"  # a missing bundle name must not be cached as immutable
            response = await super().get_response(served, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = self._cache_control(served)
        # The desktop server may choose a new port each launch (a new storage origin).
        # Seed the saved preference before the app's theme script paints anything.
        if web_state.desktop and Path(getattr(response, "path", "")).name == "index.html":
            html = Path(response.path).read_text("utf-8")
            theme = json.dumps(appearance.load_theme())
            accent = json.dumps(appearance.load_accent())
            html = html.replace(
                "<head>",
                f"<head><script>window.__RT_DESKTOP_THEME__={theme};"
                f"window.__RT_DESKTOP_ACCENT__={accent};</script>",
                1,
            )
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        return response

    @staticmethod
    def _cache_control(path: str) -> str:
        """Hashed bundles never change; everything else (index.html above all) must be
        revalidated, or a webview heuristically reuses a stale page after an update."""
        normalised = path.replace(os.sep, "/")
        if normalised.startswith("assets/"):
            return "public, max-age=31536000, immutable"
        return "no-cache"


# Serve the built SPA when it exists (production / Docker). The Vite dev server handles
# this in development, so a missing frontend/dist is not an error here. The desktop
# bundle ships it beside the frozen code (`desktop_main` sets the variable).
_FRONTEND_DIST = (
    Path(os.environ["RESUME_TAILOR_FRONTEND_DIST"])
    if os.environ.get("RESUME_TAILOR_FRONTEND_DIST")
    else config.PROJECT_ROOT / "frontend" / "dist"
)
if _FRONTEND_DIST.is_dir():
    app.mount("/", _SPAStaticFiles(directory=str(_FRONTEND_DIST), html=True), name="spa")
