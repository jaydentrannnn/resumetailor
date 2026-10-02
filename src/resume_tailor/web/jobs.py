"""Bounded job queue for tailoring runs.

Each job enters a context that captures its workspace paths, calibration, backend
routing, vocabulary, and writing style. PDF conversion is serialized in convert.py.

Each job writes into `output/jobs/<job_id>/` so successive runs never overwrite each
other's `.docx` / `.pdf`. JD and score caches stay in the shared `config.CACHE_DIR`.
"""

from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
import traceback
import uuid
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from resume_tailor import config, workspace
from resume_tailor.content import data, industries, libraries, style
from resume_tailor.content.data import MasterResume
from resume_tailor.document import rerender
from resume_tailor.document.template_profile import active_layout
from resume_tailor.infra import housekeeping, logs
from resume_tailor.infra.llm import LLMError
from resume_tailor.pipeline import (
    bullet_checks,
    coverletter,
    expand,
    facets,
    fit,
    fit_types,
    include,
    jd,
    propose,
    relevance,
    report,
    skills,
)
from resume_tailor.pipeline.events import ProgressCallback, ProgressEvent
from resume_tailor.pipeline.fabrication import FabricationError
from resume_tailor.pipeline.fit_types import FitError
from resume_tailor.web import template_ops
from resume_tailor.web.schemas import (
    CoverAnglesIn,
    CoverLetterOut,
    ExpandedEntryOut,
    ExpansionOut,
    JobSettings,
    KeywordGapOut,
    RunMetadata,
    RunReportOut,
    SectionSummaryOut,
    SkillsPlanOut,
    SkillSuggestionOut,
)

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobCancelled(Exception):
    """Raised internally to unwind `JobQueue._execute` once a user cancels a running
    job. Never escapes `_run_loop` — caught there and translated into the terminal
    "cancelled" status, same as `FabricationError`/`FitError` are translated into
    "failed"."""


@dataclass
class Job:
    """One queued or finished tailoring run, held in memory for the life of the process."""

    job_id: str
    jd_text: str
    settings: JobSettings
    status: JobStatus = "queued"
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    #: Profile that owned this run when it was submitted — needed so `GET /api/jobs`
    #: after a profile switch does not list another workspace's in-memory jobs.
    workspace_id: str | None = None
    #: Optional posting provenance for the apply funnel (URL, company, Simplify id).
    metadata: RunMetadata | None = None
    error: str | None = None
    report: RunReportOut | None = None
    expansion: ExpansionOut | None = None
    skills: SkillsPlanOut | None = None
    cover_letter: CoverLetterOut | None = None
    events: list[ProgressEvent] = field(default_factory=list)
    #: Signalled whenever a new event lands, so the SSE endpoint can wake up.
    event_notify: threading.Event = field(default_factory=threading.Event)
    #: Set by `JobQueue.cancel` on a running job; `_execute` polls it at checkpoints
    #: between pipeline stages (never mid-LLM-call) via `check_cancelled`.
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    out_dir: Path | None = None
    guidance: industries.GuidanceSnapshot | None = None

    def emit(self, event: ProgressEvent) -> None:
        """Append a progress event and wake any SSE listeners."""
        self.events.append(event)
        self.event_notify.set()

    def check_cancelled(self) -> None:
        """Raise `JobCancelled` if this job's cancellation was requested."""
        if self.cancel_requested.is_set():
            raise JobCancelled()


def _jd_title_fallback(jd_text: str) -> str:
    """First non-empty line of the JD, truncated — used when there is no report yet."""
    for line in jd_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return "Untitled run"


