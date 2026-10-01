"""Read archived tailor runs from the active workspace's output tree.

Deliberately its own module rather than a helper inside `jdsim.py`: review artifacts
and any later history feature want the same reader. Skips directories missing any of the
three required files rather than crashing on a partial write.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .. import config
from .jd import JobRequirements


@dataclass(frozen=True)
class ArchivedRun:
    """One completed run that has enough on disk to compare or reuse."""

    job_id: str
    jd_text: str
    requirements: JobRequirements
    bullets: dict[str, str]
    path: Path


def iter_runs(root: Path | None = None) -> Iterator[ArchivedRun]:
    """Yield archived runs under `root` (default: `<OUTPUT_DIR>/jobs`).

    Each child directory must contain `jd.txt`, `requirements.json`, and
    `bullets.json`. Missing any one file skips that directory silently — a
    cancelled or mid-write job must not crash an advisory scan.
    """
    base = root if root is not None else config.OUTPUT_DIR / "jobs"
    if not base.is_dir():
        return
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        jd_path = child / "jd.txt"
        req_path = child / "requirements.json"
        bullets_path = child / "bullets.json"
        if not (jd_path.is_file() and req_path.is_file() and bullets_path.is_file()):
            continue
        try:
            requirements = JobRequirements.model_validate_json(
                req_path.read_text(encoding="utf-8")
            )
            bullets = json.loads(bullets_path.read_text(encoding="utf-8"))
            if not isinstance(bullets, dict):
                continue
            jd_text = jd_path.read_text(encoding="utf-8")
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        yield ArchivedRun(
            job_id=child.name,
            jd_text=jd_text,
            requirements=requirements,
            bullets={str(k): str(v) for k, v in bullets.items()},
            path=child,
        )


def closest_run(
    jd_text: str,
    requirements: JobRequirements,
    *,
    root: Path | None = None,
    exclude_job_id: str | None = None,
) -> tuple[ArchivedRun, str, float] | None:
    """Return `(run, recommendation, score)` for the closest prior run, or None.

    Uses `jdsim.recommend_reuse` per candidate; picks the highest Jaccard score.
    `exclude_job_id` skips the current run when scanning from inside a job directory.
    """
    from . import jdsim

    best: tuple[ArchivedRun, str, float] | None = None
    for run in iter_runs(root):
        if exclude_job_id is not None and run.job_id == exclude_job_id:
            continue
        recommendation, score = jdsim.recommend_reuse(
            jd_text,
            run.jd_text,
            current_requirements=requirements,
            prior_requirements=run.requirements,
        )
        if best is None or score > best[2]:
            best = (run, recommendation, score)
    return best
