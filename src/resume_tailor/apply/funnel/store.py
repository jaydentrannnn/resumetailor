"""Application funnel state, persisted in the workspace's SQLite database.

Storage. Rows live in the ``applications`` table of ``<DATA_DIR>/app.db``
(`resume_tailor.storage.db`), one JSON document per row plus indexed copies of the
columns the Apply page filters on. A pre-SQLite ``applications.json`` is imported once
on first open (`_import_json`): the original is copied to
``backup-pre-sqlite-<stamp>/``, migrated in memory through the old schema steps, and
renamed to ``applications.json.migrated`` (rename it back and delete ``app.db`` to
downgrade). Parsed rows are cached per process and re-read only when the table's
change counter moves, so a write from another process (the nightly CLI) is seen.

Concurrency model. Web routes, the operation worker threads, the nightly run and fill
all read and write this registry, and fill holds a row for minutes while it drives a
browser. Every read-modify-write therefore goes through `_LOCK`, and `upsert` is a
field-level three-way merge rather than a blind replace: a row returned by `get`,
`load_all` or `list_applications` remembers the stored version it was read from
(`Application._base`), and `upsert` writes back only the fields the caller changed
since then, on top of whatever is stored *now*. A user's archive, note or "mark
submitted" made while a fill was running therefore survives the fill's later write.
Conflicts (both sides changed one field) go to the caller, except that a status the
user moved to a terminal state is kept (`_merge_into`). After a write the caller's
object is refreshed in place to the merged row, so it never carries stale fields into
its next write. `update(key, mutate)` is the atomic form for new code.
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resume_tailor import config
from resume_tailor.storage import db

from . import store_migrations, store_models

_log = logging.getLogger(__name__)


def _path() -> Path:
    """Active workspace's applications registry path."""
    return config.APPLICATIONS_PATH


def load_all() -> dict[str, store_models.Application]:
    """Every application keyed by ``canonical_key`` (or legacy id), as private copies."""
    with _LOCK:
        return {key: _checkout(app) for key, app in _snapshot().items()}


class StaleApplication(RuntimeError):
    """`update` could not find the row it was asked to change."""


_LOCK = threading.RLock()
_TABLE = "applications"
_JSON_MARKER = "json_import:applications"

#: (database path, table generation, parsed rows) of the last read or write. The rows
#: are private: callers only ever get `_checkout` copies, so they are never mutated.
_cache: tuple[Path, int, dict[str, store_models.Application]] | None = None
#: Databases whose JSON import is settled, so `_db` can skip the check.
_imported: set[Path] = set()


def _db_file() -> Path:
    return db.db_path(_path().parent)


def _db() -> sqlite3.Connection:
    """This thread's connection to the active workspace's database, JSON imported."""
    db_file = _db_file()
    conn = db.connect(db_file)
    if db_file not in _imported:
        _import_json(conn, db_file)
    return conn


@contextmanager
def _txn() -> Iterator[sqlite3.Connection]:
    """`_LOCK` plus a database write transaction, for every read-modify-write."""
    with _LOCK, db.transaction(_db()) as conn:
        yield conn


def _snapshot() -> dict[str, store_models.Application]:
    """Current registry rows, shared and read-only. Hold `_LOCK` while using them.

    Re-parses only when the table's change counter moved since the last read or write,
    which turns `get()` on a large registry into one small query.
    """
    global _cache
    conn = _db()
    db_file = _db_file()
    gen = db.generation(conn, _TABLE)
    if _cache is not None and _cache[0] == db_file and _cache[1] == gen:
        return _cache[2]
    rows = {
        key: store_models.Application.model_validate_json(doc)
        for key, doc in conn.execute("SELECT key, doc FROM applications ORDER BY rowid")
    }
    _cache = (db_file, gen, rows)
    return rows


def _checkout(app: store_models.Application) -> store_models.Application:
    """A private, mutable copy of a stored row that remembers where it came from."""
    out = app.model_copy(deep=True)
    out._base = app
    return out


