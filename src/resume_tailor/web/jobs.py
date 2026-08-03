"""Single-worker job queue for tailoring runs.

Concurrency is deliberately serial. `config.resolve()` writes the active backend routing
into a process-wide `_ACTIVE` dict that every LLM call site reads; two concurrent runs
with different `--model` settings would race and corrupt each other. A single worker is
the cheap way to keep that invariant without threading a context object through every
function between the CLI and the two API call sites — that refactor is the documented
follow-up if this ever becomes multi-user.

Each job writes into `output/jobs/<job_id>/` so successive runs never overwrite each
other's `.docx` / `.pdf`. JD and score caches stay in the shared `config.CACHE_DIR`.
"""

from __future__ import annotations

import queue
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config, data, expand, facets, fit, jd, report, rewrite
from resume_tailor.events import ProgressCallback, ProgressEvent
from resume_tailor.fit import FitError
from resume_tailor.llm import LLMError
from resume_tailor.rewrite import FabricationError
from resume_tailor.web.schemas import (
    ExpandedEntryOut,
    ExpansionOut,
    JobSettings,
    KeywordGapOut,
    RunReportOut,
    SectionSummaryOut,
)


JobStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass
class Job:
    """One queued or finished tailoring run, held in memory for the life of the process."""

    job_id: str
    jd_text: str
    settings: JobSettings
    status: JobStatus = "queued"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    error: str | None = None
    report: RunReportOut | None = None
    expansion: ExpansionOut | None = None
    events: list[ProgressEvent] = field(default_factory=list)
    #: Signalled whenever a new event lands, so the SSE endpoint can wake up.
    event_notify: threading.Event = field(default_factory=threading.Event)
    out_dir: Path | None = None

    def emit(self, event: ProgressEvent) -> None:
        """Append a progress event and wake any SSE listeners."""
        self.events.append(event)
        self.event_notify.set()


