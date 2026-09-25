"""SQLite database for a workspace's mutable records.

One file per workspace data directory (``<DATA_DIR>/app.db``), next to the JSON files
it replaces. Callers pass the path, derived from the config global they already use
(``config.APPLICATIONS_PATH.parent``, ``config.MASTER_RESUME_PATH.parent``), so a
workspace switch or a test's monkeypatched path lands in the right file with no extra
plumbing. Documents stay Pydantic models serialised to JSON in a ``doc`` column; the
other columns are copies for filtering and sorting. No ORM.

Connections are per thread and per path (`connect`), opened in autocommit mode with
WAL, foreign keys and a 5 s busy timeout; `transaction` issues ``BEGIN IMMEDIATE`` so a
read-modify-write holds the write lock from its first read. A thread's connections are
closed when the thread ends.

`generation(conn, name)` / `bump(conn, name)` is a per-table change counter. A process
caches parsed rows and re-reads only when the counter moved, which also picks up writes
from another process (the nightly CLI run next to the server).

Files (.docx, PDFs, JD text, screenshots, caches, templates) stay on disk.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DB_NAME = "app.db"

#: Ordered schema migrations; index + 1 is the version recorded in `schema_migrations`.
#: Append only. A released entry is never edited: add a new one instead.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE meta(name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE applications(
        key TEXT PRIMARY KEY,
        revision INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        company TEXT, role TEXT, location TEXT, ats TEXT,
        discovered_at TEXT, archived_at TEXT, group_key TEXT, job_id TEXT,
        doc TEXT NOT NULL
    );
    CREATE INDEX ix_app_status ON applications(status, archived_at);
    CREATE INDEX ix_app_group ON applications(group_key);
    CREATE TABLE resume_versions(
        version INTEGER PRIMARY KEY,
        saved_at TEXT NOT NULL,
        digest TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        doc TEXT NOT NULL
    );
    CREATE TABLE kv(name TEXT PRIMARY KEY, doc TEXT NOT NULL, updated_at TEXT NOT NULL);
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


class NewerSchema(RuntimeError):
    """The database was written by a newer version of the app."""


#: Connections kept open per thread. A process normally touches one or two databases;
#: the test suite touches one per test, and must not run out of file handles.
_MAX_OPEN_PER_THREAD = 8

_local = threading.local()
_init_lock = threading.Lock()
_initialised: set[Path] = set()


def db_path(data_dir: Path) -> Path:
    return data_dir / DB_NAME


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    """This thread's connection to ``path``, created (and the schema migrated) on first use."""
    path = Path(path)
    conns: OrderedDict[Path, sqlite3.Connection] | None = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = OrderedDict()
    conn = conns.get(path)
    if conn is not None and path.exists():
        conns.move_to_end(path)
        return conn
    if conn is not None:  # the file was deleted underneath us (tests, "delete all data")
        conns.pop(path).close()
        with _init_lock:
            _initialised.discard(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():  # a new (or replaced) file always gets the schema
        with _init_lock:
            _initialised.discard(path)
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    with suppress(sqlite3.OperationalError):  # e.g. a filesystem without shared memory
        conn.execute("PRAGMA journal_mode=WAL")
    with _init_lock:
        if path not in _initialised:
            _migrate(conn)
            _initialised.add(path)
    conns[path] = conn
    while len(conns) > _MAX_OPEN_PER_THREAD:
        conns.popitem(last=False)[1].close()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations("
            "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        numeric = [int(v) for v in applied if v.isdigit()]
        if numeric and max(numeric) > SCHEMA_VERSION:
            raise NewerSchema(
                f"This data was saved by a newer ResumeTailor (database schema "
                f"{max(numeric)}, this version reads {SCHEMA_VERSION}). Please update the app."
            )
        for number, script in enumerate(MIGRATIONS, start=1):
            if str(number) in applied:
                continue
            for statement in script.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (str(number), _now_iso()),
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT``; nested use joins the outer transaction."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def generation(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT value FROM meta WHERE name = ?", (name,)).fetchone()
    return int(row[0]) if row else 0


def bump(conn: sqlite3.Connection, name: str) -> int:
    """Advance ``name``'s change counter; call inside the writing transaction."""
    conn.execute(
        "INSERT INTO meta(name, value) VALUES (?, 1) "
        "ON CONFLICT(name) DO UPDATE SET value = value + 1",
        (name,),
    )
    return generation(conn, name)


def marker(conn: sqlite3.Connection, name: str) -> bool:
    """Whether the one-off step ``name`` (e.g. ``json_import:applications``) has run."""
    row = conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (name,)).fetchone()
    return row is not None


def set_marker(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (name, _now_iso()),
    )


def kv_get(conn: sqlite3.Connection, name: str) -> Any:
    """The JSON document stored under ``name`` in `kv`, or None."""
    row = conn.execute("SELECT doc FROM kv WHERE name = ?", (name,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def kv_set(conn: sqlite3.Connection, name: str, doc: Any) -> None:
    conn.execute(
        "INSERT INTO kv(name, doc, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at",
        (name, json.dumps(doc), _now_iso()),
    )


def close_all() -> None:
    """Close this thread's connections (tests that delete the file, shutdown)."""
    conns = getattr(_local, "conns", None) or {}
    for conn in conns.values():
        conn.close()
    conns.clear()
