"""Discovering, filtering and batching source rows for a nightly or Find jobs run."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from resume_tailor import config
from resume_tailor.apply.discovery import (
    identity,
    source_filters,
    source_rows,
    source_status,
    sources,
)
from resume_tailor.apply.funnel import store, store_models
from resume_tailor.content import data
from resume_tailor.web.schemas import ApplySettings, JobSettings

from . import daily_progress, daily_row_run, daily_rows

_ROW_POOL_SIZE = 4

def _source_status_entry(found: int, kept: int, error: str) -> dict[str, object]:
    """One source's row in `source_status.json`; an empty source with no error says so."""
    reason = source_status.short_reason(error) if error else None
    if reason is None and found == 0:
        reason = "No postings found"
    return {"found": found, "kept": kept, "error": reason, "at": daily_rows._now_iso()}

def _discover_new_rows(
    settings: ApplySettings,
    *,
    summary: daily_progress.DailySummary,
    log_file: Path,
    log: Callable[[str], None],
    on_progress: daily_progress.ProgressCallback | None = None,
) -> list[source_rows.SourceRow]:
    """Every enabled source's new rows, deduplicated by job id across sources."""
    all_new: list[source_rows.SourceRow] = []
    total_candidates = 0
    already_known = 0
    known_ids: set[tuple[str, str]] = set(store.all_ids())
    seen_job_ids: set[str] = {job_id for _src, job_id in known_ids}
    # Per-source health for the Sources tab: found = rows the source returned, kept = rows
    # surviving the funnel filters (counted before the already-known dedupe, so a healthy
    # source that has nothing new still reads as working).
    status_entries: dict[str, dict[str, object]] = {}
    enabled_sources = [s for s in settings.sources if s.enabled]
    if on_progress is not None:
        on_progress(daily_progress.FindProgress(phase="discovering", total=len(enabled_sources)))
    for completed, src in enumerate(enabled_sources):
        if on_progress is not None:
            on_progress(daily_progress.FindProgress(
                phase="discovering", processed=completed,
                total=len(enabled_sources), current=src.name or src.id,
            ))
        filtered = _filter_source(
            src, settings, known_ids=known_ids, status_entries=status_entries,
            summary=summary, log_file=log_file, log=log,
        )
        if on_progress is not None:
            on_progress(daily_progress.FindProgress(
                phase="discovering", processed=completed + 1,
                total=len(enabled_sources), current=src.name or src.id,
            ))
        if filtered is None:
            continue
        total_candidates += filtered.total_candidates
        already_known += filtered.already_known
        for row in filtered.new_rows:
            if row.job_id and row.job_id in seen_job_ids:
                already_known += 1
                continue
            if row.job_id:
                seen_job_ids.add(row.job_id)
                known_ids.add((row.source_id, row.job_id))
            all_new.append(row)
        daily_rows._append_log(
            log_file,
            f"[source {src.id}] candidates={filtered.total_candidates} "
            f"new={len(filtered.new_rows)}",
            log,
        )
    if status_entries:
        source_status.record_source_status(status_entries, daily_rows._now_iso())
    summary.total_candidates = total_candidates
    summary.new_rows = len(all_new)
    summary.already_known = already_known
    daily_rows._append_log(
        log_file,
        f"candidates={total_candidates} new={len(all_new)}",
        log,
    )
    return all_new

