"""Fill and Prepare slots shared by every Apply operation running at once.

A Fill can start on one batch while another batch is still being prepared, and two
batches of the same kind can run side by side. Each kind keeps its configured limit for
the whole app (`max_parallel_fills`, `max_concurrent_jobs`), split evenly between the
batches waiting for a slot: the next slot goes to the batch holding the fewest, then to
the one that has waited longest. A batch with nothing left to do stops asking, so the
others take its share and no slot sits idle (2026-10-23).

One fill per Workday site (`fill_hosts`) holds across batches too: `WORKDAY_BUSY` is the
set of sites being filled right now, guarded by `SITE_LOCK`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Literal

Kind = Literal["prepare", "fill"]

#: How often a waiting worker looks at its stop condition (Pause/Cancel).
_POLL_S = 0.25


class SlotPool:
    """Counting slots with a fair share per owner (an operation id)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._cond = threading.Condition()
        self._held: dict[str, int] = {}
        #: owner -> when each of its waiting workers started waiting.
        self._waiting: dict[str, list[float]] = {}

    def acquire(self, owner: str, capacity: int, should_stop: Callable[[], bool]) -> bool:
        """Wait for a slot; False when ``should_stop`` turned true first.

        ``capacity`` is the kind's limit as the asking operation captured it; the newest
        asker's value is the one in force."""
        with self._cond:
            started = self._clock()
            self._waiting.setdefault(owner, []).append(started)
            try:
                while True:
                    if should_stop():
                        return False
                    if self._in_use() < max(1, capacity) and self._next() == owner:
                        self._held[owner] = self._held.get(owner, 0) + 1
                        return True
                    self._cond.wait(_POLL_S)
            finally:
                waits = self._waiting[owner]
                waits.remove(started)
                if not waits:
                    del self._waiting[owner]
                self._cond.notify_all()

    def release(self, owner: str) -> None:
        with self._cond:
            left = self._held.get(owner, 0) - 1
            if left > 0:
                self._held[owner] = left
            else:
                self._held.pop(owner, None)
            self._cond.notify_all()

    def held(self, owner: str) -> int:
        with self._cond:
            return self._held.get(owner, 0)

    def _in_use(self) -> int:
        return sum(self._held.values())

    def _next(self) -> str:
        """The waiting owner holding the fewest slots; ties go to the longest wait."""
        return min(
            self._waiting,
            key=lambda owner: (self._held.get(owner, 0), min(self._waiting[owner])),
        )


_POOLS: dict[str, SlotPool] = {"prepare": SlotPool(), "fill": SlotPool()}


def pool(kind: Kind) -> SlotPool:
    return _POOLS[kind]


SITE_LOCK = threading.Lock()
#: Workday sites a fill is working on now, across every Fill batch.
WORKDAY_BUSY: set[str] = set()
