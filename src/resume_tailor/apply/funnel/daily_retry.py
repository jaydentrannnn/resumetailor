"""Retrying failed applications: classify the failure and re-run fetch, prefilter or tailor;
re-fetch rows stuck at ``needs_browser`` on every Find."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from resume_tailor import workspace
from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.funnel import preparation, store, store_models
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import JobSettings, RunMetadata

from . import daily_row_run, daily_rows

RetryKind = Literal["fetch", "prefilter", "tailor"]

def retry_kind(app: store_models.Application) -> RetryKind | None:
    """Which retry `retry_application` would run for ``app``, or None when it has none.

    The single definition of "retryable": the API serves it per row so the SPA shows a
    Retry button only when one can succeed, labelled by what it actually does.
    """
    if app.status == "screened_out":
        # Any screen-out with saved JD text can be re-judged without a model call
        # (`prefilter_screen` + the stored seniority), so rule fixes reach old rows.
        return "prefilter" if app.jd_text_path else None
    if app.status == "tailor_failed":
        return "tailor"
    if app.capture_stub:
        return None  # only the extension can fetch it: open the job on the board
    if app.status in {"discovered", "needs_browser", "jd_fetched"}:
        return "fetch"
    return None

def _finish_tailor_retry(source_job_id: str, job_id: str) -> None:
    """Background half of a tailor retry: wait for the job, then record its outcome."""
    finished = daily_row_run._wait_for_job(job_id, timeout_sec=3600.0)
    app = store.get(source_job_id)
    # The row may have moved on (manual status change, a newer run) while this waited.
    if app is None or app.job_id != job_id or app.status != "tailoring":
        return
    if finished is None or finished.status != "succeeded":
        err = finished.error if finished else "tailor retry timed out"
        store.set_status(app, "tailor_failed", note=err or "tailor failed")
        app.error = err
    else:
        store.set_status(app, "ready", note=f"tailored as {job_id}")
    store.upsert(app)

def retry_application(source_job_id: str) -> store_models.Application:
    """Re-run the failed step for one application (fetch JD, re-check the eligibility
    prefilter, or re-queue tailoring).

    A tailor retry returns as soon as the job is queued, with the row at ``tailoring``;
    a daemon thread records ``ready`` / ``tailor_failed`` when the job finishes.

    Raises:
        KeyError: When ``source_job_id`` is unknown.
        RuntimeError: When the current status has no retry path.
        ValueError: When ``set_status`` rejects a terminal transition.
    """
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(f"unknown application {source_job_id!r}")
    if app.archived_at:
        raise RuntimeError("cannot retry an archived application")

    kind = retry_kind(app)
    if kind == "prefilter":
        if not app.jd_text_path or not Path(app.jd_text_path).is_file():
            raise RuntimeError("prefilter retry requires saved jd text")
        jd_text = Path(app.jd_text_path).read_text(encoding="utf-8")
        raw = workspace.load_settings()
        job_defaults = JobSettings.model_validate(raw["defaults"])
        seniority = app.screen.seniority if app.screen else ""
        elig = daily_rows.prefilter_screen(
            jd_text, app.role, job_defaults.apply, seniority=seniority
        )
        if not elig.passed:
            app.screen = elig
            store.set_status(
                app,
                "screened_out",
                note="prefilter: " + "; ".join(elig.reasons),
            )
            return store.upsert(app)
        app.eligibility_flags = list(
            dict.fromkeys([*app.eligibility_flags, *elig.flags])
        )
        store.set_status(app, "jd_fetched", note="eligibility cleared on re-check")
        return store.upsert(app)

    if kind == "tailor":
        if not app.jd_text_path or not Path(app.jd_text_path).is_file():
            raise RuntimeError("tailor retry requires saved jd text")
        jd_text = Path(app.jd_text_path).read_text(encoding="utf-8")
        raw = workspace.load_settings()
        job_defaults = JobSettings.model_validate(raw["defaults"])
        settings = daily_rows._job_settings(
            job_defaults, job_defaults.apply, ats=preparation.expansion_ats(app)
        )
        metadata = RunMetadata(
            posting_url=app.posting_url,
            company=app.company,
            role=app.role,
            source=app.source,
            source_job_id=app.source_job_id,
            ats=app.ats,
        )
        store.set_status(app, "tailoring", note="retry tailor")
        with template_ops.LOCK:
            job, _position = get_queue().submit(jd_text, settings, metadata=metadata)
        app.job_id = job.job_id
        app.error = None
        saved = store.upsert(app)
        threading.Thread(
            target=_finish_tailor_retry,
            args=(source_job_id, job.job_id),
            name=f"apply-retry-{source_job_id}",
            daemon=True,
        ).start()
        return saved

    if kind == "fetch":
        return _retry_fetch(app)

    raise RuntimeError(f"no retry path for status {app.status!r}")


def _retry_fetch(app: store_models.Application) -> store_models.Application:
    """Fetch the JD again, then run the no-LLM prefilter on it as Find jobs does, so the
    row lands where a first fetch would have left it: ``jd_fetched``, ``screened_out``,
    ``skipped`` (closed) or ``needs_browser`` again."""
    url, key = daily_rows.fetch_target(app)
    if not url:
        raise RuntimeError("fetch retry requires posting_url")
    result = fetch_jd.fetch_jd(url, allow_browser=True, canonical_key=key)
    app.final_url = result.final_url
    app.ats = result.ats
    if result.closed:
        store.set_status(app, "skipped", note=result.closed)
        app.error = None
        return store.upsert(app)
    if len(result.text.strip()) < daily_rows._MIN_USABLE_JD_CHARS:
        store.set_status(app, "needs_browser", note=result.error or "jd too short")
        app.error = result.error or "jd too short"
        return store.upsert(app)
    daily_rows.save_jd(app, result.text, result.guard)
    app.error = None
    settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
    elig = daily_rows.prefilter_screen(result.text, app.role, settings)
    app.eligibility_flags = list(dict.fromkeys([*app.eligibility_flags, *elig.flags]))
    if not elig.passed:
        app.screen = elig
        store.set_status(app, "screened_out", note="prefilter: " + "; ".join(elig.reasons))
        return store.upsert(app)
    store.set_status(app, "jd_fetched", note=f"retry via {result.method}")
    return store.upsert(app)


#: A row stuck at ``needs_browser`` is fetched again once it has waited this long, until
#: it has failed this many fetches in all; one run re-fetches at most this many rows, in
#: at most this many seconds (no model calls, but a browser read can take a minute).
_REFETCH_AFTER = timedelta(hours=20)
_REFETCH_MAX_FAILURES = 5
_REFETCH_PER_RUN = 40
_REFETCH_BUDGET_S = 15 * 60


def _due_for_refetch(now: datetime) -> list[str]:
    """Registry keys of the stuck rows due another fetch, longest-waiting first.

    The count and time of the row's ``needs_browser`` entries in its history are its
    failed fetches; nothing else is stored."""
    due: list[tuple[str, str]] = []
    for key, app in store.rows_view().items():
        if app.status != "needs_browser" or app.archived_at or app.capture_stub:
            continue
        failed = [change.at for change in app.status_history if change.status == "needs_browser"]
        if len(failed) >= _REFETCH_MAX_FAILURES:
            continue
        last = failed[-1] if failed else ""
        with contextlib.suppress(ValueError, TypeError):  # an unreadable time: due
            if last and datetime.fromisoformat(last) > now - _REFETCH_AFTER:
                continue
        due.append((last, key))
    return [key for _last, key in sorted(due)]


def refetch_stuck(
    *,
    should_cancel: Callable[[], bool] = lambda: False,
    log: Callable[[str], None] = lambda _line: None,
    now: datetime | None = None,
) -> int:
    """Fetch the JD again for rows stuck at ``needs_browser`` (Find jobs and the nightly
    run call this), so a fetch that failed while offline, or before a fetch fix, heals
    without the student pressing Retry. Returns how many rows moved on."""
    started = time.monotonic()
    moved = 0
    for key in _due_for_refetch(now or datetime.now(UTC))[:_REFETCH_PER_RUN]:
        if should_cancel() or time.monotonic() - started > _REFETCH_BUDGET_S:
            break
        try:
            app = retry_application(key)
        except Exception as exc:  # noqa: BLE001 - one row's failure never stops the sweep
            log(f"[refetch] {key}: {exc}")
            continue
        if app.status != "needs_browser":
            moved += 1
        log(f"[refetch] {app.company}: {app.status}")
    return moved
