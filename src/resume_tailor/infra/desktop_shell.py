"""Window requests the web UI makes of the desktop shell, relayed by the server.

The web UI runs from a 127.0.0.1 origin and gets no Tauri IPC (see
`desktop/src-tauri/capabilities/default.json`), so — like updates (`desktop_update`) —
it asks the server, and the server asks the shell over its pipes:

- stdout, server → shell: ``SHELL save {"id", "name", "ext"}`` opens the native Save
  dialog; ``SHELL title {"title"}`` sets the window title; ``SHELL zoom {"scale"}``
  sets the webview zoom factor.
- stdin, shell → server: ``DIALOG {"id", "path"}`` — the chosen path, or ``null`` when
  the person cancelled.

The page never names a path: the person picks it in the native dialog, and the server
writes the bytes there.

``ENABLED`` is set by `desktop_main` only when the shell launched the server.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import uuid

from resume_tailor.infra import desktop_update

_log = logging.getLogger(__name__)

#: True only in the desktop build, where a shell is on the other end of the pipes.
ENABLED = False
#: How long a Save dialog may stay open before the request gives up.
DIALOG_TIMEOUT_SECONDS = 30 * 60.0

_lock = threading.Lock()
_pending: dict[str, tuple[threading.Event, list[str | None]]] = {}


class ShellUnavailable(RuntimeError):
    """No desktop shell on the other end (browser build, or a dev server)."""


def ask_save_path(name: str, ext: str, timeout: float = DIALOG_TIMEOUT_SECONDS) -> str | None:
    """Open the shell's Save dialog and wait for the chosen path (None = cancelled)."""
    if not ENABLED:
        raise ShellUnavailable("Save dialogs are only available in the desktop app.")
    request_id = uuid.uuid4().hex
    done = threading.Event()
    slot: list[str | None] = [None]
    with _lock:
        _pending[request_id] = (done, slot)
    try:
        payload = {"id": request_id, "name": name, "ext": ext.lstrip(".").lower()}
        try:
            desktop_update.write_line(f"SHELL save {json.dumps(payload)}")
        except desktop_update.ShellGone as exc:
            raise ShellUnavailable(str(exc)) from exc
        if not done.wait(timeout):
            return None
        return slot[0]
    finally:
        with _lock:
            _pending.pop(request_id, None)


def set_title(title: str) -> None:
    """Set the window title; a no-op outside the desktop app or once the shell is gone."""
    if ENABLED:
        with contextlib.suppress(desktop_update.ShellGone):
            desktop_update.write_line(f"SHELL title {json.dumps({'title': title})}")


def set_zoom(scale: float) -> None:
    """Set the webview zoom factor; a no-op outside the desktop app or once the shell is gone."""
    if ENABLED:
        with contextlib.suppress(desktop_update.ShellGone):
            desktop_update.write_line(f"SHELL zoom {json.dumps({'scale': scale})}")


def receive(line: str) -> None:
    """Handle one line from the shell; anything that is not ``DIALOG {...}`` is ignored."""
    if not line.startswith("DIALOG "):
        return
    try:
        event = json.loads(line[len("DIALOG "):])
    except json.JSONDecodeError:
        _log.warning("unreadable dialog result from the shell")
        return
    if not isinstance(event, dict):
        return
    path = event.get("path")
    with _lock:
        waiter = _pending.get(str(event.get("id")))
    if waiter is None:
        return
    done, slot = waiter
    slot[0] = path if isinstance(path, str) and path else None
    done.set()
