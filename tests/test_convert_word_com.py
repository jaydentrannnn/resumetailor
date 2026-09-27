"""Word conversion initialises COM on the calling thread (every job has its own)."""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

from resume_tailor import convert


def test_word_conversion_initialises_com_on_its_own_thread(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []

    def record(name):
        return lambda *_, **__: calls.append((name, threading.current_thread().name))

    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        types.SimpleNamespace(CoInitialize=record("init"), CoUninitialize=record("uninit")),
    )
    monkeypatch.setitem(sys.modules, "docx2pdf", types.SimpleNamespace(convert=record("convert")))

    worker = threading.Thread(
        target=convert._convert_word,  # noqa: SLF001
        args=(tmp_path / "a.docx", tmp_path / "a.pdf"),
        kwargs={"keep_active": False},
        name="job-abc",
    )
    worker.start()
    worker.join()

    assert calls == [("init", "job-abc"), ("convert", "job-abc"), ("uninit", "job-abc")]


def test_com_is_released_when_word_fails(monkeypatch, tmp_path: Path):
    calls: list[str] = []

    def fail(*_, **__):
        raise OSError("Word crashed")

    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        types.SimpleNamespace(
            CoInitialize=lambda: calls.append("init"), CoUninitialize=lambda: calls.append("uninit")
        ),
    )
    monkeypatch.setitem(sys.modules, "docx2pdf", types.SimpleNamespace(convert=fail))

    try:
        convert._convert_word(tmp_path / "a.docx", tmp_path / "a.pdf", keep_active=False)  # noqa: SLF001
    except OSError:
        pass
    assert calls == ["init", "uninit"]
