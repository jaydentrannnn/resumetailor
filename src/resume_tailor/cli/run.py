"""The CLI run: job description in, tailored resume out.

This module is deliberately thin — argument wiring, error presentation, and exit codes
only. Every decision it reports was made in `jd`, `rewrite`, `fit`, or `render`; nothing
about selection or layout lives here.

Exit codes:
  0  a resume was produced and fits the page target
  1  the run failed (missing key, unfittable content, fabrication, bad input)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from resume_tailor import config, workspace
from resume_tailor.cli.args import parse_args, validate_argument_ranges
from resume_tailor.content import data, industries, style
from resume_tailor.content.data import MasterResume
from resume_tailor.document.template_profile import active_layout
from resume_tailor.infra import logs
from resume_tailor.infra.llm import LLMError
from resume_tailor.pipeline import (
    coverletter,
    expand,
    facets,
    fit,
    fit_types,
    include,
    jd,
    relevance,
    report,
    review,
    runs,
    skills,
)
from resume_tailor.pipeline.fabrication import FabricationError

_CONTACT_FIELDS = {"location", "email", "phone", "linkedin", "github"}


def main(argv: list[str] | None = None) -> int:
    return _CliRun(parse_args(argv)).run()


class _CliRun:
    """One CLI invocation. Each step returns an exit code to stop, or `None` to go on."""

    resume: MasterResume
    full_resume: MasterResume
    master_resume: MasterResume
    requirements: jd.JobRequirements
    jd_text: str
    result: fit_types.FitResult

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.semantic: dict[str, float] | None = None

    def run(self) -> int:
        for step in (self._configure, self._load_inputs, self._score, self._select_facets,
                     self._fit):
            code = step()
            if code is not None:
                return code
        self._archive()
        self._expand()
        self._select_skills()
        self._draft_cover_letter()
        self._review()
        return 0

    @staticmethod
    def _error(message: object) -> int:
        print(f"error: {message}", file=sys.stderr)
        return 1

    # -- setup -------------------------------------------------------------------------

    def _configure(self) -> int | None:
        args = self.args
        range_error = validate_argument_ranges(args)
        if range_error is not None:
            return self._error(range_error)

        log_dir = config.log_dir_setting()
        if log_dir is not None:
            logs.setup_logging(log_dir)

        try:
            workspace.bootstrap(workspace_id=args.workspace)
        except workspace.WorkspaceError as exc:
            return self._error(exc)

        # The CLI is otherwise entirely flag-driven — every other behavior below traces to
        # an explicit `--flag`, which is what keeps a scripted/looped bulk-apply run
        # predictable regardless of what's saved in the web UI. `model_name`,
        # `rewrite_style`, and `expand_style` are the sole, deliberate exceptions: picked
        # up from the active profile's saved `settings.json` so a style/model preference
        # set once in the web UI doesn't have to be retyped as a flag on every CLI run.
        # No other saved setting (`pages`, `experience`, `include`, `fill_target`, …) is
        # read here — those always come from argparse defaults, never from settings.json.
        self.profile_settings = workspace.load_settings()
        self.saved = saved = self.profile_settings["defaults"]

        # Resolved before anything is read or spent, so a bad spec costs nothing.
        try:
            overrides = self._model_overrides()
            config.resolve(
                args.model,
                overrides=overrides or None,
                effort=args.effort,
            )
            style.activate(
                rewrite=saved.get("rewrite_style"),
                expand=saved.get("expand_style"),
                cover=saved.get("cover_style"),
            )
        except ValueError as exc:
            return self._error(exc)

        contact_fields: list[str] | None = None
        if args.contact_fields:
            contact_fields = [f.strip() for f in args.contact_fields.split(",") if f.strip()]
            unknown = [f for f in contact_fields if f not in _CONTACT_FIELDS]
            if unknown:
                return self._error(
                    f"--contact-fields has unknown field(s): {', '.join(unknown)} "
                    f"(valid: {', '.join(sorted(_CONTACT_FIELDS))})"
                )

        self.include_options = include.IncludeOptions(
            contact_fields=contact_fields,
            gpa=not args.no_gpa,
            coursework=not args.no_coursework,
            exclude_entries=list(args.exclude_ids),
        )
        return None

    def _model_overrides(self) -> dict[str, str]:
        args = self.args
        overrides: dict[str, str] = {}
        model_name = self.saved.get("model_name")
        if model_name:
            for purpose in config.PURPOSES:
                overrides[purpose] = model_name
        if args.rewrite_model:
            overrides["rewrite"] = args.rewrite_model
        if args.expand_model:
            overrides["expand"] = args.expand_model
        if args.skills_model:
            overrides["skills"] = args.skills_model
        if args.cover_model:
            overrides["cover"] = args.cover_model
        if args.review_model:
            overrides["review"] = args.review_model
        return overrides

    def _load_inputs(self) -> int | None:
        args, saved = self.args, self.saved
        try:
            resume = data.load()
            industries.bind(industries.capture(
                self.profile_settings.get("target_field"),
                {"rewrite": saved.get("rewrite_style"), "expand": saved.get("expand_style"),
                 "cover": saved.get("cover_style")},
                workspace_id=config.active_workspace_id(), resume=resume,
            ))
            if industries.active() is not None:
                # Normalize source tags against the same frozen vocabulary used for
                # extraction.
                resume = data.load()
            problems = include.validate(resume, self.include_options)
            if problems:
                for problem in problems:
                    print(f"error: {problem}", file=sys.stderr)
                return 1
            jd_text = args.jd.read_text(encoding="utf-8")
            # The resume's own tag vocabulary steers `canonical`, so the extractor stops
            # coining tags that can never match anything ("communication skills" against a
            # resume tagged `communication`). An unmatched canonical then means a real gap.
            known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})
            requirements = jd.extract_consensus(
                jd_text,
                known_tags=known_tags,
                runs=config.extract_runs(args.extract_runs),
                use_cache=not args.no_cache,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            return self._error(exc)
        self.resume, self.jd_text, self.requirements = resume, jd_text, requirements
        self._warn_about_extraction()
        if args.suggest_reuse:
            self._suggest_reuse()
        return None

    def _warn_about_extraction(self) -> None:
        # The verbatim guarantee is the feature, so it is checked rather than assumed: a
        # paraphrased phrase silently breaks the keyword-mirroring premise of the rewrite.
        paraphrased = jd.verify_verbatim(self.requirements, self.jd_text)
        if paraphrased:
            print(
                "warning: these extracted phrases are not verbatim from the posting, so "
                "mirroring them may not help:\n  " + "\n  ".join(paraphrased),
                file=sys.stderr,
            )

        diagnosis = jd.extraction_diagnosis(self.requirements)
        if diagnosis is not None:
            print(
                f"warning: JD extraction is inconclusive ({diagnosis}) — keyword coverage "
                "will not be measurable for this run",
                file=sys.stderr,
            )

    def _suggest_reuse(self) -> None:
        match = runs.closest_run(self.jd_text, self.requirements)
        if match is None:
            print(
                "reuse: no prior archived runs under "
                f"{config.OUTPUT_DIR / 'jobs'} (need jd.txt + requirements.json + "
                "bullets.json)",
                file=sys.stderr,
            )
        else:
            prior, recommendation, score = match
            print(
                f"reuse: closest prior run {prior.job_id!r} "
                f"jaccard={score:.2f} → {recommendation}",
                file=sys.stderr,
            )

    # -- the pipeline ------------------------------------------------------------------

    def _score(self) -> int | None:
        # Scored once, before the loop, and held fixed for the run — see
        # `relevance.score_table` for why it must not be recomputed per iteration.
        if self.args.no_semantic:
            return None
        try:
            self.semantic = relevance.score_table(
                self.resume.all_bullets(), self.requirements, use_cache=not self.args.no_cache
            )
        except LLMError as exc:
            # Deliberately NOT degraded. An unreachable daemon, an expired sign-in, or an
            # exhausted quota is a broken run, and silently ranking on keywords instead
            # would report success while quietly producing a worse resume.
            return self._error(exc)
        except (RuntimeError, ValueError) as exc:
            # A model that answered but unhelpfully is different: the resume is still
            # correct without this signal, just ranked more crudely.
            print(
                f"warning: semantic relevance scoring unavailable, ranking on keyword "
                f"overlap only ({exc})",
                file=sys.stderr,
            )
        return None

    def _select_facets(self) -> int | None:
        args, requirements = self.args, self.requirements
        # Kept unfiltered for the experience expansion below — an excluded job still
        # appears in the application-form paste text. Applied here (after scoring, before
        # facets) so an exclusion never invalidates the score cache, and facets never sees
        # a pool an excluded entry contributed to.
        self.full_resume = self.resume
        resume = include.apply(self.resume, self.include_options)

        # Facets: pick tech tags / coursework once before the fit loop. On skip or soft
        # failure, still run budget-only truncation so headers cannot wrap.
        include_links = not args.no_project_links
        try:
            if args.no_facets:
                facet_result = facets.budget_only(
                    resume, requirements, include_project_links=include_links
                )
            else:
                facet_result = facets.select_facets(
                    resume,
                    requirements,
                    use_cache=not args.no_cache,
                    include_project_links=include_links,
                )
        except LLMError as exc:
            return self._error(exc)
        except (RuntimeError, ValueError) as exc:
            print(
                f"warning: facet selection unavailable, truncating pools in original order "
                f"({exc})",
                file=sys.stderr,
            )
            facet_result = facets.budget_only(
                resume, requirements, include_project_links=include_links
            )
        for warning in facet_result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        # Captured before the rebind: facets.apply truncates Project.tech to its render
        # budget, and report.diagnose_gaps needs the untruncated pool to find evidence.
        self.master_resume = resume
        self.resume = facets.apply(resume, facet_result)
        self.facet_result = facet_result
        return None

    def _fit(self) -> int | None:
        args, resume, requirements = self.args, self.resume, self.requirements
        # Default export name mirrors the download: "<name> Resume - <position>.docx".
        out = args.out or (
            config.OUTPUT_DIR
            / report.export_filename(resume.contact.name, requirements.title)
        )

        # Range-validated by `validate_argument_ranges` at the top of the run, before
        # anything was read or spent — not re-checked here.
        try:
            self.result = fit.fit(
                resume,
                requirements,
                target_pages=args.pages,
                template=args.template,
                out=out,
                max_experience=args.experience,
                max_projects=args.projects,
                semantic=self.semantic,
                repair_widows=not args.no_widow_repair,
                repair_verbs=not args.no_verb_repair,
                merge_bullets=args.merge,
                include_project_links=not args.no_project_links,
                contact_fields=include.contact_order(self.include_options, active_layout()),
                fill_target=args.fill_target,
                initial_bullet_share=args.initial_bullet_share,
                experience_bullet_share=args.experience_bullet_share,
                max_bullets_per_entry=args.max_bullets_per_entry,
                coursework_pool=self.facet_result.coursework_pool,
            )
        except (FabricationError, fit_types.FitError, FileNotFoundError, RuntimeError) as exc:
            return self._error(exc)

        print(report.format_report(
            resume, requirements, self.result, master=self.master_resume
        ))
        return None

    def _archive(self) -> None:
        # Archive JD + requirements + bullets so CLI runs join the same corpus the web
        # UI already writes under output/jobs/<id>/. The human-facing `.jd.txt` sidecar
        # sits next to the .docx; the job directory is what `runs.iter_runs` reads.
        result, jd_text = self.result, self.jd_text
        try:
            jd_sidecar = result.out_path.with_name(result.out_path.stem + ".jd.txt")
            jd_sidecar.write_text(jd_text, encoding="utf-8")
            archive_dir = config.OUTPUT_DIR / "jobs" / f"cli-{result.out_path.stem}"
            archive_dir.mkdir(parents=True, exist_ok=True)
            industries.save(industries.active(), archive_dir)
            (archive_dir / "jd.txt").write_text(jd_text, encoding="utf-8")
            (archive_dir / "requirements.json").write_text(
                self.requirements.model_dump_json(indent=2), encoding="utf-8"
            )
            (archive_dir / "bullets.json").write_text(
                json.dumps(result.bullets, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"warning: could not archive run for reuse ({exc})", file=sys.stderr)

    # -- advisory stages: each must never turn a successful run into a failure ----------

    def _sidecar(self, suffix: str) -> Path:
        out_path = self.result.out_path
        return out_path.with_name(out_path.stem + suffix)

    def _expand(self) -> None:
        # Expansion is advisory paste text for application forms; the .docx is already on
        # disk.
        if self.args.no_expand:
            return
        try:
            # Unfiltered resume: an experience entry excluded from the tailored resume
            # still appears in the application-form paste text.
            expansion = expand.expand_experience(
                self.full_resume,
                self.requirements,
                fit_result=self.result,
                semantic=self.semantic,
                use_cache=not self.args.no_cache,
            )
            print()
            print(report.format_expansion(expansion))
            expand_path = self._sidecar(".expansion.md")
            expand_path.write_text(expand.format_markdown(expansion), encoding="utf-8")
            print(f"Expansion: {expand_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: experience expansion skipped ({exc})", file=sys.stderr)

    def _select_skills(self) -> None:
        # `master_resume` (post-include, pre-facets) matches exactly what
        # `report.diagnose_gaps` ran against above, so the skills tile and the gap section
        # partition one evidence universe. Not `full_resume`: an excluded entry is the user
        # saying "not part of this application", and a skill evidenced only there should
        # not be suggested for the Skills box of the package actually being submitted. Not
        # the post-facets `resume`: facets truncates Project.tech to its render budget,
        # which would silently drop evidence.
        if self.args.no_skills:
            return
        try:
            plan = skills.select_skills(
                self.master_resume,
                self.requirements,
                use_cache=not self.args.no_cache,
            )
            print()
            print(report.format_skills(plan))
            skills_path = self._sidecar(".skills.md")
            skills_path.write_text(skills.format_markdown(plan), encoding="utf-8")
            print(f"Skills: {skills_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: skills selection skipped ({exc})", file=sys.stderr)

    def _draft_cover_letter(self) -> None:
        args = self.args
        if not args.cover_letter or args.no_cover_letter:
            return
        try:
            letter = coverletter.draft_letter(
                self.master_resume,
                self.requirements,
                self.result.bullets,
                self.jd_text,
                use_cache=not args.no_cache,
                angles=coverletter.CoverAngles(
                    why_company=args.cover_why,
                    problem=args.cover_problem,
                    approach=args.cover_approach,
                    tone=args.cover_tone,
                ),
            )
            cover_path = self._sidecar(" Cover Letter.docx")
            coverletter.render_cover_letter(self.master_resume, letter, out=cover_path)
            print()
            print(report.format_cover_letter(letter))
            cover_md = self._sidecar(".cover.md")
            cover_md.write_text(coverletter.format_markdown(letter), encoding="utf-8")
            print(f"Cover letter: {cover_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: cover letter skipped ({exc})", file=sys.stderr)

    def _review(self) -> None:
        if not self.args.review:
            return
        try:
            review_result = review.review_bullets(
                self.master_resume,
                self.requirements,
                self.result.bullets,
            )
            print()
            print(report.format_review(review_result))
            review_path = self._sidecar(".review.md")
            review_path.write_text(report.format_review(review_result), encoding="utf-8")
            print(f"Review: {review_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: review skipped ({exc})", file=sys.stderr)
