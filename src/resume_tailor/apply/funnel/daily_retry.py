"""Retrying one failed application: classify the failure and re-run tailor or fill."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from resume_tailor import workspace
from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.funnel import store, store_models
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
        settings = daily_rows._job_settings(job_defaults, job_defaults.apply)
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
        if not app.posting_url:
            raise RuntimeError("fetch retry requires posting_url")
        result = fetch_jd.fetch_jd(
            app.posting_url,
            allow_browser=True,
            canonical_key=app.canonical_key or None,
        )
        app.final_url = result.final_url
        app.ats = result.ats
        if result.closed:
            store.set_status(app, "skipped", note=result.closed)
            app.error = None
            return store.upsert(app)
        if len(result.text.strip()) >= daily_rows._MIN_USABLE_JD_CHARS:
            app.jd_text_path = daily_rows._save_jd(app.source_job_id, result.text)
            store.set_status(app, "jd_fetched", note=f"retry via {result.method}")
            app.error = None
            return store.upsert(app)
        store.set_status(
            app, "needs_browser", note=result.error or "jd too short"
        )
        app.error = result.error
        return store.upsert(app)

    raise RuntimeError(f"no retry path for status {app.status!r}")
