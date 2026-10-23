"""The Tracker board: Done applications in columns by hiring stage, moved by hand.

A card's column is derived from its outcome events (`outcomes.hiring_progress`), never
stored. Moving a card records events: forward adds the column's step, back voids the
events above the target, Closed adds the reason. Nothing is deleted: a voided event is
kept, and `undo` re-adds copies of what a move voided. Pure; the route runs `move` and
`undo` inside one `store.update`.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from . import outcomes, store_models

Column = Literal["not_sent", "applied", "assessment", "interview", "offer", "closed"]
Reason = Literal["rejected", "ghosted", "withdrawn", "offer_declined"]

COLUMNS: tuple[Column, ...] = (
    "not_sent", "applied", "assessment", "interview", "offer", "closed",
)
#: Step columns in order; `hired` shares the Offer column.
_RANK: dict[str, int] = {"applied": 0, "assessment": 1, "interview": 2, "offer": 3, "hired": 4}
#: The event a forward move records for each step column.
_STEP_EVENT: dict[str, store_models.OutcomeType] = {
    "assessment": "assessment", "interview": "interview_invited", "offer": "offer",
}
_NOTE = "Moved on the tracker"
_NOT_SENT_LABELS = {"screened_out": "Screened out", "skipped": "Skipped"}


class Receipt(BaseModel):
    """What one move changed, so `undo` can reverse exactly that."""

    added: list[str] = Field(default_factory=list)
    voided: list[str] = Field(default_factory=list)


class TrackerCard(BaseModel):
    id: str
    company: str
    role: str
    location: str = ""
    source: str = ""
    column: Column
    #: The hiring label ("Interviewing", "Rejected"), or why it was never sent.
    label: str
    #: For a closed card, the furthest stage it reached ("Interviewing").
    reached: str = ""
    closed: str | None = None
    stage: str | None = None
    stage_dates: dict[str, str] = Field(default_factory=dict)
    sent_on: str | None = None
    last_update: str = ""


def column_of(app: store_models.Application) -> Column:
    progress = outcomes.hiring_progress(app)
    if progress.stage is None:
        return "not_sent"
    if progress.closed is not None:
        return "closed"
    return "offer" if progress.stage == "hired" else progress.stage


def _when(event: store_models.OutcomeEvent) -> str:
    return event.occurred_on or event.recorded_at[:10]


def _open_closings(app: store_models.Application) -> list[store_models.OutcomeEvent]:
    """Live closing events after the last live step: the ones keeping the card closed."""
    live = sorted(enumerate(outcomes.live_events(app)), key=lambda item: (_when(item[1]), item[0]))
    ordered = [event for _index, event in live]
    last_step = max(
        (i for i, e in enumerate(ordered)
         if e.type in outcomes._EVENT_STAGE and e.type not in outcomes.CLOSING),
        default=-1,
    )
    return [e for e in ordered[last_step + 1:] if e.type in outcomes.CLOSING]


def _void(app: store_models.Application, events, receipt: Receipt) -> None:
    for event in events:
        outcomes.void_event(app, event.id)
        receipt.voided.append(event.id)


def _add(app, kind, today: date, receipt: Receipt) -> None:
    event = outcomes.add_event(app, kind, occurred_on=today.isoformat(), note=_NOTE)
    receipt.added.append(event.id)


def move(
    app: store_models.Application, target: Column, *, reason: Reason | None = None,
    today: date,
) -> Receipt:
    """Record the events that put ``app`` in ``target``.

    Raises:
        ValueError: Not sent either way, a missing or impossible reason, or a stage
            that only an older status mark holds (it cannot be voided here).
    """
    current = column_of(app)
    progress = outcomes.hiring_progress(app)
    receipt = Receipt()
    if "not_sent" in (current, target):
        raise ValueError("This application was never sent; restore it on the Apply page first")
    if target == "closed":
        if reason is None:
            raise ValueError("Say why it closed")
        if reason == "offer_declined" and progress.stage not in ("offer", "hired"):
            raise ValueError("Only an application with an offer can have it declined")
        if current == "closed":
            if progress.closed == reason:
                return receipt
            _void(app, _open_closings(app), receipt)
        _add(app, reason, today, receipt)
    elif target != current:
        if current == "closed":
            _void(app, _open_closings(app), receipt)
        above = [e for e in outcomes.live_events(app)
                 if _RANK.get(outcomes._EVENT_STAGE.get(e.type, ""), -1) > _RANK[target]]
        _void(app, above, receipt)
        if _RANK[outcomes.hiring_progress(app).stage or "applied"] < _RANK[target]:
            _add(app, _STEP_EVENT[target], today, receipt)
    if column_of(app) != target:
        raise ValueError(
            "This stage comes from an older status mark; change it in the Outcome tab"
        )
    return receipt


def undo(app: store_models.Application, receipt: Receipt) -> None:
    """Reverse one move: void what it added, re-add copies of what it voided.

    Raises:
        ValueError: The card changed since (an added event is gone, or a voided one
            was already brought back).
    """
    by_id = {event.id: event for event in app.outcome_events}
    added = [by_id.get(event_id) for event_id in receipt.added]
    voided = [by_id.get(event_id) for event_id in receipt.voided]
    replaced = {event.replaces for event in outcomes.live_events(app)}
    if any(e is None or e.voided_at is not None for e in added) or any(
        e is None or e.voided_at is None or e.id in replaced for e in voided
    ):
        raise ValueError("This card changed since; use the Outcome tab")
    for event in added:
        outcomes.void_event(app, event.id)
    for event in voided:
        # The original stays voided; a copy dated as it was becomes the live one.
        outcomes.add_event(app, event.type, occurred_on=_when(event), note=event.note,
                           source=event.source, replaces=event.id)


def _last_update(app: store_models.Application, sent: str | None) -> str:
    dates = [_when(event) for event in outcomes.live_events(app)]
    dates += [d for d in (sent, (app.archived_at or "")[:10]) if d]
    return max(dates, default="")


def card(app: store_models.Application) -> TrackerCard:
    progress = outcomes.hiring_progress(app)
    column = column_of(app)
    sent = outcomes.sent_on(app)
    not_sent = _NOT_SENT_LABELS.get(app.status, "Archived")
    label = not_sent if column == "not_sent" else progress.label
    # "Reached Applied" says nothing: only a stage past applied is worth naming.
    reached = ""
    if column == "closed" and progress.stage not in (None, "applied"):
        reached = outcomes.STAGE_LABELS[progress.stage]
    return TrackerCard(
        id=app.source_job_id, company=app.company, role=app.role, location=app.location,
        source=app.source, column=column, label=label, reached=reached,
        closed=progress.closed, stage=progress.stage, stage_dates=progress.stage_dates,
        sent_on=sent, last_update=_last_update(app, sent),
    )


def board(apps: list[store_models.Application]) -> list[TrackerCard]:
    """Every Done (archived) application as a card, most recent update first."""
    cards = [card(app) for app in apps if app.archived_at]
    return sorted(cards, key=lambda c: (c.last_update, c.company.casefold()), reverse=True)
