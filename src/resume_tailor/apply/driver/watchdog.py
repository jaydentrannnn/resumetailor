"""Cut a fill whose browser call never returns, and say where it was stuck.

A fill's deadline is checked between steps, so it cannot interrupt a Playwright call
that never returns: ``page.evaluate`` and locator reads take no timeout. Magnite
(2026-10-07) blocked inside the Skills loop at 23:07:40 and held its worker until the
server restarted 13 minutes later, with nothing in the log to say which call it was.

`stall_guard` watches one fill from a side thread. Once the fill is ``grace_s`` past its
deadline it logs the fill thread's stack, then kills that fill's Playwright driver
process. The blocked call raises ("Connection closed while reading from the driver"),
the fill ends through its normal error path, and the tab stays open as it was: dropping
a CDP client never closes the browser or its pages.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: How far past its deadline a fill may run before it counts as stuck. The finish
#: (evidence screenshot, required-field check) legitimately runs after the deadline and
#: takes about 10s.
GRACE_S = 120.0
_POLL_S = 5.0
_OWN_CODE = f"{os.sep}resume_tailor{os.sep}"


@dataclass
class Stall:
    """What the guard saw when it fired; ``where`` is empty until then."""

    where: str = ""
    seconds_over: float = 0.0

    @property
    def fired(self) -> bool:
        return bool(self.where)

    def message(self) -> str:
        return (
            f"Fill stopped responding {int(self.seconds_over)}s past its deadline "
            f"(stuck in {self.where}); the tab was left as it is"
        )


def driver_pid(pw_browser: object) -> int | None:
    """The pid of the Playwright driver behind a sync ``Browser``; None if unknown."""
    try:
        pid = pw_browser._impl_obj._connection._transport._proc.pid  # type: ignore[attr-defined]  # noqa: SLF001
    except AttributeError:
        return None
    return pid if isinstance(pid, int) else None


def kill_driver(pid: int) -> None:
    """End one Playwright driver; every call waiting on it raises at once."""
    with contextlib.suppress(OSError):  # already gone
        os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows


def _where(frames: list[traceback.FrameSummary]) -> str:
    """The innermost frame in this package (the call that never returned)."""
    own = [frame for frame in frames if _OWN_CODE in frame.filename]
    frame = (own or frames or [None])[-1]
    if frame is None:
        return "unknown"
    return f"{os.path.basename(frame.filename)}:{frame.lineno} {frame.name}"


def _stack(thread_id: int) -> list[traceback.FrameSummary]:
    frame = sys._current_frames().get(thread_id)  # noqa: SLF001
    return list(traceback.extract_stack(frame)) if frame is not None else []


@contextmanager
def stall_guard(
    deadline: Callable[[], float],
    *,
    cut: Callable[[], None] | None,
    label: str,
    grace_s: float = GRACE_S,
    clock: Callable[[], float] = time.monotonic,
    poll_s: float = _POLL_S,
) -> Iterator[Stall]:
    """Watch the calling thread until the block exits; see the module docstring.

    ``deadline`` is read on every poll, so a fill that moves its deadline is followed.
    ``cut`` ends the fill's browser connection; without one the stack is still logged.
    """
    stall = Stall()
    owner = threading.get_ident()
    done = threading.Event()

    def watch() -> None:
        while not done.wait(poll_s):
            over = clock() - deadline()
            if over < grace_s:
                continue
            frames = _stack(owner)
            stall.seconds_over, stall.where = over, _where(frames)
            log.warning(
                "%s: fill stuck %ds past its deadline in %s; cutting its browser connection\n%s",
                label, int(over), stall.where, "".join(traceback.format_list(frames)),
            )
            if cut is not None:
                cut()
            return

    watcher = threading.Thread(target=watch, name=f"fill-watchdog-{label[:24]}", daemon=True)
    watcher.start()
    try:
        yield stall
    finally:
        done.set()
