"""Launch the desktop app when the computer starts (Windows Run key / macOS LaunchAgent).

The shell path comes from ``RESUME_TAILOR_SHELL_EXE`` (set by the Tauri shell). When
enabled, the entry is rewritten on each check so a moved install stays correct.
Uninstall does not remove the entry; Windows skips a missing target silently.
"""

from __future__ import annotations

import os
import platform
from contextlib import suppress
from pathlib import Path

_RUN_VALUE = "ResumeTailor"
_PLIST_LABEL = "app.resumetailor.desktop"
_PLIST_NAME = f"{_PLIST_LABEL}.plist"


def shell_exe() -> Path | None:
    """Absolute path to the desktop shell, or None when not running under it."""
    raw = os.environ.get("RESUME_TAILOR_SHELL_EXE", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def is_enabled() -> bool:
    """Whether a start-with-computer entry currently exists."""
    if platform.system() == "Windows":
        return _windows_get() is not None
    if platform.system() == "Darwin":
        return _plist_path().is_file()
    return False


def set_enabled(on: bool) -> bool:
    """Enable or disable launch at login. Returns the resulting enabled state.

    Raises ``RuntimeError`` when the shell path is unknown (browser/Docker build).
    """
    exe = shell_exe()
    if exe is None:
        raise RuntimeError("Start with computer is only available in the desktop app.")
    system = platform.system()
    if system == "Windows":
        if on:
            _windows_set(f'"{exe}" --hidden')
        else:
            _windows_clear()
        return on
    if system == "Darwin":
        if on:
            _macos_write(exe)
        else:
            _macos_clear()
        return on
    raise RuntimeError(f"Start with computer is not supported on {system}.")


def refresh_if_enabled() -> None:
    """Rewrite the entry with the current shell path when launch-at-login is on."""
    if not is_enabled():
        return
    with suppress(RuntimeError, OSError):
        set_enabled(True)


def _windows_get() -> str | None:
    """Value of the Run key, or None when missing."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
            return value if isinstance(value, str) else None
    except OSError:
        return None


def _windows_set(command: str) -> None:
    """Write the Run key value."""
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, command)


def _windows_clear() -> None:
    """Delete the Run key value if present."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, _RUN_VALUE)
    except FileNotFoundError:
        pass


def _plist_path() -> Path:
    """``~/Library/LaunchAgents/app.resumetailor.desktop.plist``."""
    return Path.home() / "Library" / "LaunchAgents" / _PLIST_NAME


def _macos_write(exe: Path) -> None:
    """Write a LaunchAgent that starts the shell hidden at login."""
    # Escape for XML text nodes.
    path = str(exe).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{_PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{path}</string>
    <string>--hidden</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
"""
    target = _plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _macos_clear() -> None:
    """Remove the LaunchAgent plist if present."""
    with suppress(OSError):
        _plist_path().unlink(missing_ok=True)
