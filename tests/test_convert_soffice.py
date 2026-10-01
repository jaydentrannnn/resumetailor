"""LibreOffice conversion mechanics, with `subprocess.run` faked (no soffice needed)."""

from __future__ import annotations

import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from resume_tailor.document import convert


class _FakeSoffice:
    """Records each call; writes `<stem>.pdf` into --outdir unless told to fail."""

    def __init__(self, fail_first: int = 0):
        self.calls: list[list[str]] = []
        self.fail_first = fail_first

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        profile_arg = next(a for a in cmd if a.startswith("-env:UserInstallation="))
        assert profile_arg.split("=", 1)[1].startswith("file:")
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        source = Path(cmd[-1])
        if len(self.calls) > self.fail_first:
            (outdir / f"{source.stem}.pdf").write_bytes(b"%PDF-1.4")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(convert.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(convert, "_profile_dir", None)
    monkeypatch.delenv("RESUME_TAILOR_SOFFICE_PARALLEL", raising=False)
    runner = _FakeSoffice()
    monkeypatch.setattr(convert.subprocess, "run", runner)
    return runner


def _docx(tmp_path: Path) -> Path:
    src = tmp_path / "resume.docx"
    src.write_bytes(b"PK")
    return src


def _profiles(cmd_list):
    return {next(a for a in cmd if a.startswith("-env:")) for cmd in cmd_list}


def test_conversions_share_one_profile(fake, tmp_path):
    src = _docx(tmp_path)
    for i in range(3):
        convert.convert(src, tmp_path / "out" / f"r{i}.pdf", backend="soffice")
    assert len(_profiles(fake.calls)) == 1
    assert (tmp_path / "out" / "r2.pdf").exists()


def test_parallel_mode_uses_and_removes_throwaway_profiles(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_SOFFICE_PARALLEL", "1")
    src = _docx(tmp_path)
    for i in range(2):
        convert.convert(src, tmp_path / f"r{i}.pdf", backend="soffice")
    assert len(_profiles(fake.calls)) == 2
    assert not list((tmp_path / "tmp").glob("rt_lo_*"))


def test_failure_retries_once_on_a_fresh_profile(fake, tmp_path):
    fake.fail_first = 1
    profile = convert._shared_profile()
    profile.mkdir(parents=True)
    (profile / ".lock").write_text("stale")
    convert.convert(_docx(tmp_path), tmp_path / "r.pdf", backend="soffice")
    assert len(fake.calls) == 2
    assert not (profile / ".lock").exists()


def test_persistent_failure_raises(fake, tmp_path):
    fake.fail_first = 99
    with pytest.raises(RuntimeError, match="did not produce a PDF"):
        convert.convert(_docx(tmp_path), tmp_path / "r.pdf", backend="soffice")
    assert len(fake.calls) == 2


def test_stale_output_is_not_mistaken_for_success(fake, tmp_path):
    fake.fail_first = 99
    out = tmp_path / "resume.pdf"
    out.write_bytes(b"old")
    with pytest.raises(RuntimeError):
        convert.convert(_docx(tmp_path), out, backend="soffice")


def test_stale_profiles_from_crashed_processes_are_pruned(fake, tmp_path):
    import os

    old = tmp_path / "tmp" / "rt_lo_123_deadbeef"
    old.mkdir()
    os.utime(old, (1, 1))
    fresh = tmp_path / "tmp" / "rt_lo_456_cafebabe"
    fresh.mkdir()
    convert.convert(_docx(tmp_path), tmp_path / "r.pdf", backend="soffice")
    assert not old.exists()
    assert fresh.exists()


def test_profile_uri_is_a_valid_file_uri(tmp_path):
    uri = convert._profile_uri(tmp_path / "a b")
    # Three slashes (empty host) on every OS; the old f"file://{posix}" gave
    # "file://C:/..." on Windows, which names a host called "C:".
    assert uri.startswith("file:///")
    assert "%20" in uri
    assert PureWindowsPath("C:/Users/a b/lo").as_uri() == "file:///C:/Users/a%20b/lo"
