"""Fetch public non-tech postings for the extraction experiment (E).

Finance roles come from the app's own banking/consulting/finance starter watchlists
and run against a finance profile; the other non-tech roles (healthcare, marketing,
operations, sales) come from a short list of public boards below. Each posting is saved
as `<id>.txt` plus a `<id>.json` sidecar (`group`, `workspace`, `ats`, `title`, `url`)
that `corpus.load_texts` reads. Boards that 404 or time out are skipped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path

_TECH = re.compile(
    r"\b(engineer|engineering|developer|software|data scien|machine learning|devops|"
    r"sre|architect|platform|security|cyber|penetration|it support|technical|technology)\b", re.I)
_FINANCE = re.compile(
    r"\b(analyst|associate|accountant|accounting|audit|finance|financial|investment|"
    r"risk|credit|treasury|tax|consultant|banking|underwrit|compliance|controller)\b", re.I)
_OTHER = re.compile(
    r"\b(nurse|nursing|clinical|care|pharmac|marketing|brand|content|communications|"
    r"operations|sales|account executive|recruit|people|hr\b|customer|coordinator|"
    r"buyer|merchandis|store|retail|supply|logistics)\b", re.I)

#: Public boards for non-finance, non-tech roles. Suggestions only: a missing board is
#: skipped, never fatal.
OTHER_BOARDS: list[dict[str, str]] = [
    {"ats": "greenhouse", "slug": "oscar", "company": "Oscar Health"},
    {"ats": "greenhouse", "slug": "talkspace", "company": "Talkspace"},
    {"ats": "greenhouse", "slug": "zocdoc", "company": "Zocdoc"},
    {"ats": "greenhouse", "slug": "parachutehealth", "company": "Parachute Health"},
    {"ats": "greenhouse", "slug": "glossier", "company": "Glossier"},
    {"ats": "greenhouse", "slug": "sweetgreen", "company": "Sweetgreen"},
    {"ats": "greenhouse", "slug": "everlane", "company": "Everlane"},
    {"ats": "greenhouse", "slug": "renttherunway", "company": "Rent the Runway"},
    {"ats": "greenhouse", "slug": "harrys", "company": "Harry's"},
    {"ats": "lever", "slug": "foodsmart", "company": "Foodsmart"},
]

Lister = Callable[[str, str], list]
Fetcher = Callable[[str, str, object], str | None]


def wanted(title: str, group: str) -> bool:
    """A non-tech title of the group's kind."""
    if _TECH.search(title):
        return False
    return bool((_FINANCE if group == "finance" else _OTHER).search(title))


def _default_lister(ats: str, slug: str) -> list:
    from resume_tailor.apply.discovery import boards

    return boards.list_board(ats, slug)


def _default_fetcher(ats: str, slug: str, job) -> str | None:
    from resume_tailor.apply.discovery import ats_api

    if ats == "workday":
        return ats_api.workday_posting(job.url).text
    return ats_api.fetch_posting(f"{ats}:{slug}:{job.id}").text


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def fetch(
    dest: Path, boards_: Iterable[dict[str, str]], *, group: str, workspace: str,
    per_board: int = 3, total: int = 20, lister: Lister = _default_lister,
    fetcher: Fetcher = _default_fetcher, log: Callable[[str], None] = print,
) -> int:
    """Save up to `total` postings of `group`, at most `per_board` per board; returns
    how many are on disk for this group afterwards (existing files count)."""
    dest.mkdir(parents=True, exist_ok=True)
    have = sum(1 for p in dest.glob("*.json")
               if json.loads(p.read_text("utf-8")).get("group") == group)
    for board in boards_:
        if have >= total:
            break
        ats, slug = board["ats"], board["slug"]
        try:
            jobs = lister(ats, slug)
        except Exception as exc:  # noqa: BLE001 - a dead board is skipped, not fatal
            log(f"  skip {ats}:{slug} ({type(exc).__name__})")
            continue
        taken = 0
        for job in jobs:
            if taken >= per_board or have >= total:
                break
            if not wanted(job.title, group):
                continue
            stem = _safe(f"{group}-{board.get('company') or slug}-{job.id}")
            if (dest / f"{stem}.txt").exists():
                continue
            try:
                text = fetcher(ats, slug, job)
            except Exception:  # noqa: BLE001
                text = None
            if not text:
                continue
            (dest / f"{stem}.txt").write_text(text, encoding="utf-8")
            (dest / f"{stem}.json").write_text(json.dumps({
                "group": group, "workspace": workspace, "ats": ats,
                "title": job.title, "url": job.url, "company": board.get("company", ""),
            }, indent=2), encoding="utf-8")
            taken += 1
            have += 1
            log(f"  saved {stem}: {job.title}")
    return have
