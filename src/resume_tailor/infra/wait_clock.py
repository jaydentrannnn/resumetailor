"""Time a fill spent queued for a shared resource: a model slot or the PDF converter.

Tailoring and Fill share the model endpoints (`model_queue`) and the one PDF converter
(`document/convert`). A fill's deadline is for its own work, so the time it waited behind
other jobs is given back (audit #28): `track()` opens a tally for the current context
(threads started with `config.submit_in_context` share it), each wait runs inside
`waiting()`, and overlapping waits count once. With no tally open nothing is recorded.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import ContextManager


class Tally:
    """Seconds spent waiting, counting overlapping waits once."""

    def __init__(self, announce: Callable[[str], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._open = 0
        self._since = 0.0
        self._total = 0.0
        self.announce = announce

    @contextmanager
    def waiting(self) -> Iterator[None]:
        with self._lock:
            if self._open == 0:
                self._since = time.monotonic()
            self._open += 1
        try:
            yield
        finally:
            with self._lock:
                self._open -= 1
                if self._open == 0:
                    self._total += time.monotonic() - self._since

    @property
    def total(self) -> float:
        with self._lock:
            running = time.monotonic() - self._since if self._open else 0.0
            return self._total + running


_TALLY: ContextVar[Tally | None] = ContextVar("wait_clock_tally", default=None)


@contextmanager
def track(announce: Callable[[str], None] | None = None) -> Iterator[Tally]:
    """Tally the waits in this context; ``announce`` hears what is being waited for."""
    tally = Tally(announce)
    token = _TALLY.set(tally)
    try:
        yield tally
    finally:
        _TALLY.reset(token)


def waiting(what: str = "") -> ContextManager[None]:
    """Count the enclosed block as waiting, saying ``what`` for when one is given."""
    tally = _TALLY.get()
    if tally is None:
        return nullcontext()
    if what and tally.announce is not None:
        tally.announce(what)
    return tally.waiting()
