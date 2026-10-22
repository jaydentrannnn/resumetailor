"""Launch-at-login helpers: macOS plist and missing shell exe."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.infra import autostart


def test_set_enabled_requires_shell_exe(monkeypatch):
    """Without RESUME_TAILOR_SHELL_EXE, enable raises."""
    monkeypatch.delenv("RESUME_TAILOR_SHELL_EXE", raising=False)
    with pytest.raises(RuntimeError, match="desktop app"):
        autostart.set_enabled(True)


def test_macos_write_and_clear(tmp_path, monkeypatch):
    """On Darwin, enable writes a LaunchAgent and disable removes it."""
    exe = tmp_path / "ResumeTailor"
    exe.write_text("x", encoding="utf-8")
    plist = tmp_path / "app.resumetailor.desktop.plist"
    monkeypatch.setenv("RESUME_TAILOR_SHELL_EXE", str(exe))
    monkeypatch.setattr(autostart.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(autostart, "_plist_path", lambda: plist)
    assert not autostart.is_enabled()
    assert autostart.set_enabled(True) is True
    assert plist.is_file()
    text = plist.read_text(encoding="utf-8")
    assert "--hidden" in text
    assert str(exe) in text
    assert autostart.is_enabled()
    assert autostart.set_enabled(False) is False
    assert not plist.exists()