def _parse_json(raw_bytes: bytes) -> dict[str, store_models.Application]:
    """Rows of a legacy ``applications.json``, upgraded through every old schema step.

    Schema v1 files are migrated to v2, then v2 registries through `_migrate_v2`
    (Workday re-keying + ATS backfill), v3 through `_migrate_v3` (one-time archive of
    submitted rows), and v4 through `_migrate_v4` (one-time archive of screen-outs).
    """
    raw = json.loads(raw_bytes.decode("utf-8"))
    apps_raw = raw.get("applications", {}) if isinstance(raw, dict) else {}
    if not isinstance(apps_raw, dict):
        return {}
    version = int(raw.get("schema_version") or 1)
    if version < 2:
        out = store_migrations._migrate_v1(apps_raw)
    else:
        out = {
            str(key): store_models.Application.model_validate(value)
            for key, value in apps_raw.items()
        }
    if version < 3:
        out, _ = store_migrations._migrate_v2(out)
    if version < 4:
        out, _ = store_migrations._migrate_v3(out)
    if version < 5:
        out, _ = store_migrations._migrate_v4(out)
    return out


def _import_json(conn: sqlite3.Connection, db_file: Path) -> None:
    """Move a pre-SQLite ``applications.json`` into the database, once.

    Rows already in the database win over same-key rows in the file. A file that does
    not parse is kept aside as ``applications.json.corrupt-<stamp>`` and logged; the
    import is not retried, since retrying would fail the same way on every read.
    """
    path = _path()
    with _LOCK:
        if db.marker(conn, _JSON_MARKER):
            if path.is_file():
                _log.warning("ignoring %s: already imported into %s", path.name, db_file.name)
            _imported.add(db_file)
            return
        if not path.is_file():
            return  # checked again on the next open, in case the file appears
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        backup_dir = path.parent / f"backup-pre-sqlite-{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir / path.name)
        try:
            rows = _parse_json(path.read_bytes())
            suffix = ".migrated"
        except (ValueError, UnicodeDecodeError, TypeError) as exc:
            _log.error("could not import %s (%s); kept it in %s", path.name, exc, backup_dir.name)
            rows = {}
            suffix = f".corrupt-{stamp}"
        with db.transaction(conn):
            existing = {row[0] for row in conn.execute("SELECT key FROM applications")}
            for key, app in rows.items():
                if key not in existing:
                    _put(conn, key, app)
            db.set_marker(conn, _JSON_MARKER)
            db.bump(conn, _TABLE)
        _imported.add(db_file)
        try:
            path.replace(path.with_name(path.name + suffix))
        except OSError as exc:  # e.g. open in an editor on Windows; the marker is set
            _log.warning("imported %s but could not rename it: %s", path.name, exc)


def _put(conn: sqlite3.Connection, key: str, app: store_models.Application) -> None:
    conn.execute(
        """INSERT INTO applications(key, revision, status, company, role, location, ats,
               discovered_at, archived_at, group_key, job_id, doc)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET
               revision = excluded.revision, status = excluded.status,
               company = excluded.company, role = excluded.role,
               location = excluded.location, ats = excluded.ats,
               discovered_at = excluded.discovered_at, archived_at = excluded.archived_at,
               group_key = excluded.group_key, job_id = excluded.job_id, doc = excluded.doc""",
        (
            key, app.revision, app.status, app.company, app.role, app.location, app.ats,
            app.discovered_at, app.archived_at, app.group_key, app.job_id,
            app.model_dump_json(),
        ),
    )


def save_all(apps: dict[str, store_models.Application]) -> None:
    """Persist the full registry in one transaction: rows not in ``apps`` are deleted.

    A blind write of every row: use `upsert`/`update` to change rows other code may
    also be changing.
    """
    stored: dict[str, store_models.Application] = {}
    for key, app in apps.items():
        row = app.model_copy(deep=True)
        row._base = None
        stored[key] = row
    _write(stored)


