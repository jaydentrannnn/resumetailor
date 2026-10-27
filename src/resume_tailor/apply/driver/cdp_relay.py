"""Loopback CDP relay between the app and the browser extension's Fill relay.

Run separately with the same RESUME_TAILOR_DATA_DIR as the app. The advertised CDP URL
contains an ephemeral secret and is printed on startup.

The extension holds one socket (``/extension``) and drives every tab the app opened
through it (`extension/lib/relay.js`); the student's own tabs are never attached. The
app connects as any number of CDP clients at once. A client sees only the tabs it opened
(``/cdp/<secret>``), or one tab it names (``/cdp/<secret>/tab/<targetId>``), and a tab
is leased to one client at a time, so a Fill, a JD fetch and the tab watcher work side
by side without driving the same tab (audit #27, #38, #39). ``?conn=<id>`` names the
connection, so the app can ask afterwards whether its tab went away (`Relay.tabGone`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from resume_tailor.apply.driver.browser import RELAY_BUSY, TAB_GONE
from resume_tailor.web import extension

#: Connections whose tab went away, remembered for the app's `Relay.tabGone` probe.
_GONE_KEPT = 64


@dataclass(eq=False)
class _Client:
    """One CDP client (a Playwright connection from the app)."""

    connection: Any
    conn_id: str
    #: The one existing tab this client may drive ("" = only the tabs it opens).
    scope: str = ""
    browser_session: str = field(default_factory=lambda: uuid.uuid4().hex)
    #: Page session id -> target id, for the tabs this client is attached to.
    sessions: dict[str, str] = field(default_factory=dict)
    auto_attach: bool = False


@dataclass(eq=False)
class _Tab:
    """A tab the app opened through the extension, with its debugger attached."""

    tab_id: int
    info: dict[str, Any]
    owner: _Client | None = None
    #: The app asked to close it: its detach is expected, not a tab gone under a task.
    closing: bool = False


class Relay:
    def __init__(self) -> None:
        self.secret = secrets.token_urlsafe(24)
        self.extension: ServerConnection | None = None
        self.extension_token = ""
        self.tabs: dict[str, _Tab] = {}
        #: Child (iframe) session id -> target id of the tab it belongs to.
        self.children: dict[str, str] = {}
        self.clients: set[_Client] = set()
        self.gone: OrderedDict[str, str] = OrderedDict()
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.next_id = 0

    async def serve_connection(self, connection: ServerConnection) -> None:
        host = connection.request.headers.get("Host", "")
        if host not in {"127.0.0.1:8011", "localhost:8011"}:
            await connection.close(1008, "Loopback Host required")
            return
        parts = urlsplit(connection.request.path)
        prefix = f"/cdp/{self.secret}"
        if parts.path == "/extension":
            origin = connection.request.headers.get("Origin", "")
            if not origin.startswith("chrome-extension://"):
                await connection.close(1008, "Extension origin required")
                return
            await self.handle_extension(connection)
        elif parts.path == prefix or parts.path.startswith(f"{prefix}/tab/"):
            scope = unquote(parts.path[len(f"{prefix}/tab/"):]) if parts.path != prefix else ""
            conn_id = (parse_qs(parts.query).get("conn") or [""])[0] or uuid.uuid4().hex
            await self.handle_client(connection, scope=scope, conn_id=conn_id)
        else:
            await connection.close(1008, "Unknown path")

    # --- the extension side -------------------------------------------------------

    async def handle_extension(self, connection: ServerConnection) -> None:
        if self.extension is not None:
            await connection.close(1008, "Another extension is connected")
            return
        try:
            hello = json.loads(await asyncio.wait_for(connection.recv(), timeout=5))
            if (
                hello.get("type") != "hello"
                or extension.verify_token(hello.get("token", "")) is None
            ):
                await connection.close(1008, "Pair again")
                return
            self.extension = connection
            self.extension_token = hello["token"]
            async for raw in connection:
                if not await self.from_extension(json.loads(raw)):
                    await connection.close(1008, "Pair again")
                    break
        except (ConnectionClosed, TimeoutError, ValueError):
            pass
        finally:
            await self._extension_gone()

    async def from_extension(self, message: dict[str, Any]) -> bool:
        """Handle one extension message; False when its pairing is no longer valid."""
        kind = message.get("type")
        if kind == "response":
            future = self.pending.pop(message.get("id"), None)
            if future and not future.done():
                future.set_result(message)
        elif kind == "event":
            await self._event(message)
        elif kind == "attached":
            # A tab the app opened before the relay restarted, attached again.
            self._adopt(message)
        elif kind == "detached":
            await self._detached(message)
        elif kind == "ping":
            return extension.verify_token(self.extension_token) is not None
        return True

    async def _extension_gone(self) -> None:
        self.extension = None
        self.extension_token = ""
        self.tabs.clear()
        self.children.clear()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError("Extension disconnected"))
        self.pending.clear()
        for client in tuple(self.clients):
            with contextlib.suppress(ConnectionClosed):
                await client.connection.close(1011, "Extension disconnected")

    def _adopt(self, message: dict[str, Any]) -> _Tab | None:
        target, tab_id = message.get("target"), message.get("tabId")
        if (
            not isinstance(target, dict)
            or target.get("type") != "page"
            or not target.get("targetId")
            or not isinstance(tab_id, int)
        ):
            return None
        tab = _Tab(tab_id=tab_id, info=dict(target))
        self.tabs[str(target["targetId"])] = tab
        return tab

    def _tab_for(self, tab_id: Any) -> _Tab | None:
        return next((tab for tab in self.tabs.values() if tab.tab_id == tab_id), None)

    async def _event(self, message: dict[str, Any]) -> None:
        tab = self._tab_for(message.get("tabId"))
        if tab is None:
            return
        target_id = str(tab.info["targetId"])
        method, params = message.get("method"), message.get("params") or {}
        child = message.get("sessionId")
        if method == "Target.attachedToTarget" and params.get("sessionId"):
            self.children[str(params["sessionId"])] = target_id
        elif method == "Target.detachedFromTarget" and params.get("sessionId"):
            self.children.pop(str(params["sessionId"]), None)
        owner = tab.owner
        if owner is None:
            return  # nobody drives this tab right now
        if child:
            await self._send(owner, {"method": method, "params": params, "sessionId": child})
            return
        for session, target in tuple(owner.sessions.items()):
            if target == target_id:
                await self._send(owner, {"method": method, "params": params, "sessionId": session})

    async def _detached(self, message: dict[str, Any]) -> None:
        tab = self._tab_for(message.get("tabId"))
        if tab is None:
            return
        target_id = str(tab.info["targetId"])
        del self.tabs[target_id]
        for child, target in tuple(self.children.items()):
            if target == target_id:
                del self.children[child]
        owner = tab.owner
        if owner is None:
            return
        if not tab.closing:
            self._mark_gone(owner.conn_id)
        for session, target in tuple(owner.sessions.items()):
            if target == target_id:
                del owner.sessions[session]
                await self._send(owner, {
                    "method": "Target.detachedFromTarget",
                    "params": {"sessionId": session, "targetId": target_id},
                })

    def _mark_gone(self, conn_id: str) -> None:
        self.gone[conn_id] = TAB_GONE
        self.gone.move_to_end(conn_id)
        while len(self.gone) > _GONE_KEPT:
            self.gone.popitem(last=False)

    async def request(self, payload: dict[str, Any], *, timeout: float = 30) -> dict[str, Any]:
        """Ask the extension for one thing (a CDP command, a new tab) and await its reply."""
        if not self.extension:
            raise RuntimeError("Extension disconnected")
        self.next_id += 1
        request_id = self.next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.extension.send(json.dumps({**payload, "id": request_id}))
            reply = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.pending.pop(request_id, None)
        if reply.get("error"):
            raise RuntimeError(reply["error"])
        return reply.get("result") or {}

    # --- the app side -------------------------------------------------------------

    async def handle_client(self, connection: Any, *, scope: str = "", conn_id: str = "") -> None:
        client = await self.admit(connection, scope=scope, conn_id=conn_id or uuid.uuid4().hex)
        if client is None:
            return
        try:
            async for raw in connection:
                await self.serve_message(client, json.loads(raw))
        except (ConnectionClosed, ValueError):
            pass
        finally:
            self.release(client)

    async def admit(self, connection: Any, *, scope: str, conn_id: str) -> _Client | None:
        """A new client, holding the lease on its named tab; None (closed) when refused."""
        if not self.extension or extension.verify_token(self.extension_token) is None:
            await connection.close(1008, "Extension unavailable")
            return None
        tab = self.tabs.get(scope) if scope else None
        if tab is not None and tab.owner is not None:
            # Another task drives this tab; `browser` reads this as "attached and in use".
            await connection.close(1013, RELAY_BUSY)
            return None
        client = _Client(connection=connection, conn_id=conn_id, scope=scope)
        if tab is not None:
            tab.owner = client
        self.clients.add(client)
        return client

    def release(self, client: _Client) -> None:
        """A client left: its tabs stay open and attached, free for the next task."""
        self.clients.discard(client)
        for tab in self.tabs.values():
            if tab.owner is client:
                tab.owner = None

    async def serve_message(self, client: _Client, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        session_id = message.get("sessionId")
        try:
            result = await self.command(client, method, message.get("params") or {}, session_id)
            response: dict[str, Any] = {"id": request_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - every failure is a CDP error reply
            response = {"id": request_id, "error": {"message": str(exc)}}
        if session_id:
            response["sessionId"] = session_id
        await self._send(client, response)
        if method == "Target.setAutoAttach" and not session_id:
            client.auto_attach = True
            for tab in tuple(self.tabs.values()):
                if tab.owner is client:
                    await self._attach(client, tab)

    async def _send(self, client: _Client, message: dict[str, Any]) -> None:
        with contextlib.suppress(ConnectionClosed):
            await client.connection.send(json.dumps(message))

    async def _attach(self, client: _Client, tab: _Tab) -> str:
        session = uuid.uuid4().hex
        client.sessions[session] = str(tab.info["targetId"])
        await self._send(client, {
            "method": "Target.attachedToTarget",
            "params": {
                "sessionId": session,
                "targetInfo": {**tab.info, "attached": True},
                "waitingForDebugger": False,
            },
        })
        return session

    def _lease(self, client: _Client, target_id: str) -> _Tab:
        tab = self.tabs.get(target_id)
        if tab is None:
            raise RuntimeError(f"No tab with target id {target_id}")
        if tab.owner is None:
            tab.owner = client
        elif tab.owner is not client:
            raise RuntimeError(RELAY_BUSY)
        return tab

    async def _refresh(self) -> None:
        """Bring each tab's URL and title up to date (they change as the tab navigates)."""
        try:
            rows = (await self.request({"type": "listTabs"}, timeout=5)).get("tabs") or []
        except Exception:  # noqa: BLE001 - the last known URLs stand
            return
        for row in rows:
            tab = self._tab_for(row.get("tabId"))
            if tab is not None:
                tab.info.update(url=str(row.get("url") or ""), title=str(row.get("title") or ""))

    async def command(
        self, client: _Client, method: str, params: dict, session_id: str | None
    ) -> dict:
        if method == "Browser.getVersion":
            return {
                "protocolVersion": "1.3",
                "product": "Chrome/Extension-Bridge",
                "userAgent": "CDP-Bridge/0.2",
                "jsVersion": "",
            }
        if method in {"Browser.setDownloadBehavior", "Target.setDiscoverTargets"}:
            return {}
        if method == "Relay.tabGone":
            return {"gone": self.gone.get(str(params.get("conn") or ""), "")}
        if method == "Target.getTargets":
            await self._refresh()
            return {"targetInfos": [dict(tab.info) for tab in self.tabs.values()]}
        if method == "Target.setAutoAttach" and not session_id:
            return {}
        if method == "Target.attachToBrowserTarget" and not session_id:
            return {"sessionId": client.browser_session}
        if method == "Target.attachToTarget" and session_id in {None, client.browser_session}:
            tab = self._lease(client, str(params.get("targetId") or ""))
            session = uuid.uuid4().hex
            client.sessions[session] = str(tab.info["targetId"])
            return {"sessionId": session}
        if method == "Target.detachFromTarget":
            client.sessions.pop(str(params.get("sessionId") or ""), None)
            return {}
        if method == "Target.getTargetInfo":
            target = client.sessions.get(session_id or "") or self.children.get(session_id or "")
            tab = self.tabs.get(target or str(params.get("targetId") or ""))
            if tab is not None:
                return {"targetInfo": {**tab.info, "attached": True}}
            return {"targetInfo": {"targetId": "browser", "type": "browser", "title": "",
                                   "url": "", "attached": True}}
        if method == "Target.createTarget":
            # A new background tab in the student's browser, leased to this client.
            created = await self.request({"type": "createTab", "url": params.get("url") or ""})
            tab = self._adopt(created)
            if tab is None:
                raise RuntimeError("The extension did not open a tab")
            tab.owner = client
            if client.auto_attach:
                # Before the reply, as Chrome does: Playwright looks the page up by then.
                await self._attach(client, tab)
            return {"targetId": tab.info["targetId"]}
        if method == "Target.closeTarget":
            tab = self.tabs.get(str(params.get("targetId") or ""))
            if tab is None:
                return {"success": False}
            tab.closing = True
            try:
                await self.request({"type": "closeTab", "tabId": tab.tab_id})
            except RuntimeError:
                tab.closing = False
                return {"success": False}
            return {"success": True}
        if not session_id:
            raise RuntimeError(f"Unsupported browser command: {method}")
        child = None
        target = client.sessions.get(session_id)
        if target is None:
            target, child = self.children.get(session_id), session_id
        if target is None:
            raise RuntimeError("Session closed")
        tab = self._lease(client, target)
        return await self.request({
            "type": "command", "tabId": tab.tab_id, "method": method,
            "params": params, "sessionId": child,
        })


async def main() -> None:
    relay = Relay()
    async with serve(relay.serve_connection, "127.0.0.1", 8011, ping_interval=20, ping_timeout=20):
        print(f"Relay CDP URL: ws://127.0.0.1:8011/cdp/{relay.secret}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
