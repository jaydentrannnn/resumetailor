"""Daily discover → screen → tailor orchestration for the apply funnel."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from resume_tailor import config, data, jd, runs, workspace
from resume_tailor.apply import browser, fetch_jd, fill, identity, sources, store
from resume_tailor.apply.screen import screen
from resume_tailor.apply.sources import SourceRow
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import ApplySettings, JobSettings, RunMetadata

_DAILY_LOCK = threading.Lock()

#: Guards `_LIVE` only. Never held across IO — a reader must not block a run.
_PROGRESS_LOCK = threading.Lock()


class DailyBusyError(RuntimeError):
    """Raised when a daily run is already in progress."""


class DailySummary(BaseModel):
    """Aggregate outcome of one ``run_daily`` invocation."""

    already_running: bool = False
    skipped: bool = False
    reason: str = ""
    date: str = ""
    total_candidates: int = 0
    new_rows: int = 0
    processed: int = 0
    discovered: int = 0
    jd_fetched: int = 0
    needs_browser: int = 0
    screened_out: int = 0
    screened_in: int = 0
    tailored: int = 0
    tailor_failed: int = 0
    reused: int = 0
    ready: int = 0
    skipped_count: int = 0
    fetch_failed: int = 0
    already_known: int = 0
    grouped: int = 0
    prefiltered_out: int = 0
    #: Populated by the unattended batch-submit stage (`_run_batch_submit`), which
    #: only runs when `ApplySettings.auto_submit_max_per_run > 0`.
    submit_attempted: int = 0
    submitted: int = 0
    submit_failed: int = 0
    submit_skipped_no_browser: bool = False
    errors: list[str] = Field(default_factory=list)
    log_path: str = ""


class DailyProgress(BaseModel):
    """Live view of the in-flight (or last finished) daily pass.

    Polled by the Apply page; every field is a plain scalar so a reader never
    needs the run's own objects. ``phase`` walks
    ``idle -> discovering -> processing -> done``.
    """

    running: bool = False
    phase: str = "idle"
    source_id: str = ""
    current: str = ""
    processed: int = 0
    total: int = 0
    dry_run: bool = False
    started_at: str = ""
    finished_at: str = ""
    date: str = ""
    summary: DailySummary | None = None


#: Mutable backing store for `daily_status`, swapped field-by-field under
#: `_PROGRESS_LOCK`. Holds a reference to the run's live `DailySummary` so
#: counters read through without copying on every poll.
_LIVE = DailyProgress()


def daily_busy() -> bool:
    """True when a daily run holds ``_DAILY_LOCK``."""
    return _DAILY_LOCK.locked()


def _progress_set(**fields: Any) -> None:
    """Patch the live progress record under `_PROGRESS_LOCK`."""
    with _PROGRESS_LOCK:
        for key, value in fields.items():
            setattr(_LIVE, key, value)


def daily_status() -> DailyProgress:
    """Return a snapshot of daily-run progress, safe to serialise.

    The snapshot is a deep copy: `summary` is mutated in place by a running
    pass, so handing out the live object would let counters change mid-response.
    """
    with _PROGRESS_LOCK:
        snapshot = _LIVE.model_copy(deep=True)
    # `running` is authoritative from the lock, not from a field a crashed run
    # might have left set.
    snapshot.running = daily_busy()
    return snapshot


def _today() -> str:
    """Return today's UTC date as ``YYYY-MM-DD``."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _log_path(date: str) -> Path:
    """Path for the daily text log under ``APPLICATIONS_OUTPUT_DIR``."""
    config.APPLICATIONS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return config.APPLICATIONS_OUTPUT_DIR / f"log-{date}.txt"