def model_routing(
    settings: JobSettings,
) -> tuple[str, dict[str, str] | None, str | None]:
    """``(profile, overrides, effort)`` for `config.resolve`/`config.pinned` from run settings.

    The one place a `JobSettings`' model fields become backend routing — shared by the
    job runner and the Apply funnel's own screening extraction, so Prepare tailors and
    screens with exactly the routing a Tailor-tab run with the same settings would use.
    """
    overrides: dict[str, str] = {}
    # Broadest first: a blanket model name repoints every stage, then origin-specific
    # tags, then per-stage fields overwrite whichever of them they name.
    if settings.model_name:
        for purpose in config.PURPOSES:
            overrides[purpose] = settings.model_name
    if settings.ollama_model:
        for purpose in config.provider_stages(settings.model, "ollama"):
            overrides[purpose] = settings.ollama_model
    if settings.gemini_model:
        for purpose in config.provider_stages(settings.model, "gemini"):
            overrides[purpose] = settings.gemini_model
    if settings.rewrite_model:
        overrides["rewrite"] = settings.rewrite_model
    if settings.expand_model:
        overrides["expand"] = settings.expand_model
    if settings.skills_model:
        overrides["skills"] = settings.skills_model
    if settings.cover_model:
        overrides["cover"] = settings.cover_model
    if settings.review_model:
        overrides["review"] = settings.review_model
    if settings.answer_model:
        overrides["answer"] = settings.answer_model
    return settings.model, overrides or None, settings.effort


def model_label(settings: JobSettings) -> str:
    """Short ``provider:model`` label for the routing `model_routing` produces.

    Names the rewrite stage's backend (the one a tailoring run spends most calls on),
    suffixed ``+ stage overrides`` when other tailoring stages route elsewhere. A spec
    that doesn't resolve falls back to the raw profile string rather than raising — this
    is a display label, and the run itself reports the real error.
    """
    profile, overrides, effort = model_routing(settings)
    try:
        with config.pinned(profile, overrides=overrides, effort=effort) as backends:
            labels = {p: b.label() for p, b in backends.items() if p != "answer"}
    except ValueError:
        return settings.model
    label = labels["rewrite"]
    if len(set(labels.values())) > 1:
        label += " + stage overrides"
    return label


def _persist_run_record(job: Job, status: str | None = None) -> None:
    """Write `out_dir/run.json` so history and downloads survive a process restart.

    Called with the terminal status *before* it is published on `job.status`, so a
    client that sees the job finish can always find its record (succeeded / failed /
    cancelled). No-op when `out_dir` was never created (cancel-while-queued).
    """
    if job.out_dir is None:
        return
    title = job.report.title if job.report else _jd_title_fallback(job.jd_text)
    record = {
        "job_id": job.job_id,
        "workspace_id": job.workspace_id,
        "created_at": job.created_at,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": status or job.status,
        "title": title,
        "error": job.error,
        "report": job.report.model_dump() if job.report else None,
        "metadata": job.metadata.model_dump() if job.metadata else None,
        "guidance": ({
            "target_field": job.guidance.target_field,
            "version": job.guidance.version,
            "fingerprint": job.guidance.fingerprint(),
            "styles": {
                stage: "custom" if text is not None else "default"
                for stage, text in job.guidance.styles.items()
            },
        } if job.guidance else None),
    }
    try:
        job.out_dir.mkdir(parents=True, exist_ok=True)
        (job.out_dir / "run.json").write_text(
            json.dumps(record, indent=2),
            encoding="utf-8",
        )
    except OSError:
        # Persistence is best-effort — a full disk must not turn a successful run into
        # a failed one after the .docx is already written.
        pass


