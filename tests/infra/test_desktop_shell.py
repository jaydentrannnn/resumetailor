"""The server's side of window requests to the desktop shell (`desktop_shell`)."""

from __future__ import annotations

import io
import json
import threading

import pytest

from resume_tailor.infra import desktop_shell, desktop_update


@pytest.fixture
def out(monkeypatch) -> io.StringIO:
    stream = io.StringIO()
    monkeypatch.setattr(desktop_update, "_out", stream)
    monkeypatch.setattr(desktop_shell, "ENABLED", True)
    return stream


def _answer_when_asked(out: io.StringIO, path: str | None) -> threading.Thread:
    """Play the shell: wait for the save request, then send its DIALOG line."""

    def shell() -> None:
        for _ in range(200):
            lines = out.getvalue().splitlines()
            if lines:
                request = json.loads(lines[0][len("SHELL save "):])
                desktop_shell.receive("DIALOG " + json.dumps({"id": request["id"], "path": path}))
                return
            threading.Event().wait(0.01)

    thread = threading.Thread(target=shell)
    thread.start()
    return thread


def test_save_request_carries_name_and_extension_and_returns_the_path(out):
    shell = _answer_when_asked(out, "C:/Users/me/Resume.pdf")
    assert desktop_shell.ask_save_path("Resume.pdf", ".PDF", timeout=5) == "C:/Users/me/Resume.pdf"
    shell.join()
    request = json.loads(out.getvalue().splitlines()[0][len("SHELL save "):])
    assert request["name"] == "Resume.pdf"
    assert request["ext"] == "pdf"


def test_cancelled_dialog_returns_none(out):
    shell = _answer_when_asked(out, None)
    assert desktop_shell.ask_save_path("a.docx", ".docx", timeout=5) is None
    shell.join()


def test_no_answer_times_out_to_none(out):
    assert desktop_shell.ask_save_path("a.pdf", ".pdf", timeout=0.05) is None


def test_unrelated_and_unreadable_lines_are_ignored(out):
    desktop_shell.receive("UPDATE {}")
    desktop_shell.receive("DIALOG not json")
    desktop_shell.receive('DIALOG {"id": "nobody-asked", "path": "x"}')


def test_browser_build_has_no_shell(monkeypatch):
    monkeypatch.setattr(desktop_shell, "ENABLED", False)
    with pytest.raises(desktop_shell.ShellUnavailable):
        desktop_shell.ask_save_path("a.pdf", ".pdf")
    desktop_shell.set_title("ignored")  # a no-op, not an error


def test_title_line(out):
    desktop_shell.set_title("Acme — ResumeTailor")
    assert out.getvalue() == 'SHELL title {"title": "Acme \\u2014 ResumeTailor"}\n'


def test_a_closed_pipe_is_a_clear_error_not_a_500(monkeypatch):
    stream = io.StringIO()
    stream.close()
    monkeypatch.setattr(desktop_update, "_out", stream)
    monkeypatch.setattr(desktop_shell, "ENABLED", True)
    with pytest.raises(desktop_shell.ShellUnavailable, match="stopped answering"):
        desktop_shell.ask_save_path("a.pdf", ".pdf", timeout=0.05)
    desktop_shell.set_title("ignored")  # nothing to tell, so no error either
