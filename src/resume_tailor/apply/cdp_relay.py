"""Experimental loopback CDP relay for the browser-extension spike.

Run separately with the same RESUME_TAILOR_DATA_DIR as the app. The advertised
CDP URL contains an ephemeral secret and is printed on startup. This prototype
is intentionally outside the default CDP browser path.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from resume_tailor.web import extension


class Relay:
    def __init__(self) -> None:
        self.secret = secrets.token_urlsafe(24)
        self.extension: ServerConnection | None = None
        self.extension_token = ""
        self.client: ServerConnection | None = None
        self.target: dict[str, Any] | None = None
        self.session_id = uuid.uuid4().hex
        self.browser_session_id = uuid.uuid4().hex
        self.page_sessions = {self.session_id}
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.next_id = 0

    async def serve_connection(self, connection: ServerConnection) -> None:
        path = connection.request.path
        host = connection.request.headers.get("Host", "")
        if host not in {"127.0.0.1:8011", "localhost:8011"}:
            await connection.close(1008, "Loopback Host required")
            return
        if path == "/extension":
            origin = connection.request.headers.get("Origin", "")
            if not origin.startswith("chrome-extension://"):
                await connection.close(1008, "Extension origin required")
                return
            await self.handle_extension(connection)
        elif path == f"/cdp/{self.secret}":
            await self.handle_client(connection)
        else:
            await connection.close(1008, "Unknown path")

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
            target = hello.get("target")
            if (
                not isinstance(target, dict)
                or target.get("type") != "page"
                or not target.get("targetId")
            ):
                await connection.close(1008, "Page target required")
                return
            self.extension = connection
            self.extension_token = hello["token"]
            self.target = target
            self.session_id = uuid.uuid4().hex
            self.browser_session_id = uuid.uuid4().hex
            self.page_sessions = {self.session_id}
            async for raw in connection:
                message = json.loads(raw)
                if message.get("type") == "response":
                    future = self.pending.pop(message.get("id"), None)
                    if future and not future.done():
                        future.set_result(message)
                elif message.get("type") == "event" and self.client:
                    for session in tuple(self.page_sessions):
                        event = {"method": message["method"], "params": message.get("params") or {}}
                        event["sessionId"] = session
                        await self.client.send(json.dumps(event))
                elif message.get("type") == "detached":
                    if self.client:
                        await self.client.close(1011, "Tab was closed or DevTools opened")
                    break
                elif message.get("type") == "ping" and not extension.verify_token(
                    self.extension_token
                ):
                    await connection.close(1008, "Pair again")
                    break
        except (ConnectionClosed, TimeoutError, ValueError):
            pass
        finally:
            self.extension = None
            self.extension_token = ""
            self.target = None
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Extension disconnected"))
            self.pending.clear()
            if self.client:
                await self.client.close(1011, "Extension disconnected")

    async def forward(self, method: str, params: dict[str, Any], session_id: str | None) -> dict:
        if not self.extension:
            raise RuntimeError("Extension disconnected")
        self.next_id += 1
        command_id = self.next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[command_id] = future
        await self.extension.send(
            json.dumps(
                {
                    "type": "command",
                    "id": command_id,
                    "method": method,
                    "params": params,
                    "sessionId": None if session_id in self.page_sessions else session_id,
                }
            )
        )
        try:
            reply = await asyncio.wait_for(future, timeout=30)
        finally:
            self.pending.pop(command_id, None)
        if reply.get("error"):
            raise RuntimeError(reply["error"])
        return reply.get("result") or {}

    async def handle_client(self, connection: ServerConnection) -> None:
        if (
            self.client
            or not self.extension
            or not self.target
            or extension.verify_token(self.extension_token) is None
        ):
            await connection.close(1008, "Extension unavailable or client already connected")
            return
        self.client = connection
        try:
            async for raw in connection:
                message = json.loads(raw)
                request_id = message.get("id")
                method = message.get("method")
                params = message.get("params") or {}
                session_id = message.get("sessionId")
                try:
                    result = await self.command(method, params, session_id)
                    response = {"id": request_id, "result": result}
                except Exception as exc:
                    response = {"id": request_id, "error": {"message": str(exc)}}
                if session_id:
                    response["sessionId"] = session_id
                await connection.send(json.dumps(response))
                if method == "Target.setAutoAttach" and not session_id:
                    await connection.send(
                        json.dumps(
                            {
                                "method": "Target.attachedToTarget",
                                "params": {
                                    "sessionId": self.session_id,
                                    "targetInfo": self.target,
                                    "waitingForDebugger": False,
                                },
                            }
                        )
                    )
        except (ConnectionClosed, ValueError):
            pass
        finally:
            self.client = None

    async def command(self, method: str, params: dict, session_id: str | None) -> dict:
        if method == "Browser.getVersion":
            return {
                "protocolVersion": "1.3",
                "product": "Chrome/Extension-Bridge",
                "userAgent": "CDP-Bridge/0.1",
                "jsVersion": "",
            }
        if method == "Browser.setDownloadBehavior":
            return {}
        if method == "Target.setDiscoverTargets":
            return {}
        if method == "Target.getTargets":
            return {"targetInfos": [self.target]}
        if method == "Target.setAutoAttach" and not session_id:
            return {}
        if method == "Target.attachToTarget" and session_id in {None, self.browser_session_id}:
            if session_id is None:
                return {"sessionId": self.session_id}
            attached_session = uuid.uuid4().hex
            self.page_sessions.add(attached_session)
            return {"sessionId": attached_session}
        if method == "Target.attachToBrowserTarget" and not session_id:
            return {"sessionId": self.browser_session_id}
        if method == "Target.detachFromTarget":
            self.page_sessions.discard(params.get("sessionId"))
            return {}
        if method == "Target.getTargetInfo":
            return {"targetInfo": self.target}
        if method == "Target.createTarget":
            # Fill's new-page path reuses the tab explicitly attached by the user.
            return {"targetId": self.target["targetId"]}
        if method == "Target.closeTarget":
            return {"success": False}
        if not session_id:
            raise RuntimeError(f"Unsupported browser command: {method}")
        return await self.forward(method, params, session_id)


async def main() -> None:
    relay = Relay()
    async with serve(relay.serve_connection, "127.0.0.1", 8011, ping_interval=20, ping_timeout=20):
        print(f"Relay CDP URL: ws://127.0.0.1:8011/cdp/{relay.secret}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
