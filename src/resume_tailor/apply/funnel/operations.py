"""Persistent coordinator for explicit Find, Prepare, and Fill operations.

Prepare and Fill batches may run side by side, each owning its own rows (`held_ids`)
and its own Pause/Resume/Skip/Cancel (`_Controls`); their workers share each kind's
slots fairly (`op_slots`). Find runs alone. A fill stuck on questions waits at the back
of its batch to come back (`come_back`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from resume_tailor import config, workspace
from resume_tailor.apply.answers import answer_memory, profile
from resume_tailor.apply.driver import browser
from resume_tailor.apply.forms import fill, submit_guard
from resume_tailor.apply.funnel import attention as attention_mod
from resume_tailor.apply.funnel import (
    answer_harvest,
    come_back,
    daily,
    daily_progress,
    fill_hosts,
    op_slots,
    preparation,
    store,
    store_models,
    store_views,
)
from resume_tailor.apply.funnel.daily_row_run import PrepareInterrupted
from resume_tailor.infra import atomic, logs
from resume_tailor.web import template_ops
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings, JobSettings

OperationState = Literal[
    "queued",
    "running",
    "paused",
    "completed",
    "completed_with_issues",
    "failed",
    "cancelled",
    "interrupted",
]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


#: When this server process started: a row left "filling" since before then was cut by
#: a restart; one left since was a fill that stopped without recording its end.
_PROCESS_STARTED = _now()


#: Per-application starting budget, matching `fill.fill_application`'s own deadline;
#: the fill pushes it out on progress (`_on_deadline`).
_APPLICATION_BUDGET_SEC = 240


def _deadline_iso(at: float | None = None) -> str:
    """When the current application's fill budget runs out, for the UI's countdown."""
    return (
        datetime.fromtimestamp(at or time.time() + _APPLICATION_BUDGET_SEC, UTC)
        .replace(microsecond=0)
        .isoformat()
    )


def _on_deadline(operation: ApplyOperation, item: InFlightItem) -> Any:
    """A fill's `on_deadline`: move this item's countdown to the extended deadline."""

    def moved(at: float) -> None:
        with _LOCK:
            item.deadline_at = _deadline_iso(at)
            if operation.current_application_id == item.application_id:
                operation.application_deadline_at = item.deadline_at

    return moved


class InFlightItem(BaseModel):
    application_id: str
    label: str = ""
    job_id: str = ""
    step: int = 0
    step_id: str = ""
    action_label: str = ""
    field_label: str = ""
    stage: str = ""
    started_at: str = ""
    deadline_at: str = ""


class ApplyOperation(BaseModel):
    operation_id: str
    action: Literal["find", "prepare", "fill", "inspect", "correct"]
    state: OperationState = "queued"
    application_ids: list[str] = Field(default_factory=list)
    in_flight: list[InFlightItem] = Field(default_factory=list)
    current_application_id: str = ""
    #: The tailor job of the item being prepared, while it runs (the page reads its
    #: stage events for progress within the item); "" otherwise.
    current_job_id: str = ""
    current_label: str = ""
    stage: str = "queued"
    message: str = ""
    processed: int = 0
    total: int = 0
    find_progress: daily_progress.FindProgress | None = None
    completed: int = 0
    blocked: int = 0
    failed: int = 0
    submitted: int = 0
    started_at: str = ""
    updated_at: str = Field(default_factory=_now)
    finished_at: str = ""
    effective_model: str = ""
    auto_submit: bool = False
    blocker_mode: Literal["pause", "continue"] = "continue"
    fill_mode: Literal["initial", "continue", "reopen"] = "initial"
    heartbeat_at: str = ""
    current_step: int = 0
    current_step_id: str = ""
    current_step_number: int = 0
    current_action_id: str = ""
    current_action_label: str = ""
    current_field_label: str = ""
    action_started_at: str = ""
    last_activity_at: str = ""
    application_started_at: str = ""
    application_deadline_at: str = ""
    ready_for_review: int = 0
    needs_input: int = 0
    attention: list[attention_mod.AttentionItem] = Field(default_factory=list)
    dry_run: bool = False
    limit: int | None = None
    max_age_days: int | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    excluded: dict[str, list[str]] = Field(default_factory=dict)
    idempotency_key: str = ""
    request_body_hash: str = ""
    #: Fill items handed back only because the model was at its limit; Continue fill
    #: runs them once more at the end when the model has recovered.
    model_limited: list[str] = Field(default_factory=list)
    #: The one operation-level "model at its limit" notice was shown.
    model_limit_noticed: bool = False
    #: Applications this operation still owns: pending, in flight or waiting to come
    #: back. Another batch cannot take them; a finished one is free at once.
    held_ids: list[str] = Field(default_factory=list)
    #: Stuck fills waiting to come back (`come_back`).
    waiting: list[come_back.WaitingItem] = Field(default_factory=list)


#: `FillResult.handoff_reason` of a fill whose required answers waited on the model.
_MODEL_UNAVAILABLE = "autofill model unavailable"


#: Most recent idempotent correction operations kept past the general history cap.
_DURABLE_CORRECTIONS_KEPT = 200

_LOCK = threading.RLock()


@dataclass
class _Controls:
    """One operation's Pause/Resume/Skip/Cancel: each batch has its own, so a control on
    one never reaches another running beside it."""

    cancel: threading.Event = field(default_factory=threading.Event)
    resume: threading.Event = field(default_factory=threading.Event)
    skip: threading.Event = field(default_factory=threading.Event)
    #: The applicant pressed Pause: stop before the next application (never mid-form).
    pause: threading.Event = field(default_factory=threading.Event)
    #: Pause or Cancel during Prepare: every item stops now (cancelling its tailor job)
    #: instead of finishing first; a paused one runs again from the start on Resume.
    hold: threading.Event = field(default_factory=threading.Event)
    #: Waiting applications to bring back now, or to leave in Needs you (`come_back`).
    retry_now: set[str] = field(default_factory=set)
    leave: set[str] = field(default_factory=set)
    #: Applications the applicant settled by hand while this batch held them (`revoke`):
    #: a running item stops at its next check and never submits; a pending one is dropped.
    revoked: set[str] = field(default_factory=set)


#: Operations running now, by id, oldest first (the live objects their workers update).
_ACTIVE: dict[str, ApplyOperation] = {}
_CONTROLS: dict[str, _Controls] = {}
#: A registry edit (`registry_edit_idle`) is in progress; nothing starts meanwhile.
_EDITING = False
#: Applications whose tab a worker is on now: a Fill or Prepare item from the moment its
#: dispatcher takes it, a review action from its start. Claimed under `_LOCK`, so two
#: never act on one tab (v1.25.0 looked at `in_flight`, which a review action never
#: fills: two corrections ran on one tab and could overwrite each other).
_AT_WORK: set[str] = set()
#: Rows a route is editing now (`rows_idle`): held, so no batch starts on them.
_EDITING_ROWS: set[str] = set()


def _ctl(operation: ApplyOperation) -> _Controls:
    with _LOCK:
        return _CONTROLS.setdefault(operation.operation_id, _Controls())


@contextmanager
def registry_edit_idle():
    """Exclude explicit and daily Apply workers during a registry mutation."""
    global _EDITING
    with _LOCK:
        if _ACTIVE or _EDITING:
            raise RuntimeError("Another Apply operation is running")
        _EDITING = True
    try:
        with daily.registry_edit_idle():
            yield
    finally:
        with _LOCK:
            _EDITING = False


@contextmanager
def rows_idle(application_ids: list[str]):
    """Exclude Apply workers from just these rows during an edit of them (archive,
    restore, undo, retry): refused while a running batch holds one or a worker is on its
    tab, and while the nightly run is busy. Batches on other rows go on meanwhile."""
    ids = {store.app_id(application_id) or application_id for application_id in application_ids}
    with _LOCK:
        if _EDITING or daily_progress.daily_busy():
            raise RuntimeError("Another Apply workflow is running; try again when it finishes")
        busy = {application_id for application_id in ids if row_busy(application_id)}
        if busy:
            raise RuntimeError(
                f"{len(busy)} of these applications are in a running Apply task; "
                "try again when it finishes"
            )
        # Counted as held (`_held_elsewhere`), so no batch takes these rows meanwhile.
        _EDITING_ROWS.update(ids)
    try:
        yield
    finally:
        with _LOCK:
            _EDITING_ROWS.difference_update(ids)


def row_busy(application_id: str) -> bool:
    """Whether a running batch holds this row or a worker is on its tab now."""
    resolved = store.app_id(application_id) or application_id
    with _LOCK:
        return resolved in (_held_elsewhere() | _AT_WORK | answer_harvest.FILLING)


def revoke(application_id: str, reason: str) -> bool:
    """Take one application away from the batch holding it: the applicant settled it by
    hand (marked it submitted or skipped). A running fill stops at its next check and
    never submits; a pending or waiting one is dropped. True when a batch held it."""
    resolved = store.app_id(application_id) or application_id
    with _LOCK:
        holders = [op for op in _ACTIVE.values() if resolved in op.held_ids]
        for operation in holders:
            _CONTROLS.setdefault(operation.operation_id, _Controls()).revoked.add(resolved)
    for operation in holders:
        _event(operation, "revoked", reason, resolved)
    return bool(holders)


def _register(operation: ApplyOperation) -> None:
    with _LOCK:
        _ACTIVE[operation.operation_id] = operation
        _CONTROLS[operation.operation_id] = _Controls()


def _unregister(operation: ApplyOperation) -> None:
    """The operation ended: its rows are free and its controls gone."""
    with _LOCK:
        operation.held_ids = []
        operation.waiting = []
        _ACTIVE.pop(operation.operation_id, None)
        _CONTROLS.pop(operation.operation_id, None)
    _persist(operation)


def _held_elsewhere(operation: ApplyOperation | None = None) -> set[str]:
    """Applications the running operations other than ``operation`` still own."""
    with _LOCK:
        return _EDITING_ROWS | {
            application_id
            for other in _ACTIVE.values()
            if other is not operation
            for application_id in other.held_ids
        }


def _start_refusal(action: str) -> str:
    """Why an operation of ``action`` cannot start beside the ones running, or ""."""
    with _LOCK:
        if _EDITING:
            return "Another Apply operation is running"
        running = list(_ACTIVE.values())
    if daily_progress.daily_busy():
        return "Another Apply workflow is already running"
    if not running:
        return ""
    if action == "find" or any(other.action == "find" for other in running):
        return f"Apply operation {running[-1].operation_id} is already active"
    # The extension's relay has one connection to the browser, and a Prepare may open
    # a posting there: only batches of the same kind share it.
    if browser.extension_mode() and any(
        other.action != action or action not in ("prepare", "fill") for other in running
    ):
        return (
            "With the browser extension, one kind of Apply task runs at a time; "
            "start this when the current one finishes"
        )
    return ""


def _path() -> Path:
    return config.APPLICATIONS_OUTPUT_DIR / "operations.json"


def _load() -> dict[str, ApplyOperation]:
    path = _path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {key: ApplyOperation.model_validate(value) for key, value in raw.items()}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save(operations: dict[str, ApplyOperation]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(
        path,
        json.dumps({key: value.model_dump() for key, value in operations.items()}, indent=2) + "\n",
    )


def _persist(operation: ApplyOperation) -> None:
    with _LOCK:
        operation.updated_at = _now()
        operations = _load()
        operations[operation.operation_id] = operation
        # Keep a bounded recent history.
        if len(operations) > 30:
            # Idempotent corrections outlive the general cap so a retried request still
            # dedupes, but are themselves bounded so they cannot grow forever.
            durable = sorted(
                (
                    item
                    for item in operations.values()
                    if item.action == "correct" and item.idempotency_key
                ),
                key=lambda item: item.updated_at,
                reverse=True,
            )[:_DURABLE_CORRECTIONS_KEPT]
            ordered = sorted(
                (
                    item
                    for item in operations.values()
                    if not (item.action == "correct" and item.idempotency_key)
                ),
                key=lambda item: item.updated_at,
                reverse=True,
            )[:30]
            operations = {item.operation_id: item for item in [*durable, *ordered]}
        _save(operations)


def _set_job(operation: ApplyOperation, job_id: str, application_id: str = "") -> None:
    """Record (or clear) the tailor job of the item in flight."""
    with _LOCK:
        item = next(
            (item for item in operation.in_flight if item.application_id == application_id), None
        )
        if item is not None:
            item.job_id = job_id
            _mirror_item(operation, item)
        else:
            operation.current_job_id = job_id
        _persist(operation)


def _mirror_item(operation: ApplyOperation, item: InFlightItem) -> None:
    operation.current_application_id = item.application_id
    operation.current_label = item.label
    operation.current_job_id = item.job_id
    operation.current_step = item.step
    operation.current_step_id = item.step_id
    operation.current_action_label = item.action_label
    operation.current_field_label = item.field_label
    operation.application_started_at = item.started_at
    operation.application_deadline_at = item.deadline_at


def _event(operation: ApplyOperation, stage: str, message: str, application_id: str = "") -> None:
    # Before any copy: the message lands in the operation, its in-flight item and events.
    message = answer_memory.redact(message)
    with _LOCK:
        operation.stage = stage
        operation.message = message
        operation.last_activity_at = _now()
        operation.current_action_label = message
        operation.action_started_at = operation.last_activity_at
        step = re.search(r"(?:form|wizard) step (\d+)", message)
        item = next(
            (item for item in operation.in_flight if item.application_id == application_id), None
        )
        if item is not None:
            item.stage = stage
            item.action_label = message
            if step:
                item.step = int(step.group(1))
            _mirror_item(operation, item)
        elif step:
            operation.current_step = int(step.group(1))
        operation.events.append(
            {"at": _now(), "stage": stage, "message": message, "application_id": application_id}
        )
        operation.events = _trim_events(operation.events)
        _persist(operation)


#: Events kept per application, and in total. A single shared cap let one chatty fill
#: push a parallel fill's whole history (and Pause/Cancel markers) out of the log.
_EVENTS_PER_APPLICATION = 60
_EVENTS_MAX = 400


def _trim_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each application's latest events and every operation-level event."""
    if len(events) <= _EVENTS_PER_APPLICATION:
        return events
    seen: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for event in reversed(events):
        owner = str(event.get("application_id") or "")
        if owner:
            seen[owner] = seen.get(owner, 0) + 1
            if seen[owner] > _EVENTS_PER_APPLICATION:
                continue
        kept.append(event)
    return kept[:_EVENTS_MAX][::-1]


