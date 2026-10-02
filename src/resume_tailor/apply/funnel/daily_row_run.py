"""Processing one source row end to end: screen, prepare (tailor), and optionally fill."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

from resume_tailor import config
from resume_tailor.apply.discovery import fetch_jd, identity
from resume_tailor.apply.discovery.source_rows import SourceRow
from resume_tailor.apply.funnel import store
from resume_tailor.apply.funnel.screen import screen
from resume_tailor.content import data
from resume_tailor.pipeline import jd, runs
from resume_tailor.web import template_ops
from resume_tailor.web.job_routing import model_routing
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import ApplySettings, JobSettings, RunMetadata

from . import daily_progress, daily_rows


def _wait_for_job(
    job_id: str,
    *,
    timeout_sec: float = 3600.0,
    poll_sec: float = 0.5,
    on_progress: Callable[[str], None] | None = None,
):
    """Poll the process queue until ``job_id`` reaches a terminal status.

    ``on_progress``, when given, is called with the tailor job's latest stage
    message (`Job.events[-1].message`, the same feed the Tailor tab's SSE stream
    reads) each time it changes — so a caller watching a single-request, single-call
    wait (like the Apply funnel's "Fetching and tailoring application") sees which
    pipeline stage it is actually on, instead of one static message for the whole
    multi-minute run.
    """
    deadline = time.monotonic() + timeout_sec
    last_message = ""
    while time.monotonic() < deadline:
        job = get_queue().get(job_id)
        if job is not None:
            if on_progress is not None and job.events:
                message = job.events[-1].message
                if message and message != last_message:
                    last_message = message
                    on_progress(message)
            if job.status in {"succeeded", "failed", "cancelled"}:
                return job
        time.sleep(poll_sec)
    return get_queue().get(job_id)

def _process_one(
    row: SourceRow,
    *,
    settings: ApplySettings,
    job_defaults: JobSettings,
    resume: data.MasterResume,
    known_tags: list[str],
    allow_browser: bool,
    dry_run: bool,
    fetch_only: bool = False,
    log_path: Path,
    log: Callable[[str], None],
    summary: daily_progress.DailySummary,
    index: store.Index,
    index_lock: threading.Lock | None = None,
    force_tailor: bool = False,
    on_job: Callable[[str], None] | None = None,
) -> None:
    """Run the funnel for one newly discovered posting."""
    if not row.job_id:
        daily_progress._bump(summary, "skipped_count")
        return
    _RowRun(
        row,
        settings=settings,
        job_defaults=job_defaults,
        resume=resume,
        known_tags=known_tags,
        allow_browser=allow_browser,
        dry_run=dry_run,
        fetch_only=fetch_only,
        log_path=log_path,
        log=log,
        summary=summary,
        index=index,
        index_lock=index_lock,
        force_tailor=force_tailor,
        on_job=on_job,
    ).run()

class _RowRun:
    """`_process_one` for one row: register it in the shared index (under the lock),
    then fetch its JD, screen it, and reuse a prior run or tailor a new one."""

    def __init__(
        self,
        row: SourceRow,
        *,
        settings: ApplySettings,
        job_defaults: JobSettings,
        resume: data.MasterResume,
        known_tags: list[str],
        allow_browser: bool,
        dry_run: bool,
        fetch_only: bool,
        log_path: Path,
        log: Callable[[str], None],
        summary: daily_progress.DailySummary,
        index: store.Index,
        index_lock: threading.Lock | None,
        force_tailor: bool,
        on_job: Callable[[str], None] | None,
    ) -> None:
        self.row = row
        self.settings = settings
        self.job_defaults = job_defaults
        self.resume = resume
        self.known_tags = known_tags
        self.allow_browser = allow_browser
        self.dry_run = dry_run
        self.fetch_only = fetch_only
        self.log_path = log_path
        self.log = log
        self.summary = summary
        self.index = index
        self.index_lock = index_lock
        self.force_tailor = force_tailor
        self.on_job = on_job

        wrapper_or_direct = row.application_link or ""
        self.final_url = (
            identity.resolve_final_url(wrapper_or_direct) if wrapper_or_direct else ""
        )
        self.ckey = (
            identity.canonical_key(self.final_url) if self.final_url else f"pending:{row.job_id}"
        )
        self.gkey = identity.group_key(row.company, row.role)
        self.ref = store.SourceRef(
            source=row.source_id or "simplify",
            source_job_id=row.job_id,
            url=wrapper_or_direct,
            first_seen=daily_rows._now_iso(),
        )

    def run(self) -> None:
        with self.index_lock or nullcontext():
            app = self._register()
        if app is None:
            return
        fetch = self._fetch_jd(app)
        if fetch is None:
            return
        requirements = self._screen(app, fetch.text)
        if requirements is None:
            return
        if self._reuse_prior_run(app, fetch.text, requirements):
            return
        self._tailor(app, fetch.text)
        self._count("processed")

    def _count(self, *fields: str) -> None:
        for name in fields:
            daily_progress._bump(self.summary, name)

    def _log(self, line: str) -> None:
        daily_rows._append_log(self.log_path, line, self.log)

    # -- registering the row -----------------------------------------------------------

    def _register(self) -> store.Application | None:
        """The application to carry on with, or None when the row is fully handled."""
        index = self.index
        if self.ckey in index.by_canonical:
            return self._merge_known(index.by_canonical[self.ckey])
        if index.by_group.get(self.gkey):
            return self._join_group()
        app = self._discover()
        if self.dry_run or self.fetch_only:
            self._count("processed")
            return None
        return app

    def _add_to_index(self, app: store.Application) -> None:
        index = self.index
        index.by_canonical[self.ckey] = app
        index.by_source_ref[(self.ref.source, self.ref.source_job_id)] = self.ckey
        index.by_group.setdefault(self.gkey, []).append(self.ckey)

    def _merge_known(self, existing: store.Application) -> store.Application | None:
        """Another sighting of a known requisition: record it; carry on only when that
        application is still waiting to be processed."""
        store.add_source_ref(existing, self.ref)
        if self.row.posted_at and not existing.posted_at:
            existing.posted_at = self.row.posted_at
        if not self.dry_run:
            store.upsert(existing)
        if existing.archived_at:
            self._count("already_known")
            return None
        if existing.status == "discovered" and not self.fetch_only and not existing.capture_stub:
            return existing
        self._count("already_known")
        self._log(f"[merge-ref] {self.row.company} → {self.ckey} via {self.ref.source}")
        return None

    def _join_group(self) -> store.Application | None:
        """Same company and role as a known application: skip it when that one is done,
        reuse its tailor run when it has one, else carry on as a normal discovery."""
        row, index, dry_run = self.row, self.index, self.dry_run
        primaries = [
            index.by_canonical[k]
            for k in index.by_group[self.gkey]
            if k in index.by_canonical
        ]
        primary = next((p for p in primaries if p.job_id), None) or primaries[0]
        app = daily_rows._application_from_row(
            row, canonical_key=self.ckey, group_key=self.gkey, final_url=self.final_url
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
            self._count("grouped", "skipped_count")
            self._log(f"[grouped-skip] {row.company} duplicate_of={app.duplicate_of}")
            self._add_to_index(app)
            return None
        if not self.fetch_only and primary.job_id:
            app.reused_from_job_id = primary.job_id
            app.job_id = primary.job_id
            store.set_status(
                app,
                "ready",
                note=f"same role group as {app.duplicate_of}",
            )
            if not dry_run:
                store.upsert(app)
            self._count("grouped", "ready", "reused", "processed")
            self._log(f"[grouped-reuse] {row.company} ← {primary.job_id}")
            self._add_to_index(app)
            return None
        # Primary not tailored yet — continue as a normal discovery; first to finish wins.
        return app

    def _discover(self) -> store.Application:
        row = self.row
        existing_app = store.get(row.job_id) if row.job_id else None
        if existing_app is not None:
            app = existing_app
            if self.final_url and not app.final_url:
                app.final_url = self.final_url
            if self.ckey and not app.canonical_key:
                app.canonical_key = self.ckey
            if self.gkey and not app.group_key:
                app.group_key = self.gkey
        else:
            app = daily_rows._application_from_row(
                row, canonical_key=self.ckey, group_key=self.gkey, final_url=self.final_url
            )
        if not self.dry_run:
            if app.status != "discovered":
                store.set_status(app, "discovered")
            store.upsert(app)
        self._count("discovered")
        self._log(f"[discovered] {row.company} — {row.role} ({row.job_id})")
        self._add_to_index(app)
        return app

    # -- fetch, screen, tailor ---------------------------------------------------------

    def _fetch_jd(self, app: store.Application) -> fetch_jd.FetchResult | None:
        """The posting's JD, saved on the application; None when the row stops here."""
        url = app.posting_url or app.final_url
        if not url:
            store.set_status(app, "skipped", note="no application link")
            store.upsert(app)
            self._count("skipped_count")
            self._log(f"[skipped] {app.company}: no application link")
            return None

        fetch = daily_rows._captured_jd(app) or fetch_jd.fetch_jd(
            url, allow_browser=self.allow_browser, canonical_key=self.ckey
        )
        app.final_url = fetch.final_url or app.final_url
        app.ats = fetch.ats
        if fetch.closed:
            # Checked before screening and tailoring, so a closed job costs no model calls.
            store.set_status(app, "skipped", note=fetch.closed)
            store.upsert(app)
            self._count("skipped_count")
            self._log(f"[closed] {app.company}: {fetch.closed}")
            self._count("processed")
            return None
        if fetch.method == "failed" or len(fetch.text.strip()) < daily_rows._MIN_USABLE_JD_CHARS:
            store.set_status(app, "needs_browser", note=fetch.error or "jd too short")
            store.upsert(app)
            self._count("needs_browser")
            daily_progress._row_attention(
                self.summary, app, "needs_input",
                fetch.error or "Job description unavailable; open this posting in your browser",
            )
            self._log(f"[needs_browser] {app.company}: {fetch.error}")
            self._count("processed")
            return None

        app.jd_text_path = daily_rows._save_jd(app.source_job_id, fetch.text)
        # A prior fetch attempt (nightly run or a per-row retry) may have left `error` set
        # (e.g. "Browser extraction too short (0 chars)"); this fetch succeeded, so that
        # error no longer describes the row's state and must not linger in the UI.
        app.error = None
        store.set_status(app, "jd_fetched")
        store.upsert(app)
        self._count("jd_fetched")
        return fetch

    def _screen(self, app: store.Application, jd_text: str) -> jd.JobRequirements | None:
        """Prefilter, extract and screen; the requirements when the posting passes."""
        elig = daily_rows.prefilter_screen(jd_text, app.role, self.settings)
        if not elig.passed:
            app.screen = elig
            app.eligibility_flags = list(self.row.flags) + list(elig.flags)
            store.set_status(
                app, "screened_out", note="prefilter: " + "; ".join(elig.reasons)
            )
            store.upsert(app)
            self._count("prefiltered_out", "screened_out")
            self._log(f"[prefilter] {app.company}: {elig.reasons}")
            self._count("processed")
            return None
        app.eligibility_flags = list(self.row.flags) + list(elig.flags)

        requirements = self._extract(app, jd_text)
        if requirements is None:
            return None
        screen_result = screen(
            jd_text, requirements, self.resume, settings=self.settings.screen, role=app.role
        )
        # Carry prefilter flags into the screen result so the queue shows one list.
        screen_result.flags = list(
            dict.fromkeys([*app.eligibility_flags, *screen_result.flags])
        )
        app.screen = screen_result
        if not screen_result.passed:
            store.set_status(app, "screened_out", note="; ".join(screen_result.reasons))
            store.upsert(app)
            self._count("screened_out")
            self._log(f"[screened_out] {app.company}: {screen_result.reasons}")
            self._count("processed")
            return None

        store.set_status(app, "screened_in")
        store.upsert(app)
        self._count("screened_in")
        return requirements

    def _extract(self, app: store.Application, jd_text: str) -> jd.JobRequirements | None:
        job_defaults = self.job_defaults
        try:
            # Same routing and vote count as the tailor job below, so its own extraction
            # is a cache hit ("Reusing cached job-description analysis") rather than a
            # second full round of JD reads.
            profile, overrides, effort = model_routing(job_defaults)
            with config.pinned(profile, overrides=overrides, effort=effort):
                return jd.extract_consensus(
                    jd_text,
                    known_tags=self.known_tags,
                    runs=config.extract_runs(job_defaults.extract_runs),
                    use_cache=not job_defaults.no_cache,
                )
        except Exception as exc:  # noqa: BLE001
            store.set_status(app, "tailor_failed", note=f"extract failed: {exc}")
            store.upsert(app)
            self._count("tailor_failed")
            daily_progress._row_error(self.summary, f"{app.company}: extract {exc}", app)
            self._log(f"[tailor_failed] {app.company}: extract failed: {exc}")
            self._count("processed")
            return None

    def _reuse_prior_run(
        self, app: store.Application, jd_text: str, requirements: jd.JobRequirements
    ) -> bool:
        """Link a near-identical earlier run for the same company instead of tailoring."""
        match = None if self.force_tailor else runs.closest_run(jd_text, requirements)
        if match is None:
            return False
        prior, recommendation, score = match
        prior_company = daily_rows._prior_company(prior.job_id)
        if not (
            recommendation == "reuse"
            and score >= self.settings.reuse_threshold
            and prior_company.casefold() == app.company.casefold()
        ):
            return False
        daily_rows._link_reused_packet(app, prior.job_id)
        store.upsert(app)
        self._count("reused", "ready")
        self._log(f"[reuse] {app.company} ← {prior.job_id} (jaccard={score:.2f})")
        self._count("processed")
        return True

    def _tailor(self, app: store.Application, jd_text: str) -> None:
        metadata = RunMetadata(
            posting_url=app.posting_url,
            company=app.company,
            role=app.role,
            source=app.source,
            source_job_id=app.source_job_id,
            ats=app.ats,
        )
        run_settings = daily_rows._job_settings(self.job_defaults, self.settings)
        store.set_status(app, "tailoring")
        store.upsert(app)

        with template_ops.LOCK:
            job, _position = get_queue().submit(
                jd_text,
                run_settings,
                metadata=metadata,
            )

        app.job_id = job.job_id
        store.upsert(app)
        if self.on_job is not None:
            self.on_job(job.job_id)
        finished = _wait_for_job(
            job.job_id,
            on_progress=lambda message: self.log(f"[tailoring] {app.company}: {message}"),
        )
        if finished is None or finished.status != "succeeded":
            err = finished.error if finished else "timed out waiting for tailor job"
            store.set_status(app, "tailor_failed", note=err or finished.status)
            app.error = err
            store.upsert(app)
            self._count("tailor_failed")
            daily_progress._row_error(self.summary, f"{app.company}: tailor {err}", app)
            self._log(f"[tailor_failed] {app.company}: {err}")
        else:
            store.set_status(app, "ready", note=f"tailored as {job.job_id}")
            store.upsert(app)
            self._count("tailored", "ready")
            self._log(f"[ready] {app.company} job={job.job_id}")
