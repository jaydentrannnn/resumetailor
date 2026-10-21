"""Build a `fill_probe.py` target list from the owner's tracked applications (eval-only).

Reads a workspace's ``app.db`` read-only (``?mode=ro``), so the live app's data is never
written. Each row's posting URL is re-detected (`fetch_jd.detect_ats`, as
`scripts/ats_stats.py` does), LinkedIn/Indeed and archived rows are dropped, and at most
one posting is kept per site (`identity._requisition`'s ATS and owner: one Workday tenant,
one Greenhouse board, one other host), so every test account is on a different site and
the set spans as many sites as the quotas allow. Within a platform the newest postings
come first (an old one is likelier closed), alternating unsubmitted and submitted rows.

The output is the probe's TSV (``tag, url, ats, modes, account``); tags name the platform
and a number, never the company, and the file stays outside the repo.

    python scripts/evals/fill_probe_targets.py \
        --out %LOCALAPPDATA%/ResumeTailorData/evals/batch3_targets.tsv
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Iterable
from itertools import zip_longest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from resume_tailor.apply.discovery import fetch_jd, identity  # noqa: E402

DEFAULT_DB = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "ResumeTailorData" / "data" / "workspaces" / "default" / "app.db"
)
#: Postings per platform; every other platform shares ``other``.
QUOTAS: dict[str, int] = {
    "workday": 40,
    "greenhouse": 15,
    "ashby": 12,
    "icims": 10,
    "oracle": 8,
    "smartrecruiters": 8,
    "lever": 8,
    "jobvite": 4,
    "other": 15,
}
#: Platforms whose application sits behind a per-site candidate account.
ACCOUNT_ATS = frozenset({"workday", "icims", "oracle", "taleo", "successfactors"})
_CAPTURE_ONLY = ("linkedin.com", "indeed.com")


def load_rows(db: Path) -> list[dict]:
    """Every application row as ``{url, ats, status, archived, discovered}``, read-only."""
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = []
        for (doc,) in connection.execute("select doc from applications"):
            data = json.loads(doc)
            rows.append(
                {
                    "url": data.get("final_url") or data.get("posting_url") or "",
                    "ats": data.get("ats") or "unknown",
                    "status": data.get("status") or "",
                    "archived": bool(data.get("archived_at")),
                    "discovered": data.get("discovered_at") or "",
                }
            )
        return rows
    finally:
        connection.close()


def platform(url: str, stored: str) -> str:
    """The posting's platform: detected from its URL unless that says nothing."""
    detected = fetch_jd.detect_ats(url)
    return stored if detected in {"other", "unknown"} else detected


def capture_only(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in _CAPTURE_ONLY)


def site_key(url: str) -> tuple[str, str]:
    """One test account per key: the requisition's ATS and owner, else the URL's host."""
    ats, owner, _ = identity._requisition(url)
    return ats, owner or (urlparse(url).hostname or "").lower()


def pick(rows: Iterable[dict], quotas: dict[str, int] = QUOTAS) -> list[dict]:
    """Targets per platform under ``quotas``, one per site, newest first, alternating
    unsubmitted and submitted rows."""
    seen: set[tuple[str, str]] = set()
    pools: dict[str, tuple[list[dict], list[dict]]] = {}
    for row in sorted(rows, key=lambda r: r["discovered"], reverse=True):
        url = row["url"]
        if row["archived"] or not url.startswith("http") or capture_only(url):
            continue
        ats = platform(url, row["ats"])
        if ats in {"linkedin", "indeed"}:
            continue
        key = site_key(url)
        if key in seen:
            continue
        seen.add(key)
        bucket = ats if ats in quotas else "other"
        unsubmitted, submitted = pools.setdefault(bucket, ([], []))
        (submitted if row["status"].startswith("submit") else unsubmitted).append(
            {**row, "platform": ats}
        )
    targets = []
    for bucket, quota in quotas.items():
        unsubmitted, submitted = pools.get(bucket, ([], []))
        mixed = [r for pair in zip_longest(unsubmitted, submitted) for r in pair if r]
        for number, row in enumerate(mixed[:quota], start=1):
            targets.append(
                {
                    "tag": f"{bucket}{number:02d}",
                    "url": row["url"],
                    "ats": row["platform"],
                    "modes": "live",
                    "account": "account" if row["platform"] in ACCOUNT_ATS else "",
                }
            )
    return targets


def to_tsv(targets: list[dict]) -> str:
    lines = ["# tag\turl\tats\tmodes\taccount"]
    lines += ["\t".join(t[k] for k in ("tag", "url", "ats", "modes", "account")) for t in targets]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    targets = pick(load_rows(args.db))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_tsv(targets), encoding="utf-8")
    counts: dict[str, int] = {}
    for target in targets:
        counts[target["ats"]] = counts.get(target["ats"], 0) + 1
    print(len(targets), "targets:", " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
