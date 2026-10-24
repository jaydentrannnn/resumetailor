"""Proposals read from job emails, waiting for the student to accept or dismiss them.

Two paths post job emails here: Claude Desktop, reading Gmail through its own connector
(`web/routes/mail_updates.py`), and the app's own read-only IMAP check (`mail_imap`,
`mail_sync`). Each email becomes at most one proposal: an outcome event (or "sent",
confirming an application) for the application `mail_signals.match` found, or an unclear
one the student assigns. Nothing reaches an application until the student accepts it,
with one exception the student switches on: `auto_close` records the rejections
`mail_signals.confident` is sure of, and `undo_auto` takes one back.

The inbox is one JSON file beside the profile's application registry. Every message id
seen is remembered, so posting the same emails again adds nothing. Only a short,
cleaned excerpt of each email is kept.
"""

from __future__ import annotations

import contextlib
import hashlib
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.infra import atomic
from resume_tailor.pipeline import posting_guard

from . import mail_signals, outcomes, store, store_models

#: Characters of an email kept with its proposal.
EXCERPT_CHARS = 500
#: Days back the first search looks, before any sync has been recorded.
FIRST_LOOKBACK_DAYS = 30
#: Most messages one post may carry.
MAX_MESSAGES = 50

State = Literal["pending", "accepted", "dismissed"]
_LOCK = threading.Lock()


class Proposal(BaseModel):
    id: str
    message_id: str
    received_on: str | None = None
    sender: str = ""
    from_domain: str = ""
    subject: str = ""
    excerpt: str = ""
    signal: mail_signals.Signal | None = None
    app_id: str | None = None
    candidates: list[str] = Field(default_factory=list)
    reason: str = ""
    #: Why this needs a second look (it contradicts what is recorded); "" when it fits.
    flag: str = ""
    state: State = "pending"
    created_at: str = ""
    decided_at: str = ""
    #: A rejection sure enough to record without asking (`mail_signals.confident`).
    confident: bool = False
    #: Recorded by `auto_close`, not by the student; `event_id` is the event it added.
    auto: bool = False
    event_id: str = ""


class Inbox(BaseModel):
    version: int = 1
    last_synced: str = ""
    seen: list[str] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)


class IncomingMail(BaseModel):
    message_id: str = Field(min_length=1, max_length=300)
    sender: str = Field(default="", max_length=300)
    subject: str = Field(default="", max_length=500)
    date: str = Field(default="", max_length=100)
    body: str = Field(default="", max_length=4000)


class IngestResult(BaseModel):
    matched: int = 0
    unclear: int = 0
    ignored: int = 0
    already_seen: int = 0
    #: Confident rejections `auto_close` recorded.
    closed: int = 0


def path() -> Path:
    return config.APPLICATIONS_PATH.parent / "mail_inbox.json"


def load() -> Inbox:
    return atomic.read_cached(path(), Inbox) or Inbox()


def _save(inbox: Inbox) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(target, inbox.model_dump_json(indent=2) + "\n")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _proposal_id(message_id: str) -> str:
    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:16]


def _excerpt(body: str) -> str:
    text, _found = posting_guard.guard(body)
    text = " ".join(text.split())
    return text[:EXCERPT_CHARS] + ("…" if len(text) > EXCERPT_CHARS else "")


def search_since(inbox: Inbox | None = None, *, today: date | None = None) -> str:
    """The date (ISO) the next mail search starts from: the last sync, else 30 days back."""
    inbox = inbox or load()
    if inbox.last_synced:
        return inbox.last_synced[:10]
    return ((today or datetime.now(UTC).date()) - timedelta(days=FIRST_LOOKBACK_DAYS)).isoformat()


def ingest(
    messages: list[IncomingMail], apps: list[store_models.Application], *,
    require_match: bool = False,
) -> IngestResult:
    """Turn new job emails into pending proposals; returns what happened to each.

    ``require_match`` (the mailbox check, which reads more than hiring mail) ignores an
    email that matched no application unless a hiring system sent it: an "offer" from a
    shop is not news about an application. It also ignores every acknowledgement ("we
    received your application"): each application gets one, often several roles at one
    company could match, and none of it is news. The exception is the one application it
    names whose submit the app could not confirm; that email confirms it.
    """
    result = IngestResult()
    with _LOCK:
        inbox = load()
        seen = set(inbox.seen)
        for message in messages[:MAX_MESSAGES]:
            if message.message_id in seen:
                result.already_seen += 1
                continue
            seen.add(message.message_id)
            inbox.seen.append(message.message_id)
            signal = mail_signals.classify(message.subject, message.body)
            if signal is None:
                result.ignored += 1
                continue
            mail = mail_signals.Mail(
                message.message_id, message.sender, message.subject, message.body,
                mail_signals.received_on(message.date),
            )
            found = mail_signals.match(mail, apps)
            if (require_match and not found.app_id and not found.candidates
                    and not mail_signals.hiring_sender(mail.from_domain)):
                result.ignored += 1
                continue
            app = next((a for a in apps if a.source_job_id == found.app_id), None)
            if (require_match and signal == "sent"
                    and not (app is not None and app.status == "submit_unconfirmed")):
                result.ignored += 1  # "We received your application": nothing new.
                continue
            flag = mail_signals.check(signal, app, mail.received_on) if app else ""
            inbox.proposals.append(Proposal(
                id=_proposal_id(message.message_id), message_id=message.message_id,
                received_on=mail.received_on, sender=message.sender,
                from_domain=mail.from_domain, subject=message.subject.strip(),
                excerpt=_excerpt(message.body), signal=signal,
                app_id=found.app_id, candidates=found.candidates, reason=found.reason,
                flag=flag, created_at=_now(),
                confident=mail_signals.confident(signal, found, app, flag),
            ))
            if found.app_id:
                result.matched += 1
            else:
                result.unclear += 1
        inbox.last_synced = _now()
        _save(inbox)
    return result


