"""The desktop sidecar entry point (plan Phase 5, DK2)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from resume_tailor.infra import desktop_main


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        (
            "win32",
            {"LOCALAPPDATA": "C:/Users/a/AppData/Local"},
            "C:/Users/a/AppData/Local/ResumeTailorData",
        ),
        ("win32", {}, "/home/a/AppData/Local/ResumeTailorData"),
        ("darwin", {}, "/home/a/Library/Application Support/ResumeTailor"),
        ("linux", {"XDG_DATA_HOME": "/xdg"}, "/xdg/resumetailor"),
        ("linux", {}, "/home/a/.local/share/resumetailor"),
    ],
)
def test_app_data_dir_per_platform(platform, env, expected):
    got = desktop_main.app_data_dir(platform, env, Path("/home/a"))
    assert got.as_posix() == expected


def test_prepare_environment_fills_blanks_and_keeps_overrides(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    mine = tmp_path / "mine"
    env = {"RESUME_TAILOR_DATA_DIR": str(mine), "RESUME_TAILOR_TOKEN": "auto"}
    token = desktop_main.prepare_environment(env, tmp_path / "app")
    assert env["RESUME_TAILOR_DATA_DIR"] == str(mine)
    assert env["RESUME_TAILOR_OUTPUT_DIR"] == str(tmp_path / "app" / "output")
    assert env["RESUME_TAILOR_CACHE_DIR"] == str(tmp_path / "app" / "cache")
    assert all(Path(env[var]).is_dir() for var in desktop_main._DIR_VARS)  # noqa: SLF001
    # "auto" would rotate inside the server; the shell needs the value it will use.
    assert token == env["RESUME_TAILOR_TOKEN"] and len(token) > 30
    assert "RESUME_TAILOR_FRONTEND_DIST" not in env

    kept = {"RESUME_TAILOR_TOKEN": "fixed"}
    assert desktop_main.prepare_environment(kept, tmp_path / "app") == "fixed"


def test_app_data_env_file_fills_only_missing_settings(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    root = tmp_path / "app"
    root.mkdir()
    (root / ".env").write_text(
        "OLLAMA_MODEL=from-file\nRESUME_TAILOR_PDF_BACKEND=word\n"
        "RESUME_TAILOR_DATA_DIR={}\n".format((tmp_path / "shared").as_posix()),
        encoding="utf-8",
    )
    env = {"RESUME_TAILOR_PDF_BACKEND": "soffice"}
    desktop_main.prepare_environment(env, root)
    assert env["OLLAMA_MODEL"] == "from-file"
    assert env["RESUME_TAILOR_PDF_BACKEND"] == "soffice"  # a real variable wins
    assert env["RESUME_TAILOR_DATA_DIR"] == (tmp_path / "shared").as_posix()
    assert env["CHROME_CDP_URL"] == "http://127.0.0.1:9222"

    kept = {"CHROME_CDP_URL": "http://127.0.0.1:9333"}
    desktop_main.prepare_environment(kept, tmp_path / "other")
    assert kept["CHROME_CDP_URL"] == "http://127.0.0.1:9333"


def test_frozen_build_points_at_the_bundled_spa(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    env: dict[str, str] = {}
    desktop_main.prepare_environment(env, tmp_path / "app")
    assert env["RESUME_TAILOR_FRONTEND_DIST"] == str(tmp_path / "frontend" / "dist")


def test_bind_socket_prefers_the_extension_ports_then_any():
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    busy = taken.getsockname()[1]
    try:
        sock = desktop_main.bind_socket([busy])
        try:
            port = sock.getsockname()[1]
            assert sock.getsockname()[0] == "127.0.0.1"
            assert port not in {busy, 0}
        finally:
            sock.close()
        free = desktop_main.bind_socket([0])
        free.close()
    finally:
        taken.close()


def test_bind_socket_fails_loudly_when_nothing_binds():
    class _Refuses:
        def bind(self, _address):
            raise OSError("in use")

        def close(self):
            pass

    with pytest.raises(RuntimeError, match="No free port"):
        desktop_main.bind_socket([8000], make_socket=_Refuses)


def test_watch_stdin_fires_at_end_of_file():
    import io
    import threading

    fired = threading.Event()
    desktop_main.watch_stdin(fired.set, io.StringIO("ignored input")).join(timeout=5)
    assert fired.is_set()


def test_frozen_build_never_spawns_itself_for_a_template_build(monkeypatch):
    """Frozen, sys.executable is the server: a spawned "build" would be a second server."""
    from resume_tailor.web import template_ops

    def _spawned(*_args, **_kwargs):
        raise AssertionError("the frozen app must build templates in-process")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(template_ops.subprocess, "run", _spawned)
    code, log = template_ops._run_build()  # noqa: SLF001
    assert code != 0 and "in-process" in log


def test_sidecar_prints_ready_once_it_serves(tmp_path):
    """End to end: the shell's contract is one READY line, then a live server."""
    env = {
        **os.environ,
        "RESUME_TAILOR_DATA_DIR": str(tmp_path / "data"),
        "RESUME_TAILOR_TEMPLATES_DIR": str(tmp_path / "templates"),
        "RESUME_TAILOR_OUTPUT_DIR": str(tmp_path / "output"),
        "RESUME_TAILOR_CACHE_DIR": str(tmp_path / "cache"),
        "RESUME_TAILOR_LOG_DIR": "off",
        "RESUME_TAILOR_TOKEN": "",
        # Keep the app-data folder (and its optional .env) out of the real profile.
        "XDG_DATA_HOME": str(tmp_path / "appdata"),
        "LOCALAPPDATA": str(tmp_path / "appdata"),
    }
    if sys.platform == "darwin":
        env["HOME"] = str(tmp_path / "home")
    proc = subprocess.Popen(
        [sys.executable, "-m", "resume_tailor.infra.desktop_main", "--exit-with-stdin"],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        ready = ""
        assert proc.stdout is not None
        for _ in range(20):
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("READY "):
                ready = line
                break
        _, port, token = ready.split()
        base = f"http://127.0.0.1:{port}"
        assert httpx.get(f"{base}/api/health", timeout=5).status_code == 200
        assert httpx.get(f"{base}/api/config", timeout=5).status_code == 401
        signed = httpx.get(f"{base}/api/config", headers={"x-rt-token": token}, timeout=10)
        assert signed.status_code == 200
        assert (tmp_path / "data" / ".session_token").read_text(encoding="utf-8") == token
        # The shell going away closes stdin; the server must not outlive it.
        assert proc.stdin is not None
        proc.stdin.close()
        assert proc.wait(timeout=15) == 0
    finally:
        proc.terminate()
        proc.wait(timeout=10)
