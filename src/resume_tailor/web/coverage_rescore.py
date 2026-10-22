"""Score saved runs again under the current must-have coverage rules (once, at startup).

A run saved before the main-resume figure (`CoverageFunnel.in_resume_text`) was measured
keeps the figures of the rules it ran under: Extra-skills tags in "your resume", soft
skills and reworded skills missing from the page. Scoring needs no model call, so
startup scores those runs again from what each run folder saved
(`rerender.rescore_coverage`) and writes `coverage.json`, which every reader prefers.
A run scored under the current rules is never touched again.
"""

from __future__ import annotations

import logging
from pathlib import Path

from resume_tailor import config
from resume_tailor.content import bullet_tags, data
from resume_tailor.document import rerender
from resume_tailor.pipeline import coverage
from resume_tailor.web import skill_refresh

_log = logging.getLogger(__name__)


def _stale(out_dir: Path) -> bool:
    """Scored under the old rules (or never): a snapshot to score, no main-resume figure."""
    if not (out_dir / rerender.SNAPSHOT).is_file():
        return False
    funnel = coverage.read(out_dir)
    return funnel is None or funnel.in_resume_text is None


def run() -> int:
    """Re-score the active workspace's stale runs; returns how many were scored."""
    jobs = config.OUTPUT_DIR / "jobs"
    todo = [d for d in sorted(jobs.iterdir()) if d.is_dir() and _stale(d)] if jobs.is_dir() else []
    if not todo:
        return 0
    master = data.load()
    # The skills a run's resume side reads: Extra skills, detection and the cached
    # inferences, under the Tailor routing that wrote them (no model call).
    inferred = skill_refresh.cached_inference(master)
    workspace_id = config.active_workspace_id()
    context = (
        config.context_for_workspace(workspace_id) if workspace_id else config.default_context()
    )
    scored = 0
    with config.use_context(context):
        bullet_tags.annotate(master, inferred)
        for out_dir in todo:
            try:
                scored += rerender.rescore_coverage(out_dir, master) is not None
            except Exception:  # noqa: BLE001 - one unreadable run must not stop the rest
                _log.warning("could not re-score coverage for %s", out_dir.name, exc_info=True)
    return scored