def pending() -> list[Proposal]:
    """Proposals still waiting on the student, newest email first."""
    rows = [p for p in load().proposals if p.state == "pending"]
    return sorted(rows, key=lambda p: (p.received_on or "", p.created_at), reverse=True)


def _note(proposal: Proposal) -> str:
    subject = proposal.subject or "(no subject)"
    return f"From email “{subject}”"


def _confirmed(app: store_models.Application) -> bool:
    return app.status in outcomes.SENT and app.status != "submit_unconfirmed"


def _apply(proposal: Proposal, signal: mail_signals.Signal,
           app: store_models.Application) -> None:
    if signal == "sent":
        if _confirmed(app):
            return  # Already confirmed as sent: nothing to change, no second status entry.
        if app.archived_at:
            raise ValueError("Restore this application before changing its status")
        store.set_status(app, "submitted", note=f"Confirmed by email: {proposal.subject}"[:300])
        return
    outcomes.add_event(app, signal, occurred_on=proposal.received_on, note=_note(proposal),
                       source="mcp")


def accept(
    proposal_id: str, *, signal: mail_signals.Signal | None = None, app_id: str | None = None
) -> tuple[Proposal, store_models.Application]:
    """Record a proposal on its application (or the one the student picked).

    Raises:
        KeyError: Unknown proposal.
        ValueError: Already decided, no application or signal, or a refused change.
        store.StaleApplication: The application no longer exists.
    """
    with _LOCK:
        inbox = load()
        proposal = next((p for p in inbox.proposals if p.id == proposal_id), None)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.state != "pending":
            raise ValueError("That email was already handled")
        target = app_id or proposal.app_id
        kind = signal or proposal.signal
        if not target or kind is None:
            raise ValueError("Pick the application and what happened first")
        app = store.update(target, lambda row: _apply(proposal, kind, row))
        proposal.state, proposal.decided_at = "accepted", _now()
        proposal.app_id, proposal.signal = target, kind
        _save(inbox)
    return proposal, app


def _close(proposal: Proposal, added: list[str]) -> Callable[[store_models.Application], None]:
    def mutate(app: store_models.Application) -> None:
        # Re-checked on the stored row: a close recorded meanwhile wins.
        if outcomes.hiring_progress(app).closed is not None:
            return
        event = outcomes.add_event(app, "rejected", occurred_on=proposal.received_on,
                                   note=f"Closed from email “{proposal.subject}”"[:500],
                                   source="monitor")
        added.append(event.id)
    return mutate


def auto_close() -> int:
    """Record every pending confident rejection on its application; returns how many."""
    closed = 0
    with _LOCK:
        inbox = load()
        for proposal in inbox.proposals:
            if proposal.state != "pending" or not proposal.confident or not proposal.app_id:
                continue
            added: list[str] = []
            try:
                store.update(proposal.app_id, _close(proposal, added))
            except store.StaleApplication:
                continue
            if not added:  # Already closed: leave it for the student to dismiss.
                proposal.confident = False
                continue
            proposal.state, proposal.decided_at = "accepted", _now()
            proposal.auto, proposal.event_id = True, added[0]
            closed += 1
        _save(inbox)
    return closed


def undo_auto(proposal_id: str) -> Proposal:
    """Take back one automatic close: remove its event (kept in the history, voided) and
    put the email back to pending. It is never closed automatically again.

    Raises:
        KeyError: Unknown proposal.
        ValueError: Not an automatic close.
    """
    with _LOCK:
        inbox = load()
        proposal = next((p for p in inbox.proposals if p.id == proposal_id), None)
        if proposal is None:
            raise KeyError(proposal_id)
        if not proposal.auto:
            raise ValueError("That email was not recorded automatically")

        def void(app: store_models.Application) -> None:
            # Already removed in the Outcome tab, or edited there: nothing left to undo.
            with contextlib.suppress(KeyError, ValueError):
                outcomes.void_event(app, proposal.event_id)

        with contextlib.suppress(store.StaleApplication):
            store.update(proposal.app_id or "", void)
        proposal.state, proposal.decided_at = "pending", ""
        proposal.auto, proposal.confident, proposal.event_id = False, False, ""
        _save(inbox)
    return proposal


def recent_auto(days: int = 14) -> list[Proposal]:
    """Automatic closes from the last ``days`` days, newest first."""
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = [p for p in load().proposals if p.auto and p.decided_at >= since]
    return sorted(rows, key=lambda p: p.decided_at, reverse=True)


def dismiss(proposal_id: str) -> Proposal:
    with _LOCK:
        inbox = load()
        proposal = next((p for p in inbox.proposals if p.id == proposal_id), None)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.state == "pending":
            proposal.state, proposal.decided_at = "dismissed", _now()
            _save(inbox)
    return proposal
