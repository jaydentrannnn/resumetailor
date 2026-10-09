"""Start the user's chosen browser with remote debugging, on demand.

The app runs on the user's machine (the desktop sidecar, or uvicorn from a checkout),
so instead of asking the user to paste a launch command, every CDP connection goes
through `ensure_browser`: when nothing answers on the debug port it starts the chosen
browser itself, with the same flags the old copy-paste command used, and waits for
the port.

- **Chromium only** (Edge, Chrome, Comet): Playwright drives the browser over CDP.
  Firefox no longer speaks CDP, so it is not offered.
- **A dedicated profile folder per browser** (`profile_dir`): a separate
  ``--user-data-dir`` runs as its own instance beside the user's everyday windows of
  the same browser, and keeps job-site logins out of their normal profile. The folders
  are the ones the old commands used, so existing logins carry over.
- **Started, not launched by Playwright**: ``chromium.launch()`` marks the browser as
  automated (``navigator.webdriver``, the infobar) and closes it when the connection
  drops. A plain process the app only connects to behaves like the user's own browser
  and survives the app.
- **Never in Docker or relay mode** (`can_launch`): a container cannot start a host
  program, and the extension relay brings its own tab.
- **Never kills anything**: when the port is held by another program, or the profile
  is already open without the port, it reports why and stops.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args
from urllib.parse import urlparse

from resume_tailor import config
from resume_tailor.apply.driver import browser

BrowserId = Literal["edge", "chrome", "comet"]
BROWSER_IDS: tuple[BrowserId, ...] = get_args(BrowserId)
#: Picked in this order when the user has not chosen one.
AUTO_ORDER: tuple[BrowserId, ...] = ("edge", "chrome", "comet")
LABELS: dict[BrowserId, str] = {"edge": "Edge", "chrome": "Chrome", "comet": "Comet"}

#: No ``--remote-allow-origins``: it would let any page open in the browser drive the
#: DevTools socket. Playwright's CDP client sends no Origin header and needs no flag.
BACKGROUND_FLAGS = (
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
)
DEFAULT_PORT = 9222
LAUNCH_TIMEOUT = 15.0

_WINDOWS_EXE: dict[BrowserId, str] = {
    "edge": "msedge.exe", "chrome": "chrome.exe", "comet": "comet.exe",
}
_WINDOWS_DIRS: dict[BrowserId, tuple[str, ...]] = {
    "edge": (r"%ProgramFiles(x86)%\Microsoft\Edge\Application",
             r"%ProgramFiles%\Microsoft\Edge\Application"),
    "chrome": (r"%ProgramFiles%\Google\Chrome\Application",
               r"%ProgramFiles(x86)%\Google\Chrome\Application",
               r"%LOCALAPPDATA%\Google\Chrome\Application"),
    "comet": (r"%LOCALAPPDATA%\Perplexity\Comet\Application",),
}
_MAC_APPS: dict[BrowserId, tuple[str, str]] = {
    "edge": ("Microsoft Edge.app", "Microsoft Edge"),
    "chrome": ("Google Chrome.app", "Google Chrome"),
    "comet": ("Comet.app", "Comet"),
}
_LINUX_NAMES: dict[BrowserId, tuple[str, ...]] = {
    "edge": ("microsoft-edge", "microsoft-edge-stable"),
    "chrome": ("google-chrome", "google-chrome-stable"),
    "comet": (),
}
_PROFILE_NAMES: dict[BrowserId, str] = {
    "edge": "ResumeTailorEdge", "chrome": "ResumeTailorChrome", "comet": "ResumeTailorComet",
}

_LOCK = threading.Lock()
#: Why the last launch failed, and for which browser: shown while the browser stays
#: unreachable and the same one is chosen.
_last_error: tuple[BrowserId | None, str] = (None, "")


def _expand(template: str, env: Mapping[str, str]) -> str | None:
    out = template
    for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        token = f"%{name}%"
        if token in out:
            value = env.get(name)
            if not value:
                return None
            out = out.replace(token, value)
    return out


def _app_path_from_registry(exe: str) -> Path | None:
    """The browser's ``App Paths`` registration, per-user first (Comet installs there)."""
    try:
        import winreg
    except ImportError:
        return None
    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        path = Path(str(value).strip('"'))
        if path.is_file():
            return path
    return None


