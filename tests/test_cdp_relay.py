"""Hermetic protocol checks for the selected-tab CDP relay."""

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close
from websockets.sync import client as ws_client

from resume_tailor.apply import browser
from resume_tailor.apply.cdp_relay import Relay


@pytest.mark.asyncio
async def test_relay_emulates_browser_and_independent_page_sessions():
    relay = Relay()
    relay.target = {
        "targetId": "chosen-tab",
        "type": "page",
        "url": "http://127.0.0.1/job",
        "title": "Synthetic job",
        "attached": True,
    }

    assert (await relay.command("Browser.getVersion", {}, None))["protocolVersion"] == "1.3"
    assert (await relay.command("Target.getTargets", {}, None))["targetInfos"] == [relay.target]
    browser_session = (await relay.command("Target.attachToBrowserTarget", {}, None))["sessionId"]
    first = (await relay.command("Target.attachToTarget", {}, browser_session))["sessionId"]
    second = (await relay.command("Target.attachToTarget", {}, browser_session))["sessionId"]
    assert first != second
    assert {first, second} <= relay.page_sessions
    assert (await relay.command("Target.createTarget", {"url": "about:blank"}, None)) == {
        "targetId": "chosen-tab"
    }
    assert (await relay.command("Target.getTargetInfo", {}, first))["targetInfo"] == relay.target
    await relay.command("Target.detachFromTarget", {"sessionId": first}, browser_session)
    assert first not in relay.page_sessions
    assert second in relay.page_sessions


class _Conn:
    def __init__(self):
        self.closed = None

    async def close(self, code, reason):
        self.closed = (code, reason)


async def test_a_second_client_is_told_the_relay_is_busy():
    relay = Relay()
    relay.extension = object()
    relay.client = object()
    probe = _Conn()
    await relay.handle_client(probe)
    assert probe.closed == (1013, browser.RELAY_BUSY)

    relay.client = None
    relay.extension = None
    probe = _Conn()
    await relay.handle_client(probe)
    assert probe.closed == (1008, "Extension unavailable")


def _relay_mode(monkeypatch):
    monkeypatch.setenv("BROWSER_MODE", "extension")
    monkeypatch.setenv("EXTENSION_CDP_URL", "ws://127.0.0.1:8011/cdp/secret")


def _connect_closing_with(reason):
    frame = Close(1013, reason)

    def _connect(*_args, **_kwargs):
        raise ConnectionClosedError(frame, None)

    return _connect


def test_status_during_a_relay_fill_is_reachable(monkeypatch):
    _relay_mode(monkeypatch)
    monkeypatch.setattr(ws_client, "connect", _connect_closing_with(browser.RELAY_BUSY))
    status = browser.browser_status()
    assert status.reachable
    assert "fill running" in status.browser
    assert browser.open_target_ids() is None


def test_a_fill_error_keeps_its_message_while_the_tab_is_attached(monkeypatch):
    _relay_mode(monkeypatch)
    monkeypatch.setattr(ws_client, "connect", _connect_closing_with(browser.RELAY_BUSY))
    assert browser._tab_gone() is False
    monkeypatch.setattr(ws_client, "connect", _connect_closing_with("Extension unavailable"))
    assert browser._tab_gone() is True
    monkeypatch.delenv("BROWSER_MODE")
    assert browser._tab_gone() is False