def _set_find_progress(operation: ApplyOperation, progress: daily_progress.FindProgress) -> None:
    """Persist measured counts independently of the human-readable activity log."""
    with _LOCK:
        operation.find_progress = progress
        _persist(operation)


def get(operation_id: str) -> ApplyOperation | None:
    if not _ACTIVE:
        list_recent()
    with _LOCK:
        return _load().get(operation_id)


def list_recent() -> list[ApplyOperation]:
    with _LOCK:
        operations = _load()
        changed = False
        if not _ACTIVE:
            for operation in operations.values():
                if operation.state in {"queued", "running", "paused"}:
                    operation.state = "interrupted"
                    operation.message = "Server restarted before this operation finished"
                    operation.finished_at = _now()
                    operation.updated_at = operation.finished_at
                    changed = True
            for app in _stranded_fills():
                fill_result = (
                    store_models.FillResult.model_validate(app.fill) if app.fill else store_models.FillResult()
                )
                if (
                    fill_result.submit_action in {"submit", "auto_submit"}
                    and not fill_result.confirmation
                ):
                    recovered_status = "submit_unconfirmed"
                else:
                    recovered_status = "awaiting_review" if app.fill else "ready"
                store.set_status(app, recovered_status, note=_stranded_note(app))
                store.upsert(app)
        if changed:
            _save(operations)
        values = list(operations.values())
    return sorted(values, key=lambda item: item.updated_at, reverse=True)


