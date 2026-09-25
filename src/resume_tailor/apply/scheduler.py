"""When to start the nightly Apply pass (`daily.run_daily`) on its own.

The server wakes every `TICK_SECONDS` and calls `tick()`. A run is due once per local
day, at or after ``ApplySettings.schedule_time``. The old check fired only when a wake
landed inside the scheduled minute exactly, so drift or a busy minute skipped a whole
day, and a machine that was asleep or off at 02:00 never ran at all.

- **Catch-up.** A run that is due but hasn't happened today starts on the next tick,
  including the first tick after startup, as long as it is less than
  `CATCH_UP_WINDOW` late.
- **Missed.** Later than that (the laptop was closed all night), it does not start in
  the middle of the day unannounced. The day is recorded as missed, which the Apply
  page shows next to "Run now".
- **Persistence.** The last run date is stored per profile in
  ``<DATA_DIR>/apply_scheduler.json``, so a restart the same day does not run twice.

Only the active profile is scheduled: running another profile's pass means rebinding
the process-wide config paths under the user (see CLAUDE.md, single process), which
waits for the per-request workspace context planned for the hosted version.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config

_log = logging.getLogger(__name__)

TICK_SECONDS = 30.0
CATCH_UP_WINDOW = timedelta(hours=12)
STATE_FILENAME = "apply_scheduler.json"

Decision = Literal["run", "wait", "done", "missed", "invalid"]

_STATE_LOCK = threading.Lock()


def parse_schedule_time(value: str) -> time | None:
    """``"HH:MM"`` as a `time`, or None when it is not a valid 24-hour time."""
    try:
        hour_str, minute_str = value.strip().split(":", 1)
        return time(int(hour_str), int(minute_str))
    except (ValueError, AttributeError):
        return None


def decide(now: datetime, schedule_time: str, last_run_date: date | None) -> Decision:
    """What the scheduler should do at local wall-clock ``now``.

    DST needs no special case: ``due`` is today's wall-clock time and the comparison
    is on dates, so a 23- or 25-hour day still runs exactly once.
    """
    at = parse_schedule_time(schedule_time)
    if at is None:
        return "invalid"
    today = now.date()
    if last_run_date is not None and last_run_date >= today:
        return "done"
    due = datetime.combine(today, at)
    if now < due:
        return "wait"
    if now - due < CATCH_UP_WINDOW:
        return "run"
    return "missed"


def next_due(now: datetime, schedule_time: str, last_run_date: date | None) -> datetime | None:
    """The next wall-clock time a run can start, for display."""
    at = parse_schedule_time(schedule_time)
    if at is None:
        return None
    today_due = datetime.combine(now.date(), at)
    if decide(now, schedule_time, last_run_date) in {"wait", "run"}:
        return today_due
    return today_due + timedelta(days=1)


def _state_path() -> Path:
    return config.DATA_DIR / STATE_FILENAME


def load_state() -> dict[str, Any]:
    """The active profile's scheduler record; empty when it never ran."""
    path = _state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_state(**fields: Any) -> None:
    with _STATE_LOCK:
        state = load_state()
        state.update(fields)
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def status(*, enabled: bool, schedule_time: str, now: datetime | None = None) -> dict[str, Any]:
    """Scheduler facts for the Apply page: last run, next run, missed day, error."""
    now = now or datetime.now()
    state = load_state()
    last_run = _parse_date(state.get("last_run_date"))
    upcoming = next_due(now, schedule_time, last_run) if enabled else None
    missed = _parse_date(state.get("missed_date"))
    return {
        "enabled": enabled,
        "schedule_time": schedule_time,
        "last_run_date": last_run.isoformat() if last_run else None,
        "last_started_at": state.get("last_started_at"),
        "next_run_at": upcoming.isoformat(timespec="minutes") if upcoming else None,
        # Only today's miss is news; yesterday's is history.
        "missed_today": bool(missed and missed == now.date() and last_run != now.date()),
        "last_error": state.get("last_error"),
    }


def tick(
    *,
    enabled: bool,
    schedule_time: str,
    busy: Callable[[], bool],
    start: Callable[[], None],
    now: Callable[[], datetime] = datetime.now,
) -> Decision | Literal["busy", "disabled"]:
    """One scheduler wake: start the day's run when it is due and nothing else runs.

    ``busy`` reports whether another Apply workflow owns the browser (retried next
    tick, not skipped), ``start`` launches the run. Returns what happened, for tests.
    """
    if not enabled:
        return "disabled"
    current = now()
    state = load_state()
    last_run = _parse_date(state.get("last_run_date"))
    decision = decide(current, schedule_time, last_run)
    if decision == "invalid":
        message = f"Schedule time {schedule_time!r} is not a valid HH:MM time"
        if state.get("last_error") != message:
            _save_state(last_error=message)
        return decision
    if decision == "missed":
        if _parse_date(state.get("missed_date")) != current.date():
            _log.info(
                "nightly Apply run missed: more than %s past %s", CATCH_UP_WINDOW, schedule_time
            )
            _save_state(missed_date=current.date().isoformat())
        return decision
    if decision != "run":
        return decision
    if busy():
        return "busy"
    # Recorded before starting: a crash mid-run must not restart it on every boot.
    _save_state(
        last_run_date=current.date().isoformat(),
        last_started_at=current.isoformat(timespec="seconds"),
        last_error=None,
    )
    start()
    return decision
