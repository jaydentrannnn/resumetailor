"""What happened after an application went out, and how far it got.

Outcome events (`store_models.OutcomeEvent`) are facts the student records: an
assessment, an interview, an offer, a rejection, silence. They can be recorded on an
archived (Done) row, since "submitted" archives it. Nothing is deleted: a correction
adds a new event that replaces the old one, and the old one is kept, voided.

`hiring_progress` derives the row's hiring stage from the live events plus its legacy
statuses (``interview``, ``rejected``, ``ghosted`` set before events existed), so no
stored row is rewritten. ``stage`` is the furthest step ever reached; ``closed`` is
the latest closing outcome, cleared by a later step (an interview after "ghosted").
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from . import store_models

Stage = Literal["applied", "assessment", "interview", "offer", "hired"]
Closed = Literal["rejected", "withdrawn", "ghosted", "offer_declined"]

STAGES: tuple[Stage, ...] = ("applied", "assessment", "interview", "offer", "hired")
_RANK = {stage: rank for rank, stage in enumerate(STAGES)}
_EVENT_STAGE: dict[str, Stage] = {
    "assessment": "assessment",
    "interview_invited": "interview",
    "interview_scheduled": "interview",
    "interview_completed": "interview",
    "offer": "offer",
    "offer_declined": "offer",
    "hired": "hired",
}
CLOSING: frozenset[str] = frozenset({"rejected", "withdrawn", "ghosted", "offer_declined"})
#: Events that mean the employer replied (silence and the student's own steps do not).
RESPONSES: frozenset[str] = frozenset(
    {
        "assessment", "interview_invited", "interview_scheduled", "interview_completed",
        "offer", "hired", "offer_declined", "rejected", "employer_timeline",
    }
)
#: Statuses that mean the application went out (an unconfirmed submit included: the
#: submit was clicked, only the confirmation page was not seen).
SENT = frozenset({"submitted", "submit_unconfirmed", "interview", "rejected", "ghosted"})
#: Legacy statuses read as events.
_LEGACY = {"interview": "interview_invited", "rejected": "rejected", "ghosted": "ghosted"}

STAGE_LABELS: dict[str, str] = {
    "applied": "Applied",
    "assessment": "Assessment",
    "interview": "Interviewing",
    "offer": "Offer",
    "hired": "Hired",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "ghosted": "No reply",
    "offer_declined": "Offer declined",
}


class HiringProgress(BaseModel):
    #: The furthest step reached; None when the application was never sent.
    stage: Stage | None = None
    closed: Closed | None = None
    responded: bool = False
    #: Step -> the first date it was reached (ISO date).
    stage_dates: dict[str, str] = Field(default_factory=dict)
    label: str = ""


def live_events(app: store_models.Application) -> list[store_models.OutcomeEvent]:
    return [event for event in app.outcome_events if event.voided_at is None]


def _when(event: store_models.OutcomeEvent) -> str:
    return event.occurred_on or event.recorded_at[:10]


def _timeline(app: store_models.Application) -> list[tuple[str, str]]:
    """``(date, event type)`` for live events and legacy statuses, oldest first."""
    items = [(_when(event), event.type) for event in live_events(app)]
    items += [
        (change.at[:10], _LEGACY[change.status])
        for change in app.status_history
        if change.status in _LEGACY
    ]
    if app.status in _LEGACY and not any(c.status == app.status for c in app.status_history):
        items.append(((app.discovered_at or "")[:10], _LEGACY[app.status]))
    return sorted(items, key=lambda item: item[0])


def sent_on(app: store_models.Application) -> str | None:
    """The date the application first went out (ISO date), or None."""
    for change in app.status_history:
        if change.status in SENT:
            return change.at[:10]
    if app.status in SENT or app.outcome_events:
        return (app.discovered_at or "")[:10] or None
    return None


def hiring_progress(app: store_models.Application) -> HiringProgress:
    sent = sent_on(app)
    timeline = _timeline(app)
    if sent is None and not timeline:
        return HiringProgress()
    progress = HiringProgress(stage="applied")
    if sent:
        progress.stage_dates["applied"] = sent
    for when, kind in timeline:
        step = _EVENT_STAGE.get(kind)
        if step is not None:
            if _RANK[step] > _RANK[progress.stage or "applied"]:
                progress.stage = step
            progress.stage_dates.setdefault(step, when)
        if kind in CLOSING:
            progress.closed = kind  # type: ignore[assignment]
        elif step is not None:
            progress.closed = None
        progress.responded = progress.responded or kind in RESPONSES
    progress.label = STAGE_LABELS[progress.closed or progress.stage or "applied"]
    return progress


def _check_date(occurred_on: str | None) -> str | None:
    if not occurred_on:
        return None
    return date.fromisoformat(occurred_on).isoformat()  # ValueError on a bad date


def add_event(
    app: store_models.Application,
    type: store_models.OutcomeType,
    *,
    occurred_on: str | None = None,
    note: str = "",
    source: Literal["manual", "mcp", "monitor"] = "manual",
    replaces: str | None = None,
) -> store_models.OutcomeEvent:
    """Append one event. Raises ValueError for a malformed date."""
    event = store_models.OutcomeEvent(
        id=uuid.uuid4().hex[:12],
        type=type,
        occurred_on=_check_date(occurred_on),
        recorded_at=store_models._now_iso(),
        source=source,
        note=note.strip(),
        replaces=replaces,
    )
    app.outcome_events.append(event)
    return event


def _find(app: store_models.Application, event_id: str) -> store_models.OutcomeEvent:
    for event in app.outcome_events:
        if event.id == event_id:
            if event.voided_at is not None:
                raise ValueError("That event was already corrected or removed")
            return event
    raise KeyError(event_id)


def void_event(app: store_models.Application, event_id: str) -> store_models.OutcomeEvent:
    """Mark an event as removed; it stays in the record."""
    event = _find(app, event_id)
    event.voided_at = store_models._now_iso()
    return event


def correct_event(
    app: store_models.Application,
    event_id: str,
    *,
    type: store_models.OutcomeType | None = None,
    occurred_on: str | None = None,
    note: str | None = None,
) -> store_models.OutcomeEvent:
    """Replace an event with a corrected copy; the original is kept, voided."""
    old = _find(app, event_id)
    new = add_event(
        app,
        type or old.type,
        occurred_on=old.occurred_on if occurred_on is None else occurred_on,
        note=old.note if note is None else note,
        source=old.source,
        replaces=old.id,
    )
    old.voided_at = new.recorded_at
    return new