class JobQueue:
    """Process-wide queue that dispatches up to the configured concurrent jobs."""

    #: Retained job records are never pruned by time — a long-running server process
    #: (this is a `daemon` background thread with no natural end) would otherwise grow
    #: `_jobs` without bound: every job keeps its full `jd_text` (up to 50k chars),
    #: every progress event (including a full traceback on failure), and its final
    #: report forever. Pruned opportunistically in `submit`, oldest terminal job first,
    #: the same way `template_ops._prune_upload_cache` runs opportunistically rather
    #: than on a timer.
    _MAX_RETAINED_JOBS = 50

    def __init__(self) -> None:
        """Create an empty queue. The worker thread starts on the first `submit`."""
        self._jobs: dict[str, Job] = {}
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
    ) -> tuple[Job, int]:
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
        job = Job(
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

    def get(self, job_id: str) -> Job | None:
        """Look up a job by id, or None if it was never submitted."""
        return self._jobs.get(job_id)

    def iter_jobs(self) -> list[Job]:
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

    def cancel(self, job_id: str) -> Job | None:
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

    def _run_job(self, job: Job) -> None:
        """Finish one dispatched job and release its queue slot."""
        try:
            try:
                logs.call_in_context(job.job_id, self._execute, job)
                _persist_run_record(job, "succeeded")
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
            except JobCancelled:
                job.emit(ProgressEvent(stage="cancel", message="Run cancelled.", detail={}))
                _persist_run_record(job, "cancelled")
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
                    _persist_run_record(job, "failed")
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

    def _execute(self, job: Job) -> None:
        """Run one job in its workspace context."""
        context = (
            config.context_for_workspace(job.workspace_id)
            if job.workspace_id is not None else config.default_context()
        )
        with config.use_context(context):
            industries.bind(job.guidance)
            self._execute_in_context(job)

    def _execute_in_context(self, job: Job) -> None:
        """Run one job end-to-end. Mutates `job` with events and a final report."""
        _TailorJobRun(job).run()


class _TailorJobRun:
    """One tailoring job's pipeline, in the active workspace context.

    The core stages (`_extract` → `_score` → `_select_facets` → `_fit`) raise
    `RuntimeError` on failure; the bonus artifacts after them (expansion, skills, cover
    letter, vocabulary proposals) report a progress event and never fail the job.
    """

    out_dir: Path
    resume: MasterResume
    full_resume: MasterResume
    master_resume: MasterResume
    known_tags: list[str]
    requirements: jd.JobRequirements
    result: fit_types.FitResult

    def __init__(self, job: Job) -> None:
        self.job = job
        self.settings = job.settings
        self.on_event: ProgressCallback = job.emit

    def run(self) -> None:
        job, settings = self.job, self.settings
        self._prepare()
        self._extract()
        job.check_cancelled()
        self._score()
        # Kept unfiltered for `expand.expand_experience` below — an excluded job still
        # appears in the application-form paste tile, per its own decision. Applied here
        # (after scoring, before facets) so an exclusion toggle never invalidates the
        # score cache, and so facets never sees a pool an excluded entry contributed to.
        self.full_resume = self.resume
        self.resume = include.apply(self.resume, settings.include)

        job.check_cancelled()
        self._select_facets()
        job.check_cancelled()
        self._fit()
        self._ensure_pdf()
        job.report = _to_report_out(
            report.report_data(
                self.resume, self.requirements, self.result, master=self.master_resume
            )
        )
        self._write_run_files()

        job.check_cancelled()
        if not settings.no_expand:
            self._expand()
        job.check_cancelled()
        if not settings.no_skills:
            self._select_skills()
        job.check_cancelled()
        if settings.cover_letter and not settings.no_cover_letter:
            self._draft_cover_letter()
        job.check_cancelled()
        if settings.suggest_vocabulary:
            self._suggest_vocabulary()

    def _emit(self, stage: str, message: str, **detail: object) -> None:
        self.on_event(ProgressEvent(stage=stage, message=message, detail=detail))

    # -- core stages -------------------------------------------------------------------

    def _prepare(self) -> None:
        job, settings = self.job, self.settings
        # Create the job directory first so a failure during extract/score still leaves
        # a place for `run.json` — history needs something on disk even for failed runs.
        self.out_dir = config.OUTPUT_DIR / "jobs" / job.job_id
        self.out_dir.mkdir(parents=True, exist_ok=True)
        job.out_dir = self.out_dir
        industries.save(job.guidance, self.out_dir)
        job.check_cancelled()

        try:
            profile, overrides, effort = model_routing(settings)
            config.resolve(profile, overrides=overrides, effort=effort)
            style.activate(
                rewrite=settings.rewrite_style,
                expand=settings.expand_style,
                cover=settings.cover_style,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        self.resume = data.load()
        self.known_tags = sorted({t for b in self.resume.all_bullets() for t in b.tags})
        job.check_cancelled()

    def _extract(self) -> None:
        job, settings, out_dir = self.job, self.settings, self.out_dir
        try:
            self.requirements = jd.extract_consensus(
                job.jd_text,
                known_tags=self.known_tags,
                runs=config.extract_runs(settings.extract_runs),
                use_cache=not settings.no_cache,
                on_event=self.on_event,
            )
        except (ValueError, RuntimeError, LLMError) as exc:
            raise RuntimeError(str(exc)) from exc

        (out_dir / "jd.txt").write_text(job.jd_text, encoding="utf-8")
        (out_dir / "requirements.json").write_text(
            self.requirements.model_dump_json(indent=2),
            encoding="utf-8",
        )
        paraphrased = jd.verify_verbatim(self.requirements, job.jd_text)
        if paraphrased:
            self._emit(
                "extract",
                "Some extracted phrases are not verbatim from the posting",
                paraphrased=paraphrased,
            )

    def _score(self) -> None:
        settings = self.settings
        self.semantic: dict[str, float] | None = None
        if settings.no_semantic:
            return
        try:
            self.semantic = relevance.score_table(
                self.resume.all_bullets(),
                self.requirements,
                use_cache=not settings.no_cache,
                on_event=self.on_event,
            )
        except LLMError as exc:
            raise RuntimeError(str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            self._emit(
                "score", f"Semantic scoring unavailable; ranking on keywords only ({exc})"
            )

    def _select_facets(self) -> None:
        settings, resume, requirements = self.settings, self.resume, self.requirements
        self.include_links = not settings.no_project_links
        try:
            if settings.no_facets:
                facet_result = facets.budget_only(
                    resume, requirements, include_project_links=self.include_links
                )
            else:
                facet_result = facets.select_facets(
                    resume,
                    requirements,
                    use_cache=not settings.no_cache,
                    include_project_links=self.include_links,
                    on_event=self.on_event,
                )
        except LLMError as exc:
            raise RuntimeError(str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            self._emit(
                "facets",
                f"Facet selection unavailable; truncating pools in original order ({exc})",
            )
            facet_result = facets.budget_only(
                resume, requirements, include_project_links=self.include_links
            )
        for warning in facet_result.warnings:
            self._emit("facets", warning)
        self.facet_result = facet_result
        # Captured before the rebind: facets.apply truncates Project.tech to its render
        # budget, and report.diagnose_gaps needs the untruncated pool to find evidence there.
        self.master_resume = resume
        self.resume = facets.apply(resume, facet_result)

    def _fit(self) -> None:
        settings = self.settings
        self.out_path = self.out_dir / "tailored.docx"
        self.layout = active_layout()
        self.contact_fields = include.contact_order(settings.include, self.layout)

        self.job.check_cancelled()
        try:
            self.result = fit.fit(
                self.resume,
                self.requirements,
                target_pages=settings.pages,
                out=self.out_path,
                max_experience=settings.experience,
                max_projects=settings.projects,
                semantic=self.semantic,
                repair_widows=not settings.no_widow_repair,
                repair_verbs=not settings.no_verb_repair,
                merge_bullets=settings.merge,
                include_project_links=self.include_links,
                contact_fields=self.contact_fields,
                fill_target=settings.fill_target,
                initial_bullet_share=settings.initial_bullet_share,
                experience_bullet_share=settings.experience_bullet_share,
                max_bullets_per_entry=settings.max_bullets_per_entry,
                coursework_pool=self.facet_result.coursework_pool,
                on_event=self.on_event,
            )
        except FabricationError as exc:
            raise RuntimeError(str(exc)) from exc
        except FitError as exc:
            raise RuntimeError(str(exc)) from exc
        except (FileNotFoundError, RuntimeError) as exc:
            raise RuntimeError(str(exc)) from exc

    def _ensure_pdf(self) -> None:
        # Ensure a PDF sits beside the docx for the preview endpoint. The fit loop already
        # measured one, but a failed measurement leaves only the estimate — regenerate so
        # the UI can still offer a downloadable preview when LibreOffice is available.
        pdf_path = self.out_path.with_suffix(".pdf")
        if pdf_path.exists():
            return
        try:
            from resume_tailor.document import render

            render.to_pdf(self.out_path, pdf_path, keep_active=False)
        except RuntimeError as exc:
            self._emit("render", f"PDF preview unavailable ({exc})")

    def _write_run_files(self) -> None:
        out_dir, result = self.out_dir, self.result
        (out_dir / "bullets.json").write_text(
            json.dumps(result.bullets, indent=2),
            encoding="utf-8",
        )
        (out_dir / "backends.json").write_text(
            json.dumps(config.backend_specs_snapshot(), indent=2),
            encoding="utf-8",
        )
        try:
            # What the final render used, so the student can edit bullets and re-render
            # later without a model call (`rerender.py`).
            rerender.save_snapshot(
                out_dir,
                self.resume,
                target_pages=self.settings.pages,
                include_project_links=self.include_links,
                contact_fields=(
                    list(self.contact_fields) if self.contact_fields is not None else None
                ),
                layout=self.layout,
                merges=result.merges,
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not save the re-render snapshot for %s: %s", self.job.job_id, exc
            )

    # -- bonus artifacts: never fail the job --------------------------------------------

    def _expand(self) -> None:
        job, out_dir = self.job, self.out_dir
        try:
            # Unfiltered resume: an experience entry excluded from the tailored resume
            # still appears in the application-form paste tile.
            expansion = expand.expand_experience(
                self.full_resume,
                self.requirements,
                fit_result=self.result,
                semantic=self.semantic,
                use_cache=not self.settings.no_cache,
                on_event=self.on_event,
            )
            job.expansion = _to_expansion_out(expansion)
            expansion_record = job.expansion.model_dump()
            # Keep durable evidence that an empty expansion truly means there were no
            # source jobs; later profile edits cannot establish this.
            expansion_record["source_experience_count"] = len(self.full_resume.experience)
            (out_dir / "expansion.json").write_text(
                json.dumps(expansion_record, indent=2), encoding="utf-8",
            )
            (out_dir / "expansion.md").write_text(
                expand.format_markdown(expansion), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the job
            self._emit("expand", f"Experience expansion skipped ({exc})")

    def _select_skills(self) -> None:
        job, out_dir = self.job, self.out_dir
        try:
            # `master_resume` (post-include, pre-facets): exactly what
            # `report.diagnose_gaps` above ran against, so the tile's "enter these" and
            # "you can't claim these" halves partition one evidence universe. Not
            # `full_resume` — an excluded entry is the user saying "not part of this
            # application", and a skill evidenced only there should not be suggested for
            # the Skills box of the package actually being submitted. Not the post-facets
            # `resume` — facets truncates Project.tech to its render budget, which would
            # silently drop evidence.
            plan = skills.select_skills(
                self.master_resume,
                self.requirements,
                use_cache=not self.settings.no_cache,
                on_event=self.on_event,
            )
            job.skills = _to_skills_out(plan)
            (out_dir / "skills.json").write_text(
                job.skills.model_dump_json(indent=2), encoding="utf-8"
            )
            (out_dir / "skills.md").write_text(
                skills.format_markdown(plan), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the job
            self._emit("skills", f"Skills selection skipped ({exc})")

    def _draft_cover_letter(self) -> None:
        job, settings, out_dir = self.job, self.settings, self.out_dir
        try:
            letter = coverletter.draft_letter(
                self.master_resume,
                self.requirements,
                self.result.bullets,
                job.jd_text,
                use_cache=not settings.no_cache,
                angles=coverletter.CoverAngles(
                    why_company=settings.cover_angles.why_company,
                    problem=settings.cover_angles.problem,
                    approach=settings.cover_angles.approach,
                    tone=settings.cover_angles.tone,
                ),
                on_event=self.on_event,
            )
            cover_path = out_dir / "cover.docx"
            coverletter.render_cover_letter(
                self.master_resume,
                letter,
                out=cover_path,
            )
            job.cover_letter = _to_cover_out(letter, out_dir=out_dir)
            (out_dir / "cover.json").write_text(
                job.cover_letter.model_dump_json(indent=2),
                encoding="utf-8",
            )
            (out_dir / "cover.md").write_text(
                coverletter.format_markdown(letter),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the job
            message = f"Cover letter skipped ({exc})"
            self._emit("cover", message)
            # Also a run warning, not just a progress event: a failed cover stage renders
            # no card at all, so an event alone leaves the user with a silently missing
            # artifact and nowhere showing why.
            if job.report is not None:
                job.report.warnings.append(message)

    def _suggest_vocabulary(self) -> None:
        try:
            _draft_vocabulary_proposals(
                known_tags=self.known_tags,
                master_resume=self.master_resume,
                requirements=self.requirements,
                selected_texts=self.result.bullets,
                on_event=self.on_event,
            )
        except Exception as exc:  # noqa: BLE001 - advisory only; never fail the job
            self._emit("propose", f"Vocabulary suggestions skipped ({exc})")


def _draft_vocabulary_proposals(
    *,
    known_tags: list[str],
    master_resume: MasterResume,
    requirements: jd.JobRequirements,
    selected_texts: dict[str, str],
    on_event: ProgressCallback,
) -> None:
    """Opportunistic, opt-in vocabulary-proposal draft for the active profile, run at
    the end of a successful job (`settings.suggest_vocabulary`).

    Fed by this run's own near-miss keyword gaps and unclassified opening verbs among
    the bullets actually selected — the same signals a user would eyeball in the report,
    turned into a queued suggestion instead. Non-fatal by construction: the caller wraps
    this in a bare `except Exception`, since a run whose `.docx` already succeeded must
    never fail over an advisory feature.
    """
    unmatched = propose.near_miss_alias_candidates(requirements, master_resume)
    unknown_verbs = sorted(
        {
            verb
            for text in selected_texts.values()
            if (verb := bullet_checks.opening_verb(text)) and config.verb_family(verb) is None
        }
    )
    if not unmatched and not unknown_verbs:
        return

    effective = libraries.resolve_effective()
    state = libraries.read_workspace_state()
    raw = propose.propose_vocabulary(
        known_tags=known_tags,
        unmatched=unmatched,
        unknown_verbs=unknown_verbs,
        families=effective.verb_families,
        on_event=on_event,
    )
    filtered = propose.filter_proposals(
        raw,
        known_tags=known_tags,
        effective=effective,
        rejected=state.rejected,
        source="run",
    )
    if not filtered:
        return

    # The read-modify-write of `state.proposals` is held under `template_ops.LOCK` —
    # the Settings tab's approve/reject routes do the same wholesale
    # read-modify-write of libraries.json with no lock of their own otherwise, so
    # whichever side runs second silently loses the other's change. `state` itself
    # (read above, before `propose_vocabulary`'s LLM call) is deliberately *not* what
    # gets written: re-reading here means a concurrent approve/reject that landed
    # while that call was in flight isn't clobbered by a write based on stale data.
    with template_ops.LOCK:
        fresh_state = libraries.read_workspace_state()
        # filter_proposals already excludes anything in `state.rejected` as of the read
        # above; this only needs to dedupe against proposals already pending, which it
        # had no visibility into.
        existing_ids = {p.id for p in fresh_state.proposals}
        new_ones = [p for p in filtered if p.id not in existing_ids]
        if not new_ones:
            return
        fresh_state.proposals = [*fresh_state.proposals, *new_ones]
        libraries.write_workspace_state(fresh_state)
        libraries.reload()
    on_event(
        ProgressEvent(
            stage="propose",
            message=f"Drafted {len(new_ones)} vocabulary suggestion(s) for review in Settings",
            detail={"count": len(new_ones)},
        )
    )


def _to_expansion_out(expansion: expand.Expansion) -> ExpansionOut:
    """Convert the expand dataclass into the Pydantic shape the API serves."""
    return ExpansionOut(
        entries=[
            ExpandedEntryOut(
                entry_key=e.entry_key,
                title=e.title,
                company=e.company,
                location=e.location,
                start=e.start,
                end=e.end,
                bullets=list(e.bullets),
                char_count=e.char_count,
                warnings=list(e.warnings),
                on_resume=e.on_resume,
            )
            for e in expansion.entries
        ],
        warnings=list(expansion.warnings),
        model=expansion.model,
        char_limit=expansion.char_limit,
    )


def _to_skills_out(plan: skills.SkillsPlan) -> SkillsPlanOut:
    """Convert the skills dataclass into the Pydantic shape the API serves."""
    return SkillsPlanOut(
        skills=[
            SkillSuggestionOut(
                skill=s.skill,
                pool_label=s.pool_label,
                tier=s.tier,
                jd_phrase=s.jd_phrase,
                sources=list(s.sources),
                reason=s.reason,
            )
            for s in plan.skills
        ],
        warnings=list(plan.warnings),
        model=plan.model,
        pool_size=plan.pool_size,
    )


def _to_cover_out(
    letter: coverletter.CoverLetter,
    *,
    out_dir: Path | None = None,
) -> CoverLetterOut:
    """Convert the cover-letter dataclass into the Pydantic shape the API serves."""
    has_docx = False
    has_pdf = False
    if out_dir is not None:
        has_docx = (out_dir / "cover.docx").exists()
        has_pdf = (out_dir / "cover.pdf").exists()
    return CoverLetterOut(
        company=letter.company,
        company_location=letter.company_location,
        addressee=letter.addressee,
        paragraphs=list(letter.paragraphs),
        salutation=letter.salutation,
        closing=letter.closing,
        signature=letter.signature,
        inside_address=list(letter.inside_address),
        date=letter.date,
        warnings=list(letter.warnings),
        model=letter.model,
        word_count=letter.word_count,
        has_docx=has_docx,
        has_pdf=has_pdf,
    )


def regenerate_cover_letter(
    job_id: str,
    *,
    instruction: str = "",
    cover_angles: CoverAnglesIn | None = None,
) -> CoverLetterOut:
    """Re-draft and re-render a job's cover letter, overwriting artifacts in place."""
    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    bullets_path = out_dir / "bullets.json"
    backends_path = out_dir / "backends.json"
    if not bullets_path.exists():
        raise FileNotFoundError("This job has no saved tailored bullets for regeneration.")

    bullets = json.loads(bullets_path.read_text(encoding="utf-8"))
    backend_specs = json.loads(backends_path.read_text(encoding="utf-8"))
    jd_path = out_dir / "jd.txt"
    if not jd_path.exists():
        raise FileNotFoundError("This job has no saved job description.")
    jd_text = jd_path.read_text(encoding="utf-8")

    requirements_path = out_dir / "requirements.json"
    if not requirements_path.exists():
        raise FileNotFoundError("This job has no saved requirements.")
    requirements = jd.JobRequirements.model_validate_json(
        requirements_path.read_text(encoding="utf-8")
    )

    angles = None
    if cover_angles is not None:
        angles = coverletter.CoverAngles(
            why_company=cover_angles.why_company,
            problem=cover_angles.problem,
            approach=cover_angles.approach,
            tone=cover_angles.tone,
        )

    snapshot = industries.load(out_dir)
    workspace_id = config.active_workspace_id()
    context = (
        config.context_for_workspace(workspace_id)
        if workspace_id is not None else config.default_context()
    )
    with config.use_context(replace(context, guidance=snapshot)), \
            config.pinned_specs(backend_specs, effort=None):
        industries.bind(snapshot)
        if snapshot is not None:
            style.activate(**snapshot.styles)
        resume = data.load()
        letter = coverletter.draft_letter(
            resume,
            requirements,
            bullets,
            jd_text,
            use_cache=False,
            instruction=instruction,
            angles=angles,
        )
        coverletter.render_cover_letter(resume, letter, out=out_dir / "cover.docx")

    out = _to_cover_out(letter, out_dir=out_dir)
    (out_dir / "cover.json").write_text(out.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "cover.md").write_text(
        coverletter.format_markdown(letter),
        encoding="utf-8",
    )
    return out


def verify_claim(job_id: str | None, text: str) -> coverletter.ClaimCheck:
    """Check free-text application prose against tailored or master-resume bullets.

    When ``job_id`` is set, reloads ``bullets.json`` and ``jd.txt`` from the job
    directory (same artifacts ``regenerate_cover_letter`` uses). When omitted,
    checks against every bullet in the master resume with an empty JD context.
    Pure — no LLM, no disk writes. Raises ``FileNotFoundError`` when a job-scoped
    run has no saved bullets or JD.
    """
    resume = data.load()
    if job_id is None:
        bullets = {bullet.id: bullet.text for bullet in resume.all_bullets()}
        return coverletter.check_claims(resume, bullets, "", text)

    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    bullets_path = out_dir / "bullets.json"
    if not bullets_path.exists():
        raise FileNotFoundError(
            "This job has no saved tailored bullets for claim verification."
        )
    jd_path = out_dir / "jd.txt"
    if not jd_path.exists():
        raise FileNotFoundError("This job has no saved job description.")

    bullets = json.loads(bullets_path.read_text(encoding="utf-8"))
    jd_text = jd_path.read_text(encoding="utf-8")
    return coverletter.check_claims(resume, bullets, jd_text, text)


def _to_report_out(data: report.RunReport) -> RunReportOut:
    """Convert the dataclass report into the Pydantic shape the API serves."""
    return RunReportOut(
        title=data.title,
        seniority=data.seniority,
        coverage_matched=data.coverage_matched,
        coverage_total=data.coverage_total,
        extraction_diagnosis=data.extraction_diagnosis,
        missing_must_haves=data.missing_must_haves,
        unmatched_canonicals=[[c, p] for c, p in data.unmatched_canonicals],
        gaps=[
            KeywordGapOut(
                canonical=g.canonical,
                phrase=g.phrase,
                importance=g.importance,
                reason=g.reason,
                evidence=g.evidence,
                band=g.band,
                evidence_tier=g.evidence_tier,
            )
            for g in data.gaps
        ],
        model=data.model,
        semantic_used=data.semantic_used,
        bullets_selected=data.bullets_selected,
        bullets_total=data.bullets_total,
        experience=[
            SectionSummaryOut(label=s.label, kept=s.kept, total=s.total, rewritten=s.rewritten)
            for s in data.experience
        ],
        projects=[
            SectionSummaryOut(label=s.label, kept=s.kept, total=s.total, rewritten=s.rewritten)
            for s in data.projects
        ],
        dropped=data.dropped,
        pages=data.pages,
        pages_are_estimated=data.pages_are_estimated,
        iterations=data.iterations,
        widows_repaired=data.widows_repaired,
        widows_remaining=data.widows_remaining,
        verbs_diversified=data.verbs_diversified,
        verb_collisions_remaining=data.verb_collisions_remaining,
        warnings=data.warnings,
        out_path=data.out_path,
        pdf_backend=data.pdf_backend,
        calibration_source=data.calibration_source,
        calibration_rejection=data.calibration_rejection,
        topped_up=data.topped_up,
        fit_trace=data.fit_trace,
    )


#: Process-wide queue. One instance is enough for a single-user tool.
queue_singleton = JobQueue()


def get_queue() -> JobQueue:
    """Return the process-wide job queue."""
    return queue_singleton
