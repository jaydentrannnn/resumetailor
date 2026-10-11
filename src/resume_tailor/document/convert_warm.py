"""Conversions for live previews, on one thread that keeps its Word open between calls.

`convert.convert` quits Word after each call unless `keep_active` is set, and Word's
private instance belongs to the thread that started it (COM). A preview that follows
every change would pay Word's ~9s startup each time, so previews run here: one worker
thread whose instance stays open while previews keep coming and quits after
`IDLE_SECONDS` without one, and when the app shuts down. LibreOffice ignores
`keep_active`, so on Docker this is just a single-thread queue.
"""

from __future__ import annotations

import atexit
import queue
import threading
from concurrent.futures import Future
from pathlib import Path

from . import convert

IDLE_SECONDS = 90.0

_JOBS: queue.Queue = queue.Queue()
_STOP = object()
_START = threading.Lock()
_worker: threading.Thread | None = None


def _release() -> None:
    """Quit this (the worker) thread's Word, if it has one."""
    if getattr(convert._WORD, "app", None) is None:
        return
    import pythoncom  # noqa: PLC0415 - Windows only, and only with Word running

    convert._release_word(pythoncom)


def _loop() -> None:
    while True:
        try:
            job = _JOBS.get(timeout=IDLE_SECONDS)
        except queue.Empty:
            _release()  # idle: give the memory back until the next preview
            continue
        if job is _STOP:
            _release()
            return
        future, docx_path, pdf_path = job
        if not future.set_running_or_notify_cancel():
            continue
        try:
            future.set_result(convert.convert(docx_path, pdf_path, keep_active=True))
        except BaseException as exc:  # noqa: BLE001 - handed to the caller
            future.set_exception(exc)


def _stop() -> None:
    if _worker is not None and _worker.is_alive():
        _JOBS.put(_STOP)
        _worker.join(timeout=30)


def _ensure_worker() -> None:
    global _worker
    with _START:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="rt-preview-pdf", daemon=True)
            _worker.start()


def to_pdf(docx_path: Path, pdf_path: Path) -> Path:
    """Convert on the preview thread, keeping its Word warm for the next preview."""
    _ensure_worker()
    future: Future = Future()
    _JOBS.put((future, docx_path, pdf_path))
    return future.result()


# Before interpreter teardown, while the worker can still run: it quits its own Word
# (COM calls must come from the thread that owns the instance).
_register = getattr(threading, "_register_atexit", None)
if _register is not None:
    _register(_stop)
else:  # pragma: no cover - every supported Python has it
    atexit.register(_stop)
