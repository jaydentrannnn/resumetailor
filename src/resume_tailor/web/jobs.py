"""Bounded job queue for tailoring runs.

Each job enters a context that captures its workspace paths, calibration, backend
routing, vocabulary, and writing style. PDF conversion is serialized in convert.py.

Each job writes into `output/jobs/<job_id>/` so successive runs never overwrite each
other's `.docx` / `.pdf`. JD and score caches stay in the shared `config.CACHE_DIR`.
"""

from __future__ import annotations

import logging
import queue
import shutil
import threading
import traceback
import uuid
from contextlib import suppress

from resume_tailor import config, workspace
from resume_tailor.content import data, industries
from resume_tailor.infra import housekeeping, logs, model_queue
from resume_tailor.pipeline.events import ProgressEvent
from resume_tailor.web.schemas import (
    JobSettings,
    RunMetadata,
)

from . import job_outputs, job_tailor_run, job_types

logger = logging.getLogger(__name__)


class JobQueue:
    """Process-wide queue that dispatches up to the configured concurrent jobs."""

    #: Retained job records are never pruned by time — a long-running server process
    #: (this is a `daemon` background thread with no natural end) would otherwise grow
    #: `_jobs` without bound: every job keeps its full `jd_text` (up to 50k chars),
    #: every progress event (including a full traceback on failure), and its final
    #: report forever. Pruned opportunistically in `submit`, oldest terminal job first,
    #: the same way `template_uploads._prune_upload_cache` runs opportunistically rather
    #: than on a timer.
    _MAX_RETAINED_JOBS = 50

    def __init__(self) -> None:
        """Create an empty queue. The worker thread starts on the first `submit`."""
        self._jobs: dict[str, job_types.Job] = {}
        self._pending: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._active = 0
        self._worker: threading.Thread | None = None
        self._order: list[str] = []  # job ids still waiting, in queue order

    def submit(
        self,
        jd_text: str,
        settings: JobSettings,
        metadata: RunMetadata | None = None,
    ) -> tuple[job_types.Job, int]:
        """Enqueue a run. Returns `(job, 1-based queue position)`."""
        job_id = uuid.uuid4().hex[:12]
        workspace_id = config.active_workspace_id()
        target_field = workspace.load_settings(workspace_id).get("target_field")
        resume = None
        if target_field is not None:
            # The pipeline still reports source errors in the normal job flow.
            with suppress(FileNotFoundError, ValueError):
                resume = data.load()
        guidance = industries.capture(
            target_field,
            {"rewrite": settings.rewrite_style, "expand": settings.expand_style,
             "cover": settings.cover_style},
            workspace_id=workspace_id, resume=resume,
        )
        job = job_types.Job(
            job_id=job_id,
            jd_text=jd_text,
            settings=settings.model_copy(deep=True),
            workspace_id=workspace_id,
            metadata=metadata,
            guidance=guidance,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._ensure_worker()
            self._prune_old_jobs()
        self._pending.put(job_id)
        return job, self.queue_position(job_id)

    def _prune_old_jobs(self) -> None:
        """Drop the oldest terminal jobs once retained history exceeds
        `_MAX_RETAINED_JOBS`. Never touches a queued/running job. Caller must already
        hold `self._lock`; `self._jobs` is a plain dict, so insertion order (Python
        3.7+) already reflects submission order without a separate tracking list —
        `job_id` is a fresh uuid every call, so no key is ever reinserted out of order.
        """
        excess = len(self._jobs) - self._MAX_RETAINED_JOBS
        if excess <= 0:
            return
        terminal_ids = [
            jid for jid, job in self._jobs.items() if job.status in ("succeeded", "failed")
        ]
        for jid in terminal_ids[:excess]:
            del self._jobs[jid]

    def get(self, job_id: str) -> job_types.Job | None:
        """Look up a job by id, or None if it was never submitted."""
        return self._jobs.get(job_id)

    def iter_jobs(self) -> list[job_types.Job]:
        """Snapshot of every retained in-memory job (for history overlay)."""
        with self._lock:
            return list(self._jobs.values())

    def queue_position(self, job_id: str) -> int:
        """1-based position among still-waiting jobs, or 0 if already running/done."""
        with self._lock:
            try:
                return self._order.index(job_id) + 1
            except ValueError:
                return 0

    def busy(self) -> bool:
        """True when any job is queued or running (template must not swap mid-run)."""
        with self._lock:
            return any(j.status in ("queued", "running") for j in self._jobs.values())

    def cancel(self, job_id: str) -> job_types.Job | None:
        """Request cancellation of a queued or running job.

        A queued job is cancelled immediately — the worker thread hasn't touched it —
        by pulling it out of `self._order` and marking it terminal directly here.
        `_run_loop` still eventually dequeues its id from `self._pending` (a plain
        `queue.Queue` has no way to remove an item early) but skips it once the status
        is no longer "queued". A running job only has its `cancel_requested` flag set:
        `_execute` notices it at the next checkpoint between pipeline stages, not
        mid-LLM-call, so the job may keep running briefly after this returns. Returns
        `None` (nothing to cancel) if the job doesn't exist or is already terminal.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status == "queued":
                if job_id in self._order:
                    self._order.remove(job_id)
                job.status = "cancelled"
                job.emit(
                    ProgressEvent(
                        stage="cancel", message="Cancelled before it started.", detail={}
                    )
                )
                self._idle.notify_all()
                return job
            if job.status == "running":
                job.cancel_requested.set()
                return job
            return None

    def remove_from_history(self, job_id: str) -> str | None:
        """Delete a finished run's artifacts and drop it from memory.

        Returns ``None`` on success, or a short reason when the run cannot be removed.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status in ("queued", "running"):
                return "still active"
            if job_id in self._jobs:
                del self._jobs[job_id]
            if job_id in self._order:
                self._order.remove(job_id)

        output_dir = (
            config.workspace_paths(job.workspace_id)["OUTPUT_DIR"]
            if job is not None and job.workspace_id is not None
            else config.OUTPUT_DIR
        )
        out_dir = output_dir / "jobs" / job_id
        if not out_dir.exists():
            return "not found"
        try:
            shutil.rmtree(out_dir)
        except OSError as exc:
            return str(exc)
        return None

    def _ensure_worker(self) -> None:
        """Start the background worker once, on first submit."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run_loop, name="job-worker", daemon=True)
        self._worker.start()

    def _run_loop(self) -> None:
        """Dispatch waiting jobs when their requested concurrency has room."""
        while True:
            job_id = self._pending.get()
            with self._idle:
                job = self._jobs.get(job_id)
                while job is not None and job.status == "queued" and (
                    self._active >= job.settings.max_concurrent_jobs
                ):
                    self._idle.wait()
                if job is None or job.status != "queued":
                    continue
                if job_id in self._order:
                    self._order.remove(job_id)
                self._active += 1
                job.status = "running"
                job.emit(
                    ProgressEvent(stage="start", message="Starting tailoring run", detail={})
                )
            threading.Thread(
                target=config.run_in_context(self._run_job),
                args=(job,), name=f"job-{job_id}", daemon=True,
            ).start()

    def _run_job(self, job: job_types.Job) -> None:
        """Finish one dispatched job and release its queue slot."""
        try:
            try:
                logs.call_in_context(job.job_id, self._execute, job)
                job_outputs._persist_run_record(job, "succeeded")
                job.status = "succeeded"
                try:
                    from resume_tailor.apply.funnel import packet as apply_packet

                    context = (
                        config.context_for_workspace(job.workspace_id)
                        if job.workspace_id is not None else config.default_context()
                    )
                    with config.use_context(context):
                        apply_packet.write_packet(job.job_id)
                except Exception as exc:  # noqa: BLE001 - never fail a finished run
                    job.emit(
                        ProgressEvent(
                            stage="packet",
                            message=f"Packet build failed: {exc}",
                            detail={},
                        )
                    )
            except job_types.JobCancelled:
                job.emit(ProgressEvent(stage="cancel", message="Run cancelled.", detail={}))
                job_outputs._persist_run_record(job, "cancelled")
                job.status = "cancelled"
            except BaseException as exc:  # noqa: BLE001 - surface any failure to the UI
                # `Exception` alone left a `SystemExit`/`KeyboardInterrupt`/
                # `RecursionError`-flavoured failure with the job frozen at "running"
                # forever: `busy()` scans for exactly that status, so every mutating
                # route (template upload, workspace switch, library writes) would 409
                # permanently until the process restarted, with no way to clear it.
                # Marking the job failed before re-raising un-wedges `busy()`
                # immediately; re-raising still lets the worker thread die for a
                # genuine `BaseException`, but `_ensure_worker` already respawns on
                # the next `submit()` since it checks `is_alive()`.
                job.error = str(exc)
                job.emit(
                    ProgressEvent(
                        stage="error",
                        message=str(exc),
                        detail={"traceback": traceback.format_exc()},
                    )
                )
                try:
                    job_outputs._persist_run_record(job, "failed")
                finally:
                    job.status = "failed"
                if not isinstance(exc, Exception):
                    raise
            context = (
                config.context_for_workspace(job.workspace_id)
                if job.workspace_id is not None else config.default_context()
            )
            with config.use_context(context):
                housekeeping.run()
        finally:
            with self._idle:
                self._active -= 1
                self._idle.notify_all()

    def _execute(self, job: job_types.Job) -> None:
        """Run one job in its workspace context."""
        context = (
            config.context_for_workspace(job.workspace_id)
            if job.workspace_id is not None else config.default_context()
        )
        with config.use_context(context), model_queue.observe(job.emit, job.check_cancelled):
            industries.bind(job.guidance)
            self._execute_in_context(job)

    def _execute_in_context(self, job: job_types.Job) -> None:
        """Run one job end-to-end. Mutates `job` with events and a final report."""
        job_tailor_run._TailorJobRun(job).run()


#: Process-wide queue. One instance is enough for a single-user tool.
queue_singleton = JobQueue()


def get_queue() -> JobQueue:
    """Return the process-wide job queue."""
    return queue_singleton
