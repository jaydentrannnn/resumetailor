"""What an application sent, read back for interview prep and follow-ups.

The submitted copy (`attempts.latest`) is the source: the bullets, cover letter and
posting the employer actually has. A row sent before attempts were recorded, or whose
copy is missing its bullets, falls back to its run folder and says so, so prep still
works for applications already in flight. Read-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ... import config
from ...pipeline import coverage
from ...pipeline.jd import JobRequirements
from . import attempts, store_models
from .packet import _load_cover_letter


@dataclass
class SentCopy:
    folder: Path
    #: The submitted attempt's number; None when read from the run folder instead.
    attempt: int | None
    bullets: dict[str, str]
    requirements: JobRequirements | None
    cover_letter: str
    jd_text: str
    #: Must-have phrases the master resume does not support, in posting order.
    gaps: list[str] = field(default_factory=list)

    @property
    def based_on(self) -> str:
        if self.attempt is not None:
            return f"Submitted copy (attempt {self.attempt})"
        return "Latest prepared files (no submitted copy was recorded)"


def _folder(app: store_models.Application) -> tuple[Path, int | None] | None:
    attempt = attempts.latest(app)
    if attempt is not None and attempt.snapshot_dir:
        folder = Path(attempt.snapshot_dir)
        if (folder / "bullets.json").is_file():
            return folder, attempt.number
    if app.job_id:
        folder = config.OUTPUT_DIR / "jobs" / app.job_id
        if (folder / "bullets.json").is_file():
            return folder, None
    return None


def _read_text(*paths: Path) -> str:
    for path in paths:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def load(app: store_models.Application) -> SentCopy | None:
    """The files behind what was sent, or None when no tailored run exists."""
    found = _folder(app)
    if found is None:
        return None
    folder, number = found
    bullets = json.loads((folder / "bullets.json").read_text(encoding="utf-8"))
    requirements = None
    # A reused run was tailored for another posting: its requirements are not this job's.
    if (folder / "requirements.json").is_file() and not app.reused_from_job_id:
        requirements = JobRequirements.model_validate_json(
            (folder / "requirements.json").read_text(encoding="utf-8")
        ).model_copy(update={"title": app.role or ""})
    app_dir = config.APPLICATIONS_OUTPUT_DIR / app.source_job_id
    jd_text = _read_text(
        folder / "jd.txt", *([Path(app.jd_text_path)] if app.jd_text_path else []),
        app_dir / "jd.txt",
    )
    funnel = coverage.read(folder) if requirements is not None else None
    gaps = [kw.phrase for kw in funnel.keywords if kw.resume is None] if funnel else []
    return SentCopy(
        folder=folder,
        attempt=number,
        bullets={str(k): str(v) for k, v in bullets.items()},
        requirements=requirements,
        cover_letter=_load_cover_letter(folder / "cover.json"),
        jd_text=jd_text,
        gaps=gaps,
    )