class JobQueue:
    """Process-wide queue that drains one job at a time on a background thread."""

    def __init__(self) -> None:
        """Create an empty queue. The worker thread starts on the first `submit`."""
        self._jobs: dict[str, Job] = {}
        self._pending: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._order: list[str] = []  # job ids still waiting, in queue order

    def submit(self, jd_text: str, settings: JobSettings) -> tuple[Job, int]:
        """Enqueue a run. Returns `(job, 1-based queue position)`."""
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, jd_text=jd_text, settings=settings)
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._ensure_worker()
        self._pending.put(job_id)
        return job, self.queue_position(job_id)

    def get(self, job_id: str) -> Job | None:
        """Look up a job by id, or None if it was never submitted."""
        return self._jobs.get(job_id)

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

    def _ensure_worker(self) -> None:
        """Start the background worker once, on first submit."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run_loop, name="job-worker", daemon=True)
        self._worker.start()

    def _run_loop(self) -> None:
        """Pull jobs forever. Exits only when the process does (daemon thread)."""
        while True:
            job_id = self._pending.get()
            job = self._jobs.get(job_id)
            if job is None:
                continue
            with self._lock:
                if job_id in self._order:
                    self._order.remove(job_id)
            job.status = "running"
            job.emit(
                ProgressEvent(stage="fit", message="Starting tailoring run", detail={})
            )
            try:
                self._execute(job)
                job.status = "succeeded"
            except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
                job.status = "failed"
                job.error = str(exc)
                job.emit(
                    ProgressEvent(
                        stage="error",
                        message=str(exc),
                        detail={"traceback": traceback.format_exc()},
                    )
                )

    def _execute(self, job: Job) -> None:
        """Run one job end-to-end. Mutates `job` with events and a final report."""
        settings = job.settings
        on_event: ProgressCallback = job.emit

        try:
            overrides: dict[str, str] = {}
            # Broadest first: the blanket Ollama/Gemini tags repoint every stage routed to
            # that origin, then the two per-stage fields overwrite whichever of them they
            # name. Reversing this would let a blanket tag clobber an explicit per-stage
            # choice. Order between the two blanket loops is irrelevant — a stage is
            # routed to at most one of them in the profile's own specs, never both.
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
            config.resolve(
                settings.model,
                overrides=overrides or None,
                effort=settings.effort,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        resume = data.load()
        known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})

        try:
            requirements = jd.extract_consensus(
                job.jd_text,
                known_tags=known_tags,
                runs=settings.extract_runs,
                use_cache=not settings.no_cache,
                on_event=on_event,
            )
        except (ValueError, RuntimeError, LLMError) as exc:
            raise RuntimeError(str(exc)) from exc

        paraphrased = jd.verify_verbatim(requirements, job.jd_text)
        if paraphrased:
            on_event(
                ProgressEvent(
                    stage="extract",
                    message="Some extracted phrases are not verbatim from the posting",
                    detail={"paraphrased": paraphrased},
                )
            )

        semantic: dict[str, float] | None = None
        if not settings.no_semantic:
            try:
                semantic = rewrite.score_table(
                    resume.all_bullets(),
                    requirements,
                    use_cache=not settings.no_cache,
                    on_event=on_event,
                )
            except LLMError as exc:
                raise RuntimeError(str(exc)) from exc
            except (RuntimeError, ValueError) as exc:
                on_event(
                    ProgressEvent(
                        stage="score",
                        message=f"Semantic scoring unavailable; ranking on keywords only ({exc})",
                        detail={},
                    )
                )

        include_links = not settings.no_project_links
        try:
            if settings.no_facets:
                facet_result = facets.budget_only(
                    resume, requirements, include_project_links=include_links
                )
            else:
                facet_result = facets.select_facets(
                    resume,
                    requirements,
                    use_cache=not settings.no_cache,
                    include_project_links=include_links,
                    on_event=on_event,
                )
        except LLMError as exc:
            raise RuntimeError(str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            on_event(
                ProgressEvent(
                    stage="facets",
                    message=(
                        f"Facet selection unavailable; truncating pools in original "
                        f"order ({exc})"
                    ),
                    detail={},
                )
            )
            facet_result = facets.budget_only(
                resume, requirements, include_project_links=include_links
            )
        for warning in facet_result.warnings:
            on_event(
                ProgressEvent(stage="facets", message=warning, detail={})
            )
        # Captured before the rebind: facets.apply truncates Project.tech to its render
        # budget, and report.diagnose_gaps needs the untruncated pool to find evidence there.
        master_resume = resume
        resume = facets.apply(resume, facet_result)

        out_dir = config.OUTPUT_DIR / "jobs" / job.job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        job.out_dir = out_dir
        out_path = out_dir / "tailored.docx"

        try:
            result = fit.fit(
                resume,
                requirements,
                target_pages=settings.pages,
                out=out_path,
                max_experience=settings.experience,
                max_projects=settings.projects,
                semantic=semantic,
                repair_widows=not settings.no_widow_repair,
                repair_verbs=not settings.no_verb_repair,
                merge_bullets=settings.merge,
                include_project_links=include_links,
                fill_target=settings.fill_target,
                initial_bullet_share=settings.initial_bullet_share,
                on_event=on_event,
            )
        except FabricationError as exc:
            raise RuntimeError(str(exc)) from exc
        except FitError as exc:
            raise RuntimeError(str(exc)) from exc
        except (FileNotFoundError, RuntimeError) as exc:
            raise RuntimeError(str(exc)) from exc

        # Ensure a PDF sits beside the docx for the preview endpoint. The fit loop already
        # measured one, but a failed measurement leaves only the estimate — regenerate so
        # the UI can still offer a downloadable preview when LibreOffice is available.
        pdf_path = out_path.with_suffix(".pdf")
        if not pdf_path.exists():
            try:
                from resume_tailor import render

                render.to_pdf(out_path, pdf_path, keep_active=False)
            except RuntimeError as exc:
                on_event(
                    ProgressEvent(
                        stage="render",
                        message=f"PDF preview unavailable ({exc})",
                        detail={},
                    )
                )

        job.report = _to_report_out(
            report.report_data(resume, requirements, result, master=master_resume)
        )

        if not settings.no_expand:
            try:
                expansion = expand.expand_experience(
                    resume,
                    requirements,
                    fit_result=result,
                    semantic=semantic,
                    use_cache=not settings.no_cache,
                    on_event=on_event,
                )
                job.expansion = _to_expansion_out(expansion)
                (out_dir / "expansion.json").write_text(
                    job.expansion.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                (out_dir / "expansion.md").write_text(
                    expand.format_markdown(expansion), encoding="utf-8"
                )
            except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the job
                on_event(
                    ProgressEvent(
                        stage="expand",
                        message=f"Experience expansion skipped ({exc})",
                        detail={},
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


def _to_report_out(data: report.RunReport) -> RunReportOut:
    """Convert the dataclass report into the Pydantic shape the API serves."""
    return RunReportOut(
        title=data.title,
        seniority=data.seniority,
        coverage_matched=data.coverage_matched,
        coverage_total=data.coverage_total,
        missing_must_haves=data.missing_must_haves,
        unmatched_canonicals=[[c, p] for c, p in data.unmatched_canonicals],
        gaps=[
            KeywordGapOut(
                canonical=g.canonical,
                phrase=g.phrase,
                importance=g.importance,
                reason=g.reason,
                evidence=g.evidence,
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
    )


#: Process-wide queue. One instance is enough for a single-user tool.
queue_singleton = JobQueue()


def get_queue() -> JobQueue:
    """Return the process-wide job queue."""
    return queue_singleton