def _append_log(path: Path, line: str, log: Callable[[str], None]) -> None:
    """Write one line to the daily log file and the live logger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    log(line)


def _application_from_row(
    row: SourceRow,
    *,
    canonical_key: str,
    group_key: str,
    final_url: str,
) -> store.Application:
    """Build a new ``Application`` record from one parsed README row."""
    ref = store.SourceRef(
        source=row.source_id or "simplify",
        source_job_id=row.job_id or "",
        url=row.application_link or "",
        first_seen=_now_iso(),
    )
    return store.Application(
        source=row.source_id or "simplify",
        source_job_id=row.job_id or "",
        company=row.company,
        role=row.role,
        location=row.location,
        posting_url=row.application_link or "",
        final_url=final_url,
        sponsorship_ok=row.sponsorship_ok,
        citizenship_required=row.citizenship_required,
        notes=row.notes,
        discovered_at=_now_iso(),
        canonical_key=canonical_key,
        group_key=group_key,
        source_refs=[ref],
        age_days=row.age_days,
        salary=row.salary,
        eligibility_flags=list(row.flags),
    )


def _save_jd(source_job_id: str, text: str) -> str:
    """Persist JD text beside other application artifacts; return the path."""
    out_dir = config.APPLICATIONS_OUTPUT_DIR / source_job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "jd.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _prior_company(job_id: str) -> str:
    """Read company name from a prior run's ``run.json`` metadata."""
    run_path = config.OUTPUT_DIR / "jobs" / job_id / "run.json"
    if not run_path.is_file():
        return ""
    try:
        raw = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    metadata = raw.get("metadata") or {}
    return str(metadata.get("company") or "")


def _link_reused_packet(app: store.Application, prior_job_id: str) -> None:
    """Point ``app`` at an existing tailoring run without re-queueing."""
    app.reused_from_job_id = prior_job_id
    app.job_id = prior_job_id
    store.set_status(app, "ready", note=f"reused tailoring from {prior_job_id}")


def _job_settings(base: JobSettings, apply: ApplySettings) -> JobSettings:
    """Merge apply funnel knobs into workspace defaults for one tailor run."""
    settings = base.model_copy(deep=True)
    if apply.cover_letter:
        settings.cover_letter = True
        settings.no_cover_letter = False
    return settings


