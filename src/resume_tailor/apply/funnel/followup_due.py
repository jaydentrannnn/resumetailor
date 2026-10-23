"""When a sent application is due a follow-up, a thank-you, or a "no reply" mark.

Pure: reads a row's status history and outcome events (`outcomes`), never writes.

- **Follow-up**: sent at least `FOLLOW_UP_AFTER_DAYS` ago, no reply from the employer,
  fewer than `MAX_FOLLOW_UPS` follow-ups sent (the latest at least `FOLLOW_UP_GAP_DAYS`
  ago), and no date the employer gave (``employer_timeline``) still ahead. A timeline
  is a reply, but once its date passes in silence a follow-up is due again.
- **Thank-you**: an interview was completed, or its scheduled date has passed, and
  nothing was sent after it. An invitation alone does not mean an interview happened.
- **Stale**: sent at least `STALE_AFTER_DAYS` ago with no reply and nothing closing it.
  The Apply page offers these for a bulk "no reply" (``ghosted`` events, never
  ``rejected``), after the student confirms.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from . import outcomes, store_models

FOLLOW_UP_AFTER_DAYS = 10
FOLLOW_UP_GAP_DAYS = 7
MAX_FOLLOW_UPS = 2
STALE_AFTER_DAYS = 60

#: Statuses from before outcome events that mean the employer answered.
_LEGACY_REPLY = frozenset({"interview", "rejected"})

Due = Literal["follow_up", "thank_you"]


class FollowUpState(BaseModel):
    sent_on: str | None = None
    days_since_sent: int | None = None
    follow_ups_sent: int = 0
    #: What to offer now; None when nothing is due.
    due: Due | None = None
    stale: bool = False
    #: Why no follow-up is offered, for display when ``due`` is None.
    reason: str = ""


class DueRow(BaseModel):
    application_id: str
    company: str
    role: str
    sent_on: str
    days_since_sent: int
    due: Due | None = None
    stale: bool = False


class DueList(BaseModel):
    due: list[DueRow]
    stale: list[DueRow]


def _day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def today() -> date:
    """Today in UTC, the calendar send dates are read in (status history timestamps)."""
    return datetime.now(UTC).date()


def _when(event: store_models.OutcomeEvent) -> str:
    return event.occurred_on or event.recorded_at[:10]


def _deadline(event: store_models.OutcomeEvent) -> date | None:
    """An undated legacy timeline gets a week's grace from when it was recorded."""
    explicit = _day(event.occurred_on)
    if explicit is not None:
        return explicit
    recorded = _day(event.recorded_at)
    return recorded + timedelta(days=FOLLOW_UP_GAP_DAYS) if recorded is not None else None


def _interview_day(event: store_models.OutcomeEvent, today: date) -> date | None:
    if event.type == "interview_completed":
        day = _day(_when(event))
        return day if day is not None and day <= today else None
    if event.type == "interview_scheduled":
        day = _day(event.occurred_on)
        return day if day is not None and day < today else None
    return None


def _replied(app: store_models.Application, events: list[store_models.OutcomeEvent]) -> bool:
    if any(e.type in outcomes.RESPONSES and e.type != "employer_timeline" for e in events):
        return True
    return app.status in _LEGACY_REPLY or any(
        change.status in _LEGACY_REPLY for change in app.status_history
    )


def state(app: store_models.Application, today: date) -> FollowUpState:
    sent = outcomes.sent_on(app)
    sent_day = _day(sent) if sent else None
    if sent_day is None:
        return FollowUpState(reason="This application hasn't been sent.")
    events = sorted(outcomes.live_events(app), key=_when)
    days = (today - sent_day).days
    sent_notes = [e for e in events if e.type == "followup_sent"]
    result = FollowUpState(sent_on=sent, days_since_sent=days, follow_ups_sent=len(sent_notes))
    progress = outcomes.hiring_progress(app)
    interviews = [day for e in events if (day := _interview_day(e, today)) is not None]
    if interviews and progress.closed is None:
        last = max(interviews).isoformat()
        if not any(_when(e) >= last for e in sent_notes):
            result.due = "thank_you"
            return result
    replied = _replied(app, events)
    if progress.closed is not None:
        result.reason = f"Closed: {outcomes.STAGE_LABELS[progress.closed].lower()}."
        return result
    if replied:
        result.reason = "The employer has replied."
        return result
    timeline = [_deadline(e) for e in events if e.type == "employer_timeline"]
    ahead = [d for d in timeline if d is not None and d >= today]
    if ahead:
        result.reason = f"The employer said to expect news by {max(ahead).isoformat()}."
        return result
    result.stale = days >= STALE_AFTER_DAYS
    if len(sent_notes) >= MAX_FOLLOW_UPS:
        result.reason = f"{MAX_FOLLOW_UPS} follow-ups sent already."
    elif days < FOLLOW_UP_AFTER_DAYS:
        result.reason = f"Sent {days} day(s) ago; follow up after {FOLLOW_UP_AFTER_DAYS}."
    elif sent_notes and (
        today - (_day(_when(sent_notes[-1])) or today)
    ).days < FOLLOW_UP_GAP_DAYS:
        result.reason = f"Followed up less than {FOLLOW_UP_GAP_DAYS} days ago."
    else:
        result.due = "follow_up"
    return result


def due_list(rows: Iterable[store_models.Application], today: date) -> DueList:
    """Rows with something to send, and rows gone silent, oldest send first."""
    due: list[DueRow] = []
    stale: list[DueRow] = []
    for app in rows:
        found = state(app, today)
        if found.sent_on is None or not (found.due or found.stale):
            continue
        row = DueRow(
            application_id=app.source_job_id, company=app.company, role=app.role,
            sent_on=found.sent_on, days_since_sent=found.days_since_sent or 0,
            due=found.due, stale=found.stale,
        )
        if found.due:
            due.append(row)
        if found.stale:
            stale.append(row)
    due.sort(key=lambda r: r.sent_on)
    stale.sort(key=lambda r: r.sent_on)
    return DueList(due=due, stale=stale)