def _stranded_fills() -> list[store_models.Application]:
    """Rows still "filling" with no worker on them: none of this process's fills (the
    nightly run's included) holds them."""
    if daily_progress.daily_busy():
        return []
    return [
        app
        for app in store_views.list_applications(status="filling", limit=None)
        if app.source_job_id not in answer_harvest.FILLING and app.source_job_id not in _AT_WORK
    ]


def _stranded_note(app: store_models.Application) -> str:
    started = next(
        (change.at for change in reversed(app.status_history) if change.status == "filling"), ""
    )
    if started and started >= _PROCESS_STARTED:
        return "Fill stopped without finishing"
    return "Fill interrupted by server restart"


def active() -> ApplyOperation | None:
    """The most recently started operation still running, or None when none is."""
    with _LOCK:
        ids = list(_ACTIVE)
    return get(ids[-1]) if ids else None


def active_all() -> list[ApplyOperation]:
    """Every operation running now, oldest first."""
    with _LOCK:
        ids = list(_ACTIVE)
    return [operation for operation_id in ids if (operation := get(operation_id))]


def _captured_settings(request: ApplyOperationRequest) -> ApplySettings:
    raw = workspace.load_settings()
    job_defaults = JobSettings.model_validate(raw["defaults"])
    settings = job_defaults.apply.model_copy(deep=True)
    settings._job_defaults = job_defaults
    settings.model_provider = request.model_provider
    settings.model_name = request.model_name.strip()
    settings.model_selection = (
        request.model_selection.model_copy(deep=True) if request.model_selection else None
    )
    settings.auto_submit_enabled = request.auto_submit
    settings.blocker_mode = request.blocker_mode
    return settings


def _effective_model(request: ApplyOperationRequest) -> str:
    """The model the operation's LLM calls will actually use, for the UI label.

    Fill runs on the Apply page's autofill model (the request's provider/model); Find
    and Prepare tailor and screen with the Tailor tab's routing (`daily_rows._job_settings`).
    """
    if request.action == "fill":
        if request.model_selection is not None:
            spec = request.model_selection.spec("heavy")
            return config._backend(spec, "answer", None).label()
        return f"{request.model_provider}:{request.model_name.strip()}"
    from resume_tailor.web.job_routing import model_label

    return model_label(JobSettings.model_validate(workspace.load_settings()["defaults"]))


def start(request: ApplyOperationRequest) -> ApplyOperation:
    """Start an operation. Holds `template_ops.LOCK` (as `activate_workspace` does) from
    its first workspace read until it is registered active, so a profile switch
    cannot land in between."""
    with template_ops.LOCK:
        return _start_locked(request)


def _start_locked(request: ApplyOperationRequest) -> ApplyOperation:
    if request.action != "find" and not request.application_ids:
        raise ValueError(f"{request.action} requires at least one selected application")
    settings_snapshot = _captured_settings(request)
    # One id per row, whichever alias the caller used (desktop and extension differ), so
    # `held_ids`, tab claims and watchers all compare the same string.
    selected = list(dict.fromkeys(
        store.app_id(application_id) or application_id
        for application_id in request.application_ids
    ))
    excluded: dict[str, list[str]] = {}
    if request.action == "fill":
        for application_id in selected:
            app = store.get(application_id)
            if app is None:
                excluded[application_id] = ["unknown_application"]
                continue
            if app.archived_at:
                excluded[application_id] = ["archived_application"]
                continue
            eligibility = preparation.check(app)
            if not eligibility.eligible:
                excluded[application_id] = eligibility.reasons
        selected = [application_id for application_id in selected if application_id not in excluded]
        if not selected:
            raise ValueError(f"No selected applications are prepared for Fill: {excluded}")
    if request.action == "prepare":
        for application_id in selected:
            app = store.get(application_id)
            if app is not None and app.archived_at:
                excluded[application_id] = ["archived_application"]
        selected = [application_id for application_id in selected if application_id not in excluded]
        if not selected:
            raise ValueError(f"No selected applications can be prepared: {excluded}")
    if refusal := _start_refusal(request.action):
        raise RuntimeError(refusal)
    applicant_snapshot = None
    if request.action == "fill":
        applicant_snapshot, _seeded = profile.load_profile()
        applicant_snapshot = applicant_snapshot.model_copy(deep=True)

    with _LOCK:
        if refusal := _start_refusal(request.action):
            raise RuntimeError(refusal)
        # A row another batch still owns stays with it; one it finished is free.
        held = _held_elsewhere()
        for application_id in selected:
            if application_id in held:
                excluded[application_id] = ["in_another_task"]
        selected = [application_id for application_id in selected if application_id not in held]
        if request.action != "find" and not selected:
            raise RuntimeError(
                "The selected applications are already in another running Apply task"
            )
        operation = ApplyOperation(
            operation_id=uuid.uuid4().hex,
            action=request.action,
            application_ids=selected,
            total=1 if request.action == "find" else len(selected),
            excluded=excluded,
            effective_model=_effective_model(request),
            auto_submit=request.auto_submit,
            blocker_mode=request.blocker_mode,
            fill_mode=request.fill_mode,
            dry_run=request.dry_run,
            limit=request.limit,
            max_age_days=request.max_age_days,
            held_ids=list(selected),
        )
        _register(operation)
    _persist(operation)
    threading.Thread(
        target=logs.call_in_context,
        args=(
            operation.operation_id,
            _worker,
            operation,
            request,
            applicant_snapshot,
            settings_snapshot,
        ),
        name=f"apply-{operation.action}-{operation.operation_id[:8]}",
        daemon=True,
    ).start()
    return operation


