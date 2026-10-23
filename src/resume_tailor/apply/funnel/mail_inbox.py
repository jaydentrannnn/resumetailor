"""Proposals read from job emails, waiting for the student to accept or dismiss them.

Claude Desktop reads the student's mail through its own Gmail connector and posts the
job emails here (`web/routes/mail_updates.py`); the app never holds mail credentials.
Each email becomes at most one proposal: an outcome event (or "sent", confirming an
application) for the application `mail_signals.match` found, or an unclear one the
student assigns. Nothing reaches an application until the student accepts it.

The inbox is one JSON file beside the profile's application registry. Every message id
seen is remembered, so posting the same emails again adds nothing. Only a short,
cleaned excerpt of each email is kept.
"""

from __future__ import annotations

import hashlib
import threading
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


def ingest(messages: list[IncomingMail], apps: list[store_models.Application]) -> IngestResult:
    """Turn new job emails into pending proposals; returns what happened to each."""
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
            app = next((a for a in apps if a.source_job_id == found.app_id), None)
            flag = mail_signals.check(signal, app, mail.received_on) if app else ""
            inbox.proposals.append(Proposal(
                id=_proposal_id(message.message_id), message_id=message.message_id,
                received_on=mail.received_on, sender=message.sender,
                from_domain=mail.from_domain, subject=message.subject.strip(),
                excerpt=_excerpt(message.body), signal=signal,
                app_id=found.app_id, candidates=found.candidates, reason=found.reason,
                flag=flag, created_at=_now(),
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


def _apply(proposal: Proposal, signal: mail_signals.Signal,
           app: store_models.Application) -> None:
    if signal == "sent":
        if app.status in outcomes.SENT and app.status != "submit_unconfirmed":
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
