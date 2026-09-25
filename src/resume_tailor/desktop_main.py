"""Desktop sidecar entry point (plan Phase 5, DK2): the server the Tauri shell launches.

The shell starts this program (a PyInstaller ``--onedir`` build, `resumetailor.spec`),
reads one line from its stdout, and then points its window at the app::

    READY <port> <token>

→ ``http://127.0.0.1:<port>/?t=<token>``. Before the app is imported this sets up:

- **Storage** in the per-user app-data folder, not next to the program: data,
  templates, output and cache under ``<app data>/ResumeTailor``. Any
  ``RESUME_TAILOR_*_DIR`` already set wins, so a developer can point a build at a
  checkout's folders. ``config`` reads these once, at import, which is why nothing from
  the app is imported at module level here.
- **A session token** (`web/security.py`): a fresh random one per launch, unless
  ``RESUME_TAILOR_TOKEN`` is already set.
- **A port** on 127.0.0.1: the first free one in 8000–8010, where the browser extension
  looks for the app, else any free port. The socket is bound here and handed to
  uvicorn, so no other process can take the port in between.

Only loopback is ever bound. The READY line is printed after uvicorn has started, so
the shell never opens a window onto a server that is not listening yet.

``--exit-with-stdin``: the shell holds this process's stdin open and never writes to
it; when the shell goes away for any reason (quit, crash, killed at logout) the pipe
closes and the server shuts down instead of lingering on its port.
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

APP_NAME = "ResumeTailor"
HOST = "127.0.0.1"
#: Ports the browser extension scans for the app (`extension/lib/api.js`).
PREFERRED_PORTS = range(8000, 8011)

_DIR_VARS = {
    "RESUME_TAILOR_DATA_DIR": "data",
    "RESUME_TAILOR_TEMPLATES_DIR": "templates",
    "RESUME_TAILOR_OUTPUT_DIR": "output",
    "RESUME_TAILOR_CACHE_DIR": "cache",
}


def app_data_dir(
    platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """The per-user folder the app keeps everything in.

    Windows ``%LOCALAPPDATA%\\ResumeTailor``, macOS ``~/Library/Application Support/
    ResumeTailor``, elsewhere ``$XDG_DATA_HOME/resumetailor`` (``~/.local/share``). The
    same locations `platformdirs` uses, without the dependency.
    """
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / APP_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    base = env.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / APP_NAME.lower()


def prepare_environment(env: dict[str, str], root: Path) -> str:
    """Fill in the storage folders and session token in ``env``; return the token.

    Values already in ``env`` are kept. The folders are created so a first launch does
    not depend on each subsystem making its own.
    """
    for var, name in _DIR_VARS.items():
        if not env.get(var):
            env[var] = str(root / name)
        Path(env[var]).mkdir(parents=True, exist_ok=True)
    token = env.get("RESUME_TAILOR_TOKEN", "").strip()
    if not token or token.lower() in {"auto", "off", "0", "none"}:
        # The desktop app always runs with the token check on.
        token = secrets.token_urlsafe(32)
        env["RESUME_TAILOR_TOKEN"] = token
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle and not env.get("RESUME_TAILOR_FRONTEND_DIST"):
        # PyInstaller unpacks data files under _MEIPASS (`resumetailor.spec` puts the
        # built SPA at frontend/dist there).
        env["RESUME_TAILOR_FRONTEND_DIST"] = str(Path(bundle) / "frontend" / "dist")
    return token


def bind_socket(
    preferred: Iterable[int] = PREFERRED_PORTS,
    make_socket: Callable[[], socket.socket] | None = None,
) -> socket.socket:
    """A listening-ready socket on 127.0.0.1: a preferred port if one is free, else any."""
    make_socket = make_socket or (lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    for port in [*preferred, 0]:
        sock = make_socket()
        try:
            sock.bind((HOST, port))
        except OSError:
            sock.close()
            continue
        return sock
    raise RuntimeError("No free port on 127.0.0.1")


def ready_line(port: int, token: str) -> str:
    return f"READY {port} {token}"


def watch_stdin(on_eof: Callable[[], None], stream=None) -> threading.Thread:
    """Call ``on_eof`` once ``stream`` (stdin) reaches end of file, from a daemon thread."""
    stream = sys.stdin if stream is None else stream

    def _wait() -> None:
        try:
            while stream.read(4096):
                pass
        except (OSError, ValueError):
            pass
        on_eof()

    thread = threading.Thread(target=_wait, name="parent-watch", daemon=True)
    thread.start()
    return thread


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    token = prepare_environment(os.environ, app_data_dir())  # type: ignore[arg-type]
    sock = bind_socket()
    port = sock.getsockname()[1]

    import uvicorn

    from resume_tailor.web.app import app

    class _Server(uvicorn.Server):
        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            await super().startup(sockets=sockets)
            if self.started:
                print(ready_line(port, token), flush=True)

    server = _Server(uvicorn.Config(app, log_level="warning", access_log=False))
    if "--exit-with-stdin" in args:

        def _parent_gone() -> None:
            server.should_exit = True

        watch_stdin(_parent_gone)
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
