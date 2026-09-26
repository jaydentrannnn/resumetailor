"""In-app updates: the server's side of the shell conversation (`desktop_update`)."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config, desktop_main, desktop_update
from resume_tailor.web.app import app


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    desktop_update.reset()
    monkeypatch.setattr(desktop_update, "ENABLED", True)
    monkeypatch.setattr(desktop_update, "CURRENT", "0.1.1")
    out = io.StringIO()
    monkeypatch.setattr(desktop_update, "_out", out)
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(config, "TEMPLATES_ROOT", tmp_path / "templates")
    monkeypatch.setattr(config, "OUTPUT_ROOT", tmp_path / "output")
    yield out
    desktop_update.reset()


def _event(**fields) -> str:
    return "UPDATE " + json.dumps(fields)


def _sent(out: io.StringIO) -> list[str]:
    return out.getvalue().splitlines()


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as test_client:
        yield test_client


def test_request_writes_shell_lines_and_rejects_unknown(_fresh):
    desktop_update.request("check")
    assert _sent(_fresh) == ["SHELL check"]
    assert desktop_update.status()["state"] == "checking"
    with pytest.raises(ValueError):
        desktop_update.request("rm -rf")


def test_request_refuses_outside_the_desktop_app(monkeypatch):
    monkeypatch.setattr(desktop_update, "ENABLED", False)
    with pytest.raises(RuntimeError):
        desktop_update.request("check")


def test_available_then_up_to_date():
    desktop_update.receive(_event(state="available", version="0.2.0", notes="Faster", date="d"))
    status = desktop_update.status()
    assert status["state"] == "available"
    assert status["available"] == {"version": "0.2.0", "notes": "Faster", "date": "d"}
    assert status["last_checked"]
    desktop_update.receive(_event(state="up_to_date"))
    assert desktop_update.status()["state"] == "up_to_date"
    assert desktop_update.status()["available"] is None


@pytest.mark.parametrize("line", ["READY 8000 tok", "UPDATE not json", "UPDATE [1]", ""])
def test_other_lines_are_ignored(line):
    desktop_update.receive(line)
    assert desktop_update.status()["state"] == "idle"


def test_a_periodic_check_does_not_interrupt_a_download():
    desktop_update.receive(_event(state="available", version="0.2.0"))
    desktop_update.request("download")
    desktop_update.receive(_event(state="downloading", pct=40))
    desktop_update.receive(_event(state="up_to_date"))
    status = desktop_update.status()
    assert status["state"] == "downloading"
    assert status["pct"] == 40


def test_error_clears_progress():
    desktop_update.request("download")
    desktop_update.receive(_event(state="error", message="signature mismatch"))
    status = desktop_update.status()
    assert status["state"] == "error"
    assert status["error"] == "signature mismatch"
    assert status["pct"] is None


def test_ready_backs_up_then_applies_when_idle(_fresh, monkeypatch, tmp_path):
    (tmp_path / "data" / "workspaces" / "default").mkdir(parents=True)
    (tmp_path / "data" / "workspaces" / "default" / "profile.json").write_text("{}")
    con = sqlite3.connect(tmp_path / "data" / "workspaces" / "default" / "app.db")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "main_template.docx").write_bytes(b"docx")
    monkeypatch.setattr(desktop_update, "busy_reason", lambda: None)

    desktop_update.receive(_event(state="available", version="0.2.0"))
    desktop_update.receive(_event(state="ready"))
    desktop_update._waiter.join(timeout=5)

    assert _sent(_fresh)[-1] == "SHELL apply"
    status = desktop_update.status()
    assert status["state"] == "installing"
    backup = status["backup"]
    assert "pre-update-0.1.1-to-0.2.0-" in backup
    with zipfile.ZipFile(backup) as archive:
        names = set(archive.namelist())
    assert "data/workspaces/default/app.db" in names
    assert "data/workspaces/default/profile.json" in names
    assert "templates/main_template.docx" in names


def test_install_waits_while_busy(_fresh, monkeypatch):
    reasons = iter(["a tailoring run", "a tailoring run", None])
    monkeypatch.setattr(desktop_update, "busy_reason", lambda: next(reasons))
    monkeypatch.setattr(desktop_update, "backup", lambda a, b: config.OUTPUT_ROOT / "b.zip")
    seen: list[str] = []

    def fake_sleep(_seconds):
        seen.append(desktop_update.status()["state"])
        assert "SHELL apply" not in _sent(_fresh)

    desktop_update.receive(_event(state="available", version="0.2.0"))
    with desktop_update._lock:
        desktop_update._state["state"] = "ready"
    desktop_update._apply_when_idle(sleep=fake_sleep)

    assert seen == ["waiting", "waiting"]
    assert _sent(_fresh)[-1] == "SHELL apply"


def test_a_failed_backup_never_applies(_fresh, monkeypatch):
    monkeypatch.setattr(desktop_update, "busy_reason", lambda: None)

    def broken(_a, _b):
        raise OSError("disk full")

    monkeypatch.setattr(desktop_update, "backup", broken)
    with desktop_update._lock:
        desktop_update._state["state"] = "ready"
    desktop_update._apply_when_idle(sleep=lambda _s: None)
    assert "SHELL apply" not in _sent(_fresh)
    assert desktop_update.status()["state"] == "error"
    assert "disk full" in desktop_update.status()["error"]


def test_backups_keep_the_newest_three(tmp_path):
    (tmp_path / "data").mkdir()
    folder = desktop_update.backups_dir()
    folder.mkdir(parents=True)
    for age, stamp in enumerate(("20260101", "20260102", "20260103")):
        old = folder / f"pre-update-z-to-b-{stamp}-000000.zip"
        old.write_bytes(b"")
        os.utime(old, (1_000_000 + age, 1_000_000 + age))
    made = desktop_update.backup("0.1.1", "0.2.0")
    left = sorted(p.name for p in folder.glob("pre-update-*.zip"))
    assert len(left) == 3
    assert "pre-update-z-to-b-20260101-000000.zip" not in left
    assert made.name in left


def test_busy_reason_reports_a_running_tailor(monkeypatch):
    from resume_tailor.web import jobs

    monkeypatch.setattr(jobs.get_queue(), "busy", lambda: True)
    assert desktop_update.busy_reason() == "a tailoring run"


def test_routes_report_unsupported_outside_the_desktop_app(client, monkeypatch):
    monkeypatch.setattr(desktop_update, "ENABLED", False)
    assert client.get("/api/update").json()["supported"] is False
    assert client.post("/api/update/check").status_code == 409
    assert client.post("/api/update/install").status_code == 409


def test_install_route_needs_an_available_update(client, _fresh):
    assert client.post("/api/update/install").status_code == 409
    desktop_update.receive(_event(state="available", version="0.2.0"))
    response = client.post("/api/update/install")
    assert response.status_code == 200
    assert response.json()["state"] == "downloading"
    assert _sent(_fresh)[-1] == "SHELL download"


def test_check_route_asks_the_shell(client, _fresh):
    assert client.post("/api/update/check").json()["state"] == "checking"
    assert _sent(_fresh) == ["SHELL check"]


def test_health_reports_the_installed_version(client):
    assert client.get("/api/health").json()["version"] == "0.1.1"


def test_stdin_lines_reach_the_handler_and_eof_still_fires():
    lines: list[str] = []
    fired = threading.Event()
    stream = io.StringIO('UPDATE {"state":"up_to_date"}\r\nsecond\n')
    desktop_main.watch_stdin(fired.set, stream, on_line=lines.append).join(timeout=5)
    assert lines == ['UPDATE {"state":"up_to_date"}', "second"]
    assert fired.is_set()


def test_a_failing_line_handler_does_not_stop_the_watcher():
    fired = threading.Event()
    seen: list[str] = []

    def handler(line: str) -> None:
        seen.append(line)
        raise RuntimeError("boom")

    desktop_main.watch_stdin(fired.set, io.StringIO("a\nb\n"), on_line=handler).join(timeout=5)
    assert seen == ["a", "b"]
    assert fired.is_set()


def test_app_version_flag():
    assert desktop_main._flag_value(["--exit-with-stdin", "--app-version", "1.2.3"], "--app-version") == "1.2.3"
    assert desktop_main._flag_value(["--app-version"], "--app-version") is None
    assert desktop_main._flag_value([], "--app-version") is None