def _wait_for_job(job_id: str, *, timeout_sec: float = 3600.0, poll_sec: float = 0.5):
    """Poll the process queue until ``job_id`` reaches a terminal status."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        job = get_queue().get(job_id)
        if job is not None and job.status in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(poll_sec)
    return get_queue().get(job_id)


def _summary_to_dict(summary: DailySummary) -> dict[str, Any]:
    """Convert a summary model to the legacy dict shape the API expects."""
    payload = summary.model_dump()
    payload["skipped"] = summary.skipped or summary.already_running
    if summary.already_running:
        payload["reason"] = "already running"
    return payload


def _process_one(
    row: SourceRow,
    *,
    settings: ApplySettings,
    job_defaults: JobSettings,
    resume: data.MasterResume,
    known_tags: list[str],
    allow_browser: bool,
    dry_run: bool,
    log_path: Path,
    log: Callable[[str], None],
    summary: DailySummary,
    index: store.Index,
) -> None:
    """Run the funnel for one newly discovered posting."""
    if not row.job_id:
        summary.skipped_count += 1
        return

    wrapper_or_direct = row.application_link or ""
    final_url = identity.resolve_final_url(wrapper_or_direct) if wrapper_or_direct else ""
    ckey = identity.canonical_key(final_url) if final_url else f"pending:{row.job_id}"
    gkey = identity.group_key(row.company, row.role)
    ref = store.SourceRef(
        source=row.source_id or "simplify",
        source_job_id=row.job_id,
        url=wrapper_or_direct,
        first_seen=_now_iso(),
    )

    if ckey in index.by_canonical:
        existing = index.by_canonical[ckey]
        store.add_source_ref(existing, ref)
        if not dry_run:
            store.upsert(existing)
        summary.already_known += 1
        _append_log(
            log_path,
            f"[merge-ref] {row.company} → {ckey} via {ref.source}",
            log,
        )
        return

    if gkey in index.by_group and index.by_group[gkey]:
        primaries = [
            index.by_canonical[k]
            for k in index.by_group[gkey]
            if k in index.by_canonical
        ]
        primary = next((p for p in primaries if p.job_id), None) or primaries[0]
        app = _application_from_row(
            row, canonical_key=ckey, group_key=gkey, final_url=final_url
        )
        app.duplicate_of = primary.canonical_key or primary.source_job_id
        terminal = {"submitted", "interview", "rejected", "ghosted", "skipped"}
        if primary.status in terminal:
            store.set_status(
                app,
                "skipped",
                note=f"duplicate of {app.duplicate_of} (already applied)",
            )
            if not dry_run:
                store.upsert(app)
            summary.grouped += 1
            summary.skipped_count += 1
            _append_log(
                log_path,
                f"[grouped-skip] {row.company} duplicate_of={app.duplicate_of}",
                log,
            )
            index.by_canonical[ckey] = app
            index.by_source_ref[(ref.source, ref.source_job_id)] = ckey
            index.by_group.setdefault(gkey, []).append(ckey)
            return
        if primary.job_id:
            app.reused_from_job_id = primary.job_id
            app.job_id = primary.job_id
            store.set_status(
                app,
                "ready",
                note=f"same role group as {app.duplicate_of}",
            )
            if not dry_run:
                store.upsert(app)
            summary.grouped += 1
            summary.ready += 1
            summary.reused += 1
            summary.processed += 1
            _append_log(
                log_path,
                f"[grouped-reuse] {row.company} ← {primary.job_id}",
                log,
            )
            index.by_canonical[ckey] = app
            index.by_source_ref[(ref.source, ref.source_job_id)] = ckey
            index.by_group.setdefault(gkey, []).append(ckey)
            return
        # Primary not tailored yet — continue as a normal discovery; first to finish wins.

    app = _application_from_row(
        row, canonical_key=ckey, group_key=gkey, final_url=final_url
    )
    if not dry_run:
        store.set_status(app, "discovered")
        store.upsert(app)
    summary.discovered += 1
    _append_log(
        log_path,
        f"[discovered] {row.company} — {row.role} ({row.job_id})",
        log,
    )
    index.by_canonical[ckey] = app
    index.by_source_ref[(ref.source, ref.source_job_id)] = ckey
    index.by_group.setdefault(gkey, []).append(ckey)

    if dry_run:
        summary.processed += 1
        return

    url = app.posting_url or app.final_url
    if not url:
        store.set_status(app, "skipped", note="no application link")
        store.upsert(app)
        summary.skipped_count += 1
        _append_log(log_path, f"[skipped] {app.company}: no application link", log)
        return

    fetch = fetch_jd.fetch_jd(
        url, allow_browser=allow_browser, canonical_key=ckey
    )
    app.final_url = fetch.final_url or app.final_url
    app.ats = fetch.ats
    if fetch.method == "failed" or len(fetch.text.strip()) < 100:
        store.set_status(app, "needs_browser", note=fetch.error or "jd too short")
        store.upsert(app)
        summary.needs_browser += 1
        _append_log(log_path, f"[needs_browser] {app.company}: {fetch.error}", log)
        summary.processed += 1
        return

    app.jd_text_path = _save_jd(app.source_job_id, fetch.text)
    store.set_status(app, "jd_fetched")
    store.upsert(app)
    summary.jd_fetched += 1

    from resume_tailor.apply import eligibility as eligibility_mod

    elig = eligibility_mod.check_text(fetch.text, settings.eligibility)
    if not elig.passed:
        from resume_tailor.apply.screen import ScreenResult

        app.screen = ScreenResult(
            passed=False, reasons=elig.reasons, flags=elig.flags
        )
        app.eligibility_flags = list(row.flags) + list(elig.flags)
        store.set_status(
            app, "screened_out", note="prefilter: " + "; ".join(elig.reasons)
        )
        store.upsert(app)
        summary.prefiltered_out += 1
        summary.screened_out += 1
        _append_log(
            log_path,
            f"[prefilter] {app.company}: {elig.reasons}",
            log,
        )
        summary.processed += 1
        return
    app.eligibility_flags = list(row.flags) + list(elig.flags)

    try:
        with config.pinned(settings.model_spec):
            requirements = jd.extract_consensus(fetch.text, known_tags=known_tags)
    except Exception as exc:  # noqa: BLE001
        store.set_status(app, "tailor_failed", note=f"extract failed: {exc}")
        store.upsert(app)
        summary.tailor_failed += 1
        summary.errors.append(f"{app.company}: extract {exc}")
        _append_log(log_path, f"[tailor_failed] {app.company}: extract failed: {exc}", log)
        summary.processed += 1
        return

    screen_result = screen(fetch.text, requirements, resume, settings=settings.screen)
    # Carry prefilter flags into the screen result so the queue shows one list.
    screen_result.flags = list(
        dict.fromkeys([*app.eligibility_flags, *screen_result.flags])
    )
    app.screen = screen_result
    if not screen_result.passed:
        store.set_status(app, "screened_out", note="; ".join(screen_result.reasons))
        store.upsert(app)
        summary.screened_out += 1
        _append_log(log_path, f"[screened_out] {app.company}: {screen_result.reasons}", log)
        summary.processed += 1
        return

    store.set_status(app, "screened_in")
    store.upsert(app)
    summary.screened_in += 1

    match = runs.closest_run(fetch.text, requirements)
    if match is not None:
        prior, recommendation, score = match
        prior_company = _prior_company(prior.job_id)
        if (
            recommendation == "reuse"
            and score >= settings.reuse_threshold
            and prior_company.casefold() == app.company.casefold()
        ):
            _link_reused_packet(app, prior.job_id)
            store.upsert(app)
            summary.reused += 1
            summary.ready += 1
            _append_log(
                log_path,
                f"[reuse] {app.company} ← {prior.job_id} (jaccard={score:.2f})",
                log,
            )
            summary.processed += 1
            return

    metadata = RunMetadata(
        posting_url=app.posting_url,
        company=app.company,
        role=app.role,
        source=app.source,
        source_job_id=app.source_job_id,
        ats=app.ats,
    )
    run_settings = _job_settings(job_defaults, settings)
    store.set_status(app, "tailoring")
    store.upsert(app)

    with template_ops.LOCK:
        job, _position = get_queue().submit(
            fetch.text,
            run_settings,
            metadata=metadata,
        )

    app.job_id = job.job_id
    store.upsert(app)
    finished = _wait_for_job(job.job_id)
    if finished is None or finished.status != "succeeded":
        err = finished.error if finished else "timed out waiting for tailor job"
        store.set_status(app, "tailor_failed", note=err or finished.status)
        app.error = err
        store.upsert(app)
        summary.tailor_failed += 1
        summary.errors.append(f"{app.company}: tailor {err}")
        _append_log(log_path, f"[tailor_failed] {app.company}: {err}", log)
    else:
        store.set_status(app, "ready", note=f"tailored as {job.job_id}")
        store.upsert(app)
        summary.tailored += 1
        summary.ready += 1
        _append_log(log_path, f"[ready] {app.company} job={job.job_id}", log)

    summary.processed += 1


def run_daily(
    *,
    settings: ApplySettings | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    allow_browser: bool = True,
    auto_submit_max_per_run: int | None = None,
    log: Callable[[str], None] = print,
) -> DailySummary:
    """Execute one daily discover/screen/tailor pass; idempotent on known ids."""
    if not _DAILY_LOCK.acquire(blocking=False):
        return DailySummary(already_running=True, date=_today(), reason="already running")

    date = _today()
    summary = DailySummary(date=date)
    log_file = _log_path(date)
    summary.log_path = str(log_file)
    _progress_set(
        running=True,
        phase="discovering",
        source_id="",
        current="",
        processed=0,
        total=0,
        dry_run=dry_run,
        started_at=_now_iso(),
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
            _append_log(log_file, "skipped: apply disabled in settings", log)
            return summary
        settings = apply_settings

        resume = data.load()
        known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})

        try:
            from resume_tailor.apply import ats_api

            ats_api.clear_ashby_cache()
        except Exception:  # noqa: BLE001
            pass

        _append_log(log_file, f"=== daily run {date} ===", log)
        all_new: list[sources.SourceRow] = []
        total_candidates = 0
        already_known = 0
        known_ids: set[tuple[str, str]] = set(store.all_ids())
        seen_job_ids: set[str] = {job_id for _src, job_id in known_ids}
        for src in [s for s in settings.sources if s.enabled]:
            _progress_set(phase="discovering", source_id=src.id, current=src.url)
            try:
                readme = sources.fetch_readme(src.url)
                if src.kind == "simplify_html":
                    rows = sources.parse_readme(readme, src.categories)
                elif src.kind == "pipe_table":
                    rows = sources.parse_pipe_table_readme(readme, src.categories)
                else:
                    raise ValueError(f"unknown source kind {src.kind!r}")
                for row in rows:
                    row.source_id = src.id
                filtered = sources.filter_rows(
                    rows,
                    max_age_days=settings.max_age_days,
                    exclude_advanced_degree=settings.exclude_advanced_degree,
                    exclude_citizenship=settings.exclude_citizenship_required,
                    exclude_no_sponsorship=settings.exclude_no_sponsorship,
                    known_ids=known_ids,
                    eligibility=settings.eligibility,
                )
            except NotImplementedError as exc:
                summary.errors.append(f"{src.id}: {exc}")
                _append_log(log_file, f"[source {src.id}] error: {exc}", log)
                continue
            except Exception as exc:  # noqa: BLE001
                summary.errors.append(f"{src.id}: {exc}")
                _append_log(log_file, f"[source {src.id}] error: {exc}", log)
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
            _append_log(
                log_file,
                f"[source {src.id}] candidates={filtered.total_candidates} "
                f"new={len(filtered.new_rows)}",
                log,
            )
        summary.total_candidates = total_candidates
        summary.new_rows = len(all_new)
        summary.already_known = already_known
        _append_log(
            log_file,
            f"candidates={total_candidates} new={len(all_new)}",
            log,
        )

        cap = limit if limit is not None else settings.max_new_per_day
        to_process = all_new[:cap]
        index = store.build_index()
        _progress_set(
            phase="processing",
            source_id="",
            current="",
            processed=0,
            total=len(to_process),
        )

        for position, row in enumerate(to_process):
            _progress_set(
                source_id=row.source_id,
                current=f"{row.company} — {row.role}".strip(" —"),
                processed=position,
            )
            try:
                _process_one(
                    row,
                    settings=settings,
                    job_defaults=job_defaults,
                    resume=resume,
                    known_tags=known_tags,
                    allow_browser=allow_browser,
                    dry_run=dry_run,
                    log_path=log_file,
                    log=log,
                    summary=summary,
                    index=index,
                )
            except Exception as exc:  # noqa: BLE001
                summary.errors.append(f"{row.company}: {exc}")
                _append_log(log_file, f"[error] {row.company}: {exc}", log)

        _progress_set(processed=len(to_process), current="")

        submit_cap = (
            auto_submit_max_per_run
            if auto_submit_max_per_run is not None
            else settings.auto_submit_max_per_run
        )
        _run_batch_submit(
            settings=settings,
            cap=submit_cap,
            dry_run=dry_run,
            log_path=log_file,
            log=log,
            summary=summary,
        )

        _append_log(
            log_file,
            f"done processed={summary.processed} ready={summary.ready} reused={summary.reused}",
            log,
        )
        return summary
    finally:
        _progress_set(
            running=False,
            phase="done",
            source_id="",
            current="",
            finished_at=_now_iso(),
            summary=summary,
        )
        _DAILY_LOCK.release()


def _run_batch_submit(
    *,
    settings: ApplySettings,
    cap: int,
    dry_run: bool,
    log_path: Path,
    log: Callable[[str], None],
    summary: DailySummary,
) -> None:
    """Fill+submit up to ``cap`` ready, auto-submit-eligible applications, oldest first.

    Reuses `fill.fill_application` — the exact function the manual "Open & fill"
    button calls — so there is no separate submit code path to keep in sync. A
    per-item failure is logged and skipped rather than aborting the batch. Workday
    is never eligible regardless of `auto_submit_ats`: `fill.decide_submit_action`
    hard-excludes it.
    """
    if cap <= 0:
        return

    status = browser.browser_status()
    if not status.reachable:
        summary.submit_skipped_no_browser = True
        _append_log(log_path, "[batch-submit] skipped: browser CDP unreachable", log)
        return

    eligible_ats = {a.lower() for a in settings.auto_submit_ats}
    candidates = [
        app
        for app in store.load_all().values()
        if app.status == "ready" and app.ats.lower() in eligible_ats
    ]
    candidates.sort(key=lambda app: app.discovered_at)
    to_submit = candidates[:cap]

    for app in to_submit:
        label = f"{app.company} — {app.role}".strip(" —")
        if dry_run:
            _append_log(log_path, f"[would-submit] {label}", log)
            continue
        summary.submit_attempted += 1
        try:
            result = fill.fill_application(
                app.canonical_key or app.source_job_id, settings=settings
            )
        except Exception as exc:  # noqa: BLE001 - one bad posting must not sink the batch
            summary.submit_failed += 1
            _append_log(log_path, f"[batch-submit] {label}: {exc}", log)
            continue
        if result.status == "submitted":
            summary.submitted += 1
        else:
            summary.submit_failed += 1
        _append_log(log_path, f"[batch-submit] {label}: {result.status}", log)


def retry_application(source_job_id: str) -> store.Application:
    """Re-run the failed step for one application (fetch JD or re-queue tailor).

    Raises:
        KeyError: When ``source_job_id`` is unknown.
        RuntimeError: When the current status has no retry path.
        ValueError: When ``set_status`` rejects a terminal transition.
    """
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(f"unknown application {source_job_id!r}")

    if app.status == "screened_out":
        last_note = ""
        if app.status_history:
            last_note = app.status_history[-1].note or ""
        if last_note.startswith("prefilter:"):
            if not app.jd_text_path or not Path(app.jd_text_path).is_file():
                raise RuntimeError("prefilter retry requires saved jd text")
            jd_text = Path(app.jd_text_path).read_text(encoding="utf-8")
            raw = workspace.load_settings()
            job_defaults = JobSettings.model_validate(raw["defaults"])
            from resume_tailor.apply import eligibility as eligibility_mod

            elig = eligibility_mod.check_text(jd_text, job_defaults.apply.eligibility)
            if not elig.passed:
                from resume_tailor.apply.screen import ScreenResult

                app.screen = ScreenResult(
                    passed=False, reasons=elig.reasons, flags=elig.flags
                )
                store.set_status(
                    app,
                    "screened_out",
                    note="prefilter: " + "; ".join(elig.reasons),
                )
                return store.upsert(app)
            app.eligibility_flags = list(
                dict.fromkeys([*app.eligibility_flags, *elig.flags])
            )
            store.set_status(app, "jd_fetched", note="prefilter cleared on retry")
            return store.upsert(app)

    if app.status == "tailor_failed":
        if not app.jd_text_path or not Path(app.jd_text_path).is_file():
            raise RuntimeError("tailor retry requires saved jd text")
        jd_text = Path(app.jd_text_path).read_text(encoding="utf-8")
        raw = workspace.load_settings()
        job_defaults = JobSettings.model_validate(raw["defaults"])
        settings = _job_settings(job_defaults, job_defaults.apply)
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
        finished = _wait_for_job(job.job_id, timeout_sec=3600.0)
        if finished is None or finished.status != "succeeded":
            err = finished.error if finished else "tailor retry timed out"
            store.set_status(app, "tailor_failed", note=err or "tailor failed")
            app.error = err
            return store.upsert(app)
        store.set_status(app, "ready", note=f"tailored as {job.job_id}")
        return store.upsert(app)

    if app.status in {"discovered", "needs_browser", "jd_fetched"}:
        if not app.posting_url:
            raise RuntimeError("fetch retry requires posting_url")
        result = fetch_jd.fetch_jd(
            app.posting_url,
            allow_browser=True,
            canonical_key=app.canonical_key or None,
        )
        app.final_url = result.final_url
        app.ats = result.ats
        if result.text.strip():
            app.jd_text_path = _save_jd(app.source_job_id, result.text)
            store.set_status(app, "jd_fetched", note=f"retry via {result.method}")
            app.error = None
            return store.upsert(app)
        store.set_status(app, "needs_browser", note=result.error or "empty jd")
        app.error = result.error
        return store.upsert(app)

    raise RuntimeError(f"no retry path for status {app.status!r}")


def try_start_daily(
    *,
    limit: int | None = None,
    dry_run: bool = False,
    max_submissions: int | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Start ``run_daily`` on a daemon thread when not already busy.

    Args:
        limit: Cap on newly discovered rows to process this pass.
        dry_run: Record discoveries only — no JD fetch, tailor, or store writes.
        max_submissions: Overrides ``ApplySettings.auto_submit_max_per_run`` for this run.

    Returns:
        ``(True, None)`` when a new worker was started, else ``(False, summary dict)``.
    """
    if daily_busy():
        return False, _summary_to_dict(DailySummary(already_running=True))

    def _worker() -> None:
        """Background target for a *manual* daily run.

        Passes `settings` explicitly so an on-demand run is not gated by
        `apply.enabled` — that flag gates the nightly scheduler (which calls
        `run_daily()` with no settings). This matches `scripts/apply_daily.py`,
        which has always passed the profile's apply settings in directly.
        """
        try:
            raw = workspace.load_settings()
            apply_settings = JobSettings.model_validate(raw["defaults"]).apply
        except Exception:  # noqa: BLE001 - fall back to the gated path on bad settings
            run_daily(limit=limit, dry_run=dry_run, auto_submit_max_per_run=max_submissions)
            return
        run_daily(
            settings=apply_settings,
            limit=limit,
            dry_run=dry_run,
            auto_submit_max_per_run=max_submissions,
        )

    threading.Thread(target=_worker, name="apply-daily", daemon=True).start()
    return True, None
