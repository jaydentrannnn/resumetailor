"""Command-line entry point: job description in, tailored resume out.

    python tailor.py --jd jd.txt [--out output/tailored.docx] [--pages 1]
                     [--experience 3] [--projects 2] [--template ...]

This module is deliberately thin — argument parsing, error presentation, and exit codes
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

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from resume_tailor import (  # noqa: E402
    config,
    coverletter,
    data,
    expand,
    facets,
    fit,
    include,
    jd,
    report,
    review,
    rewrite,
    runs,
    skills,
    style,
    workspace,
)
from resume_tailor.llm import LLMError  # noqa: E402
from resume_tailor.rewrite import FabricationError  # noqa: E402
from resume_tailor.template_profile import active_layout  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tailor.py",
        description="Tailor a resume to a job description without changing its formatting.",
    )
    parser.add_argument(
        "--jd",
        type=Path,
        required=True,
        help="Path to a text file containing the job description.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Where to write the tailored .docx "
            "(default: output/<name> Resume - <position>.docx)."
        ),
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=config.DEFAULT_PAGE_TARGET,
        help=f"Target page count (default: {config.DEFAULT_PAGE_TARGET}).",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Override the tagged template (default: templates/main_template.docx).",
    )
    parser.add_argument(
        "--experience",
        type=int,
        default=None,
        help=(
            "How many work experience entries to show "
            f"(default: {config.MAX_EXPERIENCE_ENTRIES})."
        ),
    )
    parser.add_argument(
        "--projects",
        type=int,
        default=None,
        help=f"How many project entries to show (default: {config.MAX_PROJECT_ENTRIES}).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Re-extract the job description instead of reusing a cached extraction.",
    )
    parser.add_argument(
        "--extract-runs",
        type=int,
        default=config.EXTRACT_CONSENSUS_RUNS,
        metavar="N",
        help=(
            "Vote over N independent JD extractions to damp per-call canonicalisation "
            f"noise (default: {config.EXTRACT_CONSENSUS_RUNS}). 1 restores a single call."
        ),
    )
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help=(
            "Rank on keyword tag overlap only, skipping the LLM relevance pass. Useful for "
            "isolating what semantic scoring changed, and for running without its API call."
        ),
    )
    parser.add_argument(
        "--no-widow-repair",
        action="store_true",
        help=(
            "Skip the follow-up call that shortens bullets which wrapped onto a final line "
            "holding one word. The control half of an A/B: it isolates what the rewrite "
            "prompt's length target achieves on its own."
        ),
    )
    parser.add_argument(
        "--no-verb-repair",
        action="store_true",
        help=(
            "Skip replacing opening verbs that repeat another bullet's. Rides in the same "
            "follow-up call as widow repair, so this only saves a call on a run that has "
            "no widows; the other half of the same A/B."
        ),
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help=(
            "Enable merging redundant bullet points within a single entry, using an "
            "additional non-regressive merge pass. Proposals fire only after the page has "
            "measured over its target, so a resume that already fits is never merged."
        ),
    )
    parser.add_argument(
        "--model",
        default="ollama",
        metavar="MODEL",
        help=(
            "Which backend serves the run: a profile (claude, ollama, lmstudio, gemini, "
            "hybrid) or a spec like 'ollama:gemma4:cloud' or 'gemini:gemini-3.5-flash'. "
            "'hybrid' ranks on Ollama and rewrites on Claude. Default: ollama (no "
            "Anthropic key needed). 'gemini' needs GEMINI_API_KEY in .env."
        ),
    )
    parser.add_argument(
        "--rewrite-model",
        default=None,
        metavar="MODEL",
        help=(
            "Override the rewrite stage only. Rewriting is where invented content would "
            "cost you, so it is worth keeping on a stronger model than ranking."
        ),
    )
    parser.add_argument(
        "--expand-model",
        default=None,
        metavar="MODEL",
        help=(
            "Override the experience-expansion stage only. Expansion produces "
            "application-form paste text and follows the profile by default."
        ),
    )
    parser.add_argument(
        "--no-expand",
        action="store_true",
        help=(
            "Skip generating expanded experience descriptions for application-form "
            "paste fields. The tailored resume is still produced."
        ),
    )
    parser.add_argument(
        "--skills-model",
        default=None,
        metavar="MODEL",
        help=(
            "Override the skills-selection stage only. Selection is from a closed pool "
            "with code enforcement and follows the profile by default."
        ),
    )
    parser.add_argument(
        "--no-skills",
        action="store_true",
        help=(
            "Skip generating the tailored skills list for application-form Skills "
            "fields. The tailored resume is still produced."
        ),
    )
    parser.add_argument(
        "--cover-letter",
        action="store_true",
        help=(
            "Generate a cover letter from the tailored resume and job posting. "
            "Off by default; produces a .docx and PDF sidecar when enabled."
        ),
    )
    parser.add_argument(
        "--no-cover-letter",
        action="store_true",
        help="Skip cover letter generation even when enabled in saved profile settings.",
    )
    parser.add_argument(
        "--cover-model",
        default=None,
        metavar="MODEL",
        help="Override the cover-letter stage only.",
    )
    parser.add_argument(
        "--no-facets",
        action="store_true",
        help=(
            "Skip the LLM that picks project tech tags and coursework for the posting. "
            "Pools are still truncated to the one-line / two-line budgets in original order."
        ),
    )
    parser.add_argument(
        "--no-project-links",
        action="store_true",
        help=(
            "Render projects without their link label or hyperlink. Frees no page space "
            "— the link is inline in the project's header line."
        ),
    )
    parser.add_argument(
        "--no-gpa",
        action="store_true",
        help="Suppress the GPA suffix on the degree line, regardless of Education.show_gpa.",
    )
    parser.add_argument(
        "--no-coursework",
        action="store_true",
        help='Suppress the "Relevant Coursework:" bullet.',
    )
    parser.add_argument(
        "--contact-fields",
        default=None,
        metavar="FIELD,FIELD,...",
        help=(
            "Comma-separated contact-line fields, in render order, from "
            "location/email/phone/linkedin/github. Name is not included here — it always "
            "renders first, on its own line. Omitted fields are hidden. Default: the "
            "active template profile's order."
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="ID",
        dest="exclude_ids",
        help=(
            "Omit this entry id entirely (repeatable) — any experience or project entry, "
            "in any section. Ids come from master_resume.json's sections[].entries[].id."
        ),
    )
    parser.add_argument(
        "--fill-target",
        type=float,
        default=None,
        metavar="RATIO",
        help=(
            "Page-fill fraction below which the fit loop grows "
            f"(0.80–0.95, default: {config.UNDERFLOW_THRESHOLD}). "
            "Lower accepts a sparser page; higher packs tighter."
        ),
    )
    parser.add_argument(
        "--initial-bullet-share",
        type=float,
        default=None,
        metavar="RATIO",
        help=(
            "Cap the first draft's bullet selection to this fraction of what's available "
            f"(0.30–1.00, default: {config.INITIAL_BULLET_SHARE}). Bounds only the first "
            "draft — the grow loop can still restore bullets toward the full pool if the "
            "measured page is under --fill-target, so pair a lower share with a lower "
            "--fill-target to actually end on a sparser page."
        ),
    )
    parser.add_argument(
        "--experience-bullet-share",
        type=float,
        default=None,
        metavar="RATIO",
        help=(
            "Fraction of the overall selected bullets given to experience, budgeted "
            "separately from projects (0.00–1.00, default: unweighted — one flat pool "
            "ranked by relevance, which lets a keyword-dense project out-rank every job)."
        ),
    )
    parser.add_argument(
        "--max-bullets-per-entry",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Cap on how many bullets any single job or project may take "
            "(default: unlimited)."
        ),
    )
    parser.add_argument(
        "--effort",
        choices=("low", "medium", "high"),
        default=None,
        help=(
            "Reasoning depth for every stage. Most of the per-call cost is reasoning "
            "tokens, so this is the cheapest lever available."
        ),
    )
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="ID",
        help=(
            "Run against this profile's master resume / template / cache instead of "
            "the active one. Applies to this invocation only — it never changes which "
            "profile the web UI (or a running server) has active."
        ),
    )
    parser.add_argument(
        "--suggest-reuse",
        action="store_true",
        help=(
            "Advisory: after extraction, print the closest prior archived run and a "
            "reuse/reuse_with_edits/regenerate recommendation, then continue normally. "
            "Does not feed prior bullets into the fit loop."
        ),
    )
    parser.add_argument(
        "--cover-why",
        default="",
        metavar="TEXT",
        help="Cover-letter angle: why this company (optional; requires --cover-letter).",
    )
    parser.add_argument(
        "--cover-problem",
        default="",
        metavar="TEXT",
        help="Cover-letter angle: the problem you want to solve there.",
    )
    parser.add_argument(
        "--cover-approach",
        default="",
        metavar="TEXT",
        help="Cover-letter angle: your approach or how you work.",
    )
    parser.add_argument(
        "--cover-tone",
        default="",
        choices=("", "formal", "direct", "conversational", "mirror"),
        help="Cover-letter tone preference.",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help=(
            "Opt-in: after the tailored resume succeeds, synthesise a hiring-manager "
            "review from the JD and write <out>.review.md. Verdicts are advisory — "
            "nothing is auto-applied."
        ),
    )
    parser.add_argument(
        "--review-model",
        default=None,
        metavar="MODEL",
        help="Override the review stage only.",
    )
    return parser.parse_args(argv)


def _validate_argument_ranges(args: argparse.Namespace) -> str | None:
    """Range-check the numeric flags argparse's own `type=` can't bound, returning the
    first violation's message (or `None` if all pass).

    Called at the very top of `main`, before anything is read or spent — these were
    previously checked only just before `fit.fit`, after JD extraction (up to 3 LLM
    calls), semantic scoring, and facet selection had already run, so
    `--fill-target 1.5` used to cost several model calls before failing on a value
    that only ever needed the parsed args to reject. The web path doesn't have this
    problem: `web/schemas.py`'s `JobSettings` pins the same bounds declaratively via
    Pydantic `Field(ge=..., le=...)`, rejected before a job is even queued.
    """
    if args.fill_target is not None and not (0.8 <= args.fill_target <= 0.95):
        return "--fill-target must be between 0.80 and 0.95"
    if args.initial_bullet_share is not None and not (
        0.3 <= args.initial_bullet_share <= 1.0
    ):
        return "--initial-bullet-share must be between 0.30 and 1.00"
    if args.experience_bullet_share is not None and not (
        0.0 <= args.experience_bullet_share <= 1.0
    ):
        return "--experience-bullet-share must be between 0.00 and 1.00"
    if args.max_bullets_per_entry is not None and args.max_bullets_per_entry < 1:
        return "--max-bullets-per-entry must be at least 1"
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    range_error = _validate_argument_ranges(args)
    if range_error is not None:
        print(f"error: {range_error}", file=sys.stderr)
        return 1

    try:
        workspace.bootstrap(workspace_id=args.workspace)
    except workspace.WorkspaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # The CLI is otherwise entirely flag-driven — every other behavior below traces to
    # an explicit `--flag`, which is what keeps a scripted/looped bulk-apply run
    # predictable regardless of what's saved in the web UI. `model_name`,
    # `rewrite_style`, and `expand_style` are the sole, deliberate exceptions: picked
    # up from the active profile's saved `settings.json` so a style/model preference
    # set once in the web UI doesn't have to be retyped as a flag on every CLI run.
    # No other saved setting (`pages`, `experience`, `include`, `fill_target`, …) is
    # read here — those always come from argparse defaults, never from settings.json.
    saved = workspace.load_settings()["defaults"]

    # Resolved before anything is read or spent, so a bad spec costs nothing.
    try:
        overrides: dict[str, str] = {}
        model_name = saved.get("model_name")
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
        print(f"error: {exc}", file=sys.stderr)
        return 1

    contact_fields: list[str] | None = None
    if args.contact_fields:
        valid = {"location", "email", "phone", "linkedin", "github"}
        contact_fields = [f.strip() for f in args.contact_fields.split(",") if f.strip()]
        unknown = [f for f in contact_fields if f not in valid]
        if unknown:
            print(
                f"error: --contact-fields has unknown field(s): {', '.join(unknown)} "
                f"(valid: {', '.join(sorted(valid))})",
                file=sys.stderr,
            )
            return 1

    include_options = include.IncludeOptions(
        contact_fields=contact_fields,
        gpa=not args.no_gpa,
        coursework=not args.no_coursework,
        exclude_entries=list(args.exclude_ids),
    )

    try:
        resume = data.load()
        problems = include.validate(resume, include_options)
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
            runs=args.extract_runs,
            use_cache=not args.no_cache,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # The verbatim guarantee is the feature, so it is checked rather than assumed: a
    # paraphrased phrase silently breaks the keyword-mirroring premise of the rewrite.
    paraphrased = jd.verify_verbatim(requirements, jd_text)
    if paraphrased:
        print(
            "warning: these extracted phrases are not verbatim from the posting, so "
            "mirroring them may not help:\n  " + "\n  ".join(paraphrased),
            file=sys.stderr,
        )

    diagnosis = jd.extraction_diagnosis(requirements)
    if diagnosis is not None:
        print(
            f"warning: JD extraction is inconclusive ({diagnosis}) — keyword coverage "
            "will not be measurable for this run",
            file=sys.stderr,
        )

    if args.suggest_reuse:
        match = runs.closest_run(jd_text, requirements)
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

    # Scored once, before the loop, and held fixed for the run — see `rewrite.score_table`
    # for why it must not be recomputed per iteration.
    semantic: dict[str, float] | None = None
    if not args.no_semantic:
        try:
            semantic = rewrite.score_table(
                resume.all_bullets(), requirements, use_cache=not args.no_cache
            )
        except LLMError as exc:
            # Deliberately NOT degraded. An unreachable daemon, an expired sign-in, or an
            # exhausted quota is a broken run, and silently ranking on keywords instead
            # would report success while quietly producing a worse resume.
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except (RuntimeError, ValueError) as exc:
            # A model that answered but unhelpfully is different: the resume is still
            # correct without this signal, just ranked more crudely.
            print(
                f"warning: semantic relevance scoring unavailable, ranking on keyword "
                f"overlap only ({exc})",
                file=sys.stderr,
            )

    # Kept unfiltered for the experience expansion below — an excluded job still appears
    # in the application-form paste text. Applied here (after scoring, before facets) so
    # an exclusion never invalidates the score cache, and facets never sees a pool an
    # excluded entry contributed to.
    full_resume = resume
    resume = include.apply(resume, include_options)

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
        print(f"error: {exc}", file=sys.stderr)
        return 1
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
    # budget, and report.diagnose_gaps needs the untruncated pool to find evidence there.
    master_resume = resume
    resume = facets.apply(resume, facet_result)

    # Default export name mirrors the download: "<name> Resume - <position>.docx".
    out = args.out or (
        config.OUTPUT_DIR
        / report.export_filename(resume.contact.name, requirements.title)
    )

    # Range-validated by `_validate_argument_ranges` at the top of `main`, before
    # anything was read or spent — not re-checked here.
    try:
        result = fit.fit(
            resume,
            requirements,
            target_pages=args.pages,
            template=args.template,
            out=out,
            max_experience=args.experience,
            max_projects=args.projects,
            semantic=semantic,
            repair_widows=not args.no_widow_repair,
            repair_verbs=not args.no_verb_repair,
            merge_bullets=args.merge,
            include_project_links=include_links,
            contact_fields=include.contact_order(include_options, active_layout()),
            fill_target=args.fill_target,
            initial_bullet_share=args.initial_bullet_share,
            experience_bullet_share=args.experience_bullet_share,
            max_bullets_per_entry=args.max_bullets_per_entry,
        )
    except FabricationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except fit.FitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(report.format_report(resume, requirements, result, master=master_resume))

    # Archive JD + requirements + bullets so CLI runs join the same corpus the web
    # UI already writes under output/jobs/<id>/. The human-facing `.jd.txt` sidecar
    # sits next to the .docx; the job directory is what `runs.iter_runs` reads.
    try:
        jd_sidecar = result.out_path.with_name(result.out_path.stem + ".jd.txt")
        jd_sidecar.write_text(jd_text, encoding="utf-8")
        archive_dir = config.OUTPUT_DIR / "jobs" / f"cli-{result.out_path.stem}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "jd.txt").write_text(jd_text, encoding="utf-8")
        (archive_dir / "requirements.json").write_text(
            requirements.model_dump_json(indent=2), encoding="utf-8"
        )
        (archive_dir / "bullets.json").write_text(
            json.dumps(result.bullets, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"warning: could not archive run for reuse ({exc})", file=sys.stderr)

    # Expansion is advisory paste text for application forms. It must never turn a
    # successful resume run into a failure — the .docx is already on disk.
    if not args.no_expand:
        try:
            # Unfiltered resume: an experience entry excluded from the tailored resume
            # still appears in the application-form paste text.
            expansion = expand.expand_experience(
                full_resume,
                requirements,
                fit_result=result,
                semantic=semantic,
                use_cache=not args.no_cache,
            )
            print()
            print(report.format_expansion(expansion))
            expand_path = result.out_path.with_name(
                result.out_path.stem + ".expansion.md"
            )
            expand_path.write_text(expand.format_markdown(expansion), encoding="utf-8")
            print(f"Expansion: {expand_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: experience expansion skipped ({exc})", file=sys.stderr)

    # Skills list is also advisory; also must never turn a successful run into a failure.
    # `master_resume` (post-include, pre-facets) matches exactly what `report.diagnose_gaps`
    # ran against above, so the skills tile and the gap section partition one evidence
    # universe. Not `full_resume`: an excluded entry is the user saying "not part of this
    # application", and a skill evidenced only there should not be suggested for the Skills
    # box of the package actually being submitted. Not the post-facets `resume`: facets
    # truncates Project.tech to its render budget, which would silently drop evidence.
    if not args.no_skills:
        try:
            plan = skills.select_skills(
                master_resume,
                requirements,
                use_cache=not args.no_cache,
            )
            print()
            print(report.format_skills(plan))
            skills_path = result.out_path.with_name(result.out_path.stem + ".skills.md")
            skills_path.write_text(skills.format_markdown(plan), encoding="utf-8")
            print(f"Skills: {skills_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: skills selection skipped ({exc})", file=sys.stderr)

    # Cover letter is advisory; must never turn a successful run into a failure.
    if args.cover_letter and not args.no_cover_letter:
        try:
            letter = coverletter.draft_letter(
                master_resume,
                requirements,
                result.bullets,
                jd_text,
                use_cache=not args.no_cache,
                angles=coverletter.CoverAngles(
                    why_company=args.cover_why,
                    problem=args.cover_problem,
                    approach=args.cover_approach,
                    tone=args.cover_tone,
                ),
            )
            cover_path = result.out_path.with_name(
                result.out_path.stem + " Cover Letter.docx"
            )
            coverletter.render_cover_letter(master_resume, letter, out=cover_path)
            print()
            print(report.format_cover_letter(letter))
            cover_md = result.out_path.with_name(result.out_path.stem + ".cover.md")
            cover_md.write_text(coverletter.format_markdown(letter), encoding="utf-8")
            print(f"Cover letter: {cover_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: cover letter skipped ({exc})", file=sys.stderr)

    if args.review:
        try:
            review_result = review.review_bullets(
                master_resume,
                requirements,
                result.bullets,
            )
            print()
            print(report.format_review(review_result))
            review_path = result.out_path.with_name(result.out_path.stem + ".review.md")
            review_path.write_text(report.format_review(review_result), encoding="utf-8")
            print(f"Review: {review_path}")
        except Exception as exc:  # noqa: BLE001 - bonus artifact; never fail the run
            print(f"warning: review skipped ({exc})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
