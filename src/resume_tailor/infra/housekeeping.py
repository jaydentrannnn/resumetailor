"""Disk housekeeping: the LLM response cache and old tailoring-run directories.

- `prune_cache` keeps `config.CACHE_DIR` under `CACHE_MAX_BYTES` by deleting the least
  recently used files (access time, or modification time where the filesystem does not
  record access). Every cache entry is regenerable: a deleted one costs one model call.
- `prune_jobs` keeps the newest `KEEP_JOBS` run directories under
  ``OUTPUT_DIR/jobs/``, never one an application still points at (its ``job_id`` or
  ``reused_from_job_id``: the files a fill uploads) and never one touched in the last
  hour (a run in progress).
- `dedupe_run_templates` moves each older run's own ``template.docx`` into the shared
  ``OUTPUT_DIR/run_templates/`` store (one file per content hash, `rerender.py`) and
  deletes store files no run snapshot names any more.

`run()` does all three and never raises; it runs at server start and after each tailoring
run. `clear_cache` backs the Settings "Clear cache" button.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from resume_tailor import config

_log = logging.getLogger(__name__)

CACHE_MAX_BYTES = 500 * 1024 * 1024
KEEP_JOBS = 200
_RECENT_SECONDS = 3600


def _files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def cache_usage(cache_dir: Path | None = None) -> dict[str, int]:
    files = _files(cache_dir or config.CACHE_DIR)
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return {"files": len(files), "bytes": total}


def prune_cache(cache_dir: Path | None = None, max_bytes: int | None = None) -> dict[str, int]:
    """Delete least-recently-used cache files until the cache fits ``max_bytes``."""
    root = cache_dir or config.CACHE_DIR
    limit = CACHE_MAX_BYTES if max_bytes is None else max_bytes
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for path in _files(root):
        try:
            st = path.stat()
        except OSError:
            continue
        entries.append((max(st.st_atime, st.st_mtime), st.st_size, path))
        total += st.st_size
    removed = freed = 0
    for _used, size, path in sorted(entries, key=lambda e: e[0]):
        if total <= limit:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
        freed += size
    return {"removed": removed, "freed": freed}


def clear_cache(cache_dir: Path | None = None) -> dict[str, int]:
    """Delete every cache file (the directory itself stays)."""
    return prune_cache(cache_dir, max_bytes=0)


def _referenced_jobs() -> set[str]:
    from resume_tailor.apply.funnel import store

    refs: set[str] = set()
    for app in store.load_all().values():
        refs.update(j for j in (app.job_id, app.reused_from_job_id) if j)
    return refs


def prune_jobs(keep: int | None = None, jobs_dir: Path | None = None) -> dict[str, int]:
    """Delete run directories beyond the newest ``keep``, except protected ones."""
    root = jobs_dir or config.OUTPUT_DIR / "jobs"
    limit = KEEP_JOBS if keep is None else keep
    if not root.is_dir():
        return {"removed": 0}
    dirs: list[tuple[float, Path]] = []
    for child in root.iterdir():
        if child.is_dir():
            try:
                dirs.append((child.stat().st_mtime, child))
            except OSError:
                continue
    if len(dirs) <= limit:
        return {"removed": 0}
    protected = _referenced_jobs()
    now = time.time()
    removed = 0
    for mtime, child in sorted(dirs, reverse=True)[limit:]:
        if child.name in protected or now - mtime < _RECENT_SECONDS:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return {"removed": removed}


def dedupe_run_templates(jobs_dir: Path | None = None) -> dict[str, int]:
    """Move legacy per-run templates into the shared store; drop unreferenced ones."""
    from resume_tailor.document import rerender

    root = jobs_dir or config.OUTPUT_DIR / "jobs"
    if not root.is_dir():
        return {"moved": 0, "removed": 0}
    store = root.parent / rerender.TEMPLATE_STORE
    moved = 0
    referenced: set[str] = set()
    for child in root.iterdir():
        snap_path = child / rerender.SNAPSHOT
        if not snap_path.is_file():
            continue
        try:
            snapshot = json.loads(snap_path.read_text("utf-8"))
            legacy = child / rerender.TEMPLATE
            if legacy.is_file():
                snapshot["template_sha"] = rerender.store_template(child, legacy.read_bytes())
                tmp = snap_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(snapshot, indent=2), "utf-8")
                tmp.replace(snap_path)
                legacy.unlink()
                moved += 1
        except (OSError, ValueError):
            continue
        sha = snapshot.get("template_sha")
        if isinstance(sha, str):
            referenced.add(sha)
    removed = 0
    now = time.time()
    if store.is_dir():
        for path in store.glob("*.docx"):
            try:
                if path.stem in referenced or now - path.stat().st_mtime < _RECENT_SECONDS:
                    continue
                path.unlink()
            except OSError:
                continue
            removed += 1
    return {"moved": moved, "removed": removed}


def run() -> None:
    """All prunes, logged; never raises (housekeeping must not fail a run or a start)."""
    try:
        cache = prune_cache()
        jobs = prune_jobs()
        templates = dedupe_run_templates()
    except Exception:  # noqa: BLE001
        _log.warning("housekeeping failed", exc_info=True)
        return
    if cache["removed"] or jobs["removed"] or templates["moved"] or templates["removed"]:
        _log.info(
            "housekeeping: removed %d cache file(s) (%d bytes) and %d old run folder(s); "
            "moved %d run template(s) into the shared store, removed %d unused",
            cache["removed"], cache["freed"], jobs["removed"],
            templates["moved"], templates["removed"],
        )
