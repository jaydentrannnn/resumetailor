"""Eval cases: saved runs (deduped by posting) and fetched postings, plus a stable sample."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

#: Below this many characters a posting counts as short (a hard case for extraction).
SHORT_POSTING = 1500

_HEDGED = re.compile(r"\b(not required|nice[- ]to[- ]have|a plus|preferred but)\b", re.I)
_SHORT_NAMES = re.compile(r"(?<![\w+#])(Go|R|C|C\+\+|C#|Spark|Excel)(?![\w+#])")


@dataclass(frozen=True)
class Case:
    """One posting to replay. `job_dir` is None for a fetched posting with no saved run."""

    case_id: str
    jd_text: str
    job_dir: Path | None = None
    ats: str = "unknown"
    bullet_ids: tuple[str, ...] = ()
    workspace: str = "default"
    group: str = "tech"
    tags: frozenset[str] = field(default_factory=frozenset)

    def requirements_json(self) -> str | None:
        """The run's own saved extraction, when there is one."""
        if self.job_dir is None:
            return None
        path = self.job_dir / "requirements.json"
        return path.read_text(encoding="utf-8") if path.exists() else None


def digest(text: str) -> str:
    """Posting identity: whitespace- and case-insensitive."""
    return hashlib.sha1(" ".join(text.lower().split()).encode()).hexdigest()


def hard_case_tags(text: str) -> frozenset[str]:
    """Tags for the extraction hard cases the E experiment reports separately."""
    tags = set()
    if len(text) < SHORT_POSTING:
        tags.add("short")
    if _HEDGED.search(text):
        tags.add("hedged")
    if _SHORT_NAMES.search(text):
        tags.add("short_names")
    return frozenset(tags)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_saved(jobs_dir: Path, workspace: str = "default") -> list[Case]:
    """One case per distinct posting, the newest run winning; newest first.

    A run needs `jd.txt` and `requirements.json`. `bullets.json` (the ids the resume
    used) is optional here; stages that need it skip cases without it.
    """
    dirs = sorted(
        (p for p in jobs_dir.iterdir()
         if (p / "jd.txt").exists() and (p / "requirements.json").exists()),
        key=lambda p: p.stat().st_mtime, reverse=True,
    ) if jobs_dir.exists() else []
    seen: set[str] = set()
    cases = []
    for job_dir in dirs:
        text = (job_dir / "jd.txt").read_text(encoding="utf-8").strip()
        key = digest(text)
        if not text or key in seen:
            continue
        seen.add(key)
        bullets = _read_json(job_dir / "bullets.json")
        ats = _read_json(job_dir / "packet.json").get("ats") or "unknown"
        cases.append(Case(
            case_id=job_dir.name, jd_text=text, job_dir=job_dir, ats=ats,
            bullet_ids=tuple(bullets), workspace=workspace, tags=hard_case_tags(text),
        ))
    return cases


def load_texts(folder: Path) -> list[Case]:
    """Fetched postings: `<id>.txt`, with an optional `<id>.json` sidecar naming the
    `group` (e.g. "finance") and the `workspace` whose resume it runs against."""
    cases = []
    for path in sorted(folder.glob("*.txt")) if folder.exists() else []:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        meta = _read_json(path.with_suffix(".json"))
        cases.append(Case(
            case_id=path.stem, jd_text=text, ats=meta.get("ats", "unknown"),
            workspace=meta.get("workspace", "default"), group=meta.get("group", "nontech"),
            tags=hard_case_tags(text),
        ))
    return cases


def _stratum(case: Case) -> tuple[str, bool]:
    return case.ats, len(case.jd_text) < SHORT_POSTING


def sample(
    cases: Iterable[Case], n: int | None, *, seed: int = 0,
    stratum: Callable[[Case], object] = _stratum,
) -> list[Case]:
    """`n` cases spread proportionally over strata (ATS x short posting), deterministic.

    Every stratum gets at least one case while `n` allows, so rare ATSes are not lost
    to rounding. `n=None` (or `n >= len`) returns every case in its original order.
    """
    pool = list(cases)
    if n is None or n >= len(pool):
        return pool
    groups: dict[object, list[Case]] = defaultdict(list)
    for case in pool:
        groups[stratum(case)].append(case)
    rng = random.Random(seed)
    for members in groups.values():
        rng.shuffle(members)
    order = sorted(groups, key=lambda k: (-len(groups[k]), str(k)))
    quota = {k: 0 for k in order}
    for k in order[:n]:
        quota[k] = 1
    left = n - sum(quota.values())
    while left > 0:
        open_ = [k for k in order if quota[k] < len(groups[k])]
        k = max(open_, key=lambda k: (len(groups[k]) / (quota[k] + 1), -order.index(k)))
        quota[k] += 1
        left -= 1
    chosen = {id(c) for k in order for c in groups[k][:quota[k]]}
    return [c for c in pool if id(c) in chosen]
