"""One tailoring job end to end: activate the profile, run the pipeline, write outputs."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from resume_tailor import config
from resume_tailor.content import bullet_tags, data, industries, style
from resume_tailor.content.data import MasterResume
from resume_tailor.document import rerender
from resume_tailor.document.template_profile import active_layout
from resume_tailor.infra import telemetry
from resume_tailor.infra.llm import LLMError
from resume_tailor.pipeline import (
    coverletter,
    coverletter_format,
    coverletter_models,
    expand,
    facets,
    fit,
    fit_types,
    include,
    jd,
    relevance,
    report,
    skills,
)
from resume_tailor.pipeline.events import ProgressCallback, ProgressEvent
from resume_tailor.pipeline.fabrication import FabricationError
from resume_tailor.pipeline.fit_types import FitError

from . import job_followups, job_outputs, job_routing, job_types

logger = logging.getLogger(__name__)


def _jd_title_fallback(jd_text: str) -> str:
    """First non-empty line of the JD, truncated — used when there is no report yet."""
    for line in jd_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return "Untitled run"

class _TailorJobRun:
    """One tailoring job's pipeline, in the active workspace context.

    The core stages (`_extract` → `_score` with `_select_facets` → `_fit`) raise
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

    def __init__(self, job: job_types.Job) -> None:
        self.job = job
        self.settings = job.settings
        self.on_event: ProgressCallback = job.emit

    def run(self) -> None:
        with telemetry.recording(
            config.OUTPUT_DIR, run_id=self.job.job_id, archive_id=self.job.job_id, source="web",
        ):
            self._run_measured()

    def _run_measured(self) -> None:
        job, settings = self.job, self.settings
        self._prepare()
        telemetry.configure()
        self._extract()
        job.check_cancelled()
        # Kept unfiltered for `expand.expand_experience` below — an excluded job still
        # appears in the application-form paste tile, per its own decision. Scoring reads
        # it too, so an exclusion toggle never invalidates the score cache; facets gets
        # the filtered pool, so it never sees one an excluded entry contributed to.
        self.full_resume = self.resume
        self.resume = include.apply(self.resume, settings.include)
        self._score_with_facets()
        job.check_cancelled()
        self._fit()
        self._ensure_pdf()
        telemetry.ready()
        job.report = job_outputs._to_report_out(
            report.report_data(
                self.resume, self.requirements, self.result, master=self.master_resume
            )
        )
        self._write_run_files()

        job.check_cancelled()
        self._bonus_artifacts()
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
            profile, overrides, effort = job_routing.model_routing(settings)
            config.resolve(profile, overrides=overrides, effort=effort)
            style.activate(
                rewrite=settings.rewrite_style,
                expand=settings.expand_style,
                cover=settings.cover_style,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        self.resume = data.load()
        bullet_tags.annotate(self.resume)
        self.known_tags = bullet_tags.known_terms(self.resume)
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

    def _score_with_facets(self) -> None:
        """Score relevance and select facets at the same time.

        Neither reads the other's output, so on a cloud backend the facets call no longer
        waits behind scoring (`infra/model_queue.py` still serialises a local one). Facets
        runs on a worker; if scoring fails, the pool still waits for facets before the
        error propagates.
        """
        with ThreadPoolExecutor(max_workers=1) as pool:
            facets_done = config.submit_in_context(pool, self._select_facets)
            self._score()
        facets_done.result()

    def _score(self) -> None:
        settings = self.settings
        self.semantic: dict[str, float] | None = None
        if settings.no_semantic:
            telemetry.event("score", skipped=True)
            return
        try:
            self.semantic = relevance.score_table(
                self.full_resume.all_bullets(),
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
        from resume_tailor.pipeline import resume_quality

        out_dir, result = self.out_dir, self.result
        if result.quality is not None:
            resume_quality.save(
                out_dir, resume_quality.ResumeQuality.model_validate(result.quality),
            )
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
                fill_target=result.fill_target,
                lines_per_page=config.LINES_PER_PAGE,
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not save the re-render snapshot for %s: %s", self.job.job_id, exc
            )

    # -- bonus artifacts: never fail the job --------------------------------------------

    def _bonus_artifacts(self) -> None:
        """Expansion, skills and the cover letter, at the same time.

        Each only reads the finished fit and writes its own files, so none waits on
        another. Expansion and skills go to worker threads (`config.submit_in_context`
        carries this run's config and style into them); the cover letter stays on this
        thread because rendering it may drive Word over COM. `infra/model_queue.py`
        still caps how many model requests are in flight, so a local backend simply
        takes them one at a time.
        """
        settings = self.settings
        background = [
            stage for stage, skipped in (
                (self._expand, settings.no_expand),
                (self._select_skills, settings.no_skills),
            ) if not skipped
        ]
        for stage, skipped in (("expand", settings.no_expand), ("skills", settings.no_skills)):
            if skipped:
                telemetry.event(stage, skipped=True)
        with ThreadPoolExecutor(max_workers=max(1, len(background))) as pool:
            futures = [config.submit_in_context(pool, stage) for stage in background]
            if settings.cover_letter and not settings.no_cover_letter:
                self._draft_cover_letter()
            for future in futures:
                future.result()

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
                max_bullets_per_entry=self.settings.max_bullets_per_entry,
                use_cache=not self.settings.no_cache,
                on_event=self.on_event,
            )
            job.expansion = job_outputs.write_expansion(
                out_dir, expansion,
                source_experience_count=len(self.full_resume.experience),
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
            job.skills = job_outputs._to_skills_out(plan)
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
                angles=coverletter_models.CoverAngles(
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
            job.cover_letter = job_outputs._to_cover_out(letter, out_dir=out_dir)
            (out_dir / "cover.json").write_text(
                job.cover_letter.model_dump_json(indent=2),
                encoding="utf-8",
            )
            (out_dir / "cover.md").write_text(
                coverletter_format.format_markdown(letter),
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
            job_followups._draft_vocabulary_proposals(
                known_tags=self.known_tags,
                master_resume=self.master_resume,
                requirements=self.requirements,
                selected_texts=self.result.bullets,
                on_event=self.on_event,
            )
        except Exception as exc:  # noqa: BLE001 - advisory only; never fail the job
            self._emit("propose", f"Vocabulary suggestions skipped ({exc})")
