"""Hermetic protocol checks for the multi-tab CDP relay (audit #27, #38, #39)."""

import json

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close
from websockets.sync import client as ws_client

from resume_tailor.apply.driver import browser, cdp_relay
from resume_tailor.apply.driver.cdp_relay import Relay

#: The real one: `conftest._no_tab_closing` stubs it for every test.
_CLOSE_TARGET = browser.close_target


class _Conn:
    """A client or extension socket that records what the relay sends it."""

    def __init__(self):
        self.closed = None
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self, code, reason):
        self.closed = (code, reason)

    def events(self, method):
        return [m for m in self.sent if m.get("method") == method]


class _Extension(_Conn):
    """Answers the relay's requests at once, like `extension/lib/relay.js`."""

    def __init__(self, relay):
        super().__init__()
        self.relay = relay
        self.next_tab = 10

    async def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        if message["type"] == "createTab":
            tab_id, self.next_tab = self.next_tab, self.next_tab + 1
            result = {"tabId": tab_id, "target": _info(f"T{tab_id}")}
        elif message["type"] == "closeTab":
            result = {}
        elif message["type"] == "listTabs":
            result = {"tabs": [{"tabId": 1, "url": "https://jobs.example/applied", "title": "Done"}]}
        else:
            result = {"echo": message["method"], "tab": message["tabId"]}
        self.relay.pending[message["id"]].set_result(
            {"type": "response", "id": message["id"], "result": result}
        )


def _info(target_id, url="https://jobs.example/1"):
    return {"targetId": target_id, "type": "page", "url": url, "title": "Job", "attached": True}


@pytest.fixture
def relay(monkeypatch):
    monkeypatch.setattr(cdp_relay.extension, "verify_token", lambda _token: object())
    relay = Relay()
    relay.extension = _Extension(relay)
    relay.extension_token = "token"
    relay.tabs = {}
    return relay


async def _client(relay, scope=""):
    conn = _Conn()
    client = await relay.admit(conn, scope=scope, conn_id=f"conn-{scope or 'new'}")
    return conn, client


async def _auto_attach(relay, client):
    await relay.serve_message(client, {"id": 1, "method": "Target.setAutoAttach", "params": {}})


@pytest.mark.asyncio
async def test_each_client_drives_only_its_own_tab(relay):
    relay._adopt({"tabId": 1, "target": _info("A")})
    relay._adopt({"tabId": 2, "target": _info("B")})
    first, a = await _client(relay, "A")
    second, b = await _client(relay, "B")
    await _auto_attach(relay, a)
    await _auto_attach(relay, b)
    [attached_a] = first.events("Target.attachedToTarget")
    [attached_b] = second.events("Target.attachedToTarget")
    assert attached_a["params"]["targetInfo"]["targetId"] == "A"
    assert attached_b["params"]["targetInfo"]["targetId"] == "B"

    session_a = attached_a["params"]["sessionId"]
    reply = await relay.command(a, "Runtime.evaluate", {}, session_a)
    assert reply == {"echo": "Runtime.evaluate", "tab": 1}

    # A tab's events reach only the client driving it, on that client's session.
    await relay.from_extension({"type": "event", "tabId": 2, "method": "Page.loadEventFired"})
    assert first.events("Page.loadEventFired") == []
    [event] = second.events("Page.loadEventFired")
    assert event["sessionId"] == attached_b["params"]["sessionId"]

    # Another client asking for a tab in use is turned away; the tab stays leased.
    probe = _Conn()
    assert await relay.admit(probe, scope="A", conn_id="x") is None
    assert probe.closed == (1013, browser.RELAY_BUSY)
    with pytest.raises(RuntimeError, match=browser.RELAY_BUSY):
        await relay.command(b, "Target.attachToTarget", {"targetId": "A"}, None)
    relay.release(a)
    assert relay.tabs["A"].owner is None


@pytest.mark.asyncio
async def test_a_new_page_is_a_new_background_tab_attached_before_the_reply(relay):
    conn, client = await _client(relay)
    await _auto_attach(relay, client)
    assert conn.events("Target.attachedToTarget") == []  # the student's tabs are not shown
    await relay.serve_message(client, {"id": 7, "method": "Target.createTarget",
                                       "params": {"url": "about:blank"}})
    attached = next(i for i, m in enumerate(conn.sent) if m.get("method") == "Target.attachedToTarget")
    replied = next(i for i, m in enumerate(conn.sent) if m.get("id") == 7)
    assert attached < replied  # Playwright looks the page up as soon as the reply comes
    assert conn.sent[replied]["result"] == {"targetId": "T10"}
    assert relay.tabs["T10"].owner is client
    assert relay.extension.sent[-1]["type"] == "createTab"

    # Target ids come back through a session of its own (`browser.target_id`).
    browser_session = (await relay.command(client, "Target.attachToBrowserTarget", {}, None))["sessionId"]
    probe = (await relay.command(client, "Target.attachToTarget", {"targetId": "T10"}, browser_session))
    info = await relay.command(client, "Target.getTargetInfo", {}, probe["sessionId"])
    assert info["targetInfo"]["targetId"] == "T10"


