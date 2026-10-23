"""Skills the postings you went after asked for and your resume lacks — pure, no LLM.

Reads each pursued application's coverage funnel (`coverage.read`: the tailored run's
`coverage.json` or run report). A must-have the master resume does not back at all
(`resume is None`) is a **gap**; one it backs that the page did not show is listed apart
as **not shown** (worth stating in a bullet's own words). Each counts distinct postings,
weighted by how close the posting was: its share of must-haves the resume backs. A gap
in a near-miss counts more than one in a posting that was never close.

A funnel is a snapshot of the resume at run time, so `known` (the current resume's
`bullet_tags.known_terms`) drops a gap the resume has backed since. Rows that never got
a tailored run have no funnel and are only counted (`uncounted`).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from pydantic import BaseModel

from ... import config
from ...pipeline import coverage
from . import store_models

#: Postings the applicant went after: screened in, then any later stage.
PURSUED: frozenset[str] = frozenset({
    "screened_in", "tailoring", "tailor_failed", "ready", "filling", "awaiting_otp",
    "fill_failed", "awaiting_review", "submitted", "submit_unconfirmed", "interview",
    "rejected", "ghosted",
})
#: Skills listed per kind; the rest are only counted in `SkillGaps`.
LIMIT = 8


class SkillGap(BaseModel):
    #: The posting's own wording, the one used most often.
    skill: str
    canonical: str
    #: Distinct postings that asked for it.
    jobs: int
    #: Those postings' coverage shares, summed; the ranking key.
    weight: float
    #: Up to three of the companies, most recent first.
    companies: list[str]


class SkillGaps(BaseModel):
    #: Pursued postings with a coverage funnel, and those without one.
    counted: int = 0
    uncounted: int = 0
    gaps: list[SkillGap] = []
    not_shown: list[SkillGap] = []


def _run_dir(job_id: str) -> Path:
    return config.OUTPUT_DIR / "jobs" / job_id


class _Tally:
    def __init__(self) -> None:
        self.weight: dict[str, float] = defaultdict(float)
        self.phrases: dict[str, Counter[str]] = defaultdict(Counter)
        self.companies: dict[str, list[str]] = defaultdict(list)

    def add(self, kw: coverage.KeywordCoverage, share: float, company: str) -> None:
        self.weight[kw.canonical] += share
        self.phrases[kw.canonical][kw.phrase] += 1
        if company and company not in self.companies[kw.canonical]:
            self.companies[kw.canonical].append(company)

    def ranked(self, limit: int) -> list[SkillGap]:
        rows = [
            SkillGap(skill=phrases.most_common(1)[0][0], canonical=canonical,
                     jobs=phrases.total(), weight=round(self.weight[canonical], 2),
                     companies=self.companies[canonical][:3])
            for canonical, phrases in self.phrases.items()
        ]
        rows.sort(key=lambda g: (-g.weight, -g.jobs, g.skill.lower()))
        return rows[:limit]


def _last_change(row: store_models.Application) -> str:
    return row.status_history[-1].at if row.status_history else row.discovered_at


def _pursued(rows:Iterable[store_models.Application]) -> list[store_models.Application]:
    """Pursued rows, newest first, one per tailored run (a reused run counts once)."""
    keep = [r for r in rows if r.status in PURSUED and not r.duplicate_of]
    keep.sort(key=_last_change, reverse=True)
    seen: set[str] = set()
    out = []
    for row in keep:
        key = row.job_id or f"row:{row.source_job_id}"
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def skill_gaps(
    rows: Iterable[store_models.Application],
    *,
    known: set[str] | None = None,
    read: Callable[[Path], coverage.CoverageFunnel | None] = coverage.read,
    limit: int = LIMIT,
) -> SkillGaps:
    """The must-haves pursued postings asked for, ranked; see the module docstring."""
    gaps, not_shown = _Tally(), _Tally()
    counted = uncounted = 0
    for row in _pursued(rows):
        funnel = read(_run_dir(row.job_id)) if row.job_id else None
        if funnel is None or not funnel.total:
            uncounted += 1
            continue
        counted += 1
        share = funnel.in_resume / funnel.total
        for kw in funnel.keywords:
            if kw.resume is None:
                if known is None or kw.canonical not in known:
                    gaps.add(kw, share, row.company)
            elif kw.page not in coverage.ON_PAGE:
                not_shown.add(kw, share, row.company)
    return SkillGaps(counted=counted, uncounted=uncounted, gaps=gaps.ranked(limit),
                     not_shown=not_shown.ranked(limit))
