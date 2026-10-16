"""Eval-only pipeline variants, switched per task (context variable) or per process
(environment), never by editing production code.

* `CLAUSE`: one extra rule in `rewrite_prompts._system()`, so it reaches every call
  that prompt serves (first draft, factual retry, widow repair, merge), exactly as a
  production edit would.

In-process arms (`arms.run` threads) use `clause()`; an end-to-end worker process sets
`CLAUSE_ENV` before `install()`. (The cosmetic-polish switch went with the polish:
`stages.cosmetic_polish` replays it on frozen drafts.)
"""

from __future__ import annotations

import contextvars
import os
from collections.abc import Iterator
from contextlib import contextmanager

#: The narrow anti-invention clause under test (experiment E2).
CLAUSE = (
    "- Do not add specifics the bullet never states (audience, frequency, setting, error "
    "types, scope), even plausible ones.\n"
)
CLAUSE_ENV = "RT_EVAL_CLAUSE"
#: Every `_system()` variant ends with this line; the clause goes just above it.
_RETURN_MARKER = "Return one entry per input item"

_CLAUSE_ON: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "eval_clause", default=None)
_installed = False


def with_clause(system: str) -> str:
    """`system` with `CLAUSE` added as the last rule, before the return shape."""
    i = system.rfind(_RETURN_MARKER)
    if i < 0:
        return system.rstrip("\n") + "\n" + CLAUSE
    head = system[:i].rstrip("\n")
    return f"{head}\n{CLAUSE}\n{system[i:]}"


def _clause_active() -> bool:
    value = _CLAUSE_ON.get()
    return value if value is not None else os.environ.get(CLAUSE_ENV) == "1"


def install() -> None:
    """Wrap the prompt seam once per process; with the clause off it is a no-op."""
    global _installed
    if _installed:
        return
    from resume_tailor.pipeline import rewrite_prompts

    original_system = rewrite_prompts._system

    def system() -> str:
        text = original_system()
        return with_clause(text) if _clause_active() else text

    rewrite_prompts._system = system
    _installed = True


@contextmanager
def clause(on: bool = True) -> Iterator[None]:
    install()
    token = _CLAUSE_ON.set(on)
    try:
        yield
    finally:
        _CLAUSE_ON.reset(token)
