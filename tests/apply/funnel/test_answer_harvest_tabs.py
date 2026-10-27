"""The background pass over retained tabs: quick submission checks, and closing a finished
application's tab only when it is safe (audit #4)."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.apply.driver import browser
from resume_tailor.apply.funnel import answer_harvest as harvest
from resume_tailor.apply.funnel import store, store_models, tab_close

URL = "https://job-boards.greenhouse.io/synthetic/jobs/1"


@pytest.fixture
def tabs(tmp_path, monkeypatch):
    """A fake browser: ``tabs.urls`` is what /json/list shows; closes are recorded, and
    ``tabs.reading`` is what the tab's input listener reads."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(harvest, "_WATCHED", set())
    monkeypatch.setattr(harvest, "FILLING", set())
    monkeypatch.setattr(tab_close, "_PENDING", {})
    monkeypatch.setattr(tab_close, "KEPT", set())
    monkeypatch.setattr(tab_close, "_STARTED", "2000-01-01T00:00:00+00:00")

    class _Tabs:
        urls: dict[str, str] = {}
        closed: list[str] = []
        collected: list[str] = []
        #: (last input, page clock) in ms, or None when the tab cannot be read.
        reading: tuple[float, float] | None = (0.0, 1000.0)

    fake = _Tabs()
    fake.urls, fake.closed, fake.collected = {"T1": URL}, [], []
    monkeypatch.setattr(tab_close, "_read", lambda _target, install: fake.reading)
    monkeypatch.setattr(browser, "extension_mode", lambda: False)
    monkeypatch.setattr(browser, "open_targets", lambda: dict(fake.urls))
    monkeypatch.setattr(browser, "close_target", lambda target: fake.closed.append(target) or True)
    monkeypatch.setattr(harvest, "collect", lambda app_id: fake.collected.append(app_id) or 0)
    return fake


def _watched(status="awaiting_review", target="T1", confirmation="Thank you for applying"):
    app = store_models.Application(
        source="manual", source_job_id="app", company="Synthetic", role="Engineer",
        posting_url=URL, final_url=URL, ats="greenhouse", status="awaiting_review",
        fill={"browser_target_id": target, "browser_url": URL, "status": "awaiting_review",
              "confirmation": confirmation if status == "submitted" else ""},
    )
    if status != "awaiting_review":
        store.set_status(app, status)
    store.upsert(app)
    harvest._WATCHED.add("app")
    return app


def _state(now=1000.0):
    return harvest._Pass(urls={}, last_full=now)


def _at(monkeypatch, now: float) -> None:
    monkeypatch.setattr(harvest.time, "monotonic", lambda: now)
    monkeypatch.setattr(tab_close.time, "monotonic", lambda: now)


def _history() -> list[tuple[str, str]]:
    fill = store_models.FillResult.model_validate(store.get("app").fill)
    return [(event["event"], event["reason"]) for event in fill.tab_history]


def test_a_tab_is_read_as_soon_as_its_url_changes(tabs, monkeypatch):
    _watched()
    state = _state()
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 1002.0)
    harvest._tick(state)
    assert tabs.collected == []  # first sight, no full pass due yet
    tabs.urls["T1"] = URL + "/confirmation"
    harvest._tick(state)
    assert tabs.collected == ["app"]


def test_an_unchanged_tab_waits_for_the_full_pass(tabs, monkeypatch):
    _watched()
    state = _state()
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 1002.0)
    harvest._tick(state)
    assert tabs.collected == []
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 1000.0 + harvest._INTERVAL_S)
    harvest._tick(state)
    assert tabs.collected == ["app"]


@pytest.mark.parametrize("status", ["submitted", "skipped"])
def test_a_finished_applications_tab_is_closed_after_the_countdown(tabs, monkeypatch, status):
    _watched(status=status)
    state = _state()
    _at(monkeypatch, 1001.0)
    harvest._tick(state)
    assert tabs.closed == [] and "app" in harvest._WATCHED
    assert [item["id"] for item in tab_close.pending()] == ["app"]
    _at(monkeypatch, 1001.0 + tab_close.GRACE_S)
    harvest._tick(state)
    assert tabs.closed == ["T1"]
    assert "app" not in harvest._WATCHED and tab_close.pending() == []
    assert tabs.collected == []
    assert _history()[-1][0] == "closed"


