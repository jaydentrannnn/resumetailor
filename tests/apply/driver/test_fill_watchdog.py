"""The fill watchdog: a browser call that never returns is cut past the deadline.

Magnite (2026-10-07) blocked in the Workday Skills loop for 13 minutes past its
deadline, until the server restarted, and nothing logged which call it was.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from contextlib import contextmanager
from types import SimpleNamespace

from resume_tailor.apply.driver import browser, watchdog
from resume_tailor.apply.forms import fill
from resume_tailor.apply.funnel.store_models import FillResult


def _never_returns(release: threading.Event) -> None:
    release.wait(10)  # stands in for a page.evaluate with no timeout


def test_a_call_stuck_past_the_deadline_is_cut_and_its_place_logged(caplog):
    release = threading.Event()
    cuts: list[str] = []
    clock = SimpleNamespace(now=0.0)

    def cut() -> None:
        cuts.append("cut")
        release.set()  # killing the driver makes the blocked call raise

    def tick() -> float:
        clock.now += 50.0
        return clock.now

    with watchdog.stall_guard(lambda: 100.0, cut=cut, label="Magnite 97fe6a41",
                              grace_s=120.0, clock=tick, poll_s=0.01) as stall:
        _never_returns(release)
    assert cuts == ["cut"]
    assert stall.fired and stall.seconds_over >= 120
    assert "fill stuck" in caplog.text and "_never_returns" in caplog.text
    assert "past its deadline" in stall.message() and "tab was left as it is" in stall.message()


def test_a_fill_that_finishes_in_time_is_never_cut():
    cuts: list[str] = []
    with watchdog.stall_guard(lambda: 100.0, cut=lambda: cuts.append("cut"), label="x",
                              clock=lambda: 0.0, poll_s=0.01) as stall:
        threading.Event().wait(0.05)
    assert not cuts and not stall.fired


def test_the_stuck_place_is_the_innermost_frame_of_our_own_code():
    own = traceback.FrameSummary(os.path.join("x", "resume_tailor", "apply", "workday_skills.py"), 105, "_search_prompt")
    lib = traceback.FrameSummary(os.path.join("x", "playwright", "_sync_base.py"), 111, "_sync")
    assert watchdog._where([own, lib]) == "workday_skills.py:105 _search_prompt"  # noqa: SLF001
    assert watchdog._where([lib]) == "_sync_base.py:111 _sync"  # noqa: SLF001
    assert watchdog._where([]) == "unknown"  # noqa: SLF001


def test_the_driver_pid_is_read_from_a_sync_browser_and_its_process_can_be_ended():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        fake = SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(
            _transport=SimpleNamespace(_proc=SimpleNamespace(pid=proc.pid)))))
        assert watchdog.driver_pid(fake) == proc.pid
        assert watchdog.driver_pid(object()) is None
        watchdog.kill_driver(proc.pid)
        assert proc.wait(10) is not None
        watchdog.kill_driver(proc.pid)  # already gone: no error
    finally:
        proc.kill()


def test_a_cut_fill_reports_where_it_was_stuck(monkeypatch):
    @contextmanager
    def fake_browser():
        yield SimpleNamespace(contexts=[])

    @contextmanager
    def fired_guard(*_a, **_k):
        yield watchdog.Stall(where="workday_skills.py:105 _search_prompt", seconds_over=130)

    def connection_closed(_self, _browser):
        raise Exception("Connection closed while reading from the driver")  # noqa: TRY002

    monkeypatch.setattr(browser, "cdp_browser", fake_browser)
    monkeypatch.setattr(watchdog, "stall_guard", fired_guard)
    monkeypatch.setattr(fill._FillRun, "_run_connected", connection_closed)  # noqa: SLF001
    statuses: list[str] = []
    monkeypatch.setattr(fill.store, "set_status", lambda _app, status, note="": statuses.append(note))
    monkeypatch.setattr(fill.store, "upsert", lambda _app: None)

    run = fill._FillRun.__new__(fill._FillRun)  # noqa: SLF001
    run.app = SimpleNamespace(company="Magnite", fill=None, error=None)
    run.source_job_id, run.deadline, run.on_progress = "97fe6a41-dd50", 0.0, None
    run.previous_fill, run.target_id, run.page = FillResult(), "BBE840C9", None
    result = run.run()
    assert result.status == "fill_failed"
    assert result.handoff_reason == "fill stopped responding"
    assert "stuck in workday_skills.py:105 _search_prompt" in (result.error or "")
    assert statuses == [result.error]
