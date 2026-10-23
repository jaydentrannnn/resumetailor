"""The Tracker board (`apply/funnel/tracker.py`): Done applications by hiring stage.

A move records outcome events in one atomic `store.update`; undo reverses exactly what
a move changed. Pending email updates ride on their cards; the rest wait in the tray
(accepted and dismissed through `routes/mail_updates.py`).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor.apply.funnel import mail_inbox, mail_sync, tracker
from resume_tailor.apply.funnel import store as apply_store

from .mail_updates import ProposalView, _view

router = APIRouter()


class BoardCard(tracker.TrackerCard):
    proposals: list[ProposalView] = Field(default_factory=list)


class MailStatus(BaseModel):
    """The app's own mailbox check, for the Tracker's email line."""

    configured: bool = False
    username: str = ""
    last_checked: str = ""
    last_error: str = ""
    running: bool = False


class TrackerBoard(BaseModel):
    cards: list[BoardCard]
    #: Pending email updates with no card on the board: unmatched, or about an
    #: application that is not in Done.
    unmatched: list[ProposalView]
    counts: dict[str, int]
    last_synced: str = ""
    #: Rejections recorded from email without a click, last 14 days (each can be undone).
    auto_closed: list[ProposalView] = Field(default_factory=list)
    mail: MailStatus


class MoveRequest(BaseModel):
    column: tracker.Column
    reason: tracker.Reason | None = None


class MoveResult(BaseModel):
    card: tracker.TrackerCard
    receipt: tracker.Receipt


class UndoRequest(BaseModel):
    receipt: tracker.Receipt


@router.get("/api/tracker", response_model=TrackerBoard)
def get_board() -> TrackerBoard:
    rows = list(apply_store.rows_view().values())
    by_id = {app.source_job_id: app for app in rows}
    cards = [BoardCard(**c.model_dump()) for c in tracker.board(rows)]
    on_board = {c.id: c for c in cards}
    unmatched: list[ProposalView] = []
    for proposal in mail_inbox.pending():
        view = _view(proposal, by_id)
        holder = on_board.get(proposal.app_id or "")
        (holder.proposals if holder else unmatched).append(view)
    counts = {column: 0 for column in tracker.COLUMNS}
    for c in cards:
        counts[c.column] += 1
    settings = mail_sync.load()
    mail = MailStatus(
        configured=settings.imap is not None,
        username=settings.imap.username if settings.imap else "",
        last_checked=settings.last_checked, last_error=settings.last_error,
        running=mail_sync.running(),
    )
    return TrackerBoard(cards=cards, unmatched=unmatched, counts=counts,
                        last_synced=mail_inbox.load().last_synced,
                        auto_closed=[_view(p, by_id) for p in mail_inbox.recent_auto()],
                        mail=mail)


def _write(source_job_id: str, change) -> tuple[tracker.TrackerCard, object]:
    """Run ``change(app)`` on a Done row in one store write; returns its card and result."""
    out: list[object] = []

    def mutate(app) -> None:
        if not app.archived_at:
            raise ValueError("That application is not in Done.")
        out.append(change(app))

    try:
        app = apply_store.update(source_job_id, mutate)
    except apply_store.StaleApplication as exc:
        raise HTTPException(status_code=404, detail="That application no longer exists.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return tracker.card(app), out[0]


@router.post("/api/tracker/{source_job_id}/move", response_model=MoveResult)
def move_card(source_job_id: str, body: MoveRequest) -> MoveResult:
    """Move a card to another column by recording (or voiding) outcome events."""
    card, receipt = _write(source_job_id, lambda app: tracker.move(
        app, body.column, reason=body.reason, today=date.today()))
    return MoveResult(card=card, receipt=receipt)


@router.post("/api/tracker/{source_job_id}/undo", response_model=tracker.TrackerCard)
def undo_move(source_job_id: str, body: UndoRequest) -> tracker.TrackerCard:
    """Reverse one move, as long as the card has not changed since."""
    card, _ = _write(source_job_id, lambda app: tracker.undo(app, body.receipt))
    return card
