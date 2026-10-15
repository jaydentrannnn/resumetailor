"""Run the harness against a copy of the live app data, never the live folders.

`resume_tailor.config` reads its directory env vars at import time, so `environment()`
must be applied before anything from `resume_tailor` is imported (`eval_models.py`
does this first thing). Saved runs are read straight from the live output folder,
read-only; everything the stages write (caches, telemetry) lands in the sandbox.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: The desktop app's data root on Windows.
LIVE_ROOT = Path(os.path.expandvars(r"%LOCALAPPDATA%\ResumeTailorData"))

#: Copied into the sandbox. `output/` is not: the harness reads saved runs in place.
_COPIED = ("data", "cache", "templates")


def _ignore(directory: str, names: list[str]) -> set[str]:
    """Skip the bulky per-workspace legacy output folders and backups under `data/`."""
    parent = Path(directory)
    skipped = {"backups", "__pycache__"}
    if parent.name == "workspaces" or parent.parent.name == "workspaces":
        skipped.add("output")
    return {n for n in names if n in skipped}


def prepare(eval_dir: Path, live_root: Path = LIVE_ROOT) -> Path:
    """Copy the live data/cache/templates into `<eval_dir>/sandbox` once; return it.

    An existing sandbox is reused as-is, so a resumed eval keeps the caches the first
    pass filled, and the copy reflects the data as it was when the eval started.
    """
    sandbox = eval_dir / "sandbox"
    for name in _COPIED:
        source, dest = live_root / name, sandbox / name
        if dest.exists():
            continue
        if source.exists():
            shutil.copytree(source, dest, ignore=_ignore)
        else:
            dest.mkdir(parents=True)
    (sandbox / "output").mkdir(parents=True, exist_ok=True)
    return sandbox


def environment(sandbox: Path) -> dict[str, str]:
    """The env vars that point `resume_tailor.config` at `sandbox`."""
    return {
        "RESUME_TAILOR_DATA_DIR": str(sandbox / "data"),
        "RESUME_TAILOR_OUTPUT_DIR": str(sandbox / "output"),
        "RESUME_TAILOR_CACHE_DIR": str(sandbox / "cache"),
        "RESUME_TAILOR_TEMPLATES_DIR": str(sandbox / "templates"),
        "RESUME_TAILOR_LOG_DIR": "off",
    }


def live_jobs_dir(workspace_id: str = "default", live_root: Path = LIVE_ROOT) -> Path:
    """Where the desktop app keeps one profile's saved runs (read-only to the harness)."""
    return live_root / "output" / "workspaces" / workspace_id / "jobs"