def _wait_if_paused(operation: ApplyOperation) -> Literal["resume", "skip", "cancel"]:
    if operation.state != "paused":
        return "resume"
    ctl = _ctl(operation)
    while not ctl.cancel.is_set():
        if ctl.skip.wait(timeout=0.25):
            ctl.skip.clear()
            ctl.hold.clear()
            operation.state = "running"
            _event(operation, "resumed", "Skipped blocked application")
            return "skip"
        if ctl.resume.wait(timeout=0.25):
            ctl.resume.clear()
            ctl.hold.clear()
            operation.state = "running"
            _event(operation, "resumed", "Batch resumed")
            return "resume"
    return "cancel"


def _wait_while_automation_paused(operation: ApplyOperation) -> bool:
    """Hold the batch while "Pause all automation" is on; False when cancelled meanwhile."""
    if not submit_guard.is_paused():
        return True
    operation.state = "paused"
    _event(
        operation,
        "automation_paused",
        "Automation is paused. Turn it back on to continue with the next application.",
    )
    _persist(operation)
    while not _ctl(operation).cancel.wait(timeout=0.5):
        if not submit_guard.is_paused():
            operation.state = "running"
            _event(operation, "resumed", "Automation resumed")
            return True
    return False


def _label(app: store_models.Application | None, application_id: str) -> str:
    return f"{app.company} — {app.role}".strip(" —") if app else application_id


def _hold_for_verification(operation: ApplyOperation, application_id: str, reason: str) -> None:
    """Hand an application back unfilled: its Workday site's new account is unverified."""
    label = _label(store.get(application_id), application_id)
    with _LOCK:
        operation.processed += 1
        operation.blocked += 1
        operation.needs_input += 1
        attention_mod.record(operation.attention, application_id, label, "needs_input", reason)
    _event(operation, "filling", reason, application_id)


#: How one item ended, for the dispatcher: finished (counted), stopped by Pause/Cancel
#: before it finished (it runs again on Resume), or a stuck fill waiting to come back.
Outcome = Literal["done", "stopped", "come_back"]


def _process_item(
    operation: ApplyOperation,
    request: ApplyOperationRequest,
    settings: ApplySettings,
    applicant_snapshot: profile.ApplicantProfile | None,
    application_id: str,
    reserve_submit: Any,
    release_submit: Any,
    *,
    comebacks: int = 0,
    again: bool = False,
) -> Outcome:
    """Run one item. ``comebacks`` counts the times this fill already came back, and
    ``again`` is set while it is coming back now (`come_back`)."""
    app = store.get(application_id)
    started_at = _now()
    item = InFlightItem(
        application_id=application_id,
        label=_label(app, application_id),
        started_at=started_at,
        deadline_at=_deadline_iso(),
    )
    with _LOCK:
        operation.in_flight.append(item)
        operation.current_step_number = 0
        _mirror_item(operation, item)
        _persist(operation)
    outcome: Outcome = "done"
    try:
        if app is None:
            with _LOCK:
                operation.failed += 1
                attention_mod.record(operation.attention, application_id, item.label, "failed", "Application no longer exists")
            _event(operation, "failed", "Application no longer exists", application_id)
            return outcome
        if app.archived_at:
            with _LOCK:
                operation.excluded[application_id] = ["archived_application"]
            _event(operation, "excluded", "Application is archived", application_id)
            return outcome
        if application_id in _ctl(operation).revoked:
            _event(operation, "revoked", "You settled this application; leaving it", application_id)
            return outcome
        if operation.action == "prepare":
            outcome = _prepare_item(operation, request, settings, application_id, item)
            return outcome
        if _already_settled(operation, app, application_id):
            return outcome
        if again and _settled_while_waiting(operation, app, application_id, item.label):
            return outcome
        outcome = _fill_item(
            operation, request, settings, applicant_snapshot, application_id, item,
            reserve_submit, release_submit, comebacks=comebacks, again=again,
        )
        return outcome
    except Exception as exc:  # noqa: BLE001 - one item must not erase batch evidence
        with _LOCK:
            operation.failed += 1
            attention_mod.record(operation.attention, application_id, item.label, "failed", str(exc))
        _event(operation, "failed", str(exc), application_id)
    finally:
        with _LOCK:
            if outcome == "done":
                operation.processed += 1
            operation.in_flight.remove(item)
            if operation.in_flight:
                _mirror_item(operation, operation.in_flight[-1])
            _persist(operation)
    return outcome


def _prepare_item(
    operation: ApplyOperation,
    request: ApplyOperationRequest,
    settings: ApplySettings,
    application_id: str,
    item: InFlightItem,
) -> Outcome:
    """Fetch and tailor one application; ``stopped`` when Pause/Cancel cut it short."""
    ctl = _ctl(operation)
    _event(operation, "preparing", "Fetching and tailoring application", application_id)

    def stop() -> bool:
        return ctl.hold.is_set() or application_id in ctl.revoked

    def progress(message: str) -> None:
        # A stopped item stays quiet: its late progress would bury "Paused".
        if not stop():
            _event(operation, "preparing", message, application_id)

    try:
        result_app = daily.prepare_application(
            application_id,
            settings=settings,
            on_progress=progress,
            force_prepare=request.force_prepare,
            on_job=lambda job_id: _set_job(operation, job_id, application_id),
            should_stop=stop,
        )
    except PrepareInterrupted:
        return "stopped"
    finally:
        _set_job(operation, "", application_id)
    with _LOCK:
        if result_app.status == "ready" or result_app.status in daily.RETAINED_TAB_STATUSES:
            operation.completed += 1
        elif result_app.status in {"needs_browser", "screened_out"}:
            operation.blocked += 1
            attention_mod.record(
                operation.attention, application_id, item.label, "blocked",
                result_app.error
                or ("; ".join(result_app.screen.reasons) if result_app.screen else "")
                or store_views.review_summary(result_app)
                or (result_app.status_history[-1].note if result_app.status_history else "")
                or result_app.status.replace("_", " "),
            )
        else:
            operation.failed += 1
            attention_mod.record(operation.attention, application_id, item.label, "failed", result_app.error or result_app.status.replace("_", " "))
    if result_app.status in daily.RETAINED_TAB_STATUSES:
        _event(
            operation,
            "preparing",
            f"[ready] packet refreshed; {result_app.status.replace('_', ' ')} tab retained",
            application_id,
        )
    return "done"


def _updated_profile(
    operation: ApplyOperation, application_id: str,
    applicant: profile.ApplicantProfile | None,
) -> profile.ApplicantProfile | None:
    """The profile a Continue fill uses: the one saved now, when it changed since the
    batch started (an answer added while the fill waited on you; audit #12). A single
    attempt keeps one profile throughout."""
    if applicant is None:
        return None
    try:
        current, _seeded = profile.load_profile()
    except Exception:  # noqa: BLE001 - an unreadable profile keeps the batch's copy
        return applicant
    secret = {"workday_password"}
    if current.model_dump(exclude=secret) == applicant.model_dump(exclude=secret):
        return applicant
    _event(operation, "filling", "Using your updated profile", application_id)
    return current.model_copy(deep=True)


