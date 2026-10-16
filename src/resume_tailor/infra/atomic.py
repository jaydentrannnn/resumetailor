"""Atomic file replacement that survives concurrent writers on Windows.

A fixed temp name (``path.with_suffix(".tmp")``) breaks as soon as two threads write the
same file: the second ``write_text`` hits the first one's open handle and Windows answers
``PermissionError`` (a parallel Workday fill crashed on ``workday_vault.tmp`` this way).
Each write here gets its own temp name, and the final rename is retried briefly while a
reader holds the destination open.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

#: One rename at a time across the process; renames are fast, so a single lock is enough.
_REPLACE_LOCK = threading.Lock()


def replace_with_retry(src: Path, dst: Path, attempts: int = 10) -> None:
    """``os.replace``, retried briefly while a reader holds ``dst`` open (Windows)."""
    for attempt in range(attempts):
        try:
            with _REPLACE_LOCK:
                os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a unique temp file and an atomic rename."""
    tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        replace_with_retry(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_cached[M: BaseModel](path: Path, model: type[M]) -> M | None:
    """``path`` parsed as ``model``, or None when it is absent, unreadable or corrupt.

    A corrupt cache entry is a miss: the stage recomputes and replaces it with
    `write_text`. Nothing is deleted here, so a file another job has just rewritten is
    never removed from under it.
    """
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable cache file %s: %s", path.name, exc)
        return None
