"""The background pass over retained tabs: quick submission checks and closing finished tabs."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.apply.driver import browser
from resume_tailor.apply.funnel import answer_harvest as harvest
from resume_tailor.apply.funnel import store, store_models

URL = "https://job-boards.greenhouse.io/synthetic/jobs/1"


@pytest.fixture
def tabs(tmp_path, monkeypatch):
    """A fake browser: ``tabs.urls`` is what /json/list shows; closes are recorded."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(harvest, "_WATCHED", set())
    monkeypatch.setattr(harvest, "FILLING", set())

    class _Tabs:
        urls: dict[str, str] = {}
        closed: list[str] = []
        collected: list[str] = []

    fake = _Tabs()
    fake.urls, fake.closed, fake.collected = {"T1": URL}, [], []
    monkeypatch.setattr(browser, "extension_mode", lambda: False)
    monkeypatch.setattr(browser, "open_targets", lambda: dict(fake.urls))
    monkeypatch.setattr(browser, "close_target", lambda target: fake.closed.append(target) or True)
    monkeypatch.setattr(harvest, "collect", lambda app_id: fake.collected.append(app_id) or 0)
    return fake


def _watched(status="awaiting_review", target="T1"):
    app = store_models.Application(
        source="manual", source_job_id="app", company="Synthetic", role="Engineer",
        posting_url=URL, final_url=URL, ats="greenhouse", status=status,
        fill={"browser_target_id": target, "browser_url": URL, "status": "awaiting_review"},
    )
    store.upsert(app)
    harvest._WATCHED.add("app")
    return app


def _state(now=1000.0):
    return harvest._Pass(urls={}, closing={}, last_full=now)


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
def test_a_finished_applications_tab_is_closed_after_a_grace(tabs, monkeypatch, status):
    _watched(status=status)
    state = _state()
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 1001.0)
    harvest._tick(state)
    assert tabs.closed == [] and "app" in harvest._WATCHED
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 1001.0 + harvest._CLOSE_GRACE_S)
    harvest._tick(state)
    assert tabs.closed == ["T1"]
    assert "app" not in harvest._WATCHED
    assert tabs.collected == []


def test_a_review_tab_is_never_closed_and_a_gone_tab_is_dropped(tabs, monkeypatch):
    _watched()
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 5000.0)
    harvest._tick(_state())
    assert tabs.closed == []
    tabs.urls.clear()
    harvest._tick(_state())
    assert tabs.closed == [] and "app" not in harvest._WATCHED


def test_nothing_is_read_while_the_browser_is_unreachable(tabs, monkeypatch):
    _watched()
    monkeypatch.setattr(browser, "open_targets", lambda: None)
    monkeypatch.setattr(harvest.time, "monotonic", lambda: 5000.0)
    harvest._tick(_state())
    assert tabs.collected == [] and "app" in harvest._WATCHED