def _write(rows: dict[str, store_models.Application]) -> None:
    """`save_all` for rows the store owns outright: cached as-is, not copied.

    Writes only the rows that are not the very objects already stored, so an `upsert`
    that took its dict from `_snapshot` rewrites one row, not the table.
    """
    global _cache
    with _txn() as conn:
        current = _snapshot()
        for key in current.keys() - rows.keys():
            conn.execute("DELETE FROM applications WHERE key = ?", (key,))
        for key, app in rows.items():
            if current.get(key) is not app:
                _put(conn, key, app)
        gen = db.bump(conn, _TABLE)
        _cache = (_db_file(), gen, rows)


def build_index(apps: dict[str, store_models.Application] | None = None) -> store_models.Index:
    """Build canonical / source-ref / group lookup tables."""
    if apps is None:
        apps = load_all()
    index = store_models.Index()
    for key, app in apps.items():
        ckey = app.canonical_key or key
        index.by_canonical[ckey] = app
        refs = app.source_refs or [
            store_models.SourceRef(source=app.source, source_job_id=app.source_job_id)
        ]
        for ref in refs:
            index.by_source_ref[(ref.source, ref.source_job_id)] = ckey
        # Always index the mirrored primary source_job_id too.
        index.by_source_ref[(app.source, app.source_job_id)] = ckey
        if app.group_key:
            index.by_group.setdefault(app.group_key, []).append(ckey)
    return index


def _locate(apps: dict[str, store_models.Application], key: str) -> str | None:
    """Registry key of the row ``key`` names: a registry key, canonical key or source id."""
    if key in apps:
        return key
    index = build_index(apps)
    if key in index.by_canonical:
        found = index.by_canonical[key]
        return next((k for k, app in apps.items() if app is found), None)
    for (_source, source_job_id), ckey in index.by_source_ref.items():
        if source_job_id == key:
            if ckey in apps:
                return ckey
            found = index.by_canonical.get(ckey)
            return next((k for k, app in apps.items() if app is found), None)
    return None


def get(key: str) -> store_models.Application | None:
    """Return one application by canonical key or any source_job_id."""
    with _LOCK:
        apps = _snapshot()
        found = _locate(apps, key)
        return _checkout(apps[found]) if found is not None else None


#: Fields `_merge_into` never copies from the caller: bookkeeping it computes itself.
_MERGE_SKIP = frozenset({"revision", "status_history", "source_refs"})


def _merge_into(
    stored: store_models.Application, app: store_models.Application, base: store_models.Application
) -> store_models.Application:
    """Apply the fields ``app`` changed since ``base`` onto ``stored`` (the row as it is now).

    Returns a new row; none of the three inputs is modified. ``status_history`` and
    ``source_refs`` are append-only, so the caller's new entries are appended to the
    stored ones rather than replacing entries a concurrent writer added. When the
    caller changed ``status`` while someone else moved the row to a terminal status
    (the user marked it submitted, skipped, ...), the terminal status is kept and a
    note says what arrived late: a background fill must never un-submit a row.
    """
    merged = stored.model_copy(deep=True)
    merged._base = None
    keep_status = (
        app.status != base.status
        and stored.status != base.status
        and stored.status in store_models.TERMINAL_STATUSES
        and app.status != stored.status
    )
    for name in type(app).model_fields:
        if name in _MERGE_SKIP:
            continue
        mine = getattr(app, name)
        if mine == getattr(base, name):
            continue
        if keep_status and name in {"status", "archived_at"}:
            continue
        setattr(merged, name, copy.deepcopy(mine))

    base_history = base.status_history
    if app.status_history[: len(base_history)] == base_history:
        merged.status_history.extend(
            change.model_copy() for change in app.status_history[len(base_history):]
        )
    else:  # the caller rewrote history rather than appending: its version wins
        merged.status_history = [change.model_copy() for change in app.status_history]
    if keep_status:
        merged.status_history.append(
            store_models.StatusChange(
                status=stored.status,
                at=store_models._now_iso(),
                note=f"{app.status} arrived after this was marked {stored.status}; status kept",
            )
        )

    known = {(ref.source, ref.source_job_id) for ref in merged.source_refs}
    for ref in app.source_refs:
        if (ref.source, ref.source_job_id) not in known:
            merged.source_refs.append(ref.model_copy())
            known.add((ref.source, ref.source_job_id))
    return merged


