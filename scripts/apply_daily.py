"""CLI entry for one daily apply-funnel pass.

Use either this host-side script *or* the in-process Docker scheduler — not both
against the same workspace at once (they share ``applications.json`` via the bind mount).

    python scripts/apply_daily.py --dry-run
    python scripts/apply_daily.py --workspace default --limit 5 --no-browser
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/apply_daily.py` without an editable install.
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resume_tailor import config, workspace  # noqa: E402
from resume_tailor.apply.daily import run_daily  # noqa: E402
from resume_tailor.web.schemas import JobSettings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Parse flags, bootstrap the workspace, and run one daily pass."""
    parser = argparse.ArgumentParser(description="ResumeTailor daily apply funnel")
    parser.add_argument("--workspace", default=None, help="Workspace id (default: active)")
    parser.add_argument("--limit", type=int, default=None, help="Cap new discoveries")
    parser.add_argument(
        "--max-submissions",
        type=int,
        default=None,
        help="Cap unattended fill+submit this run (overrides auto_submit_max_per_run)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Discover only; no writes")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch job boards only — record as discovered without tailoring or applying",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Skip CDP fallback when HTTP JD extraction is short",
    )
    parser.add_argument(
        "--list-sections",
        metavar="URL",
        default=None,
        help="Fetch a README and print its ##–#### section names, then exit",
    )
    args = parser.parse_args(argv)

    if args.list_sections:
        from resume_tailor.apply import sources

        text = sources.fetch_readme(args.list_sections)
        for level, name in sources.list_sections(text):
            print(f"{'#' * level} {name}")
        return 0

    workspace.bootstrap()
    if args.workspace:
        workspace.activate(args.workspace)

    raw = workspace.load_settings()["defaults"]
    settings = JobSettings.model_validate(raw)
    config.resolve(settings.model)

    summary = run_daily(
        settings=settings.apply,
        limit=args.limit,
        dry_run=args.dry_run,
        allow_browser=not args.no_browser,
        auto_submit_max_per_run=args.max_submissions,
        fetch_only=args.fetch_only,
        log=print,
    )
    if summary.already_running:
        print("already_running", file=sys.stderr)
        return 2
    print(
        f"ready={summary.ready} screened_out={summary.screened_out} "
        f"needs_browser={summary.needs_browser} errors={len(summary.errors)} "
        f"submitted={summary.submitted} submit_failed={summary.submit_failed}"
    )
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
