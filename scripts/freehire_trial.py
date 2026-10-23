"""Trial of the freehire.me provider: does it find postings our other sources miss?

Each run searches freehire with the keyword sources' phrases (country, age limit and
filters as the workspace sets them) and records which hits the registry already holds,
by requisition (`identity.canonical_key`) or by company + role (`identity.group_key`).
Read-only: settings and the registry (`app.db`, opened read-only) are never written.
A snapshot goes to ``output/freehire_trial/<date>.json``; ``--report`` re-checks every
snapshot's new postings against today's registry, so a posting another source found
later stops counting as unique. Run it once a day for a week, then decide.

    python scripts/freehire_trial.py --workspace-dir <workspace folder>
    python scripts/freehire_trial.py --workspace-dir <workspace folder> --report

The desktop app's default workspace folder is
``%LOCALAPPDATA%/ResumeTailorData/data/workspaces/default``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resume_tailor.apply.discovery import fetch_jd, freehire, identity, job_apis  # noqa: E402
from resume_tailor.apply.discovery.source_filters import with_global_filters  # noqa: E402
from resume_tailor.web.schemas import ApplySettings  # noqa: E402

OUT = _ROOT / "output" / "freehire_trial"
#: Platforms Fill can't drive or that aren't an employer's own posting.
_NOT_FILLABLE = {"linkedin", "indeed", "handshake", "other", "unknown"}


def _registry(workspace_dir: Path) -> tuple[set[str], set[str]]:
    """Requisition keys and company + role keys of every tracked row."""
    uri = f"file:{(workspace_dir / 'app.db').as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        rows = db.execute("SELECT key, group_key, company, role FROM applications").fetchall()
    keys = {key for key, *_ in rows}
    groups = {g or identity.group_key(c or "", r or "") for _k, g, c, r in rows}
    return keys, groups


def _settings(workspace_dir: Path) -> ApplySettings:
    raw = json.loads((workspace_dir / "settings.json").read_text(encoding="utf-8"))
    return ApplySettings.model_validate((raw.get("defaults") or raw).get("apply") or {})


def _search(settings: ApplySettings) -> list[dict]:
    now = datetime.now(UTC)
    hits: dict[str, dict] = {}
    for src in settings.sources:
        if not (src.enabled and src.kind == "job_search"):
            continue
        source = with_global_filters(src, settings.source_filters)
        for phrase in job_apis.split_phrases(source.query):
            rows, errors = freehire.search(
                source, query=phrase, get=httpx.get, now=now, max_pages=job_apis.MAX_PAGES,
                pause=lambda: time.sleep(job_apis.JOB_SEARCH_DELAY_SECONDS))
            for message in errors:
                print(f"  {phrase}: {message}")
            for row in rows:
                hits.setdefault(row.job_id, {
                    "phrase": phrase, "company": row.company, "role": row.role,
                    "location": row.location, "url": row.application_link,
                    "key": identity.canonical_key(row.application_link or ""),
                    "group": identity.group_key(row.company, row.role),
                    "ats": fetch_jd.detect_ats(row.application_link or ""),
                })
            time.sleep(job_apis.JOB_SEARCH_DELAY_SECONDS)
    return list(hits.values())


def _new(hits: list[dict], keys: set[str], groups: set[str]) -> list[dict]:
    return [h for h in hits if h["key"] not in keys and h["group"] not in groups]


def _summary(label: str, hits: list[dict], new: list[dict]) -> None:
    fillable = [h for h in new if h["ats"] not in _NOT_FILLABLE]
    print(f"{label}: {len(hits)} kept after filters, {len(new)} not in the registry, "
          f"{len(fillable)} of those on a fillable ATS")
    print("  by ATS:", dict(Counter(h["ats"] for h in new).most_common()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace-dir", type=Path, required=True,
                        help="A workspace data folder holding settings.json and app.db.")
    parser.add_argument("--report", action="store_true",
                        help="Re-check every saved snapshot against today's registry.")
    args = parser.parse_args()
    keys, groups = _registry(args.workspace_dir)
    if args.report:
        seen: dict[str, dict] = {}
        for path in sorted(OUT.glob("*.json")):
            for hit in json.loads(path.read_text(encoding="utf-8"))["new"]:
                seen.setdefault(hit["key"], hit)
        snapshots = len(list(OUT.glob("*.json")))
        _summary(f"{snapshots} snapshot(s), still unique today", list(seen.values()),
                 _new(list(seen.values()), keys, groups))
        return 0
    hits = _search(_settings(args.workspace_dir))
    new = _new(hits, keys, groups)
    OUT.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    (OUT / f"{day}.json").write_text(json.dumps({"hits": hits, "new": new}, indent=2), "utf-8")
    _summary(day, hits, new)
    for hit in new[:15]:
        print(f"  {hit['ats']:>15}  {hit['company']} · {hit['role']} · {hit['location']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
