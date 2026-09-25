"""Disk housekeeping: the LLM response cache and old tailoring-run directories.

- `prune_cache` keeps `config.CACHE_DIR` under `CACHE_MAX_BYTES` by deleting the least
  recently used files (access time, or modification time where the filesystem does not
  record access). Every cache entry is regenerable: a deleted one costs one model call.
- `prune_jobs` keeps the newest `KEEP_JOBS` run directories under
  ``OUTPUT_DIR/jobs/``, never one an application still points at (its ``job_id`` or
  ``reused_from_job_id``: the files a fill uploads) and never one touched in the last
  hour (a run in progress).

`run()` does both and never raises; it runs at server start and after each tailoring
run. `clear_cache` backs the Settings "Clear cache" button.
"""

from __future__ import annotations

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
    from resume_tailor.apply import store

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


def run() -> None:
    """Both prunes, logged; never raises (housekeeping must not fail a run or a start)."""
    try:
        cache = prune_cache()
        jobs = prune_jobs()
    except Exception:  # noqa: BLE001
        _log.warning("housekeeping failed", exc_info=True)
        return
    if cache["removed"] or jobs["removed"]:
        _log.info(
            "housekeeping: removed %d cache file(s) (%d bytes) and %d old run folder(s)",
            cache["removed"], cache["freed"], jobs["removed"],
        )