def _fill_item(
    operation: ApplyOperation,
    request: ApplyOperationRequest,
    settings: ApplySettings,
    applicant_snapshot: profile.ApplicantProfile | None,
    application_id: str,
    item: InFlightItem,
    reserve_submit: Any,
    release_submit: Any,
    *,
    comebacks: int,
    again: bool,
) -> Outcome:
    """Fill one application; ``come_back`` when it stuck on questions and waits at the
    back of the batch (`come_back`). A comeback, or Resume after a blocker, is a
    Continue fill: it reuses the retained tab and its answers."""
    ctl = _ctl(operation)
    attempt_mode = "continue" if again else request.fill_mode
    applicant = applicant_snapshot
    while True:
        if application_id in ctl.revoked:
            return "done"
        if attempt_mode == "continue":
            _harvest_typed(operation, application_id)
            applicant = _updated_profile(operation, application_id, applicant)
        _event(operation, "filling", "Opening application form", application_id)
        submit_allowed = reserve_submit()
        answer_harvest.FILLING.add(application_id)
        try:
            result = fill.fill_application(
                application_id,
                settings=settings,
                submit_mode="auto_submit" if submit_allowed else "awaiting_review",
                fill_mode=attempt_mode,
                should_cancel=lambda: ctl.cancel.is_set() or application_id in ctl.revoked,
                on_progress=lambda message: _event(
                    operation, "filling", message, application_id
                ),
                applicant_profile=applicant,
                on_deadline=_on_deadline(operation, item),
            )
        except BaseException:
            release_submit(submit_allowed, _stored_submit_status(application_id))
            raise
        finally:
            answer_harvest.FILLING.discard(application_id)
        release_submit(submit_allowed, result.status)
        if application_id in ctl.revoked:
            _event(operation, "revoked", "Stopped: you settled this application", application_id)
            return "done"
        if result.status in {"awaiting_review", "awaiting_otp"} or (
            result.status == "fill_failed" and result.browser_target_id
        ):
            # A failed fill's tab too (audit #3): finished by hand, it is recorded.
            answer_harvest.watch(application_id)
        if result.status == "submitted":
            with _LOCK:
                operation.completed += 1
            return "done"
        if result.status == "awaiting_review" and result.ready_to_submit:
            with _LOCK:
                operation.completed += 1
                operation.ready_for_review += 1
                attention_mod.record(operation.attention, application_id, item.label, "ready_for_review", "Ready to submit — final check")
            return "done"
        if result.status in {"awaiting_review", "awaiting_otp"}:
            if result.handoff_reason == _MODEL_UNAVAILABLE:
                _note_model_limit(operation, settings, application_id)
            if come_back.eligible(
                result, settings, blocker_mode=request.blocker_mode, comebacks=comebacks,
                model_unavailable=_MODEL_UNAVAILABLE,
            ):
                _wait_to_come_back(operation, settings, application_id, item.label, result, comebacks + 1)
                return "come_back"
            with _LOCK:
                current = store.get(application_id)
                operation.blocked += 1
                operation.needs_input += 1
                attention_mod.record(
                    operation.attention,
                    application_id,
                    item.label,
                    "needs_input",
                    result.handoff_reason
                    or result.error
                    or (store_views.review_summary(current) if current else "")
                    or result.status.replace("_", " "),
                )
            if request.blocker_mode != "pause":
                return "done"
            with _LOCK:
                operation.state = "paused"
            _event(operation, "blocked", "Application needs your attention", application_id)
            pause_action = _wait_if_paused(operation)
            if pause_action == "resume":
                with _LOCK:
                    operation.blocked -= 1
                    operation.needs_input -= 1
                    attention_mod.remove(operation.attention, application_id)
                    item.started_at = _now()
                    item.deadline_at = _deadline_iso()
                    _mirror_item(operation, item)
                attempt_mode = "continue"
                continue
            return "done"
        with _LOCK:
            operation.failed += 1
            attention_mod.record(operation.attention, application_id, item.label, "failed", result.error or result.handoff_reason or result.status.replace("_", " "))
        return "done"


def _wait_to_come_back(
    operation: ApplyOperation,
    settings: ApplySettings,
    application_id: str,
    label: str,
    result: store_models.FillResult,
    comebacks: int,
) -> None:
    """Show a stuck fill as waiting to come back; the dispatcher requeues it."""
    come_back.forget(application_id)
    current = store.get(application_id)
    reason = (
        result.handoff_reason
        or result.error
        or (store_views.review_summary(current) if current else "")
        or "Needs your answers"
    )
    waiting = come_back.WaitingItem(
        application_id=application_id,
        label=label,
        due_at=_deadline_iso(time.time() + come_back.wait_seconds(settings)),
        comebacks=comebacks,
        reason=reason,
    )
    with _LOCK:
        operation.waiting = [w for w in operation.waiting if w.application_id != application_id]
        operation.waiting.append(waiting)
    _event(
        operation,
        "waiting",
        f"Needs your answers; coming back in {settings.come_back_after_min} min, "
        "or as soon as you've answered",
        application_id,
    )


def _unwait(operation: ApplyOperation, application_id: str) -> come_back.WaitingItem | None:
    """Take an application off the waiting list; what it showed there."""
    with _LOCK:
        waiting = next((w for w in operation.waiting if w.application_id == application_id), None)
        operation.waiting = [w for w in operation.waiting if w.application_id != application_id]
        return waiting


def _release(operation: ApplyOperation, application_id: str) -> None:
    """The application is finished here: another batch may take it now."""
    with _LOCK:
        if application_id in operation.held_ids:
            operation.held_ids.remove(application_id)


def _already_settled(
    operation: ApplyOperation, app: store_models.Application, application_id: str
) -> bool:
    """The applicant submitted or skipped this application by hand after the batch took
    it: counted as they left it, never filled."""
    if app.status not in store_models.TERMINAL_STATUSES:
        return False
    _note_settled(operation, app, application_id)
    return True


def _note_settled(
    operation: ApplyOperation, app: store_models.Application, application_id: str
) -> None:
    if app.status == "submitted":
        with _LOCK:
            operation.completed += 1
    _event(
        operation, "filling",
        f"Already {app.status.replace('_', ' ')}; not filling it again", application_id,
    )


def _settled_while_waiting(
    operation: ApplyOperation, app: store_models.Application, application_id: str, label: str
) -> bool:
    """A waiting application that needs no fill now: the applicant submitted or skipped
    it by hand (counted as they left it), or its tab is gone (left in Needs you)."""
    if app.status not in come_back.STILL_WAITING:
        _note_settled(operation, app, application_id)
        return True
    target = store_models.FillResult.model_validate(app.fill).browser_target_id if app.fill else ""
    open_ids = browser.open_target_ids()
    if open_ids is not None and target not in open_ids:
        reason = "The application tab was closed; Continue fill or Start over from Needs you"
        with _LOCK:
            operation.blocked += 1
            operation.needs_input += 1
            attention_mod.record(operation.attention, application_id, label, "needs_input", reason)
        _event(operation, "filling", reason, application_id)
        return True
    return False


