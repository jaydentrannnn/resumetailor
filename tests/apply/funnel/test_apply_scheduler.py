"""The nightly Apply scheduler: due window, catch-up, persistence."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import scheduler


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)


@pytest.mark.parametrize(
    ("now", "last", "expected"),
    [
        (datetime(2026, 9, 25, 1, 59), None, "wait"),
        (datetime(2026, 9, 25, 2, 0), None, "run"),
        # A wake that lands a few seconds past the minute still runs (the old bug).
        (datetime(2026, 9, 25, 2, 1, 5), None, "run"),
        # Machine asleep at 02:00, opened at 09:00: catch up.
        (datetime(2026, 9, 25, 9, 0), date(2026, 9, 24), "run"),
        # However late: the nightly run never submits, so a mid-day start is harmless.
        (datetime(2026, 9, 25, 23, 0), date(2026, 9, 24), "run"),
        (datetime(2026, 9, 25, 3, 0), date(2026, 9, 25), "done"),
    ],
)
def test_decide(now, last, expected):
    assert scheduler.decide(now, "02:00", last) == expected


@pytest.mark.parametrize("bad", ["", "2am", "25:00", "02:75", "02"])
def test_invalid_schedule_time(bad):
    assert scheduler.decide(datetime(2026, 9, 25, 3, 0), bad, None) == "invalid"


def _tick(now, *, busy=False, enabled=True, schedule="02:00", started=None):
    started = started if started is not None else []
    return scheduler.tick(
        enabled=enabled,
        schedule_time=schedule,
        busy=lambda: busy,
        start=lambda: started.append(now),
        now=lambda: now,
    )


def test_runs_once_per_day_across_restarts():
    started: list[datetime] = []
    assert _tick(datetime(2026, 9, 25, 2, 0, 40), started=started) == "run"
    # A restart re-reads the persisted date instead of a process global.
    assert _tick(datetime(2026, 9, 25, 2, 1), started=started) == "done"
    assert _tick(datetime(2026, 9, 26, 2, 0, 10), started=started) == "run"
    assert len(started) == 2


def test_busy_defers_to_the_next_tick():
    started: list[datetime] = []
    assert _tick(datetime(2026, 9, 25, 2, 0), busy=True, started=started) == "busy"
    assert started == []
    assert _tick(datetime(2026, 9, 25, 2, 10), started=started) == "run"


def test_a_late_start_still_runs_once():
    started: list[datetime] = []
    assert _tick(datetime(2026, 9, 25, 15, 0), started=started) == "run"
    assert _tick(datetime(2026, 9, 25, 16, 0), started=started) == "done"
    assert len(started) == 1
    info = scheduler.status(enabled=True, schedule_time="02:00", now=datetime(2026, 9, 25, 16, 0))
    assert info["next_run_at"] == "2026-09-26T02:00"


def test_disabled_does_nothing():
    assert _tick(datetime(2026, 9, 25, 2, 0), enabled=False) == "disabled"
    assert scheduler.load_state() == {}


def test_invalid_time_is_reported():
    assert _tick(datetime(2026, 9, 25, 2, 0), schedule="nope") == "invalid"
    info = scheduler.status(enabled=True, schedule_time="nope")
    assert "not a valid" in info["last_error"]
    assert info["next_run_at"] is None


def test_status_after_a_run():
    _tick(datetime(2026, 9, 25, 2, 0))
    info = scheduler.status(enabled=True, schedule_time="02:00", now=datetime(2026, 9, 25, 8, 0))
    assert info["last_run_date"] == "2026-09-25"
    assert info["next_run_at"] == "2026-09-26T02:00"


def _run_now(now, *, busy=False, schedule="02:00", started=None):
    started = started if started is not None else []
    return scheduler.run_now(
        schedule_time=schedule,
        busy=lambda: busy,
        start=lambda: started.append(now),
        now=lambda: now,
    )


def test_run_now_after_todays_time_counts_as_todays_run():
    started: list[datetime] = []
    assert _run_now(datetime(2026, 9, 25, 13, 0), started=started) is True
    assert _tick(datetime(2026, 9, 25, 13, 1), started=started) == "done"
    assert len(started) == 1


def test_run_now_before_todays_time_keeps_tonights_run():
    started: list[datetime] = []
    assert _run_now(datetime(2026, 9, 25, 13, 0), schedule="23:00", started=started) is True
    assert _tick(datetime(2026, 9, 25, 23, 0), schedule="23:00", started=started) == "run"
    assert len(started) == 2


def test_run_now_refuses_while_busy():
    started: list[datetime] = []
    assert _run_now(datetime(2026, 9, 25, 13, 0), busy=True, started=started) is False
    assert started == []