@pytest.mark.asyncio
async def test_closing_an_app_tab_is_expected_and_a_vanished_tab_is_remembered(relay):
    conn, client = await _client(relay)
    await _auto_attach(relay, client)
    await relay.command(client, "Target.createTarget", {}, None)
    await relay.command(client, "Target.createTarget", {}, None)
    assert await relay.command(client, "Target.closeTarget", {"targetId": "T10"}, None) == {"success": True}
    await relay.from_extension({"type": "detached", "tabId": 10, "reason": "target_closed"})
    assert [m["params"]["targetId"] for m in conn.events("Target.detachedFromTarget")] == ["T10"]
    gone = await relay.command(client, "Relay.tabGone", {"conn": "conn-new"}, None)
    assert gone == {"gone": ""}

    # The student closes the other one (or opens DevTools) under the task.
    await relay.from_extension({"type": "detached", "tabId": 11, "reason": "target_closed"})
    gone = await relay.command(client, "Relay.tabGone", {"conn": "conn-new"}, None)
    assert gone == {"gone": browser.TAB_GONE}
    assert relay.tabs == {}
    assert await relay.command(client, "Target.closeTarget", {"targetId": "T11"}, None) == {"success": False}


@pytest.mark.asyncio
async def test_targets_list_every_app_tab_with_its_current_url(relay):
    relay._adopt({"tabId": 1, "target": _info("A")})
    relay._adopt({"tabId": 2, "target": _info("B")})
    _conn, owner = await _client(relay, "A")
    _conn, probe = await _client(relay)
    infos = (await relay.command(probe, "Target.getTargets", {}, None))["targetInfos"]
    assert {(i["targetId"], i["url"]) for i in infos} == {
        ("A", "https://jobs.example/applied"), ("B", "https://jobs.example/1"),
    }
    assert relay.tabs["A"].owner is owner  # listing holds nothing


@pytest.mark.asyncio
async def test_iframe_sessions_route_to_their_tab(relay):
    relay._adopt({"tabId": 1, "target": _info("A")})
    conn, client = await _client(relay, "A")
    await _auto_attach(relay, client)
    await relay.from_extension({
        "type": "event", "tabId": 1, "method": "Target.attachedToTarget",
        "params": {"sessionId": "child", "targetInfo": {"type": "iframe"}},
    })
    await relay.from_extension({"type": "event", "tabId": 1, "sessionId": "child",
                                "method": "Runtime.executionContextCreated"})
    assert conn.events("Runtime.executionContextCreated")[0]["sessionId"] == "child"
    await relay.command(client, "Runtime.evaluate", {}, "child")
    assert relay.extension.sent[-1]["sessionId"] == "child"
    assert relay.extension.sent[-1]["tabId"] == 1


@pytest.mark.asyncio
async def test_clients_need_a_connected_extension(relay):
    relay.extension = None
    probe = _Conn()
    assert await relay.admit(probe, scope="", conn_id="x") is None
    assert probe.closed == (1008, "Extension unavailable")


def _relay_mode(monkeypatch):
    monkeypatch.setenv("BROWSER_MODE", "extension")
    monkeypatch.setenv("EXTENSION_CDP_URL", "ws://127.0.0.1:8011/cdp/secret")


def test_connections_name_their_tab_and_themselves(monkeypatch):
    _relay_mode(monkeypatch)
    assert browser._relay_endpoint() == "ws://127.0.0.1:8011/cdp/secret"
    assert browser._relay_endpoint("T/1", "c1") == "ws://127.0.0.1:8011/cdp/secret/tab/T%2F1?conn=c1"


def _connect_closing_with(reason):
    frame = Close(1013, reason)

    def _connect(*_args, **_kwargs):
        raise ConnectionClosedError(frame, None)

    return _connect


def test_status_with_a_busy_tab_is_reachable(monkeypatch):
    _relay_mode(monkeypatch)
    monkeypatch.setattr(ws_client, "connect", _connect_closing_with(browser.RELAY_BUSY))
    status = browser.browser_status()
    assert status.reachable
    assert browser.open_target_ids() is None


def test_the_tab_gone_probe_asks_the_relay_about_this_connection(monkeypatch):
    _relay_mode(monkeypatch)
    asked = []

    def _call(method, params=None):
        asked.append((method, params))
        return {"gone": browser.TAB_GONE if params["conn"] == "lost" else ""}

    monkeypatch.setattr(browser, "_relay_call", _call)
    assert browser._tab_gone("lost") is True
    assert browser._tab_gone("fine") is False
    assert asked[0] == ("Relay.tabGone", {"conn": "lost"})

    def _down(*_args, **_kwargs):
        raise OSError("refused")

    monkeypatch.setattr(browser, "_relay_call", _down)
    assert browser._tab_gone("any") is True  # the extension left: its tabs went with it
    monkeypatch.delenv("BROWSER_MODE")
    assert browser._tab_gone("any") is False


def test_close_target_asks_the_relay_in_extension_mode(monkeypatch):
    _relay_mode(monkeypatch)
    calls = []
    monkeypatch.setattr(browser, "_relay_call", lambda method, params=None: calls.append(
        (method, params)) or {"success": params["targetId"] == "APP"})
    assert _CLOSE_TARGET("APP") is True
    assert _CLOSE_TARGET("MINE") is False
    assert calls[0] == ("Target.closeTarget", {"targetId": "APP"})
