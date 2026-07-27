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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from resume_tailor import config, data, fit, jd, report, rewrite  # noqa: E402
from resume_tailor.llm import LLMError  # noqa: E402
from resume_tailor.rewrite import FabricationError  # noqa: E402


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
        help="Where to write the tailored .docx (default: output/tailored.docx).",
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
        "--merge",
        action="store_true",
        help=(
            "Enable merging redundant bullet points within a single entry, using an "
            "additional non-regressive merge pass."
        ),
    )
    parser.add_argument(
        "--model",
        default="claude",
        metavar="MODEL",
        help=(
            "Which backend serves the run: a profile (claude, ollama, hybrid) or a spec "
            "like 'ollama:minimax-m3:cloud'. 'hybrid' ranks on Ollama and rewrites "
            "on Claude. Default: claude."
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
        "--effort",
        choices=("low", "medium", "high"),
        default=None,
        help=(
            "Reasoning depth for every stage. Most of the per-call cost is reasoning "
            "tokens, so this is the cheapest lever available."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Resolved before anything is read or spent, so a bad spec costs nothing.
    try:
        config.resolve(
            args.model,
            overrides={"rewrite": args.rewrite_model} if args.rewrite_model else None,
            effort=args.effort,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        resume = data.load()
        jd_text = args.jd.read_text(encoding="utf-8")
        # The resume's own tag vocabulary steers `canonical`, so the extractor stops
        # coining tags that can never match anything ("communication skills" against a
        # resume tagged `communication`). An unmatched canonical then means a real gap.
        known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})
        requirements = jd.extract(
            jd_text, known_tags=known_tags, use_cache=not args.no_cache
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

    try:
        result = fit.fit(
            resume,
            requirements,
            target_pages=args.pages,
            template=args.template,
            out=args.out,
            max_experience=args.experience,
            max_projects=args.projects,
            semantic=semantic,
            repair_widows=not args.no_widow_repair,
            merge_bullets=args.merge,
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

    print(report.format_report(resume, requirements, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
