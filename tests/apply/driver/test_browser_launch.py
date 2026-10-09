"""`browser_launch`: find the chosen browser, start it once, and say why when it can't."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.apply.driver import browser, browser_launch


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_find_executable_windows_falls_back_to_known_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_launch, "_app_path_from_registry", lambda exe: None)
    exe = _touch(tmp_path / "local" / "Perplexity" / "Comet" / "Application" / "comet.exe")
    env = {"LOCALAPPDATA": str(tmp_path / "local"), "ProgramFiles": str(tmp_path / "pf")}
    assert browser_launch.find_executable("comet", platform="win32", env=env) == exe
    assert browser_launch.find_executable("edge", platform="win32", env=env) is None


def test_find_executable_windows_prefers_registry(tmp_path, monkeypatch):
    exe = _touch(tmp_path / "msedge.exe")
    monkeypatch.setattr(browser_launch, "_app_path_from_registry", lambda name: exe)
    assert browser_launch.find_executable("edge", platform="win32", env={}) == exe


def test_find_executable_mac_checks_user_applications(tmp_path):
    binary = _touch(tmp_path / "Applications" / "Comet.app" / "Contents" / "MacOS" / "Comet")
    assert browser_launch.find_executable("comet", platform="darwin", home=tmp_path) == binary


def test_find_executable_linux_uses_path(monkeypatch):
    monkeypatch.setattr(
        browser_launch.shutil, "which",
        lambda name: "/usr/bin/google-chrome-stable" if name == "google-chrome-stable" else None,
    )
    assert browser_launch.find_executable("chrome", platform="linux") == Path(
        "/usr/bin/google-chrome-stable"
    )
    assert browser_launch.find_executable("comet", platform="linux") is None


def test_profile_dir_matches_the_old_launch_commands(tmp_path):
    env = {"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
    assert browser_launch.profile_dir("edge", platform="win32", env=env) == Path(
        r"C:\Users\u\AppData\Local\ResumeTailorEdge"
    )
    assert browser_launch.profile_dir("chrome", platform="darwin", home=tmp_path) == (
        tmp_path / "Library" / "Application Support" / "ResumeTailorChrome"
    )


@pytest.mark.parametrize(("selected", "installed", "expected"), [
    (None, {"edge": False, "chrome": True, "comet": True}, "chrome"),
    ("comet", {"edge": True, "chrome": True, "comet": True}, "comet"),
    ("comet", {"edge": True, "chrome": True, "comet": False}, None),
    (None, {}, None),
])
def test_resolve_browser(selected, installed, expected):
    assert browser_launch.resolve_browser(selected, installed) == expected


def test_can_launch_is_off_in_tests_docker_and_for_remote_urls(monkeypatch):
    assert not browser_launch.can_launch()  # tests/conftest.py turns it off
    monkeypatch.setenv("RESUME_TAILOR_BROWSER_LAUNCH", "on")
    monkeypatch.setattr(browser_launch, "in_docker", lambda: False)
    monkeypatch.setattr(browser_launch.config, "CHROME_CDP_URL", "http://127.0.0.1:9222")
    assert browser_launch.can_launch()
    monkeypatch.setattr(browser_launch.config, "CHROME_CDP_URL", "http://host.docker.internal:9222")
    assert not browser_launch.can_launch()
    monkeypatch.setattr(browser_launch.config, "CHROME_CDP_URL", "http://127.0.0.1:9222")
    monkeypatch.setattr(browser_launch, "in_docker", lambda: True)
    assert not browser_launch.can_launch()


class _Host:
    """A fake machine: which browsers exist, what answers on the port, what got started."""

    def __init__(self, monkeypatch, *, reachable_after: int | None = 1, port_busy=False):
        self.launched: list[tuple[str, int]] = []
        self.probes = 0
        self.reachable_after = reachable_after
        monkeypatch.setattr(browser_launch, "can_launch", lambda: True)
        monkeypatch.setattr(browser_launch, "_debug_port", lambda: 9222)
        monkeypatch.setattr(browser_launch, "selected_browser", lambda: None)
        monkeypatch.setattr(
            browser_launch, "installed_browsers",
            lambda: {"edge": True, "chrome": True, "comet": False},
        )
        monkeypatch.setattr(browser_launch, "_port_in_use", lambda port: port_busy)
        monkeypatch.setattr(browser_launch, "launch", lambda b, port: self.launched.append((b, port)))
        monkeypatch.setattr(browser_launch.time, "sleep", lambda s: None)
        monkeypatch.setattr(browser, "browser_status", self.status)
        monkeypatch.setattr(browser_launch, "_last_error", (None, ""))

    def status(self) -> browser.BrowserStatus:
        self.probes += 1
        up = bool(self.launched) and self.reachable_after is not None and (
            self.probes > self.reachable_after
        )
        return browser.BrowserStatus(reachable=up, error="" if up else "refused")


def test_ensure_browser_does_nothing_when_already_reachable(monkeypatch):
    host = _Host(monkeypatch)
    monkeypatch.setattr(browser, "browser_status", lambda: browser.BrowserStatus(reachable=True))
    assert browser_launch.ensure_browser().reachable
    assert host.launched == []


def test_ensure_browser_does_nothing_when_it_may_not_launch(monkeypatch):
    host = _Host(monkeypatch)
    monkeypatch.setattr(browser_launch, "can_launch", lambda: False)
    assert not browser_launch.ensure_browser().reachable
    assert host.launched == []


def test_ensure_browser_starts_the_automatic_pick_and_waits(monkeypatch):
    host = _Host(monkeypatch, reachable_after=3)
    assert browser_launch.ensure_browser().reachable
    assert host.launched == [("edge", 9222)]


def test_ensure_browser_reports_a_held_port_without_launching(monkeypatch):
    host = _Host(monkeypatch, port_busy=True)
    with pytest.raises(RuntimeError, match="Port 9222 is used by another program"):
        browser_launch.ensure_browser()
    assert host.launched == []


def test_ensure_browser_reports_an_uninstalled_choice(monkeypatch):
    host = _Host(monkeypatch)
    monkeypatch.setattr(browser_launch, "selected_browser", lambda: "comet")
    with pytest.raises(RuntimeError, match="Comet isn't installed"):
        browser_launch.ensure_browser()
    assert host.launched == []


def test_ensure_browser_timeout_names_the_open_profile_and_is_remembered(monkeypatch):
    _Host(monkeypatch, reachable_after=None)
    with pytest.raises(RuntimeError, match="Close any open ResumeTailor Edge window"):
        browser_launch.ensure_browser(timeout=0.01)
    status = browser_launch.launch_status()
    assert status.state == "unavailable"
    assert "ResumeTailor Edge" in status.reason
    # A different choice doesn't inherit Edge's failure.
    monkeypatch.setattr(browser_launch, "selected_browser", lambda: "chrome")
    assert browser_launch.launch_status().state == "idle"


def test_launch_status_states(monkeypatch):
    _Host(monkeypatch)
    status = browser_launch.launch_status()
    assert (status.state, status.resolved, status.reason) == ("idle", "edge", "")
    monkeypatch.setattr(browser, "browser_status", lambda: browser.BrowserStatus(reachable=True))
    assert browser_launch.launch_status().state == "ready"


def test_launch_passes_fixed_flags_and_the_profile(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    exe = _touch(tmp_path / "msedge.exe")
    monkeypatch.setattr(browser_launch, "find_executable", lambda b: exe)
    monkeypatch.setattr(browser_launch, "profile_dir", lambda b: tmp_path / "profile")
    monkeypatch.setattr(
        browser_launch.subprocess, "Popen", lambda args, **kwargs: calls.append(args)
    )
    browser_launch.launch("edge", 9222)
    (args,) = calls
    assert args[0] == str(exe)
    assert "--remote-debugging-port=9222" in args
    assert f"--user-data-dir={tmp_path / 'profile'}" in args
    assert not any(arg.startswith("--remote-allow-origins") for arg in args)
    assert (tmp_path / "profile").is_dir()
