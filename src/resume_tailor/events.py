"""Optional progress reporting for a tailoring run.

A run takes a minute or more — three or four model calls plus several render-and-measure
cycles — so a UI driving it needs to say more than "working". The pipeline emits named
stage events; the CLI ignores them and the web layer forwards them to the browser.

Deliberately one-way and side-effect free. A callback cannot influence the run, and every
emitting function keeps working unchanged when `on_event` is `None`, which is what keeps
this out of the way of the existing tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ProgressEvent:
    """One thing that happened, named so a UI can render it without parsing prose."""

    #: Coarse pipeline phase: "extract", "score", "rewrite", "expand", "render",
    #: "measure", "fit".
    stage: str

    #: Human-readable one-liner, safe to show directly.
    message: str

    #: Structured extras (page counts, iteration numbers, cache hits). Kept separate from
    #: `message` so the UI can drive progress bars off numbers rather than scrape text.
    detail: dict[str, Any] = field(default_factory=dict)


#: What a caller supplies to observe a run.
ProgressCallback = Callable[[ProgressEvent], None]


def emit(
    on_event: ProgressCallback | None, stage: str, message: str, **detail: Any
) -> None:
    """Send one event, doing nothing when no callback was supplied.

    Exceptions raised by the callback are allowed to propagate: a progress sink that
    throws is a bug in the caller, and swallowing it here would hide it during exactly
    the long-running operation the callback exists to make visible.
    """
    if on_event is not None:
        on_event(ProgressEvent(stage=stage, message=message, detail=detail))
