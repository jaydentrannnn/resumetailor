"""Version history of the master resume, for undo and "restore an earlier save".

``master_resume.json`` stays the source of truth: the CLI, `data.load` and hand edits
all read it. Every save through the app also records the saved text here, in the
``resume_versions`` table of the workspace's ``app.db`` (`storage.db`), keeping the
last `KEEP` versions. A file edited outside the app (a text editor while the server was
down) is noticed the next time history is read or a save happens, and recorded as its
own version, so restoring never silently discards a hand edit.

The stored text is exactly what was written, so a restore writes back the same bytes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resume_tailor import config
from resume_tailor.storage import db

KEEP = 50
_EXTERNAL_NOTE = "edited outside the app"


def _path() -> Path:
    return config.MASTER_RESUME_PATH


def _conn():
    return db.connect(db.db_path(_path().parent))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _latest_digest(conn) -> str | None:
    row = conn.execute(
        "SELECT digest FROM resume_versions ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def record(text: str, note: str = "") -> int | None:
    """Store ``text`` as the newest version, unless it equals the newest already.

    Returns the new version number, or None when nothing changed.
    """
    conn = _conn()
    digest = _digest(text)
    with db.transaction(conn):
        if _latest_digest(conn) == digest:
            return None
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM resume_versions").fetchone()
        version = int(row[0]) + 1
        conn.execute(
            "INSERT INTO resume_versions(version, saved_at, digest, note, doc) "
            "VALUES (?, ?, ?, ?, ?)",
            (version, datetime.now(UTC).replace(microsecond=0).isoformat(), digest, note, text),
        )
        conn.execute(
            "DELETE FROM resume_versions WHERE version <= ?", (version - KEEP,)
        )
    return version


def sync_external() -> int | None:
    """Record the file on disk if it differs from the newest version (a hand edit)."""
    path = _path()
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    conn = _conn()
    latest = _latest_digest(conn)
    if latest == _digest(text):
        return None
    return record(text, _EXTERNAL_NOTE if latest is not None else "first recorded version")


def _summary(text: str) -> dict[str, Any]:
    try:
        raw = json.loads(text)
    except ValueError:
        return {"name": "", "bullets": 0, "sections": 0}
    sections = raw.get("sections") or []
    bullets = sum(
        len(entry.get("bullets") or [])
        for section in sections
        if isinstance(section, dict)
        for entry in section.get("entries") or []
        if isinstance(entry, dict)
    )
    name = ((raw.get("contact") or {}).get("name")) or ""
    return {"name": name, "bullets": bullets, "sections": len(sections)}


def list_versions() -> list[dict[str, Any]]:
    """Newest first: ``{version, saved_at, note, name, bullets, sections, current}``."""
    sync_external()
    conn = _conn()
    rows = conn.execute(
        "SELECT version, saved_at, note, doc FROM resume_versions ORDER BY version DESC"
    ).fetchall()
    out = []
    for index, (version, saved_at, note, text) in enumerate(rows):
        out.append(
            {"version": version, "saved_at": saved_at, "note": note, "current": index == 0}
            | _summary(text)
        )
    return out


def text_of(version: int) -> str | None:
    row = _conn().execute(
        "SELECT doc FROM resume_versions WHERE version = ?", (version,)
    ).fetchone()
    return row[0] if row else None