def _leave_waiting(operation: ApplyOperation, application_id: str, reason: str = "") -> None:
    """A waiting application is left for the applicant to finish (they chose to, or its
    timer ran out first): Needs you, as with come-back off."""
    waiting = _unwait(operation, application_id)
    with _LOCK:
        operation.processed += 1
        operation.blocked += 1
        operation.needs_input += 1
        attention_mod.record(
            operation.attention, application_id, waiting.label if waiting else application_id,
            "needs_input", reason or (waiting.reason if waiting else "Needs your answers"),
        )
    _release(operation, application_id)
    _event(operation, "filling", reason or "Left for you to finish", application_id)


def _still_quiet(application_id: str) -> bool:
    """Right before a comeback takes the tab back: look again (the watcher's last look
    may be 20 s old) and come back only if the applicant is still done there."""
    answer_harvest.collect(application_id)
    return come_back.ready_to_continue(application_id)


def _drop_revoked(operation: ApplyOperation, application_id: str) -> None:
    """A row the applicant settled by hand leaves the batch: counted, off the waiting
    list, free for anything else."""
    _unwait(operation, application_id)
    with _LOCK:
        operation.processed += 1
    _release(operation, application_id)


def _claim(operation: ApplyOperation, application_id: str) -> bool:
    """Take an application's tab for a dispatched item: False while another operation
    holds the application (a review action on its tab)."""
    with _LOCK:
        if application_id in _AT_WORK or application_id in _held_elsewhere(operation):
            return False
        _AT_WORK.add(application_id)
        return True


def _unclaim(application_id: str) -> None:
    with _LOCK:
        _AT_WORK.discard(application_id)


def _dispatch_items(
    operation: ApplyOperation,
    request: ApplyOperationRequest,
    settings: ApplySettings,
    applicant_snapshot: profile.ApplicantProfile | None,
) -> None:
    reserved = 0
    # A submit whose confirmation never showed may well have gone out: it uses a slot.
    unconfirmed = 0

    def reserve_submit() -> bool:
        nonlocal reserved
        with _LOCK:
            allowed = request.auto_submit and (
                operation.submitted + unconfirmed + reserved < settings.auto_submit_max_per_run
            )
            if allowed:
                reserved += 1
            return allowed

    def release_submit(was_reserved: bool, status: str) -> None:
        nonlocal reserved, unconfirmed
        with _LOCK:
            if not was_reserved:
                return
            reserved -= 1
            if status == "submitted":
                operation.submitted += 1
            elif status == "submit_unconfirmed":
                unconfirmed += 1

    # Fill only: one application per Workday site at a time (see fill_hosts).
    gate = fill_hosts.HostGate() if operation.action == "fill" else None
    _dispatch_round(
        operation, request, settings, applicant_snapshot, list(operation.application_ids),
        reserve_submit, release_submit, gate,
    )
    retry = _reclaim_model_limited(operation, request, settings)
    if retry is not None:
        # Through the dispatcher again, not straight to `_process_item` (v1.25.0): the
        # shared Fill slots, one fill per Workday site and a tab a review action is on
        # all hold for a refill too. No comebacks are left: a stuck refill ends in
        # Needs you.
        again, ids = retry
        _dispatch_round(
            operation, again, settings, applicant_snapshot, ids,
            reserve_submit, release_submit, gate,
            comebacks_used=come_back.MAX_COMEBACKS,
            on_take=lambda application_id: _recount(operation, application_id),
        )


def _dispatch_round(
    operation: ApplyOperation,
    request: ApplyOperationRequest,
    settings: ApplySettings,
    applicant_snapshot: profile.ApplicantProfile | None,
    ids: list[str],
    reserve_submit: Callable[[], bool],
    release_submit: Callable[[bool, str], None],
    gate: fill_hosts.HostGate | None,
    *,
    comebacks_used: int = 0,
    on_take: Callable[[str], None] | None = None,
) -> None:
    """Run ``ids`` on the batch's workers until each is done. ``on_take`` runs as each
    item is taken, before it is filled."""
    ctl = _ctl(operation)
    if operation.action == "prepare":
        capacity = JobSettings.model_validate(
            workspace.load_settings()["defaults"]
        ).max_concurrent_jobs
        workers = capacity
    else:
        capacity = 1 if browser.extension_mode() else settings.max_parallel_fills
        workers = 1 if request.blocker_mode == "pause" else capacity
    workers = min(workers, len(ids))
    # Shared with every batch of this kind running beside this one.
    slots = op_slots.pool("prepare" if operation.action == "prepare" else "fill")
    # A paused Prepare item goes back on the front, to run again on Resume; a stuck fill
    # goes on the back, to come back later.
    pending = deque(ids)
    #: application id -> monotonic time before which a waiting fill is not taken.
    not_before: dict[str, float] = {}
    comebacks: dict[str, int] = dict.fromkeys(ids, comebacks_used)
    dispatch_lock = threading.Lock()
    site_free = threading.Condition(dispatch_lock)

    def ready(application_id: str) -> bool:
        """Whether a pending application may be taken now: never while another
        operation holds it (a review action on its tab), a waiting fill once due."""
        if application_id in _held_elsewhere(operation):
            return False
        waited = not_before.get(application_id)
        return come_back.is_due(
            waited,
            time.monotonic(),
            ready=waited is not None and come_back.ready_to_continue(application_id),
            retry_now=application_id in ctl.retry_now,
        )

    def take() -> str | None:
        if gate is not None:
            return gate.take(pending, ready)
        for index, application_id in enumerate(pending):
            if ready(application_id):
                del pending[index]
                return application_id
        return None

    def drop_revoked() -> None:
        """Drop the pending applications the applicant settled by hand (`revoke`)."""
        for application_id in [a for a in pending if a in ctl.revoked]:
            pending.remove(application_id)
            not_before.pop(application_id, None)
            _drop_revoked(operation, application_id)

    def leave_requested() -> None:
        for application_id in list(ctl.leave):
            ctl.leave.discard(application_id)
            if application_id in not_before and application_id in pending:
                pending.remove(application_id)
                del not_before[application_id]
                _leave_waiting(operation, application_id)
        now = time.monotonic()
        for application_id in [a for a in pending if come_back.expired(not_before.get(a), now)]:
            if ready(application_id):
                continue  # ready at the last moment: it comes back
            pending.remove(application_id)
            del not_before[application_id]
            _leave_waiting(operation, application_id, come_back.STILL_WAITING_NOTE)

    def show_answered() -> None:
        """Mark the waiting fills whose questions are all answered (they come back once
        the applicant stops typing)."""
        with _LOCK:
            changed = False
            for waiting in operation.waiting:
                answered = come_back.answered(waiting.application_id)
                changed = changed or waiting.answered != answered
                waiting.answered = answered
            if changed:
                _persist(operation)

    def stopping() -> bool:
        return ctl.cancel.is_set() or ctl.pause.is_set()

    def process_next() -> None:
        while True:
            with dispatch_lock:
                if not pending:
                    return
                if not _wait_while_automation_paused(operation):
                    return
                if ctl.pause.is_set() and not ctl.cancel.is_set():
                    ctl.pause.clear()
                    # A paused Prepare already said so when Pause was pressed.
                    if operation.state != "paused":
                        with _LOCK:
                            operation.state = "paused"
                        _event(
                            operation,
                            "paused_by_user",
                            "Paused. Resume continues with the next application.",
                        )
                if ctl.cancel.is_set() or _wait_if_paused(operation) == "cancel":
                    return
                leave_requested()
                drop_revoked()
                if not pending:
                    return
                if not any(ready(application_id) for application_id in pending):
                    # Only fills waiting to come back are left (or rows a review holds).
                    show_answered()
                    site_free.wait(timeout=0.5)
                    continue
            if not slots.acquire(operation.operation_id, capacity, stopping):
                continue  # Pause or Cancel: handled at the top
            with dispatch_lock:
                application_id = take()
                if application_id is None:
                    slots.release(operation.operation_id)
                    # Every ready application is on a Workday site another worker is
                    # filling; wait for one to finish (or for Pause/Cancel).
                    site_free.wait(timeout=0.5)
                    continue
                if not _claim(operation, application_id):
                    # A review action took its tab after `ready` looked; it waits for it.
                    pending.appendleft(application_id)
                    if gate is not None:
                        gate.release(application_id)
                    slots.release(operation.operation_id)
                    site_free.wait(timeout=0.5)
                    continue
                waited_until = not_before.pop(application_id, None)
                again = waited_until is not None
                asked = application_id in ctl.retry_now
                ctl.retry_now.discard(application_id)
                # A comeback is that site's own verification wait; it goes on.
                hold = gate.verification_hold(application_id) if gate and not again else ""
            if again and not asked and not _still_quiet(application_id):
                # They typed there since the last look: the tab stays theirs for now.
                with dispatch_lock:
                    not_before[application_id] = waited_until
                    pending.append(application_id)
                    if gate is not None:
                        gate.release(application_id)
                    site_free.notify_all()
                _unclaim(application_id)
                slots.release(operation.operation_id)
                continue
            if on_take is not None:
                on_take(application_id)
            if again:
                _unwait(operation, application_id)
            outcome: Outcome = "done"
            try:
                if hold:
                    _hold_for_verification(operation, application_id, hold)
                else:
                    # Same-role postings in other locations prepare side by side: each is
                    # its own store row with its own tailor run, so nothing is shared.
                    outcome = _process_item(
                        operation,
                        request,
                        settings,
                        applicant_snapshot,
                        application_id,
                        reserve_submit,
                        release_submit,
                        comebacks=comebacks.get(application_id, 0),
                        again=again,
                    )
            finally:
                _unclaim(application_id)
                slots.release(operation.operation_id)
                if gate is not None:
                    with dispatch_lock:
                        gate.release(application_id)
                        site_free.notify_all()
            if gate is not None and not hold:
                label = _label(store.get(application_id), application_id)
                with dispatch_lock:
                    gate.record_result(application_id, label)
            with dispatch_lock:
                if outcome != "done" and application_id in ctl.revoked:
                    _drop_revoked(operation, application_id)
                elif outcome == "stopped" and not ctl.cancel.is_set():
                    pending.appendleft(application_id)
                elif outcome == "come_back":
                    comebacks[application_id] = comebacks.get(application_id, 0) + 1
                    not_before[application_id] = time.monotonic() + come_back.wait_seconds(settings)
                    pending.append(application_id)
                elif outcome == "done":
                    _release(operation, application_id)
                site_free.notify_all()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [config.submit_in_context(executor, process_next) for _ in range(workers)]
        for future in futures:
            future.result()


