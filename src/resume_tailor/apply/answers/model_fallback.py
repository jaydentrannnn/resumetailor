"""Heavy -> Light fallback for Fill's model calls.

Fill pins the Heavy task model (`ApplySettings.model_spec`). When Heavy's provider is at
its limit (a 429 or 5xx, or its quota marked used up in `infra.model_queue`), the rest of
that fill answers with the Light task model instead, saying so once in the progress log.
`pin` opens the block; `call` retries one model call under Light after Heavy fails.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from resume_tailor import config
from resume_tailor.infra import llm, model_queue

_ENDPOINT_DEFAULTS = {"anthropic": "https://api.anthropic.com"}


@dataclass
class Fallback:
    """One fill's routing: Heavy until it fails, then Light for the rest of the fill."""

    heavy: config.ModelSpec
    light: config.ModelSpec | None
    effort: str | None = None
    progress: Callable[[str], None] | None = None
    heavy_down: bool = False
    announced: bool = False

    def use_light(self, why: str) -> bool:
        """Switch to Light; False when there is no distinct Light model to switch to."""
        # A Vertex connection explicitly selects a billing project. Do not switch
        # into or out of that connection automatically when another provider fails.
        for spec in (self.heavy, self.light):
            if (
                isinstance(spec, dict)
                and (spec.get("origin") or spec.get("provider")) == "vertex_ai"
            ):
                return False
            if isinstance(spec, str) and spec.startswith("vertex_ai:"):
                return False
        if self.light is None or self.light == self.heavy:
            return False
        self.heavy_down = True
        if not self.announced and self.progress:
            self.announced = True
            self.progress(f"Heavy model {why}; answering with Light ({_model_name(self.light)})")
        return True


_ACTIVE: ContextVar[Fallback | None] = ContextVar("model_fallback", default=None)


def _model_name(spec: config.ModelSpec) -> str:
    if isinstance(spec, dict):
        return str(spec.get("model") or "")
    return config.parse_spec(spec)[1] or str(spec)


def endpoint(spec: config.ModelSpec) -> str:
    """The server URL `model_queue` keys ``spec``'s answer calls on."""
    with config.pinned(spec) as backends:
        backend = backends["answer"]
    return backend.base_url or _ENDPOINT_DEFAULTS.get(backend.provider, "")


def heavy_exhausted(spec: config.ModelSpec) -> bool:
    try:
        url = endpoint(spec)
    except Exception:  # noqa: BLE001 - an unresolvable spec fails later, where it is used
        return False
    return bool(url) and model_queue.queue.exhausted_for(url) > 0


@contextmanager
def pin(state: Fallback) -> Iterator[None]:
    """Pin Heavy, or Light once Heavy is down or its quota is used up."""
    if not state.heavy_down and heavy_exhausted(state.heavy):
        state.use_light("is at its quota limit")
    spec = state.light if state.heavy_down and state.light is not None else state.heavy
    token = _ACTIVE.set(state)
    try:
        with config.pinned(spec, effort=state.effort):
            yield
    finally:
        _ACTIVE.reset(token)


def _light_now() -> Fallback | None:
    """The routing to answer under Light now: Heavy went down inside the block that
    pinned it, so the block's own pin still names Heavy."""
    state = _ACTIVE.get()
    return state if state is not None and state.heavy_down and state.light else None


def call[T](fn: Callable[[], T]) -> T:
    """Run ``fn``; when Heavy is at its limit, run it once more under Light, and every
    later call of the fill under Light straight away."""
    if (down := _light_now()) is not None:
        with config.pinned(down.light, effort=down.effort):  # type: ignore[arg-type]
            return fn()
    try:
        return fn()
    except Exception as exc:
        state = _ACTIVE.get()
        status = llm.unavailable(exc)
        if state is None or state.heavy_down or status is None:
            raise
        if not state.use_light(f"is at its limit (HTTP {status})"):
            raise
        with config.pinned(state.light, effort=state.effort):  # type: ignore[arg-type]
            return fn()


async def acall[T](fn: Callable[[], Awaitable[T]]) -> T:
    """`call` for a coroutine-returning ``fn`` (the verified engine)."""
    if (down := _light_now()) is not None:
        with config.pinned(down.light, effort=down.effort):  # type: ignore[arg-type]
            return await fn()
    try:
        return await fn()
    except Exception as exc:
        state = _ACTIVE.get()
        status = llm.unavailable(exc)
        if state is None or state.heavy_down or status is None:
            raise
        if not state.use_light(f"is at its limit (HTTP {status})"):
            raise
        with config.pinned(state.light, effort=state.effort):  # type: ignore[arg-type]
            return await fn()


def active() -> Fallback | None:
    return _ACTIVE.get()


__all__ = ["Fallback", "active", "call", "endpoint", "heavy_exhausted", "pin"]
