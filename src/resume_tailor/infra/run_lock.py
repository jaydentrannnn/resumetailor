"""One lock per run folder, so the files of one revision change together.

A run's documents and the files that describe them (``tailored.pdf`` and
``bullets.json``; ``cover.pdf`` and ``cover.json``) are rewritten by several paths: a
bullet re-render, a regenerated cover letter. A fill pins them (`fill_files.pin`) while
those may run. Each such multi-file update holds `of(run_dir)`, and so does the pin, so
a pinned resume and the bullets kept with it are always one revision. Reentrant: the
cover letter written during a fill holds it from the draft through its pin. In-process
only (the app is one process).
"""

from __future__ import annotations

import threading
from pathlib import Path

_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


def of(run_dir: Path) -> threading.RLock:
    """The lock of run folder ``run_dir``."""
    key = str(Path(run_dir).resolve()).casefold()
    with _GUARD:
        return _LOCKS.setdefault(key, threading.RLock())