def _model_exhausted(settings: ApplySettings) -> bool:
    from resume_tailor.apply.answers import model_fallback

    return model_fallback.heavy_exhausted(settings.model_spec)


def _harvest_typed(operation: ApplyOperation, application_id: str) -> None:
    """Before Continue fill touches the tab: save what the applicant typed there."""
    saved = answer_harvest.collect(application_id)
    if saved:
        _event(
            operation, "filling",
            f"Saved {saved} answer(s) you typed to your Answer book", application_id,
        )


def _note_model_limit(
    operation: ApplyOperation, settings: ApplySettings, application_id: str
) -> None:
    """Remember a fill the model's limit held back; say so once for the operation."""
    with _LOCK:
        if application_id not in operation.model_limited:
            operation.model_limited.append(application_id)
        if operation.model_limit_noticed:
            return
        operation.model_limit_noticed = True
    light = settings.fallback_model_spec is not None
    _event(
        operation,
        "model_limit",
        "The AI model is at its limit; fills continue without AI answers"
        + (" (Light answers where it can)" if light else "")
        + ". They are filled again at the end if it recovers.",
    )


def _stored_submit_status(application_id: str) -> str:
    """After a fill raised: the submit status it recorded before dispatching, if any."""
    try:
        app = store.get(application_id)
    except Exception:  # noqa: BLE001 - unknown counts as dispatched, the safe side
        return "submit_unconfirmed"
    fill_status = ""
    if app is not None and app.fill is not None:
        fill = app.fill
        fill_status = str(fill.get("status") if isinstance(fill, dict) else fill.status)
    statuses = {app.status if app else "", fill_status}
    return next((s for s in ("submitted", "submit_unconfirmed") if s in statuses), "")


def _reclaim_model_limited(
    operation: ApplyOperation, request: ApplyOperationRequest, settings: ApplySettings
) -> tuple[ApplyOperationRequest, list[str]] | None:
    """Once, at the end of a Fill: the fills the model's limit held back, taken back for
    one Continue fill when its quota has recovered by then; None when there are none.

    Each was released when it was counted, so a task that took it since keeps it."""
    if operation.action != "fill" or not operation.model_limited or _ctl(operation).cancel.is_set():
        return None
    if _model_exhausted(settings):
        _event(operation, "model_limit", "The AI model is still at its limit; not refilling")
        return None
    ids, operation.model_limited = list(operation.model_limited), []
    taken: list[str] = []
    for application_id in ids:
        app = store.get(application_id)
        if app is None or app.status not in {"awaiting_review", "awaiting_otp"}:
            continue
        with _LOCK:
            if application_id in _held_elsewhere(operation):
                continue
            operation.held_ids.append(application_id)
        taken.append(application_id)
    if not taken:
        return None
    _event(operation, "model_limit", f"Model available again; refilling {len(taken)} application(s)")
    return request.model_copy(update={"fill_mode": "continue", "blocker_mode": "continue"}), taken


def _recount(operation: ApplyOperation, application_id: str) -> None:
    """A refill is starting: this application was counted once already, and the rerun
    replaces that result."""
    with _LOCK:
        operation.blocked -= 1
        operation.needs_input -= 1
        operation.processed -= 1
        attention_mod.remove(operation.attention, application_id)


