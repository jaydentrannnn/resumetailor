"""Count tracked applications by ATS and status, to pick which adapter to build next.

Rows are counted under the ATS detected from their URL today, so a row stored as
``other`` before a platform was recognised (Taleo, SuccessFactors, Oracle, ...) shows up
under its platform. ``--stored`` counts the stored ``ats`` value instead.

    python scripts/ats_stats.py
    python scripts/ats_stats.py --workspace default --include-archived
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from resume_tailor.apply.funnel import store_models

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resume_tailor import workspace  # noqa: E402
from resume_tailor.apply.discovery import fetch_jd  # noqa: E402
from resume_tailor.apply.funnel import store  # noqa: E402

#: Statuses that mean the form was reached, in the order they are printed.
_COLUMNS = (
    "ready",
    "filling",
    "awaiting_review",
    "awaiting_otp",
    "fill_failed",
    "submitted",
    "submit_unconfirmed",
)


def ats_of(app: store_models.Application, *, stored: bool = False) -> str:
    """The row's ATS: detected from its URL unless ``stored`` or the URL is unhelpful."""
    if stored:
        return app.ats
    url = app.final_url or app.posting_url
    detected = fetch_jd.detect_ats(url) if url else "unknown"
    return app.ats if detected in {"other", "unknown"} else detected


def tally(
    apps: Iterable[store_models.Application],
    *,
    stored: bool = False,
    include_archived: bool = False,
) -> dict[str, Counter[str]]:
    """``{ats: Counter(status)}`` plus a ``total`` per ATS, busiest ATS first."""
    table: dict[str, Counter[str]] = {}
    for app in apps:
        if app.archived_at and not include_archived:
            continue
        row = table.setdefault(ats_of(app, stored=stored), Counter())
        row[app.status] += 1
        row["total"] += 1
    return dict(sorted(table.items(), key=lambda item: (-item[1]["total"], item[0])))


def format_table(table: dict[str, Counter[str]]) -> str:
    """A fixed-width text table: one row per ATS, the fill-stage statuses as columns."""
    header = ("ats", "total", *_COLUMNS)
    rows = [header] + [
        (ats, str(counts["total"]), *(str(counts[c] or "") for c in _COLUMNS))
        for ats, counts in table.items()
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Applications by ATS and status")
    parser.add_argument("--workspace", default=None, help="Workspace id (default: active)")
    parser.add_argument("--stored", action="store_true", help="Use the stored ats value")
    parser.add_argument("--include-archived", action="store_true", help="Count archived rows too")
    args = parser.parse_args(argv)

    workspace.bootstrap()
    if args.workspace:
        workspace.activate(args.workspace)
    table = tally(
        store.load_all().values(), stored=args.stored, include_archived=args.include_archived
    )
    if not table:
        print("No applications tracked yet.")
        return 0
    print(format_table(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
