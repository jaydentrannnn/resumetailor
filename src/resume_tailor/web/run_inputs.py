"""What a tailoring run was built from, recorded in its ``run.json`` as ``inputs``.

A run captures the master resume when it is queued (`JobQueue.submit`), so an edit
saved while it waits or runs never mixes into it (audit #13); that copy is kept beside
the run (``resume_snapshot.json``) for the cover letter regenerated later. ``inputs``
names the resume, template, guidance, writing styles and model routing by hash: the
nightly run reuses an earlier run only when all of them still match (audit #30).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from resume_tailor.content.data import MasterResume
from resume_tailor.content.industries import GuidanceSnapshot
from resume_tailor.web.schemas import JobSettings

SNAPSHOT = "resume_snapshot.json"


def _hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _template() -> str:
    from resume_tailor.document import calibrate  # noqa: PLC0415

    try:
        return calibrate._template_fingerprint()
    except OSError:
        return ""


def fingerprints(
    resume: MasterResume, settings: JobSettings, guidance: GuidanceSnapshot | None
) -> dict[str, str]:
    from resume_tailor.web import job_routing  # noqa: PLC0415

    return {
        "resume": _hash(resume.model_dump(mode="json")),
        "template": _template(),
        "guidance": guidance.fingerprint() if guidance is not None else "",
        "styles": _hash([settings.rewrite_style, settings.expand_style, settings.cover_style]),
        "model": _hash(job_routing.model_routing(settings)),
    }


def recorded(run_dir: Path) -> dict[str, str]:
    """The ``inputs`` a run recorded; empty for a run made before they were."""
    try:
        raw = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    inputs = raw.get("inputs") if isinstance(raw, dict) else None
    return inputs if isinstance(inputs, dict) else {}


def stale(run_dir: Path) -> list[str]:
    """Which of "resume" and "template" moved on since the run recorded them; empty for
    a run that recorded none (made before runs did) or a resume that cannot be read."""
    inputs = recorded(run_dir)
    if not inputs:
        return []
    from resume_tailor.content import data  # noqa: PLC0415

    changed: list[str] = []
    try:
        resume = _hash(data.load().model_dump(mode="json"))
    except Exception:  # noqa: BLE001 - the run's own files are still what was reviewed
        resume = inputs.get("resume", "")
    if inputs.get("resume") and inputs["resume"] != resume:
        changed.append("resume")
    template = _template()
    if inputs.get("template") and template and inputs["template"] != template:
        changed.append("template")
    return changed


def save_snapshot(resume: MasterResume, run_dir: Path) -> None:
    (run_dir / SNAPSHOT).write_text(resume.model_dump_json(by_alias=True), encoding="utf-8")


def load_snapshot(run_dir: Path) -> MasterResume | None:
    path = run_dir / SNAPSHOT
    if not path.is_file():
        return None
    return MasterResume.model_validate_json(path.read_text(encoding="utf-8"))
