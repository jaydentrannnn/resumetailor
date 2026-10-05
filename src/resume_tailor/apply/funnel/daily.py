"""Daily discover → screen → tailor orchestration for the apply funnel."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from contextlib import contextmanager

from resume_tailor import workspace
from resume_tailor.apply.discovery import source_rows
from resume_tailor.apply.funnel import store, store_models, store_views
from resume_tailor.content import data
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import ApplySettings, JobSettings

from . import daily_batch, daily_progress, daily_row_run, daily_rows


@contextmanager
def registry_edit_idle():
    """Hold the daily-run gate while changing application archive state."""
    if not daily_progress._DAILY_LOCK.acquire(blocking=False):
        raise RuntimeError("Another Apply workflow is running")
    try:
        yield
    finally:
        daily_progress._DAILY_LOCK.release()


def recover_orphaned_tailoring() -> int:
    """Mark ``tailoring`` rows whose tailor job no longer exists as ``tailor_failed``.

    Tailor jobs live in process memory, so a server restart orphans any row that was
    mid-tailoring; without this it would show "tailoring" forever. Returns the count.
    """
    queue = get_queue()
    recovered = 0
    for app in store_views.list_applications(status="tailoring", limit=None):
        if app.job_id and queue.get(app.job_id) is not None:
            continue
        note = "Tailoring was interrupted by a server restart; prepare again"
        store.set_status(app, "tailor_failed", note=note)
        app.error = note
        store.upsert(app)
        recovered += 1
    return recovered


#: Statuses whose retained browser tab and fill report survive a Prepare again.
RETAINED_TAB_STATUSES = frozenset({"awaiting_review", "awaiting_otp"})


def _heal_missing_expansion(app, settings: ApplySettings):
    """Write the one artifact a finished run lacks instead of re-tailoring it.

    Runs made outside Apply skip expansion by default; re-tailoring the whole run for
    it would cost every pipeline call again, where this costs one expand call. Any
    failure falls through to the normal full Prepare.
    """
    from resume_tailor.apply.funnel import preparation
    from resume_tailor.web import job_followups

    # Any failure leaves the run as it was; the full Prepare below still recovers it.
    with contextlib.suppress(Exception):
        job_followups.generate_expansion(app.job_id)
    return preparation.check(
        app, require_cover=settings.cover_letter, require_acknowledgement=False,
    )


def prepare_application(
    source_job_id: str,
    *,
    settings: ApplySettings,
    on_progress: Callable[[str], None] | None = None,
    force_prepare: bool = False,
    on_job: Callable[[str], None] | None = None,
) -> store_models.Application:
    """Prepare one selected application through the existing fetch/screen/tailor path.

    ``on_job`` is called with the tailor job's id as soon as it is queued, so the Apply
    page can show that job's own progress inside the current item.
    """
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(f"unknown application {source_job_id!r}")
    if app.archived_at:
        raise RuntimeError("cannot prepare an archived application")
    if app.status in store_models.TERMINAL_STATUSES:
        raise RuntimeError(f"cannot prepare terminal application {app.status!r}")
    if app.capture_stub:
        # LinkedIn/Indeed are never fetched server-side; the description arrives when
        # the user opens the job with the browser extension installed.
        raise RuntimeError(
            "This job has no description yet. Open it on the job board with the "
            "ResumeTailor extension installed to capture it."
        )
    from resume_tailor.apply.funnel import preparation

    existing_preparation = preparation.check(
        app, require_cover=settings.cover_letter, require_acknowledgement=False,
    )
    if existing_preparation.reasons == ["missing_expansion"] and not force_prepare:
        existing_preparation = _heal_missing_expansion(app, settings)
    if app.status == "ready" and existing_preparation.eligible and not force_prepare:
        return app
    previous = app.model_copy(deep=True)
    refresh_artifacts = force_prepare or not existing_preparation.eligible

    raw = workspace.load_settings()
    job_defaults = JobSettings.model_validate(raw["defaults"])
    resume = data.load()
    known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})
    row = source_rows.SourceRow(
        company=app.company,
        role=app.role,
        location=app.location,
        application_link=app.posting_url or app.final_url or None,
        source_id=app.source,
        job_id=app.source_job_id,
        age=f"{app.age_days}d" if app.age_days is not None else "0d",
        salary=app.salary,
        flags=list(app.eligibility_flags),
    )
    if app.status != "discovered":
        store.set_status(app, "discovered", note="prepare selected")
        store.upsert(app)
    summary = daily_progress.DailySummary(date=daily_rows._today())
    log_path = daily_rows._log_path(daily_rows._today())
    log = on_progress or (lambda _message: None)
    try:
        daily_row_run._process_one(
            row,
            settings=settings,
            job_defaults=job_defaults,
            resume=resume,
            known_tags=known_tags,
            allow_browser=True,
            dry_run=False,
            log_path=log_path,
            log=log,
            summary=summary,
            index=store.build_index(),
            force_tailor=refresh_artifacts,
            on_job=on_job,
        )
    except Exception as exc:
        daily_rows._settle_failed_prepare(previous, source_job_id, error=str(exc))
        raise
    prepared = store.get(source_job_id)
    assert prepared is not None
    if refresh_artifacts and prepared.status != "ready":
        daily_rows._settle_failed_prepare(previous, source_job_id)
        raise RuntimeError(f"Prepare again failed: {prepared.error or prepared.status}")
    # Only a live hand-off (a tab the user may be working in) survives a refresh. An old
    # ``fill_failed`` describes the previous packet, so the fresh one starts ``ready``.
    if previous.fill and previous.status in RETAINED_TAB_STATUSES:
        prepared.fill = previous.fill
        store.set_status(
            prepared, previous.status, note="Prepared artifacts refreshed; review tab retained"
        )
        store.upsert(prepared)
    return prepared


def run_daily(
    *,
    settings: ApplySettings | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    allow_browser: bool = True,
    auto_submit_max_per_run: int | None = None,
    fetch_only: bool = False,
    log: Callable[[str], None] = print,
) -> daily_progress.DailySummary:
    """Execute one daily discover/screen/tailor pass; idempotent on known ids."""
    if not daily_progress._DAILY_LOCK.acquire(blocking=False):
        return daily_progress.DailySummary(
            already_running=True, date=daily_rows._today(), reason="already running"
        )

    date = daily_rows._today()
    summary = daily_progress.DailySummary(date=date)
    log_file = daily_rows._log_path(date)
    summary.log_path = str(log_file)
    daily_progress._progress_set(
        running=True,
        phase="discovering",
        source_id="",
        current="",
        processed=0,
        total=0,
        dry_run=dry_run,
        fetch_only=fetch_only,
        started_at=daily_rows._now_iso(),
        finished_at="",
        date=date,
        summary=summary,
    )

    try:
        raw = workspace.load_settings()
        job_defaults = JobSettings.model_validate(raw["defaults"])
        apply_settings = settings if settings is not None else job_defaults.apply

        if settings is None and not apply_settings.enabled:
            summary.skipped = True
            summary.reason = "apply disabled"
            daily_rows._append_log(log_file, "skipped: apply disabled in settings", log)
            return summary
        settings = apply_settings

        resume = data.load()
        known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})

        try:
            from resume_tailor.apply.discovery import ats_api

            ats_api.clear_ashby_cache()
        except Exception:  # noqa: BLE001
            pass

        daily_rows._append_log(log_file, f"=== daily run {date} ===", log)
        all_new = daily_batch._discover_new_rows(
            settings, summary=summary, log_file=log_file, log=log
        )
        cap = limit if limit is not None else settings.max_new_per_day
        to_process = daily_batch._rows_to_process(all_new, cap=cap, fetch_only=fetch_only)

        index = store.build_index()
        daily_progress._progress_set(
            phase="processing",
            source_id="",
            current="",
            processed=0,
            total=len(to_process),
        )
        daily_batch._process_rows(
            to_process,
            settings=settings,
            job_defaults=job_defaults,
            resume=resume,
            known_tags=known_tags,
            allow_browser=allow_browser,
            dry_run=dry_run,
            fetch_only=fetch_only,
            log_file=log_file,
            log=log,
            summary=summary,
            index=index,
        )
        daily_progress._progress_set(processed=len(to_process), current="")

        if not fetch_only:
            submit_cap = (
                auto_submit_max_per_run
                if auto_submit_max_per_run is not None
                else settings.auto_submit_max_per_run
            )
            if not settings.auto_submit_enabled:
                submit_cap = 0
            daily_batch._run_batch_submit(
                settings=settings,
                cap=submit_cap,
                dry_run=dry_run,
                log_path=log_file,
                log=log,
                summary=summary,
            )

        daily_rows._append_log(
            log_file,
            f"done processed={summary.processed} ready={summary.ready} reused={summary.reused}",
            log,
        )
        return summary
    finally:
        daily_progress._progress_set(
            running=False,
            phase="done",
            source_id="",
            current="",
            finished_at=daily_rows._now_iso(),
            summary=summary,
        )
        daily_progress._DAILY_LOCK.release()