def _refresh(app: store_models.Application, row: store_models.Application) -> None:
    """Make the caller's ``app`` equal to the stored ``row`` it just wrote."""
    for name in type(app).model_fields:
        setattr(app, name, copy.deepcopy(getattr(row, name)))
    app._base = row


def upsert(app: store_models.Application) -> store_models.Application:
    """Insert ``app``, or write its changes onto the stored row, and persist.

    A row read from the store is merged (see `_merge_into`); a row built in memory
    replaces whatever is stored under its key. Either way ``app`` is refreshed in
    place to the stored result and returned.
    """
    with _txn():
        apps = dict(_snapshot())
        key = store_models._registry_key(app)
        base = app._base
        stored_key: str | None = None
        if base is not None:
            stored_key = _locate(apps, store_models._registry_key(base))
            if stored_key is None:
                stored_key = _locate(apps, base.source_job_id)
        if stored_key is not None and base is not None:
            row = _merge_into(apps[stored_key], app, base)
            if stored_key != key:
                del apps[stored_key]
            key = store_models._registry_key(row)
        else:
            row = app.model_copy(deep=True)
            row._base = None
            previous = apps.get(key)
            row.revision = previous.revision if previous is not None else row.revision
        # Drop a stale legacy key if we are promoting to a canonical key.
        if row.canonical_key and row.source_job_id in apps and row.source_job_id != key:
            del apps[row.source_job_id]
        row.revision += 1
        apps[key] = row
        _write(apps)
        _refresh(app, row)
        return app


def update(
    key: str, mutate: Callable[[store_models.Application], None]
) -> store_models.Application:
    """Atomically re-read the row ``key`` names, apply ``mutate`` to it, and save.

    Raises:
        StaleApplication: When no row matches ``key`` (deleted or re-keyed).
    """
    with _txn():
        app = get(key)
        if app is None:
            raise StaleApplication(f"application {key!r} not found")
        mutate(app)
        return upsert(app)


def patch(key: str, **fields: Any) -> store_models.Application:
    """`update` that assigns ``fields``: ``patch(key, notes="...")``."""

    def _assign(app: store_models.Application) -> None:
        for name, value in fields.items():
            setattr(app, name, value)

    return update(key, _assign)


def restore(previous: store_models.Application) -> store_models.Application:
    """Put back an earlier copy of a row, e.g. after a failed Prepare refresh.

    Unlike `upsert`, every field returns to ``previous`` except what the user owns:
    the stored ``notes``, and a terminal status set since (kept, with a note).
    """
    with _txn():
        apps = _snapshot()
        found = _locate(apps, store_models._registry_key(previous))
        if found is None:
            found = _locate(apps, previous.source_job_id)
        row = previous.model_copy(deep=True)
        row._base = None
        if found is not None:
            stored = apps[found]
            row.notes = stored.notes
            if stored.status in store_models.TERMINAL_STATUSES and stored.status != previous.status:
                row.status = stored.status
                row.archived_at = stored.archived_at
                row.status_history = [change.model_copy() for change in stored.status_history]
                row.status_history.append(
                    store_models.StatusChange(
                        status=stored.status,
                        at=store_models._now_iso(),
                        note=f"restore skipped: already marked {stored.status}",
                    )
                )
            row.revision = stored.revision
            if found != store_models._registry_key(row):
                apps = dict(apps)
                del apps[found]
                _write(apps)
        return upsert(row)


