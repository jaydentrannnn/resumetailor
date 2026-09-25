"""FastAPI application: JSON API for the SPA, plus static-file serving in production.

Run locally with:

    uvicorn resume_tailor.web.app:app --reload --app-dir src

Or from Docker Compose, which is the intended production path.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from resume_tailor import (
    config,
    logs,
    workspace,
)
from resume_tailor.apply import daily as apply_daily
from resume_tailor.apply import operations as apply_operations
from resume_tailor.apply import scheduler as apply_scheduler
from resume_tailor.web import security, template_ops
from resume_tailor.web import state as web_state
from resume_tailor.web.schemas import (
    JobSettings,
)

_log = logging.getLogger(__name__)
_scheduler_stop = threading.Event()


def _apply_busy() -> bool:
    """Another Apply workflow owns the browser; the scheduled run waits a tick."""
    return apply_daily.daily_busy() or apply_operations.active() is not None


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
    token = security.session_token()
    if token is not None:
        security.write_token_file(token)
        # Printed, not logged: the log file must never hold the token.
        print(f"ResumeTailor: open http://127.0.0.1:<port>/?t={token} to sign in", flush=True)
    result = workspace.bootstrap()
    if result is not None:
        web_state.migrated_from_legacy = result.migrated
    try:
        recovered = apply_daily.recover_orphaned_tailoring()
    except Exception:  # noqa: BLE001 — a bad store must not block startup
        _log.exception("could not recover orphaned tailoring rows")
    else:
        if recovered:
            _log.info("marked %d orphaned tailoring row(s) tailor_failed", recovered)
    _scheduler_stop.clear()
    scheduler = threading.Thread(
        target=_apply_scheduler_loop,
        args=(_scheduler_stop,),
        name="apply-scheduler",
        daemon=True,
    )
    scheduler.start()
    yield
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

    A check inside a route handler (e.g. `len(raw) > _MAX_UPLOAD_BYTES` after
    `await file.read()`, as `template_ops._validate_upload_bytes` does) is too late to
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
            if length is not None and length > self._MAX_BYTES:
                response = JSONResponse(
                    {
                        "detail": (
                            f"Request body is {length} bytes; maximum is "
                            f"{self._MAX_BYTES}."
                        )
                    },
                    status_code=413,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(_RequestSizeLimitMiddleware)
# Added last, so it runs first: nothing, not even the size check, answers a foreign
# Host or a cross-site write (see `web/security.py`).
app.add_middleware(security.RequestGateMiddleware)


# Imported after `app` exists and its middleware is added, deliberately.
from resume_tailor.web.routes import (  # noqa: E402, I001
    applications as _applications_routes,
    config as _config_routes,
    diagnostics as _diagnostics_routes,
    jobs as _jobs_routes,
    libraries as _libraries_routes,
    resume as _resume_routes,
    secrets as _secrets_routes,
    template as _template_routes,
    workspaces as _workspaces_routes,
)

# Registration order is route-matching order: keep it the order these areas had in
# the single-file app (config, jobs, applications, resume, template, libraries, profiles).
for _router in (
    _config_routes, _jobs_routes, _applications_routes, _resume_routes,
    _template_routes, _libraries_routes, _workspaces_routes, _diagnostics_routes,
    _secrets_routes,
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
