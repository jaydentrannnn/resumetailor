"""In-app updates for the desktop build: the server's half of the shell conversation.

The web UI has no Tauri IPC (it runs from ``http://127.0.0.1``), so it asks this server,
and the server talks to the Tauri shell over the pipes the shell already holds:

- **stdout, server → shell**: ``SHELL check`` / ``SHELL download`` / ``SHELL apply``.
  The shell reads the same stream for ``READY`` (`desktop_main`).
- **stdin, shell → server**: one ``UPDATE <json>`` line per event, ``state`` one of
  ``checking``, ``available`` (+ ``version``, ``notes``, ``date``), ``up_to_date``,
  ``downloading`` (+ ``pct``), ``ready`` (downloaded and signature-checked, waiting for
  ``SHELL apply``), ``error`` (+ ``message``).

The shell does all fetching and signature checking (tauri-plugin-updater, key in
``tauri.conf.json``); nothing here downloads. What this side owns is *when*: the user
clicks Install (never automatic), the shell downloads while the app keeps working, and
``SHELL apply`` (which stops this server and runs the installer) is sent only once no
tailoring run or Apply operation is in flight, after a backup of the data and templates.

``ENABLED`` is set by `desktop_main` only when the shell launched the server; in a dev
checkout or Docker the routes report ``supported: false``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

_log = logging.getLogger(__name__)

#: True only in the desktop build, where a shell is on the other end of stdin/stdout.
ENABLED = False
#: The installed app's version, passed by the shell (``--app-version``).
CURRENT: str | None = None

#: Commands the shell understands.
COMMANDS = frozenset({"check", "download", "apply"})
#: Seconds between "is it idle yet?" checks while an install waits for a run to end.
IDLE_POLL_SECONDS = 10.0
#: Pre-update backups kept; older ones are deleted.
KEEP_BACKUPS = 3
#: Folders never zipped. Run output belongs under OUTPUT_ROOT and is regenerable; a
#: copy left inside the data folder (an old layout, a hand migration) once made every
#: backup ~290 MB instead of ~30 MB.
_BACKUP_SKIP_DIRS = frozenset({"output"})

_lock = threading.Lock()
_write_lock = threading.Lock()
_out: TextIO | None = None  # tests swap this; None means sys.stdout
_waiter: threading.Thread | None = None
_state: dict[str, Any] = {
    "state": "idle",
    "available": None,
    "pct": None,
    "last_checked": None,
    "error": None,
    "waiting_for": None,
    "backup": None,
}
#: States in which a new check result must not overwrite progress already under way.
_IN_PROGRESS = frozenset({"downloading", "ready", "waiting", "installing"})


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def status() -> dict[str, Any]:
    """What the Settings → About card shows."""
    with _lock:
        return {"supported": ENABLED, "current": CURRENT, **_state}


def reset() -> None:
    """Back to a fresh start (tests)."""
    global _waiter
    with _lock:
        _state.update(
            state="idle", available=None, pct=None, last_checked=None, error=None,
            waiting_for=None, backup=None,
        )
        _waiter = None


def request(command: str) -> None:
    """Send ``SHELL <command>`` to the shell."""
    if command not in COMMANDS:
        raise ValueError(f"unknown shell command {command!r}")
    if not ENABLED:
        raise RuntimeError("updates are only available in the desktop app")
    with _lock:
        if command == "check" and _state["state"] not in _IN_PROGRESS:
            _state.update(state="checking", error=None)
        elif command == "download":
            _state.update(state="downloading", pct=0, error=None)
        elif command == "apply":
            _state.update(state="installing", waiting_for=None)
    out = _out or sys.stdout
    with _write_lock:
        out.write(f"SHELL {command}\n")
        out.flush()


def receive(line: str) -> None:
    """Handle one line from the shell; anything that is not ``UPDATE {...}`` is ignored."""
    if not line.startswith("UPDATE "):
        return
    try:
        event = json.loads(line[len("UPDATE "):])
    except json.JSONDecodeError:
        _log.warning("unreadable update event from the shell")
        return
    if not isinstance(event, dict):
        return
    kind = event.get("state")
    start_waiter = False
    with _lock:
        busy_installing = _state["state"] in _IN_PROGRESS
        if kind == "checking":
            if not busy_installing:
                _state.update(state="checking", error=None)
        elif kind == "available":
            _state["last_checked"] = _now()
            _state["available"] = {
                "version": str(event.get("version") or ""),
                "notes": str(event.get("notes") or ""),
                "date": str(event.get("date") or ""),
            }
            if not busy_installing:
                _state.update(state="available", error=None)
        elif kind == "up_to_date":
            _state["last_checked"] = _now()
            if not busy_installing:
                _state.update(state="up_to_date", available=None, error=None)
        elif kind == "downloading":
            pct = event.get("pct")
            _state.update(state="downloading", pct=pct if isinstance(pct, int) else None)
        elif kind == "ready":
            _state.update(state="ready", pct=100)
            start_waiter = True
        elif kind == "error":
            # A download or install that failed needs a fresh check before retrying:
            # the shell has dropped the update it had.
            _state.update(
                state="error",
                error=str(event.get("message") or "The update failed."),
                pct=None,
                waiting_for=None,
            )
    if start_waiter:
        _start_waiter()


def busy_reason() -> str | None:
    """Why an install must wait right now, or None when nothing is running."""
    from resume_tailor.apply.funnel import daily as apply_daily
    from resume_tailor.apply.funnel import operations as apply_operations
    from resume_tailor.web.jobs import get_queue

    if get_queue().busy():
        return "a tailoring run"
    if apply_daily.daily_busy() or apply_operations.active() is not None:
        return "an Apply operation"
    return None


def _start_waiter() -> None:
    global _waiter
    with _lock:
        if _waiter is not None and _waiter.is_alive():
            return
        _waiter = threading.Thread(target=_apply_when_idle, name="update-apply", daemon=True)
        _waiter.start()


def _apply_when_idle(sleep=time.sleep) -> None:
    while True:
        with _lock:
            if _state["state"] not in {"ready", "waiting"}:
                return  # an error or a new check superseded this install
        reason = busy_reason()
        if reason is None:
            break
        with _lock:
            _state.update(state="waiting", waiting_for=reason)
        sleep(IDLE_POLL_SECONDS)
    with _lock:
        target = (_state["available"] or {}).get("version") or "new"
    try:
        path = backup(CURRENT or "unknown", target)
    except Exception as exc:  # never install over data we could not back up
        _log.exception("pre-update backup failed")
        with _lock:
            _state.update(state="error", error=f"Could not back up your data first: {exc}")
        return
    with _lock:
        _state["backup"] = str(path)
    request("apply")


def backups_dir() -> Path:
    from resume_tailor import config

    # Under output/, which is never itself backed up (and is gitignored in a checkout).
    return config.OUTPUT_ROOT / "backups"


def _db_snapshot(path: Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "snapshot.db"
        source = sqlite3.connect(path)
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        return target.read_bytes()


def backup(from_version: str, to_version: str) -> Path:
    """Zip the data and templates folders before an update; keep the newest few."""
    from resume_tailor import config

    folder = backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = folder / f"pre-update-{_safe(from_version)}-to-{_safe(to_version)}-{stamp}.zip"
    partial = path.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for label, root in (("data", config.DATA_ROOT), ("templates", config.TEMPLATES_ROOT)):
            if not root.is_dir():
                continue
            for file in sorted(root.rglob("*")):
                if not file.is_file() or file.name.endswith(("-wal", "-shm", "-journal")):
                    continue
                if _BACKUP_SKIP_DIRS.intersection(file.relative_to(root).parts[:-1]):
                    continue
                name = f"{label}/{file.relative_to(root).as_posix()}"
                if file.suffix == ".db":
                    archive.writestr(name, _db_snapshot(file))
                else:
                    archive.write(file, name)
    partial.replace(path)
    # Oldest first by write time (names start with the version, so they do not sort by
    # age); the one just written is never a candidate.
    older = sorted(
        (p for p in folder.glob("pre-update-*.zip") if p != path), key=lambda p: p.stat().st_mtime
    )
    for old in older[: max(0, len(older) - (KEEP_BACKUPS - 1))]:
        old.unlink(missing_ok=True)
    return path


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in text) or "unknown"
