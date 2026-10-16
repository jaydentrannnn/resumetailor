"""Eval-only pipeline variants, switched per task (context variable) or per process
(environment), never by editing production code.

* `CLAUSE`: one extra rule in `rewrite_prompts._system()`, so it reaches every call
  that prompt serves (first draft, factual retry, polish, merge), exactly as a
  production edit would.
* polish effort: `rewrite.cosmetic_polish` at another effort, or skipped ("none").

In-process arms (`arms.run` threads) use `clause()` / `polish_effort()`; an end-to-end
worker process sets `CLAUSE_ENV` / `POLISH_ENV` before `install()`.
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
POLISH_ENV = "RT_EVAL_POLISH_EFFORT"
#: Every `_system()` variant ends with this line; the clause goes just above it.
_RETURN_MARKER = "Return one entry per input item"

_CLAUSE_ON: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "eval_clause", default=None)
_POLISH: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "eval_polish_effort", default=None)
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


def _polish_effort() -> str | None:
    return _POLISH.get() or os.environ.get(POLISH_ENV) or None


def install() -> None:
    """Wrap the two seams once per process; with nothing switched on, both are no-ops."""
    global _installed
    if _installed:
        return
    from resume_tailor.pipeline import rewrite, rewrite_prompts

    original_system, original_polish = rewrite_prompts._system, rewrite.cosmetic_polish

    def system() -> str:
        text = original_system()
        return with_clause(text) if _clause_active() else text

    def cosmetic_polish(out, *args, **kwargs):
        effort = _polish_effort()
        if effort == "none":
            return dict(out), 0, 0, {}
        if effort is not None:
            kwargs["effort"] = effort
        return original_polish(out, *args, **kwargs)

    rewrite_prompts._system = system
    rewrite.cosmetic_polish = cosmetic_polish
    _installed = True


@contextmanager
def clause(on: bool = True) -> Iterator[None]:
    install()
    token = _CLAUSE_ON.set(on)
    try:
        yield
    finally:
        _CLAUSE_ON.reset(token)


@contextmanager
def polish_effort(effort: str | None) -> Iterator[None]:
    install()
    token = _POLISH.set(effort)
    try:
        yield
    finally:
        _POLISH.reset(token)