def _counted_down(monkeypatch, state) -> None:
    _at(monkeypatch, 1001.0)
    harvest._tick(state)
    _at(monkeypatch, 1001.0 + tab_close.GRACE_S)


def test_a_tab_taken_to_another_page_is_kept(tabs, monkeypatch):
    _watched(status="submitted")
    state = _state()
    _at(monkeypatch, 1001.0)
    harvest._tick(state)
    tabs.urls["T1"] = "https://mail.example.com/drafts/1"
    _at(monkeypatch, 1001.0 + tab_close.GRACE_S)
    harvest._tick(state)
    assert tabs.closed == []
    assert _history()[-1] == ("kept", "The tab moved to another page")


def test_typing_during_the_countdown_keeps_the_tab(tabs, monkeypatch):
    _watched(status="submitted")
    state = _state()
    _counted_down(monkeypatch, state)
    tabs.reading = (1500.0, 2000.0)  # input after the page clock read at arm time
    harvest._tick(state)
    assert tabs.closed == []
    assert _history()[-1] == ("kept", "You used the tab")


def test_an_unreadable_tab_is_kept(tabs, monkeypatch):
    _watched(status="submitted")
    state = _state()
    tabs.reading = None
    _counted_down(monkeypatch, state)
    harvest._tick(state)
    assert tabs.closed == []
    assert _history()[-1] == ("kept", "Could not check the tab for your input")


def test_keep_open_keeps_the_tab(tabs, monkeypatch):
    _watched(status="submitted")
    state = _state()
    _counted_down(monkeypatch, state)
    assert tab_close.keep("app") is True
    harvest._tick(state)
    assert tabs.closed == [] and tab_close.pending() == []
    assert _history()[-1] == ("kept", "You chose to keep it open")


def test_a_mark_without_a_seen_confirmation_keeps_the_tab(tabs, monkeypatch):
    _watched(status="submitted", confirmation="")
    _counted_down(monkeypatch, _state())
    assert tabs.closed == [] and "app" not in harvest._WATCHED
    assert _history()[-1] == ("kept", "Marked submitted without a confirmation the app saw")


def test_a_skip_from_before_this_session_keeps_the_tab(tabs, monkeypatch):
    _watched(status="skipped")
    monkeypatch.setattr(tab_close, "_STARTED", "2999-01-01T00:00:00+00:00")
    _counted_down(monkeypatch, _state())
    assert tabs.closed == []
    assert _history()[-1] == ("kept", "Skipped before this session")


def test_a_restart_never_closes_a_finished_tab(tabs):
    _watched(status="submitted")
    harvest._WATCHED.clear()
    harvest.restore()
    assert "app" not in harvest._WATCHED


def test_a_failed_fill_with_a_tab_is_watched_after_a_restart(tabs, monkeypatch):
    """Audit #3: the applicant may finish it by hand; the watcher records that."""
    monkeypatch.setattr(harvest, "watch", harvest._WATCHED.add)  # no background loop
    _watched(status="fill_failed")
    harvest._WATCHED.clear()
    harvest.restore()
    assert "app" in harvest._WATCHED


def test_a_review_tab_is_never_closed_and_a_gone_tab_is_dropped(tabs, monkeypatch):
    _watched()
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 5000.0)
    harvest._tick(_state())
    assert tabs.closed == []
    tabs.urls.clear()
    harvest._tick(_state())
    assert tabs.closed == [] and "app" not in harvest._WATCHED
    assert _history()[-1] == ("gone", "The tab was closed outside the app")


def test_nothing_is_read_while_the_browser_is_unreachable(tabs, monkeypatch):
    _watched()
    monkeypatch.setattr(browser, "open_targets", lambda: None)
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 5000.0)
    harvest._tick(_state())
    assert tabs.collected == [] and "app" in harvest._WATCHED
