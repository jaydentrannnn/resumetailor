"""Background skill inference after a master-resume save.

Every save (editor, merge, restore) schedules one refresh of `tag_infer`'s cache so the
next tailoring run starts with nothing left to infer. Coalesced: while a refresh runs,
further saves only replace the pending one, so a burst of saves costs one extra pass.

The refresh captures the active workspace and the Tailor settings' model routing at
schedule time and runs under them (`config.use_context` + `config.pinned`), so a profile
switch mid-refresh can never write one profile's skills into another's cache. It never
fails a save: errors are logged and reported through `status()`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from resume_tailor import config, workspace
from resume_tailor.content import bullet_tags
from resume_tailor.content.data import MasterResume
from resume_tailor.pipeline import tag_infer
from resume_tailor.web import job_routing
from resume_tailor.web.schemas import JobSettings

_log = logging.getLogger(__name__)


@dataclass
class _Job:
    workspace_id: str | None
    resume: MasterResume
    routing: tuple[str, dict[str, str] | None, str | None]


_LOCK = threading.Lock()
_pending: _Job | None = None
_running: str | None = None  # workspace id being refreshed ("" for the legacy default)
_thread: threading.Thread | None = None
_errors: dict[str, str] = {}


def _slot(workspace_id: str | None) -> str:
    return workspace_id or ""


def schedule(resume: MasterResume) -> None:
    """Queue a refresh for the active workspace's freshly saved `resume`."""
    global _pending, _thread
    try:
        settings = JobSettings.model_validate(workspace.load_settings()["defaults"])
        routing = job_routing.model_routing(settings)
    except Exception:  # noqa: BLE001 - a refresh is a convenience; the save already landed
        _log.warning("skill refresh not scheduled", exc_info=True)
        return
    job = _Job(config.active_workspace_id(), resume, routing)
    with _LOCK:
        _pending = job
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_worker, name="skill-refresh", daemon=True)
        _thread.start()


def _worker() -> None:
    global _pending, _running
    while True:
        with _LOCK:
            job, _pending = _pending, None
            _running = None if job is None else _slot(job.workspace_id)
            if job is None:
                return
        _run(job)


def _run(job: _Job) -> None:
    profile, overrides, effort = job.routing
    context = (
        config.context_for_workspace(job.workspace_id)
        if job.workspace_id
        else config.default_context()
    )
    try:
        with config.use_context(context), config.pinned(
            profile, overrides=overrides, effort=effort
        ):
            inference = tag_infer.ensure(
                job.resume, preferred=bullet_tags.known_terms(job.resume)
            )
        error = inference.error
    except Exception as exc:  # noqa: BLE001 - background work must never escape
        _log.warning("skill refresh failed", exc_info=True)
        error = f"Skill detection skipped ({exc})"
    with _LOCK:
        if error:
            _errors[_slot(job.workspace_id)] = error
        else:
            _errors.pop(_slot(job.workspace_id), None)


def status() -> tuple[bool, str | None]:
    """`(running, last_error)` for the active workspace."""
    slot = _slot(config.active_workspace_id())
    with _LOCK:
        busy = _running == slot or (_pending is not None and _slot(_pending.workspace_id) == slot)
        return busy, _errors.get(slot)
