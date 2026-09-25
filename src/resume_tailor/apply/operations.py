"""Persistent coordinator for explicit Find, Prepare, and Fill operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from resume_tailor import config, logs, workspace
from resume_tailor.apply import daily, fill, preparation, profile, store, submit_guard
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings, JobSettings

OperationState = Literal[
    "queued", "running", "paused", "completed", "completed_with_issues", "failed", "cancelled", "interrupted"
]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


#: Per-application budget, matching `fill.fill_application`'s own 240s deadline.
_APPLICATION_BUDGET_SEC = 240


def _deadline_iso() -> str:
    """When the current application's fill budget runs out, for the UI's countdown."""
    return datetime.fromtimestamp(
        time.time() + _APPLICATION_BUDGET_SEC, UTC
    ).replace(microsecond=0).isoformat()


class ApplyOperation(BaseModel):
    operation_id: str
    action: Literal["find", "prepare", "fill", "inspect", "correct"]
    state: OperationState = "queued"
    application_ids: list[str] = Field(default_factory=list)
    current_application_id: str = ""
    current_label: str = ""
    stage: str = "queued"
    message: str = ""
    processed: int = 0
    total: int = 0
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
    dry_run: bool = False
    limit: int | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    excluded: dict[str, list[str]] = Field(default_factory=dict)
    idempotency_key: str = ""
    request_body_hash: str = ""


#: Most recent idempotent correction operations kept past the general history cap.
_DURABLE_CORRECTIONS_KEPT = 200

_LOCK = threading.RLock()
_RUN_LOCK = threading.Lock()


@contextmanager
def registry_edit_idle():
    """Exclude explicit and daily Apply workers during a registry mutation."""
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("Another Apply operation is running")
    try:
        with daily.registry_edit_idle():
            yield
    finally:
        _RUN_LOCK.release()
_ACTIVE_ID: str | None = None
_CANCEL = threading.Event()
_RESUME = threading.Event()
_SKIP = threading.Event()
#: The applicant pressed Pause: stop before the next application (never mid-form).
_PAUSE = threading.Event()


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
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({key: value.model_dump() for key, value in operations.items()}, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _persist(operation: ApplyOperation) -> None:
    operation.updated_at = _now()
    with _LOCK:
        operations = _load()
        operations[operation.operation_id] = operation
        # Keep a bounded recent history.
        if len(operations) > 30:
            # Idempotent corrections outlive the general cap so a retried request still
            # dedupes, but are themselves bounded so they cannot grow forever.
            durable = sorted(
                (item for item in operations.values() if item.action == "correct" and item.idempotency_key),
                key=lambda item: item.updated_at, reverse=True,
            )[:_DURABLE_CORRECTIONS_KEPT]
            ordered = sorted(
                (item for item in operations.values() if not (item.action == "correct" and item.idempotency_key)),
                key=lambda item: item.updated_at, reverse=True,
            )[:30]
            operations = {item.operation_id: item for item in [*durable, *ordered]}
        _save(operations)


def _event(operation: ApplyOperation, stage: str, message: str, application_id: str = "") -> None:
    operation.stage = stage
    operation.message = message
    operation.last_activity_at = _now()
    operation.current_action_label = message
    operation.action_started_at = operation.last_activity_at
    step = re.search(r"(?:form|wizard) step (\d+)", message)
    if step:
        operation.current_step = int(step.group(1))
    if application_id and application_id != operation.current_application_id:
        operation.current_step = 0
    operation.events.append({"at": _now(), "stage": stage, "message": message, "application_id": application_id})
    operation.events = operation.events[-100:]
    _persist(operation)


def get(operation_id: str) -> ApplyOperation | None:
    if _ACTIVE_ID is None:
        list_recent()
    with _LOCK:
        return _load().get(operation_id)


def list_recent() -> list[ApplyOperation]:
    with _LOCK:
        operations = _load()
        changed = False
        if _ACTIVE_ID is None:
            for operation in operations.values():
                if operation.state in {"queued", "running", "paused"}:
                    operation.state = "interrupted"
                    operation.message = "Server restarted before this operation finished"
                    operation.finished_at = _now()
                    operation.updated_at = operation.finished_at
                    changed = True
            for app in store.list_applications(status="filling", limit=None):
                fill_result = store.FillResult.model_validate(app.fill) if app.fill else store.FillResult()
                if fill_result.submit_action in {"submit", "auto_submit"} and not fill_result.confirmation:
                    recovered_status = "submit_unconfirmed"
                else:
                    recovered_status = "awaiting_review" if app.fill else "ready"
                store.set_status(app, recovered_status, note="Fill interrupted by server restart")
                store.upsert(app)
        if changed:
            _save(operations)
        values = list(operations.values())
    return sorted(values, key=lambda item: item.updated_at, reverse=True)


def active() -> ApplyOperation | None:
    with _LOCK:
        operation_id = _ACTIVE_ID
    return get(operation_id) if operation_id else None


def _captured_settings(request: ApplyOperationRequest) -> ApplySettings:
    raw = workspace.load_settings()
    settings = JobSettings.model_validate(raw["defaults"]).apply.model_copy(deep=True)
    settings.model_provider = request.model_provider
    settings.model_name = request.model_name.strip()
    settings.auto_submit_enabled = request.auto_submit
    settings.blocker_mode = request.blocker_mode
    return settings


def _effective_model(request: ApplyOperationRequest) -> str:
    """The model the operation's LLM calls will actually use, for the UI label.

    Fill runs on the Apply page's autofill model (the request's provider/model); Find
    and Prepare tailor and screen with the Tailor tab's routing (`daily._job_settings`).
    """
    if request.action == "fill":
        return f"{request.model_provider}:{request.model_name.strip()}"
    from resume_tailor.web.jobs import model_label

    return model_label(JobSettings.model_validate(workspace.load_settings()["defaults"]))


def start(request: ApplyOperationRequest) -> ApplyOperation:
    global _ACTIVE_ID
    if request.action != "find" and not request.application_ids:
        raise ValueError(f"{request.action} requires at least one selected application")
    settings_snapshot = _captured_settings(request)
    selected = list(dict.fromkeys(request.application_ids))
    excluded: dict[str, list[str]] = {}
    if request.action == "fill":
        require_cover = settings_snapshot.cover_letter
        for application_id in selected:
            app = store.get(application_id)
            if app is None:
                excluded[application_id] = ["unknown_application"]
                continue
            if app.archived_at:
                excluded[application_id] = ["archived_application"]
                continue
            eligibility = preparation.check(app, require_cover=require_cover)
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
    if not _RUN_LOCK.acquire(blocking=False):
        current = active()
        label = current.operation_id if current else "unknown"
        raise RuntimeError(f"Apply operation {label} is already active")
    if daily.daily_busy():
        _RUN_LOCK.release()
        raise RuntimeError("Another Apply workflow is already running")
    applicant_snapshot = None
    try:
        if request.action == "fill":
            applicant_snapshot, _seeded = profile.load_profile()
            applicant_snapshot = applicant_snapshot.model_copy(deep=True)
    except Exception:
        _RUN_LOCK.release()
        raise

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
    )
    _CANCEL.clear()
    _RESUME.clear()
    _SKIP.clear()
    _PAUSE.clear()
    with _LOCK:
        _ACTIVE_ID = operation.operation_id
    _persist(operation)
    threading.Thread(
        target=logs.call_in_context,
        args=(operation.operation_id, _worker, operation, request, applicant_snapshot, settings_snapshot),
        name=f"apply-{operation.action}-{operation.operation_id[:8]}",
        daemon=True,
    ).start()
    return operation


def _wait_if_paused(operation: ApplyOperation) -> Literal["resume", "skip", "cancel"]:
    if operation.state != "paused":
        return "resume"
    while not _CANCEL.is_set():
        if _SKIP.wait(timeout=0.25):
            _SKIP.clear()
            operation.state = "running"
            _event(operation, "resumed", "Skipped blocked application")
            return "skip"
        if _RESUME.wait(timeout=0.25):
            _RESUME.clear()
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
    while not _CANCEL.wait(timeout=0.5):
        if not submit_guard.is_paused():
            operation.state = "running"
            _event(operation, "resumed", "Automation resumed")
            return True
    return False


def _worker(
    operation: ApplyOperation, request: ApplyOperationRequest,
    applicant_snapshot: profile.ApplicantProfile | None = None,
    settings_snapshot: ApplySettings | None = None,
) -> None:
    global _ACTIVE_ID
    operation.state = "running"
    operation.started_at = _now()
    _event(operation, "starting", f"Starting {operation.action}")
    heartbeat_stop = threading.Event()
    def heartbeat() -> None:
        while not heartbeat_stop.wait(5):
            operation.heartbeat_at = _now()
            _persist(operation)
    threading.Thread(target=heartbeat, name=f"apply-heartbeat-{operation.operation_id[:8]}", daemon=True).start()
    try:
        settings = settings_snapshot or _captured_settings(request)
        if operation.action == "find":
            _event(operation, "discovering", "Fetching configured job sources")
            result = daily.run_daily(
                settings=settings,
                limit=request.limit,
                dry_run=request.dry_run,
                fetch_only=True,
                auto_submit_max_per_run=0,
                log=lambda message: _event(operation, "discovering", message),
            )
            operation.processed = operation.completed = 1
            if result.errors:
                operation.failed = len(result.errors)
        else:
            for application_id in operation.application_ids:
                if not _wait_while_automation_paused(operation):
                    break
                if _PAUSE.is_set() and not _CANCEL.is_set():
                    _PAUSE.clear()
                    operation.state = "paused"
                    _event(
                        operation,
                        "paused_by_user",
                        "Paused. Resume continues with the next application.",
                    )
                if _CANCEL.is_set() or _wait_if_paused(operation) == "cancel":
                    break
                app = store.get(application_id)
                operation.current_application_id = application_id
                operation.current_step = 0
                operation.current_step_id = ""
                operation.current_step_number = 0
                operation.application_started_at = _now()
                operation.application_deadline_at = _deadline_iso()
                operation.current_label = (
                    f"{app.company} — {app.role}".strip(" —") if app else application_id
                )
                if app is None:
                    operation.failed += 1
                    operation.processed += 1
                    _event(operation, "failed", "Application no longer exists", application_id)
                    continue
                if app.archived_at:
                    operation.excluded[application_id] = ["archived_application"]
                    operation.processed += 1
                    _event(operation, "excluded", "Application is archived", application_id)
                    continue
                try:
                    if operation.action == "prepare":
                        _event(operation, "preparing", "Fetching and tailoring application", application_id)
                        result_app = daily.prepare_application(
                            application_id,
                            settings=settings,
                            on_progress=lambda message, aid=application_id: _event(operation, "preparing", message, aid),
                            force_prepare=request.force_prepare,
                        )
                        if result_app.status == "ready":
                            operation.completed += 1
                        elif result_app.status in daily.RETAINED_TAB_STATUSES:
                            # Prepared fine; the row went back to its open review tab.
                            operation.completed += 1
                            _event(
                                operation, "preparing",
                                f"[ready] packet refreshed; {result_app.status.replace('_', ' ')} tab retained",
                                application_id,
                            )
                        elif result_app.status in {"needs_browser", "screened_out"}:
                            operation.blocked += 1
                        else:
                            operation.failed += 1
                    else:
                        # After a pause, the user has been working in the retained tab
                        # (entering a code, fixing answers); resuming must reuse it
                        # rather than open a new one and discard that work.
                        attempt_mode = request.fill_mode
                        while True:
                            _event(operation, "filling", "Opening application form", application_id)
                            submit_allowed = (
                                request.auto_submit
                                and operation.submitted < settings.auto_submit_max_per_run
                            )
                            result = fill.fill_application(
                                application_id,
                                settings=settings,
                                submit_mode="auto_submit" if submit_allowed else "awaiting_review",
                                fill_mode=attempt_mode,
                                should_cancel=_CANCEL.is_set,
                                on_progress=lambda message, aid=application_id: _event(operation, "filling", message, aid),
                                applicant_profile=applicant_snapshot,
                            )
                            if result.status == "submitted":
                                operation.submitted += 1
                                operation.completed += 1
                                break
                            if result.status == "awaiting_review" and result.ready_to_submit:
                                operation.completed += 1
                                operation.ready_for_review += 1
                                break
                            if result.status in {"awaiting_review", "awaiting_otp"}:
                                operation.blocked += 1
                                operation.needs_input += 1
                                if request.blocker_mode != "pause":
                                    break
                                operation.state = "paused"
                                _event(operation, "blocked", "Application needs your attention", application_id)
                                pause_action = _wait_if_paused(operation)
                                if pause_action == "resume":
                                    operation.blocked -= 1
                                    operation.needs_input -= 1
                                    attempt_mode = "continue"
                                    operation.application_started_at = _now()
                                    operation.application_deadline_at = _deadline_iso()
                                    continue
                                break
                            operation.failed += 1
                            break
                except Exception as exc:  # noqa: BLE001 - one item must not erase batch evidence
                    operation.failed += 1
                    _event(operation, "failed", str(exc), application_id)
                operation.processed += 1
                _persist(operation)

        if _CANCEL.is_set():
            operation.state = "cancelled"
            operation.message = "Cancelled"
        elif operation.failed or operation.blocked:
            operation.state = "completed_with_issues"
        else:
            operation.state = "completed"
        operation.current_application_id = ""
        operation.current_label = ""
        operation.finished_at = _now()
        _event(operation, "done", operation.state.replace("_", " ").title())
    except Exception as exc:  # noqa: BLE001
        operation.state = "failed"
        operation.failed += 1
        operation.finished_at = _now()
        _event(operation, "failed", str(exc))
    finally:
        heartbeat_stop.set()
        with _LOCK:
            _ACTIVE_ID = None
        _RUN_LOCK.release()


def control(
    operation_id: str, action: Literal["pause", "resume", "skip", "cancel"]
) -> ApplyOperation:
    operation = get(operation_id)
    if operation is None:
        raise KeyError(operation_id)
    with _LOCK:
        if operation_id != _ACTIVE_ID or operation.state not in {"queued", "running", "paused"}:
            raise RuntimeError("Apply operation is no longer active")
    if action == "cancel":
        _CANCEL.set()
    elif action == "pause":
        if operation.action == "find":
            raise RuntimeError("Finding jobs cannot be paused; cancel it instead")
        _PAUSE.set()
        _event(operation, "pause_requested", "Pausing after the current application…")
    elif action == "skip":
        _SKIP.set()
    else:
        _RESUME.set()
    return operation


def start_review_action(
    source_job_id: str, *, action: Literal["inspect", "correct"],
    correction: dict[str, Any] | None = None,
) -> ApplyOperation:
    """Schedule one short review action under the same Apply worker ownership."""
    global _ACTIVE_ID
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(source_job_id)
    if app.archived_at:
        raise ValueError("Archived applications cannot be inspected or corrected until restored")
    prior = store.FillResult.model_validate(app.fill) if app.fill else None
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
                if existing.action == "correct" and existing.idempotency_key == f"{source_job_id}:{key}":
                    if existing.request_body_hash != digest:
                        raise ValueError("Idempotency key was reused with different correction data")
                    return existing
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("Another Apply operation owns the browser")
    if daily.daily_busy():
        _RUN_LOCK.release()
        raise RuntimeError("Another Apply workflow owns the browser")
    operation = ApplyOperation(
        operation_id=uuid.uuid4().hex, action=action,
        application_ids=[source_job_id], total=1,
        current_application_id=source_job_id,
        current_label=f"{app.company} — {app.role}".strip(" —"),
        idempotency_key=f"{source_job_id}:{key}" if key else "",
        request_body_hash=digest,
    )
    with _LOCK:
        _ACTIVE_ID = operation.operation_id
    _persist(operation)
    threading.Thread(
        target=logs.call_in_context,
        args=(operation.operation_id, _review_worker, operation, source_job_id, correction),
        name=f"apply-{action}-{operation.operation_id[:8]}", daemon=True,
    ).start()
    return operation


def _review_worker(
    operation: ApplyOperation, source_job_id: str, correction: dict[str, Any] | None,
) -> None:
    global _ACTIVE_ID
    from resume_tailor.apply import review

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
            asyncio.run(asyncio.wait_for(review.correct(
                source_job_id,
                snapshot_id=str(correction["snapshot_id"]),
                field_id=str(correction["field_id"]),
                expected_state_hash=str(correction["expected_state_hash"]),
                value=correction.get("value"),
                option_ids=list(correction.get("option_ids") or []),
            ), timeout=30))
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
        _persist(operation)
        with _LOCK:
            _ACTIVE_ID = None
        _RUN_LOCK.release()
