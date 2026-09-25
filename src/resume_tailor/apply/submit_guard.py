"""Guard rails checked just before an automatic submit (plan P4-S).

`fill.decide_submit_action` decides whether policy *allows* auto-submit for a form.
This module decides whether *now* is a safe moment to do it. It runs right before
`clicks.submit_click`, and a ``Hold`` turns the submit into ``awaiting_review`` with a
plain-language note:

- **Pause switch.** "Pause all automation" in the header. It is stored in one file under
  ``config.DATA_ROOT`` because it covers every profile. It also stops the operation
  worker between applications, the nightly batch and the scheduler.
- **Caps.** At most ``auto_submit_max_per_day`` automatic submits, and at most
  ``auto_submit_max_per_company_per_day`` to one company. Both count over the last 24
  hours, not by calendar day, so there is no burst at midnight. The count comes from
  status history: a ``submitted`` or ``submit_unconfirmed`` change noted
  ``auto_submit``. An unconfirmed click may still have reached the employer, so it
  counts too.
- **Duplicates.** The row itself was already submitted, or another row was. "Another
  row" means one in the same duplicate group (`group_key`), or one with the same
  company and role that was submitted in the last 30 days.
- **Pacing.** A random 20–90 s gap between automatic submits in this process, and only
  one submit in flight at a time (`pace`).

Every function reads the live registry and settings, so a cap reached mid-batch holds
the next form, not the whole batch.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config

HoldCode = Literal["paused", "daily_cap", "company_cap", "already_submitted", "duplicate"]

#: Statuses that mean the employer (probably) has the application.
APPLIED_STATUSES = frozenset(
    {"submitted", "submit_unconfirmed", "interview", "rejected", "ghosted"}
)
AUTO_NOTE = "auto_submit"
DUPLICATE_WINDOW = timedelta(days=30)
CAP_WINDOW = timedelta(hours=24)
#: Seconds between two automatic submits: (min, max), drawn uniformly.
PACING_SECONDS: tuple[float, float] = (20.0, 90.0)

_COMPANY_SUFFIX = re.compile(
    r"[,\s]+(?:inc|llc|ltd|corp|corporation|co|company|plc|lp|llp|group|holdings)\.?$",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^\w]+")


@dataclass(frozen=True)
class Hold:
    """Why an automatic submit was held for the student instead."""

    code: HoldCode
    message: str


# --- pause switch -------------------------------------------------------------------

_PAUSE_LOCK = threading.Lock()


def pause_path() -> Path:
    """Where the pause switch lives; one file for every profile."""
    return config.DATA_ROOT / "automation.json"


def automation_state() -> dict[str, Any]:
    """``{"paused": bool, "changed_at": str}``; not paused when never set or unreadable."""
    try:
        raw = json.loads(pause_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {"paused": bool(raw.get("paused")), "changed_at": str(raw.get("changed_at") or "")}


def is_paused() -> bool:
    return automation_state()["paused"]


def set_paused(paused: bool) -> dict[str, Any]:
    state = {"paused": bool(paused), "changed_at": _now().isoformat(timespec="seconds")}
    with _PAUSE_LOCK:
        path = pause_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state) + "\n", encoding="utf-8")
        tmp.replace(path)
    return state


# --- caps and duplicates ------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(at: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def normalize_company(company: str) -> str:
    """Company names that compare equal: "Acme, Inc." and "ACME" both give "acme"."""
    name = (company or "").strip()
    while True:
        shorter = _COMPANY_SUFFIX.sub("", name).strip()
        if shorter == name:
            break
        name = shorter
    return _NON_WORD.sub(" ", name.casefold()).strip()


def normalize_role(role: str) -> str:
    return _NON_WORD.sub(" ", (role or "").casefold()).strip()


def _key(app: Any) -> str:
    return app.canonical_key or app.source_job_id


def auto_submits(apps: Iterable[Any], *, since: datetime) -> Iterator[tuple[Any, datetime]]:
    """``(application, when)`` for every automatic submit at or after ``since``."""
    for app in apps:
        for change in app.status_history:
            if change.status not in {"submitted", "submit_unconfirmed"}:
                continue
            if change.note != AUTO_NOTE:
                continue
            when = _parse(change.at)
            if when is not None and when >= since:
                yield app, when


def _submitted_at(app: Any) -> datetime | None:
    """When the row was last sent to the employer, by hand or automatically."""
    for change in reversed(app.status_history):
        if change.status in APPLIED_STATUSES:
            return _parse(change.at)
    return None


def _describe(app: Any) -> str:
    label = f"{app.company} — {app.role}".strip(" —")
    return label or _key(app)


def check(
    app: Any,
    settings: Any,
    *,
    apps: Iterable[Any] | None = None,
    now: datetime | None = None,
) -> Hold | None:
    """The first guard that holds ``app`` back from an automatic submit, else None.

    ``apps`` is every tracked application (read from the store when omitted), and
    ``settings`` is the `ApplySettings` in force.
    """
    if is_paused():
        return Hold("paused", "Automation is paused")
    now = now or _now()
    if apps is None:
        from resume_tailor.apply import store

        apps = store.load_all().values()
    others = [other for other in apps if _key(other) != _key(app)]

    if app.status in APPLIED_STATUSES or any(
        change.status in APPLIED_STATUSES for change in app.status_history
    ):
        return Hold("already_submitted", "This application was already submitted")

    group = app.group_key or ""
    company = normalize_company(app.company)
    role = normalize_role(app.role)
    for other in others:
        submitted_at = _submitted_at(other)
        if submitted_at is None:
            continue
        same_group = bool(group) and other.group_key == group
        same_job = (
            bool(company and role)
            and normalize_company(other.company) == company
            and normalize_role(other.role) == role
            and now - submitted_at <= DUPLICATE_WINDOW
        )
        if same_group or same_job:
            return Hold("duplicate", f"Possible duplicate of {_describe(other)}")

    since = now - CAP_WINDOW
    recent = [(other, when) for other, when in auto_submits(others, since=since)]
    daily_cap = int(getattr(settings, "auto_submit_max_per_day", 0) or 0)
    if len(recent) >= daily_cap:
        return Hold(
            "daily_cap",
            f"Daily cap reached ({daily_cap} automatic submits in 24 hours)",
        )
    company_cap = int(getattr(settings, "auto_submit_max_per_company_per_day", 0) or 0)
    if company:
        same_company = sum(1 for other, _ in recent if normalize_company(other.company) == company)
        if same_company >= company_cap:
            return Hold(
                "company_cap",
                f"Daily cap for {app.company} reached ({company_cap} in 24 hours)",
            )
    return None


# --- pacing -------------------------------------------------------------------------

_PACE_LOCK = threading.Lock()
_last_submit: float | None = None
_rng = random.Random()
#: Replaced in tests; the real one sleeps in short steps so a cancel is noticed.
_sleep: Callable[[float], None] = time.sleep
_clock: Callable[[], float] = time.monotonic


def seed(value: int | None) -> None:
    """Make the pacing delays repeatable (tests)."""
    _rng.seed(value)


def reset() -> None:
    global _last_submit
    _last_submit = None


def next_delay() -> float:
    low, high = PACING_SECONDS
    return _rng.uniform(low, high) if high > 0 else 0.0


@contextmanager
def pace(
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_wait: Callable[[float], None] | None = None,
) -> Iterator[bool]:
    """Hold the one submit slot, first waiting out the gap since the previous submit.

    Yields False when the wait was cancelled or automation was paused meanwhile, in
    which case the caller must not click. The slot is recorded as used only when the
    block finishes after a True yield.
    """
    global _last_submit
    with _PACE_LOCK:
        proceed = True
        if _last_submit is not None:
            remaining = _last_submit + next_delay() - _clock()
            if remaining > 0 and on_wait:
                on_wait(remaining)
            while remaining > 0:
                if (should_cancel and should_cancel()) or is_paused():
                    proceed = False
                    break
                step = min(remaining, 1.0)
                _sleep(step)
                remaining -= step
        if proceed and is_paused():
            proceed = False
        try:
            yield proceed
        finally:
            if proceed:
                _last_submit = _clock()