def _worker(
    operation: ApplyOperation,
    request: ApplyOperationRequest,
    applicant_snapshot: profile.ApplicantProfile | None = None,
    settings_snapshot: ApplySettings | None = None,
) -> None:
    ctl = _ctl(operation)
    operation.state = "running"
    operation.started_at = _now()
    _event(operation, "starting", f"Starting {operation.action}")
    heartbeat_stop = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(5):
            operation.heartbeat_at = _now()
            _persist(operation)

    threading.Thread(
        target=heartbeat, name=f"apply-heartbeat-{operation.operation_id[:8]}", daemon=True
    ).start()
    try:
        settings = settings_snapshot or _captured_settings(request)
        if operation.action == "find":
            _event(operation, "discovering", "Fetching configured job sources")
            if request.max_age_days is not None:
                # One-off catch-up window; the saved settings are left as they are.
                settings = settings.model_copy(update={"max_age_days": request.max_age_days})
            result = daily.run_daily(
                settings=settings,
                limit=request.limit,
                dry_run=request.dry_run,
                fetch_only=True,
                log=lambda message: _event(operation, "discovering", message),
                on_progress=lambda progress: _set_find_progress(operation, progress),
            )
            operation.processed = operation.completed = 1
            operation.attention = result.attention
            if result.errors:
                operation.failed = len(result.errors)
        else:
            _dispatch_items(operation, request, settings, applicant_snapshot)

        if ctl.cancel.is_set():
            operation.state = "cancelled"
            operation.message = "Cancelled"
        elif operation.failed or operation.blocked:
            operation.state = "completed_with_issues"
        else:
            operation.state = "completed"
        operation.current_application_id = ""
        operation.current_job_id = ""
        operation.current_label = ""
        operation.finished_at = _now()
        _event(operation, "done", operation.state.replace("_", " ").title())
    except Exception as exc:  # noqa: BLE001
        operation.state = "failed"
        operation.current_job_id = ""
        operation.failed += 1
        if operation.current_application_id:
            application_id = operation.current_application_id
            app = store.get(application_id)
            attention_mod.record(operation.attention, application_id, f"{app.company} — {app.role}" if app else application_id, "failed", str(exc))
        operation.finished_at = _now()
        _event(operation, "failed", str(exc))
    finally:
        heartbeat_stop.set()
        _unregister(operation)


ControlAction = Literal["pause", "resume", "skip", "cancel", "retry_now", "leave"]


def control(operation_id: str, action: ControlAction, application_id: str = "") -> ApplyOperation:
    """Pause/Resume/Skip/Cancel one operation, or bring one of its waiting fills back
    now (``retry_now``) or leave it to the applicant (``leave``)."""
    with _LOCK:
        operation = _ACTIVE.get(operation_id)
    if operation is None:
        if get(operation_id) is None:
            raise KeyError(operation_id)
        raise RuntimeError("Apply operation is no longer active")
    if operation.state not in {"queued", "running", "paused"}:
        raise RuntimeError("Apply operation is no longer active")
    ctl = _ctl(operation)
    if action in ("retry_now", "leave"):
        application_id = store.app_id(application_id) or application_id
        with _LOCK:
            if not any(w.application_id == application_id for w in operation.waiting):
                raise RuntimeError("That application is not waiting to come back")
            (ctl.retry_now if action == "retry_now" else ctl.leave).add(application_id)
        if action == "retry_now":
            _event(operation, "waiting", "Coming back to it now", application_id)
    elif action == "cancel":
        ctl.cancel.set()
        ctl.hold.set()
        _event(operation, "cancel_requested", "Cancelling…")
    elif action == "pause":
        if operation.action == "find":
            raise RuntimeError("Finding jobs cannot be paused; cancel it instead")
        ctl.pause.set()
        if operation.action == "prepare":
            # Tailoring stops now; a form fill is never left half-done.
            ctl.hold.set()
            with _LOCK:
                operation.state = "paused"
            _event(
                operation,
                "paused_by_user",
                "Paused. Tailoring stopped; Resume starts it again.",
            )
        else:
            _event(operation, "pause_requested", "Pausing after the current application…")
    elif action == "skip":
        ctl.skip.set()
    else:
        ctl.resume.set()
    return operation


def start_review_action(
    source_job_id: str,
    *,
    action: Literal["inspect", "correct"],
    correction: dict[str, Any] | None = None,
) -> ApplyOperation:
    """Schedule one short review action under the same Apply worker ownership (and the
    same profile-switch exclusion as `start`)."""
    with template_ops.LOCK:
        return _start_review_locked(source_job_id, action=action, correction=correction)


def _start_review_locked(
    source_job_id: str,
    *,
    action: Literal["inspect", "correct"],
    correction: dict[str, Any] | None,
) -> ApplyOperation:
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(source_job_id)
    # The one id fills and other review actions claim this row's tab by (`store.app_id`).
    source_job_id = app.source_job_id
    if app.archived_at:
        raise ValueError("Archived applications cannot be inspected or corrected until restored")
    prior = store_models.FillResult.model_validate(app.fill) if app.fill else None
    if prior is None or not prior.browser_target_id:
        raise ValueError("No recorded review tab")
    body = correction or {}
    key = str(body.get("idempotency_key") or "")
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() if key else ""
    if action == "correct":
        if not key:
            raise ValueError("Correction requires an idempotency key")
        with _LOCK:
            for existing in _load().values():
                if (
                    existing.action == "correct"
                    and existing.idempotency_key == f"{source_job_id}:{key}"
                ):
                    if existing.request_body_hash != digest:
                        raise ValueError(
                            "Idempotency key was reused with different correction data"
                        )
                    return existing
    with _LOCK:
        if daily_progress.daily_busy():
            raise RuntimeError("Another Apply workflow owns the browser")
        # Beside a running batch this is fine (its own tab), unless a fill or another
        # review action is on this application's tab right now.
        if _start_refusal(action) or source_job_id in _AT_WORK:
            raise RuntimeError("Another Apply operation owns the browser")
        _AT_WORK.add(source_job_id)
        operation = ApplyOperation(
            operation_id=uuid.uuid4().hex,
            action=action,
            application_ids=[source_job_id],
            total=1,
            current_application_id=source_job_id,
            current_label=f"{app.company} — {app.role}".strip(" —"),
            idempotency_key=f"{source_job_id}:{key}" if key else "",
            request_body_hash=digest,
            held_ids=[source_job_id],
        )
        _register(operation)
    _persist(operation)
    threading.Thread(
        target=logs.call_in_context,
        args=(operation.operation_id, _review_worker, operation, source_job_id, correction),
        name=f"apply-{action}-{operation.operation_id[:8]}",
        daemon=True,
    ).start()
    return operation


def _review_worker(
    operation: ApplyOperation,
    source_job_id: str,
    correction: dict[str, Any] | None,
) -> None:
    from resume_tailor.apply.funnel import review

    operation.state = "running"
    operation.started_at = _now()
    operation.application_started_at = operation.started_at
    try:
        _event(operation, operation.action, "Inspecting recorded review tab", source_job_id)
        if operation.action == "inspect":
            asyncio.run(asyncio.wait_for(review.refresh(source_job_id), timeout=30))
            _event(operation, "review", "Review snapshot updated", source_job_id)
        else:
            assert correction is not None
            asyncio.run(
                asyncio.wait_for(
                    review.correct(
                        source_job_id,
                        snapshot_id=str(correction["snapshot_id"]),
                        field_id=str(correction["field_id"]),
                        expected_state_hash=str(correction["expected_state_hash"]),
                        value=correction.get("value"),
                        option_ids=list(correction.get("option_ids") or []),
                    ),
                    timeout=30,
                )
            )
            _event(operation, "review", "Correction verified", source_job_id)
        operation.completed = 1
        operation.state = "completed"
    except Exception as exc:  # noqa: BLE001
        operation.failed = 1
        operation.state = "completed_with_issues"
        _event(operation, "failed", str(exc), source_job_id)
    finally:
        operation.processed = 1
        operation.finished_at = _now()
        _unclaim(source_job_id)
        _unregister(operation)
