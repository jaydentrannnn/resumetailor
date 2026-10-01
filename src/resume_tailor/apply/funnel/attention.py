"""Application-specific outcomes shown in Apply run progress."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

AttentionKind = Literal["failed", "needs_input", "ready_for_review", "blocked"]


class AttentionItem(BaseModel):
    application_id: str
    label: str
    kind: AttentionKind
    message: str
    at: str


def record(
    items: list[AttentionItem], application_id: str, label: str,
    kind: AttentionKind, message: str,
) -> None:
    """Replace this application's prior outcome with its latest one."""
    items[:] = [item for item in items if item.application_id != application_id]
    items.append(AttentionItem(
        application_id=application_id, label=label, kind=kind, message=message,
        at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    ))


def remove(items: list[AttentionItem], application_id: str) -> None:
    items[:] = [item for item in items if item.application_id != application_id]