def _filter_source(
    src: Any,
    settings: ApplySettings,
    *,
    known_ids: set[tuple[str, str]],
    status_entries: dict[str, dict[str, object]],
    summary: daily_progress.DailySummary,
    log_file: Path,
    log: Callable[[str], None],
) -> Any:
    """One source's rows through the funnel filters, recording its health; None when the
    source failed."""
    rows: list[source_rows.SourceRow] = []
    daily_progress._progress_set(
        phase="discovering",
        source_id=src.id,
        current=src.url
        or (f"{src.provider}: {src.query}" if src.kind == "job_search" else ""),
    )
    try:
        rows, source_errors = sources.fetch_source_rows(
            source_filters.with_global_filters(src, settings.source_filters)
        )
        for message in source_errors:
            summary.errors.append(f"{src.id}: {message}")
            daily_rows._append_log(log_file, f"[source {src.id}] {message}", log)
        filtered = sources.filter_rows(
            rows,
            # A source's own limit only widens the funnel-wide one, so a catch-up window
            # reaches watchlists too (and 1 day never shrinks a watchlist below its own 7).
            max_age_days=(
                max(src.max_age_days, settings.max_age_days)
                if src.max_age_days is not None
                else settings.max_age_days
            ),
            exclude_advanced_degree=settings.exclude_advanced_degree,
            exclude_citizenship=settings.exclude_citizenship_required,
            exclude_no_sponsorship=settings.exclude_no_sponsorship,
            known_ids=known_ids,
            eligibility=settings.eligibility,
        )
    except Exception as exc:  # noqa: BLE001 - NotImplementedError included
        summary.errors.append(f"{src.id}: {exc}")
        daily_rows._append_log(log_file, f"[source {src.id}] error: {exc}", log)
        status_entries[src.id] = _source_status_entry(
            len(rows), 0, source_status.failure_reason(exc)
        )
        return None
    status_entries[src.id] = _source_status_entry(
        len(rows),
        len(filtered.new_rows) + filtered.already_known,
        "; ".join(source_errors),
    )
    return filtered

def _rows_to_process(
    all_new: list[source_rows.SourceRow], *, cap: int
) -> list[source_rows.SourceRow]:
    """This run's new rows, up to `cap`. Applications already waiting (found by an
    earlier Find jobs) are the user's to Prepare, so they are never swept in here."""
    return all_new[:cap]

def _process_rows(
    to_process: list[source_rows.SourceRow],
    *,
    settings: ApplySettings,
    job_defaults: JobSettings,
    resume: data.MasterResume,
    known_tags: list[str],
    allow_browser: bool,
    dry_run: bool,
    fetch_only: bool,
    log_file: Path,
    log: Callable[[str], None],
    summary: daily_progress.DailySummary,
    index: store_models.Index,
    on_progress: daily_progress.ProgressCallback | None = None,
) -> None:
    """Run `_process_one` over the rows on a small pool, one role group at a time."""
    index_lock = threading.Lock()
    group_locks: dict[str, threading.Lock] = {}
    if on_progress is not None:
        on_progress(daily_progress.FindProgress(phase="processing", total=len(to_process)))

    def process_row(row: source_rows.SourceRow, prior: Any = None) -> None:
        if prior is not None:
            prior.result()
        group_key = identity.group_key(row.company, row.role)
        with group_locks[group_key]:
            daily_progress._progress_set(
                source_id=row.source_id,
                current=f"{row.company} — {row.role}".strip(" —"),
            )
            try:
                daily_row_run._process_one(
                    row,
                    settings=settings,
                    job_defaults=job_defaults,
                    resume=resume,
                    known_tags=known_tags,
                    allow_browser=allow_browser,
                    dry_run=dry_run,
                    fetch_only=fetch_only,
                    log_path=log_file,
                    log=log,
                    summary=summary,
                    index=index,
                    index_lock=index_lock,
                    include_known=False,
                )
            except Exception as exc:  # noqa: BLE001
                daily_progress._row_error(
                    summary, f"{row.company}: {exc}",
                    store.get(row.job_id) if row.job_id else None,
                )
                daily_rows._append_log(log_file, f"[error] {row.company}: {exc}", log)

    for row in to_process:
        group_locks.setdefault(identity.group_key(row.company, row.role), threading.Lock())
    with ThreadPoolExecutor(max_workers=_ROW_POOL_SIZE) as executor:
        futures = {}
        prior_by_group: dict[str, Any] = {}
        for row in to_process:
            group_key = identity.group_key(row.company, row.role)
            future = config.submit_in_context(
                executor, process_row, row, prior_by_group.get(group_key)
            )
            futures[future] = row
            prior_by_group[group_key] = future
        for completed, future in enumerate(as_completed(futures), start=1):
            future.result()
            daily_progress._progress_set(processed=completed)
            if on_progress is not None:
                row = futures[future]
                on_progress(daily_progress.FindProgress(
                    phase="processing", processed=completed, total=len(to_process),
                    current=f"{row.company} — {row.role}",
                ))
