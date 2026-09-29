"""Request gate for the local server: Host check, cross-site write check, optional token.

The app has no accounts and serves real PII (the master resume, the applicant
profile), so it only answers requests that come from the user's own browser tab.

- **Host allow-list** (always on). A page on any website can point a hostname it
  controls at 127.0.0.1 (DNS rebinding) and then read this API as "same origin". The
  browser still sends that hostname in ``Host``, so anything other than a loopback name
  is refused. ``RESUME_TAILOR_ALLOWED_HOSTS`` (comma-separated, ``*`` for any) adds
  names, e.g. the Cloudflare tunnel's public hostname.
- **Cross-site writes** (always on). A non-GET request whose ``Origin`` is not an
  allowed host, or that the browser marks ``Sec-Fetch-Site: cross-site``, is refused.
  Without CORS a foreign page cannot read responses, but a plain form POST would still
  be delivered.
- **Session token** (opt-in, ``RESUME_TAILOR_TOKEN``: a value, or ``auto`` for a random
  one per start). ``/api/*`` then needs the ``rt_session`` cookie or an ``X-RT-Token``
  header. Opening ``/?t=<token>`` sets the cookie. The token is also written to
  ``<DATA_ROOT>/.session_token`` (0600) for the MCP server and CLI clients. The desktop
  build turns this on; other local processes can read the data folder anyway, so it
  matters most when the port is reachable by someone else.
- **Extension lane** (``/api/extension/*``, plan P4-X). The paired browser extension
  calls from a ``chrome-extension://`` origin with no cookie, so these paths skip the two
  checks above and instead need the pairing token in ``X-RT-Extension``
  (`web/extension.py`); only ``/api/extension/pair/complete``, which trades a
  6-digit code for that token, is open. Their ``Origin`` must be an extension or an
  allowed host, so a web page cannot use them even with a stolen token.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from resume_tailor import config
from resume_tailor.web import extension

COOKIE_NAME = "rt_session"
HEADER_NAME = "x-rt-token"
TOKEN_FILE_NAME = ".session_token"
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Answered without the token: liveness only, no data (container healthcheck, and the
#: browser extension finding which port the app is on).
_PUBLIC_PATHS = frozenset({"/api/health"})

_EXTENSION_PREFIX = "/api/extension/"
_EXTENSION_OPEN = frozenset({"/api/extension/pair/complete"})
_EXTENSION_SCHEMES = frozenset({"chrome-extension", "moz-extension", "safari-web-extension"})

_auto_token: str | None = None


def session_token() -> str | None:
    """The token requests must carry, or None when the token check is off."""
    global _auto_token
    raw = os.environ.get("RESUME_TAILOR_TOKEN", "").strip()
    if not raw or raw.lower() in {"off", "0", "none"}:
        return None
    if raw.lower() == "auto":
        if _auto_token is None:
            _auto_token = secrets.token_urlsafe(32)
        return _auto_token
    return raw


def token_file() -> Path:
    return config.DATA_ROOT / TOKEN_FILE_NAME


def write_token_file(token: str) -> Path:
    """Publish the token for local clients (MCP server, CLI), readable by the user only."""
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    tmp.replace(path)
    return path


def read_client_token() -> str | None:
    """Token a local client should send: the env value, else the server's token file."""
    raw = os.environ.get("RESUME_TAILOR_TOKEN", "").strip()
    if raw and raw.lower() not in {"auto", "off", "0", "none"}:
        return raw
    try:
        value = token_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _allowed_hosts() -> tuple[frozenset[str], bool]:
    extra = {
        name.strip().lower()
        for name in os.environ.get("RESUME_TAILOR_ALLOWED_HOSTS", "").split(",")
        if name.strip()
    }
    return _LOOPBACK | extra, "*" in extra


def hostname(value: str) -> str:
    """The name part of a ``Host`` header or URL netloc: no port, no IPv6 brackets."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}


async def _send_json(send, status: int, body: dict[str, Any], headers=()) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            *headers,
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class RequestGateMiddleware:
    """Raw ASGI middleware applying the three checks in the module docstring."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        allowed, any_host = _allowed_hosts()

        host = hostname(headers.get("host", ""))
        if not any_host and host not in allowed:
            await _send_json(send, 400, {
                "error": "host",
                "detail": (
                    f"Host {host!r} is not allowed. If you reach the app through this "
                    "name, add it to RESUME_TAILOR_ALLOWED_HOSTS."
                ),
            })
            return

        path = scope.get("path", "")
        if path.startswith(_EXTENSION_PREFIX):
            await self._extension_lane(scope, receive, send, headers, path, allowed, any_host)
            return

        method = scope.get("method", "GET")
        if scope["type"] == "http" and method not in _SAFE_METHODS:
            origin = headers.get("origin")
            cross_site = headers.get("sec-fetch-site") == "cross-site"
            origin_host = hostname(urlsplit(origin).netloc) if origin and origin != "null" else ""
            bad_origin = origin is not None and (
                origin == "null" or (not any_host and origin_host not in allowed)
            )
            if cross_site or bad_origin:
                await _send_json(send, 403, {
                    "error": "origin",
                    "detail": "Cross-site requests are not accepted.",
                })
                return

        token = session_token()
        if token is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and path == "/" and method == "GET":
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            offered = (query.get("t") or [""])[0]
            if offered and hmac.compare_digest(offered, token):
                cookie = (
                    f"{COOKIE_NAME}={token}; HttpOnly; SameSite=Strict; Path=/"
                ).encode("latin-1")
                # `?v=<version>` is a fresh cache key for `/`, so a webview holding a
                # stale index.html from an older release loads the new one exactly once
                # (the SPA strips the param on boot).
                from resume_tailor.web.routes.diagnostics import _version

                location = f"/?v={quote(_version(), safe='')}".encode("latin-1")
                await send({
                    "type": "http.response.start",
                    "status": 303,
                    "headers": [(b"location", location), (b"set-cookie", cookie),
                                (b"content-length", b"0")],
                })
                await send({"type": "http.response.body", "body": b""})
                return
        if (
            path.startswith("/api/")
            and path not in _PUBLIC_PATHS
            and not self._authorised(headers, token)
        ):
            await _send_json(send, 401, {
                "error": "auth",
                "detail": "Session expired or missing. Reopen ResumeTailor from its "
                "window, or open the link printed when the server started.",
            })
            return
        await self.app(scope, receive, send)

    async def _extension_lane(
        self, scope, receive, send, headers, path, allowed, any_host
    ) -> None:
        origin = headers.get("origin")
        if origin is not None:
            parts = urlsplit(origin)
            ok = parts.scheme in _EXTENSION_SCHEMES or (
                origin != "null" and (any_host or hostname(parts.netloc) in allowed)
            )
            if not ok:
                await _send_json(send, 403, {
                    "error": "origin",
                    "detail": "Only the paired browser extension may call this.",
                })
                return
        token = headers.get(extension.HEADER_NAME, "")
        if path not in _EXTENSION_OPEN and extension.verify_token(token) is None:
            await _send_json(send, 401, {
                "error": "extension_auth",
                "detail": "This browser is not paired. Pair it again from "
                "ResumeTailor Settings → Browser.",
            })
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _authorised(headers: dict[str, str], token: str) -> bool:
        offered = headers.get(HEADER_NAME, "")
        if offered and hmac.compare_digest(offered, token):
            return True
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("cookie", ""))
        except Exception:  # noqa: BLE001 - a malformed Cookie header is just "no cookie"
            return False
        morsel = cookies.get(COOKIE_NAME)
        return bool(morsel and hmac.compare_digest(morsel.value, token))