def find_executable(
    browser_id: BrowserId,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path | None:
    """The browser's program file on this machine, or ``None`` when not installed."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform.startswith("win"):
        exe = _WINDOWS_EXE[browser_id]
        found = _app_path_from_registry(exe)
        if found:
            return found
        for template in _WINDOWS_DIRS[browser_id]:
            folder = _expand(template, env)
            if folder and (Path(folder) / exe).is_file():
                return Path(folder) / exe
        return None
    if platform == "darwin":
        bundle, binary = _MAC_APPS[browser_id]
        home = home or Path.home()
        for apps in (Path("/Applications"), home / "Applications"):
            candidate = apps / bundle / "Contents" / "MacOS" / binary
            if candidate.is_file():
                return candidate
        return None
    for name in _LINUX_NAMES[browser_id]:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def installed_browsers() -> dict[BrowserId, bool]:
    return {browser_id: find_executable(browser_id) is not None for browser_id in BROWSER_IDS}


def profile_dir(
    browser_id: BrowserId,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """The dedicated ``--user-data-dir`` — the folders the old launch commands used."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    name = _PROFILE_NAMES[browser_id]
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / name
    if platform == "darwin":
        return home / "Library" / "Application Support" / name
    return home / ".config" / name


def in_docker() -> bool:
    return os.environ.get("RESUME_TAILOR_IN_DOCKER") == "1" or Path("/.dockerenv").exists()


def _debug_port() -> int | None:
    """The loopback port ``CHROME_CDP_URL`` points at, or ``None`` when it isn't local."""
    parsed = urlparse(config.CHROME_CDP_URL)
    if (parsed.hostname or "").lower() not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return parsed.port or DEFAULT_PORT


def can_launch() -> bool:
    """Whether this process may start the browser itself.

    ``RESUME_TAILOR_BROWSER_LAUNCH=off`` turns it off (the test suite does).
    """
    if os.environ.get("RESUME_TAILOR_BROWSER_LAUNCH", "").lower() == "off":
        return False
    return not in_docker() and not browser.extension_mode() and _debug_port() is not None


def selected_browser() -> BrowserId | None:
    """The browser chosen in Apply settings, or ``None`` for automatic."""
    try:
        from resume_tailor import workspace
        from resume_tailor.web.schemas import JobSettings

        return JobSettings.model_validate(workspace.load_settings()["defaults"]).apply.browser
    except Exception:  # noqa: BLE001 - unreadable settings fall back to automatic
        return None


def resolve_browser(
    selected: BrowserId | None, installed: Mapping[BrowserId, bool]
) -> BrowserId | None:
    """The browser to start: the chosen one when installed, else the first installed."""
    if selected is not None:
        return selected if installed.get(selected) else None
    return next((browser_id for browser_id in AUTO_ORDER if installed.get(browser_id)), None)


def _port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def port_busy_reason(port: int) -> str:
    return f"Port {port} is used by another program, so the browser can't open its debug port."


def unavailable_reason(selected: BrowserId | None, installed: Mapping[BrowserId, bool]) -> str:
    """Why the browser can't be started right now; ``""`` when it can."""
    port = _debug_port()
    if not can_launch() or port is None:
        return ""
    if resolve_browser(selected, installed) is None:
        if selected is not None:
            return f"{LABELS[selected]} isn't installed on this computer."
        return "No supported browser (Edge, Chrome or Comet) is installed."
    if _port_in_use(port):
        return port_busy_reason(port)
    failed_id, message = _last_error
    return message if failed_id == resolve_browser(selected, installed) else ""


def launch(browser_id: BrowserId, port: int = DEFAULT_PORT) -> None:
    """Start the browser detached, so it outlives this process."""
    exe = find_executable(browser_id)
    if exe is None:
        raise RuntimeError(f"{LABELS[browser_id]} isn't installed on this computer.")
    profile = profile_dir(browser_id)
    profile.mkdir(parents=True, exist_ok=True)
    args = [str(exe), f"--remote-debugging-port={port}", *BACKGROUND_FLAGS,
            f"--user-data-dir={profile}"]
    common = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    if sys.platform.startswith("win"):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                             **common)
        except OSError:
            # A job object that forbids breakaway refuses the flag; start inside it.
            subprocess.Popen(args, creationflags=flags, **common)
    else:
        subprocess.Popen(args, start_new_session=True, **common)


def ensure_browser(timeout: float = LAUNCH_TIMEOUT) -> browser.BrowserStatus:
    """Return a reachable status, starting the chosen browser first when needed.

    Returns the unreachable status unchanged when this process may not start a
    browser (Docker, relay mode); raises ``RuntimeError`` with the reason when a
    launch was possible but failed.
    """
    global _last_error
    status = browser.browser_status()
    if status.reachable or not can_launch():
        return status
    with _LOCK:
        status = browser.browser_status()
        if status.reachable:
            return status
        port = _debug_port() or DEFAULT_PORT
        selected = selected_browser()
        installed = installed_browsers()
        browser_id = resolve_browser(selected, installed)
        if browser_id is None:
            raise RuntimeError(unavailable_reason(selected, installed))
        if _port_in_use(port):
            raise RuntimeError(port_busy_reason(port))
        launch(browser_id, port)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.25)
            status = browser.browser_status()
            if status.reachable:
                _last_error = (None, "")
                return status
        name = LABELS[browser_id]
        message = (
            f"{name} started but didn't open its debug port. Close any open "
            f"ResumeTailor {name} window and try again."
        )
        _last_error = (browser_id, message)
        raise RuntimeError(message)


@dataclass
class LaunchStatus:
    """The browser probe plus what the app would do about an unreachable one."""

    probe: browser.BrowserStatus
    state: Literal["ready", "idle", "unavailable"]
    reason: str
    can_launch: bool
    docker: bool
    installed: dict[BrowserId, bool]
    selected: BrowserId | None
    resolved: BrowserId | None


def launch_status() -> LaunchStatus:
    """Probe the browser and say whether it is ready, startable, or unavailable."""
    probe = browser.browser_status()
    allowed = can_launch()
    installed = installed_browsers()
    selected = selected_browser()
    resolved = resolve_browser(selected, installed)
    if probe.reachable:
        state, reason = "ready", ""
    elif not allowed:
        state, reason = "unavailable", probe.error
    else:
        reason = unavailable_reason(selected, installed)
        state = "unavailable" if reason else "idle"
    return LaunchStatus(
        probe=probe, state=state, reason=reason, can_launch=allowed, docker=in_docker(),
        installed=installed, selected=selected, resolved=resolved,
    )
