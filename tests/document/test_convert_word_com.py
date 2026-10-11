"""Word conversion: a private Word per thread, never the user's own instance."""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

from resume_tailor.document import convert


class _FakeDoc:
    def __init__(self, log, fail):
        self.log, self.fail = log, fail

    def SaveAs(self, path, FileFormat):  # noqa: N802 - COM casing
        if self.fail:
            raise OSError("Word crashed")
        self.log.append(("save", FileFormat))

    def Close(self, how):  # noqa: N802
        self.log.append(("close", how))


class _FakeWord:
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail
        self.Documents = types.SimpleNamespace(Open=self._open)

    def _open(self, path, **kwargs):
        self.log.append(("open", kwargs.get("ReadOnly")))
        return _FakeDoc(self.log, self.fail)

    def Quit(self, how=None):  # noqa: N802
        self.log.append(("quit", how))


@pytest.fixture
def com(monkeypatch):
    """Fake pythoncom + win32com; `Dispatch` (attach to the user's Word) must never run."""
    log: list = []
    state = {"fail": False, "instances": 0}

    def dispatch_ex(name):
        assert name == "Word.Application"
        state["instances"] += 1
        log.append(("start", threading.current_thread().name))
        return _FakeWord(log, state["fail"])

    def dispatch(_name):
        raise AssertionError("Dispatch would attach to the user's own Word")

    client = types.SimpleNamespace(DispatchEx=dispatch_ex, Dispatch=dispatch)
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        types.SimpleNamespace(
            CoInitialize=lambda: log.append(("init", threading.current_thread().name)),
            CoUninitialize=lambda: log.append(("uninit", threading.current_thread().name)),
        ),
    )
    monkeypatch.setattr(convert, "_WORD", threading.local())
    return log, state


def test_conversion_uses_a_private_word_and_quits_it(com, tmp_path):
    log, _ = com
    worker = threading.Thread(
        target=convert._convert_word,  # noqa: SLF001
        args=(tmp_path / "a.docx", tmp_path / "a.pdf"),
        kwargs={"keep_active": False},
        name="job-abc",
    )
    worker.start()
    worker.join()
    assert log == [
        ("init", "job-abc"),
        ("start", "job-abc"),
        ("open", True),
        ("save", 17),
        ("close", 0),
        ("quit", 0),
        ("uninit", "job-abc"),
    ]


def test_keep_active_reuses_the_threads_instance_until_the_last_call(com, tmp_path: Path):
    log, state = com
    for keep in (True, True, False):
        convert._convert_word(tmp_path / "a.docx", tmp_path / "a.pdf", keep_active=keep)  # noqa: SLF001
    assert state["instances"] == 1
    assert [e for e in log if e[0] in ("init", "quit", "uninit")] == [
        ("init", "MainThread"),
        ("quit", 0),
        ("uninit", "MainThread"),
    ]


def test_a_failed_conversion_quits_even_with_keep_active(com, tmp_path: Path):
    log, state = com
    state["fail"] = True
    with pytest.raises(OSError):
        convert._convert_word(tmp_path / "a.docx", tmp_path / "a.pdf", keep_active=True)  # noqa: SLF001
    assert ("quit", 0) in log and log[-1][0] == "uninit"
    state["fail"] = False
    convert._convert_word(tmp_path / "a.docx", tmp_path / "a.pdf", keep_active=False)  # noqa: SLF001
    assert state["instances"] == 2  # a fresh instance, not the failed one
