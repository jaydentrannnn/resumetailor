"""Argument parsing for the `tailor.py` CLI (flag reference: `docs/REFERENCE.md` §1)."""

from __future__ import annotations

import argparse
from pathlib import Path

from resume_tailor import config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tailor.py",
        description="Tailor a resume to a job description without changing its formatting.",
    )
    _add_input_flags(parser)
    _add_pipeline_flags(parser)
    _add_stage_flags(parser)
    _add_content_flags(parser)
    _add_fit_tuning_flags(parser)
    _add_run_flags(parser)
    _add_cover_review_flags(parser)
    return parser.parse_args(argv)


def _add_input_flags(parser: argparse.ArgumentParser) -> None:
    """Inputs, output, and the page/entry budget."""
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


def _add_pipeline_flags(parser: argparse.ArgumentParser) -> None:
    """Caching, extraction voting, and the fit loop's repair ladder."""
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Re-extract the job description instead of reusing a cached extraction.",
    )
    parser.add_argument(
        "--extract-runs",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Vote over N independent JD extractions to damp per-call canonicalisation "
            "noise (default: 1 on Anthropic/Gemini, "
            f"{config.EXTRACT_CONSENSUS_RUNS} on local models). 1 restores a single call."
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
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Merge redundant bullet points within a single entry (on by default; "
            "--no-merge opts out). It is the first rung of the overflow ladder and fires "
            "only after the page has measured over its target, so a resume that already "
            "fits is never merged."
        ),
    )


def _add_stage_flags(parser: argparse.ArgumentParser) -> None:
    """Model routing and the opt-out/opt-in bonus stages."""
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


def _add_content_flags(parser: argparse.ArgumentParser) -> None:
    """What content is eligible: facets, links, GPA, coursework, contact, exclusions."""
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


def _add_fit_tuning_flags(parser: argparse.ArgumentParser) -> None:
    """Fit-loop tuning, range-checked by `validate_argument_ranges`."""
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


def _add_run_flags(parser: argparse.ArgumentParser) -> None:
    """Effort, workspace selection, and prior-run reuse."""
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


def _add_cover_review_flags(parser: argparse.ArgumentParser) -> None:
    """Cover-letter angles and the hiring-manager review."""
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


def validate_argument_ranges(args: argparse.Namespace) -> str | None:
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
