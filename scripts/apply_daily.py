"""CLI entry for one daily apply-funnel pass.

The pass finds and tailors new postings; it never fills or submits (that is Fill's job).
Use either this host-side script *or* the in-process Docker scheduler — not both
against the same workspace at once. Both write the workspace's ``app.db`` (safe: SQLite
transactions), but two runs would discover and tailor the same postings.

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
from resume_tailor.apply.funnel.daily import run_daily  # noqa: E402
from resume_tailor.web.schemas import JobSettings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Parse flags, bootstrap the workspace, and run one daily pass."""
    parser = argparse.ArgumentParser(description="ResumeTailor daily apply funnel")
    parser.add_argument("--workspace", default=None, help="Workspace id (default: active)")
    parser.add_argument("--limit", type=int, default=None, help="Cap new discoveries")
    parser.add_argument("--dry-run", action="store_true", help="Discover only; no writes")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Find jobs only — discover, fetch each JD and prefilter; no tailoring",
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
        from resume_tailor.apply.discovery import source_headings, sources

        text = sources.fetch_readme(args.list_sections)
        for level, name in source_headings.list_sections(text):
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
        fetch_only=args.fetch_only,
        log=print,
    )
    if summary.already_running:
        print("already_running", file=sys.stderr)
        return 2
    print(
        f"ready={summary.ready} screened_out={summary.screened_out} "
        f"needs_browser={summary.needs_browser} errors={len(summary.errors)}"
    )
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
