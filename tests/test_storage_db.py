"""The SQLite helper: schema migrations, markers, change counters, connection reuse."""

from __future__ import annotations

import sqlite3

import pytest

from resume_tailor.storage import db


def test_schema_is_created_once_and_recorded(tmp_path):
    path = db.db_path(tmp_path)
    conn = db.connect(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"applications", "resume_versions", "kv", "meta", "schema_migrations"} <= tables
    versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    assert versions == {str(n) for n in range(1, db.SCHEMA_VERSION + 1)}
    assert db.connect(path) is conn


def test_a_newer_schema_refuses_to_open(tmp_path):
    path = db.db_path(tmp_path)
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT)")
    raw.execute("INSERT INTO schema_migrations VALUES ('99', 'x')")
    raw.commit()
    raw.close()
    with pytest.raises(db.NewerSchema, match="update the app"):
        db.connect(path)


def test_counters_markers_and_rollback(tmp_path):
    conn = db.connect(db.db_path(tmp_path))
    assert db.generation(conn, "t") == 0
    with db.transaction(conn):
        assert db.bump(conn, "t") == 1
        db.set_marker(conn, "once")
    assert db.marker(conn, "once") and db.generation(conn, "t") == 1
    with pytest.raises(RuntimeError), db.transaction(conn):
        db.bump(conn, "t")
        raise RuntimeError
    assert db.generation(conn, "t") == 1


def test_open_connections_per_thread_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_MAX_OPEN_PER_THREAD", 2)
    first = db.connect(db.db_path(tmp_path / "a"))
    db.connect(db.db_path(tmp_path / "b"))
    db.connect(db.db_path(tmp_path / "c"))
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")  # evicted and closed
    assert db.connect(db.db_path(tmp_path / "a")).execute("SELECT 1").fetchone() == (1,)
