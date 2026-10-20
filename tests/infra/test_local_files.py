"""Opening and revealing files on the person's machine (`local_files`)."""

from __future__ import annotations

from pathlib import Path

from resume_tailor.infra import local_files


def test_show_in_folder_selects_the_file_even_with_spaces(monkeypatch, tmp_path):
    """A list argument made Popen quote "/select,…" whole, and Explorer opened Documents."""
    started: list[object] = []
    monkeypatch.setattr(local_files.sys, "platform", "win32")
    monkeypatch.setattr(local_files.subprocess, "Popen", lambda cmd, *a, **k: started.append(cmd))
    path = tmp_path / "My Runs" / "Jane Doe Resume.pdf"
    local_files.reveal(path)
    assert started == [f'explorer /select,"{path.resolve()}"']


def test_show_in_folder_on_macos_reveals_in_finder(monkeypatch):
    started: list[object] = []
    monkeypatch.setattr(local_files.sys, "platform", "darwin")
    monkeypatch.setattr(local_files.subprocess, "Popen", lambda cmd, *a, **k: started.append(cmd))
    local_files.reveal(Path("/x/a b.pdf"))
    assert started == [["open", "-R", str(Path("/x/a b.pdf"))]]