def set_archived(application_ids: list[str], archived: bool) -> tuple[list[str], dict[str, str]]:
    """Change archive state in one write; restoring also undoes submitted/skipped."""
    with _txn():
        apps = load_all()
        updated: list[str] = []
        errors: dict[str, str] = {}
        changed = False
        for requested_id in dict.fromkeys(application_ids):
            found = _locate(apps, requested_id)
            if found is None:
                errors[requested_id] = "Application not found"
                continue
            app = apps[found]
            if archived and not app.archived_at:
                app.archived_at = store_models._now_iso()
                app.revision += 1
                changed = True
            elif not archived and app.archived_at:
                app.archived_at = None
                app.revision += 1
                undo_terminal(app, "Restored from Done; submitted mark undone")
                changed = True
            updated.append(requested_id)
        if changed:
            save_all(apps)
        return updated, errors


def all_ids() -> set[tuple[str, str]]:
    """Return every ``(source, source_job_id)`` currently on disk."""
    refs: set[tuple[str, str]] = set()
    with _LOCK:
        rows = list(_snapshot().values())
    for app in rows:
        if app.source_refs:
            for ref in app.source_refs:
                refs.add((ref.source, ref.source_job_id))
        else:
            refs.add((app.source, app.source_job_id))
    return refs


def add_source_ref(
    app: store_models.Application, ref: store_models.SourceRef
) -> store_models.Application:
    """Append ``ref`` when its ``(source, source_job_id)`` is not already present."""
    existing = {(r.source, r.source_job_id) for r in app.source_refs}
    if (ref.source, ref.source_job_id) not in existing:
        app.source_refs.append(ref)
    return app


def status_at(app: store_models.Application) -> str:
    """Timestamp of the latest status change, or discovery for legacy rows."""
    return app.status_history[-1].at if app.status_history else app.discovered_at


def undo_terminal(app: store_models.Application, note: str) -> bool:
    """Undo a submitted/skipped mark, the one sanctioned bypass of `set_status`'s terminal guard."""
    if app.status not in {"submitted", "skipped"}:
        return False
    mark = next(
        (index for index in range(len(app.status_history) - 1, -1, -1)
         if app.status_history[index].status in {"submitted", "skipped"}),
        len(app.status_history),
    )
    previous = next(
        (change.status for change in reversed(app.status_history[:mark])
         if change.status not in store_models.TERMINAL_STATUSES),
        "ready" if app.job_id else "jd_fetched",
    )
    app.status = {"filling": "ready", "tailoring": "tailor_failed"}.get(previous, previous)
    app.status_history.append(
        store_models.StatusChange(status=app.status, at=store_models._now_iso(), note=note)
    )
    app.revision += 1
    return True


def set_status(
    app: store_models.Application,
    new_status: store_models.ApplicationStatus,
    note: str = "",
) -> store_models.Application:
    """Append a status change and enforce terminal-state guards.

    `undo_terminal` is the one sanctioned bypass of this guard for mistaken
    submitted/skipped marks.

    Raises:
        ValueError: When ``app.status`` is terminal and ``new_status`` is pre-ready.
    """
    if (
        app.status in store_models.TERMINAL_STATUSES
        and new_status in store_models.PRE_READY_STATUSES
    ):
        raise ValueError(
            f"cannot move from terminal status {app.status!r} to pre-ready {new_status!r}"
        )
    if app.status == new_status and not note:
        return app
    at = store_models._now_iso()
    # A submitted or skipped application is done with the working queue (the Apply
    # page's "Done" tab lists archived rows). Only the transition archives it: a row
    # the user restores stays restored.
    if (
        new_status in ("submitted", "skipped")
        and app.status != new_status
        and not app.archived_at
    ):
        app.archived_at = at
    # A failed recheck can set screened_out on a restored screened_out row again.
    if new_status == "screened_out" and not app.archived_at:
        app.archived_at = at
    app.status = new_status
    app.status_history.append(
        store_models.StatusChange(status=new_status, at=at, note=note)
    )
    return app
