"""The app's own mailbox check: when it runs, what it reads since, and what it records.

Settings live per profile in ``mail_settings.json`` beside ``mail_inbox.json``; the
password only in `infra/secret_store` (``profile:<id>:mail:imap``), never in a file or a
response. A check reads hiring mail since the last one (the first goes back to the first
application sent) with `mail_imap.fetch`, turns it into proposals (`mail_inbox.ingest`)
and, when the student has switched it on, records the confident rejections
(`mail_inbox.auto_close`). One check runs at a time; the server starts one after startup
and every `Settings.every_hours` (`web/app.py`), and the Settings page can start one.

Only the active profile is checked, as with the nightly Apply pass (`scheduler`). A
profile switch during a check discards what it read; the next check reads it again.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from resume_tailor import config
from resume_tailor.infra import atomic, secret_store

from . import mail_imap, mail_inbox, mail_signals, outcomes, store, store_models

_log = logging.getLogger(__name__)

PASSWORD_SECRET = "mail:imap"
#: Hours between automatic checks the Settings page offers; 0 checks only on request.
CHECK_EVERY: tuple[int, ...] = (0, 1, 3, 6, 12)
TICK_SECONDS = 60.0
#: Days the first check reads back when nothing has been sent yet.
_FALLBACK_DAYS = 30

_SETTINGS_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()
#: When this process started: the first tick after it checks whatever the schedule.
_STARTED = datetime.now(UTC)


class Settings(BaseModel):
    imap: mail_imap.MailAccount | None = None
    every_hours: int = 3
    #: Record confident rejections without asking (off until the student turns it on).
    auto_close: bool = False
    #: Last check that read the mailbox (ISO, UTC), and the day it read from.
    last_checked: str = ""
    last_since: str = ""
    #: Last check started, read or failed (ISO, UTC): spaces out retries after an error.
    last_attempt: str = ""
    last_error: str = ""
    last_result: mail_inbox.IngestResult | None = None


class AlreadyRunning(RuntimeError):
    pass


def path() -> Path:
    return config.APPLICATIONS_PATH.parent / "mail_settings.json"


def load() -> Settings:
    return atomic.read_cached(path(), Settings) or Settings()


def update(mutate: Callable[[Settings], None]) -> Settings:
    """Re-read the settings, apply ``mutate`` and save, so a check's result never
    overwrites an edit made while it ran."""
    with _SETTINGS_LOCK:
        settings = load()
        mutate(settings)
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_text(target, settings.model_dump_json(indent=2) + "\n")
        return settings


def _secret_name() -> str:
    return secret_store.profile_name(PASSWORD_SECRET)


def password() -> str:
    return secret_store.get(_secret_name()) or ""


def set_password(value: str) -> None:
    secret_store.set(_secret_name(), value)


def forget() -> Settings:
    """Remove the account and its password; mail already read stays as proposals."""
    secret_store.delete(_secret_name())
    return update(lambda s: _reset(s))


def _reset(settings: Settings) -> None:
    for name, value in Settings().model_dump().items():
        setattr(settings, name, value)


def running() -> bool:
    return _RUN_LOCK.locked()


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None


def due(now: datetime, settings: Settings, *, started: datetime = _STARTED) -> bool:
    """Whether the schedule wants a check at ``now``: the first tick after startup, then
    every ``every_hours`` after the last attempt. Never without an account or on 0."""
    if settings.imap is None or settings.every_hours <= 0:
        return False
    last = _parse(settings.last_attempt)
    if last is None or last < started:
        return True
    return now - last >= timedelta(hours=settings.every_hours)


def _employer_rows(apps: list[store_models.Application]) -> list[store_models.Application]:
    return [a for a in apps if a.status in mail_signals._APPLIED_OR_PREPARED or a.outcome_events]


def since_date(settings: Settings, apps: list[store_models.Application], today: date) -> date:
    """The day a check reads from: a day before the last check (mail can arrive late
    with an earlier date), else the first application sent, else 30 days back."""
    if (last := _parse(settings.last_checked)) is not None:
        return last.date() - timedelta(days=1)
    sent = [day for app in apps if (day := outcomes.sent_on(app))]
    if sent:
        return date.fromisoformat(min(sent))
    return today - timedelta(days=_FALLBACK_DAYS)


def _record_error(message: str, at: str) -> None:
    def mutate(settings: Settings) -> None:
        settings.last_attempt, settings.last_error = at, message
    update(mutate)


def run() -> mail_inbox.IngestResult | None:
    """Check the mailbox once; None when it could not be read (see ``last_error``) or a
    profile switch discarded it.

    Raises:
        AlreadyRunning: A check is under way.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        raise AlreadyRunning("A mail check is already running")
    try:
        return _run()
    finally:
        _RUN_LOCK.release()


def _run() -> mail_inbox.IngestResult | None:
    workspace = config.active_workspace_id()
    started = datetime.now(UTC)
    at = started.isoformat(timespec="seconds")
    settings = load()
    secret = password()
    if settings.imap is None or not secret:
        _record_error("Set up the email account first (server, username and password).", at)
        return None
    apps = list(store.rows_view().values())
    since = since_date(settings, apps, started.date())
    companies = sorted({app.company for app in _employer_rows(apps) if app.company})
    try:
        mails = mail_imap.fetch(settings.imap, secret, since=since, companies=companies)
    except mail_imap.MailError as exc:
        _log.info("mail check failed: %s", type(exc).__name__)
        if config.active_workspace_id() == workspace:
            _record_error(str(exc), at)
        return None
    if config.active_workspace_id() != workspace:
        _log.info("mail check discarded: the active profile changed")
        return None
    total = mail_inbox.IngestResult()
    apps = list(store.rows_view().values())
    for start in range(0, len(mails), mail_inbox.MAX_MESSAGES):
        part = mail_inbox.ingest(mails[start:start + mail_inbox.MAX_MESSAGES], apps,
                                 require_match=True)
        for name in ("matched", "unclear", "ignored", "already_seen"):
            setattr(total, name, getattr(total, name) + getattr(part, name))
    if load().auto_close:
        total.closed = mail_inbox.auto_close()

    def record(current: Settings) -> None:
        current.last_checked, current.last_attempt = at, at
        current.last_since, current.last_error = since.isoformat(), ""
        current.last_result = total
    update(record)
    _log.info("mail check: %s", total.model_dump())
    return total


def tick(now: datetime | None = None) -> None:
    """One scheduler wake-up: start a check when one is due and none is running."""
    if running() or not due(now or datetime.now(UTC), load()):
        return
    with contextlib.suppress(AlreadyRunning):  # Another check started first.
        run()
