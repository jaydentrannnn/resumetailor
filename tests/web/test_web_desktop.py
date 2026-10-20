"""`routes/desktop.py`: Save as…, Show in folder / Open, window title (desktop app only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.infra import desktop_shell, local_files
from resume_tailor.web import state as web_state
from tests.web.helpers import _disk_only_run


@pytest.fixture
def desktop(client, monkeypatch):
    """The desktop app; returns (client, calls made to the OS)."""
    c, _ = client
    monkeypatch.setattr(web_state, "desktop", True)
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(local_files, "reveal", lambda p: calls.append(("reveal", p)))
    monkeypatch.setattr(local_files, "open_default", lambda p: calls.append(("open", p)))
    monkeypatch.setattr(local_files, "open_in_word_processor", lambda p: calls.append(("word", p)))
    return c, calls


def _finished_run(job_id: str) -> Path:
    run_dir = _disk_only_run(job_id)
    for name in ("tailored.pdf", "tailored.docx", "cover.pdf", "cover.docx"):
        (run_dir / name).write_bytes(b"x")
    return run_dir


def test_browser_build_gets_404_for_every_desktop_route(client):
    c, _ = client
    _finished_run("job00001")
    assert c.post("/api/desktop/save-as?name=a.pdf", content=b"x").status_code == 404
    assert c.post("/api/jobs/job00001/files/resume-pdf/reveal").status_code == 404
    assert c.post("/api/desktop/title", json={"title": "x"}).status_code == 404


def test_save_as_writes_where_the_dialog_points(desktop, tmp_path, monkeypatch):
    c, _ = desktop
    asked: list[tuple[str, str]] = []

    def dialog(name, ext):
        asked.append((name, ext))
        return str(tmp_path / "Chosen")  # the person dropped the extension

    monkeypatch.setattr(desktop_shell, "ask_save_path", dialog)
    res = c.post("/api/desktop/save-as?name=..%2F..%2FMy%3AResume.pdf", content=b"%PDF-1")
    assert res.status_code == 200
    assert res.json() == {"saved": True, "path": str(tmp_path / "Chosen.pdf")}
    assert (tmp_path / "Chosen.pdf").read_bytes() == b"%PDF-1"
    # Only the file name reaches the dialog, with characters Windows refuses replaced.
    assert asked == [("My_Resume.pdf", ".pdf")]


def test_save_as_cancelled_writes_nothing(desktop, monkeypatch):
    c, _ = desktop
    monkeypatch.setattr(desktop_shell, "ask_save_path", lambda name, ext: None)
    res = c.post("/api/desktop/save-as?name=a.pdf", content=b"x")
    assert res.json() == {"saved": False, "path": None}


def test_save_as_reports_a_locked_target(desktop, tmp_path, monkeypatch):
    c, _ = desktop
    folder = tmp_path / "a-folder.pdf"
    folder.mkdir()  # writing bytes to a folder fails like a file held open elsewhere
    monkeypatch.setattr(desktop_shell, "ask_save_path", lambda name, ext: str(folder))
    res = c.post("/api/desktop/save-as?name=a.pdf", content=b"x")
    assert res.status_code == 409
    assert "close it and try again" in res.json()["detail"]


@pytest.mark.parametrize(
    ("kind", "action", "expected"),
    [
        ("resume-pdf", "reveal", ("reveal", "tailored.pdf")),
        ("resume-docx", "open", ("word", "tailored.docx")),
        ("cover-pdf", "open", ("open", "cover.pdf")),
        ("cover-docx", "reveal", ("reveal", "cover.docx")),
    ],
)
def test_file_actions_reach_the_run_folder(desktop, kind, action, expected):
    c, calls = desktop
    run_dir = _finished_run("job00002")
    res = c.post(f"/api/jobs/job00002/files/{kind}/{action}")
    assert res.status_code == 204
    assert calls == [(expected[0], run_dir / expected[1])]


def test_file_actions_reject_unknown_jobs_and_kinds(desktop):
    c, calls = desktop
    assert c.post("/api/jobs/nosuchjob/files/resume-pdf/open").status_code == 404
    assert c.post("/api/jobs/nosuchjob/files/notes-md/open").status_code == 422
    assert calls == []


def test_window_title_goes_to_the_shell(desktop, monkeypatch):
    c, _ = desktop
    titles: list[str] = []
    monkeypatch.setattr(desktop_shell, "set_title", titles.append)
    assert c.post("/api/desktop/title", json={"title": "Acme — ResumeTailor"}).status_code == 204
    assert titles == ["Acme — ResumeTailor"]


def test_save_as_takes_a_file_over_the_shared_10_mb_request_cap(desktop, tmp_path, monkeypatch):
    c, _ = desktop
    monkeypatch.setattr(desktop_shell, "ask_save_path", lambda name, ext: str(tmp_path / "b.zip"))
    body = b"z" * (11 * 1024 * 1024)
    res = c.post("/api/desktop/save-as?name=b.zip", content=body)
    assert res.status_code == 200
    assert (tmp_path / "b.zip").stat().st_size == len(body)


def test_profile_export_is_written_straight_to_the_chosen_path(desktop, tmp_path, monkeypatch):
    from resume_tailor import config
    from resume_tailor.content import data_transfer

    c, _ = desktop
    monkeypatch.setattr(config, "active_workspace_id", lambda: "default")
    built: list[bool] = []

    def export_zip(workspace_id, include_output):
        built.append(include_output)
        path = tmp_path / "staged.zip"
        path.write_bytes(b"PK")
        return path

    monkeypatch.setattr(data_transfer, "export_zip", export_zip)
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        desktop_shell,
        "ask_save_path",
        lambda name, ext: asked.append((name, ext)) or str(tmp_path / "Backup"),
    )
    res = c.post("/api/data/export/save?include_output=false")
    assert res.json() == {"saved": True, "path": str(tmp_path / "Backup.zip")}
    assert (tmp_path / "Backup.zip").read_bytes() == b"PK"
    assert not (tmp_path / "staged.zip").exists()
    assert built == [False]
    assert asked[0][0].startswith("resumetailor-") and asked[0][1] == ".zip"

    monkeypatch.setattr(desktop_shell, "ask_save_path", lambda name, ext: None)
    assert c.post("/api/data/export/save").json() == {"saved": False, "path": None}
    assert built == [False]  # cancelling builds nothing


def test_profile_export_save_is_desktop_only(client):
    c, _ = client
    assert c.post("/api/data/export/save").status_code == 404
