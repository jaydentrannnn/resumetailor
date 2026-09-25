"""CDP connection to the user's host browser (Edge recommended — see README) for
JD fetch and form fill.

The legacy filler uses synchronous Playwright from a worker thread. The gated
verified engine and review actions use the async CDP connection below.

Chromium's DevTools HTTP endpoint rejects a ``Host`` header that is neither an IP
nor ``localhost``. From Docker, ``CHROME_CDP_URL`` is typically
``http://host.docker.internal:9222``, which fails that check — so we resolve
the hostname to an IP before probing or connecting.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from resume_tailor import config


@dataclass
class BrowserStatus:
    """Reachability of the configured host browser's CDP endpoint."""

    reachable: bool
    browser: str = ""
    user_agent: str = ""
    error: str = ""
    cdp_url: str = ""


#: Close reason the extension relay (`cdp_relay.py`) sends a second client while a fill
#: holds the one connection it allows: the relay and tab are fine, just in use.
RELAY_BUSY = "Relay busy: a fill is connected"
TAB_GONE = "Tab was closed or DevTools opened"


def extension_mode() -> bool:
    """True when fills drive the extension's selected tab through the relay."""
    return os.environ.get("BROWSER_MODE", "cdp").lower() == "extension"


def _relay_call(method: str) -> dict[str, Any]:
    """One CDP browser-level command to the relay on a short-lived connection."""
    from websockets.sync.client import connect

    with connect(effective_cdp_url(), open_timeout=2, close_timeout=1) as connection:
        connection.send(json.dumps({"id": 1, "method": method}))
        reply = json.loads(connection.recv(timeout=2))
    if reply.get("error"):
        raise RuntimeError(reply["error"].get("message", "Relay rejected connection"))
    return reply["result"]


def _relay_busy(exc: BaseException) -> bool:
    received = getattr(exc, "rcvd", None)
    return getattr(received, "reason", "") == RELAY_BUSY


def effective_cdp_url(cdp_url: str | None = None) -> str:
    """Return a CDP base URL Chrome will accept from this process.

    Resolves ``host.docker.internal`` (and similar gateway names) to an IP so
    the HTTP ``Host`` header is an address Chrome allows. Leaves ``localhost`` /
    literal IPs unchanged.
    """
    if extension_mode():
        endpoint = os.environ.get("EXTENSION_CDP_URL", "").strip()
        if not endpoint.startswith("ws://127.0.0.1:"):
            raise RuntimeError("Set EXTENSION_CDP_URL to the loopback relay WebSocket endpoint")
        return endpoint
    raw = (cdp_url or config.CHROME_CDP_URL).rstrip("/")
    parsed = urlparse(raw)
    host = parsed.hostname or ""
    if not host or host.lower() in {"localhost", "127.0.0.1", "::1"}:
        return raw
    # Already an IPv4/IPv6 literal — Chrome accepts these as Host.
    try:
        socket.inet_pton(socket.AF_INET, host)
        return raw
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host.strip("[]"))
        return raw
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return raw
    netloc = ip
    if parsed.port:
        netloc = f"{ip}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc)).rstrip("/")


def browser_status() -> BrowserStatus:
    """Probe ``CHROME_CDP_URL/json/version`` with a short timeout."""
    if extension_mode():
        endpoint = os.environ.get("EXTENSION_CDP_URL", "")
        try:
            product = _relay_call("Browser.getVersion")["product"]
            return BrowserStatus(reachable=True, browser=product, cdp_url=endpoint)
        except Exception as exc:  # noqa: BLE001 - a stopped relay is normal
            if _relay_busy(exc):
                # A fill holds the relay's only connection; the tab is attached.
                return BrowserStatus(
                    reachable=True, browser="Extension relay (fill running)", cdp_url=endpoint
                )
            return BrowserStatus(reachable=False, error=str(exc), cdp_url=endpoint)
    configured = config.CHROME_CDP_URL.rstrip("/")
    cdp = effective_cdp_url(configured)
    try:
        # CDP HTTP is plain JSON on /json/version — not the Playwright WebSocket.
        resp = httpx.get(f"{cdp}/json/version", timeout=1.0)
        resp.raise_for_status()
        data = resp.json()
        return BrowserStatus(
            reachable=True,
            browser=str(data.get("Browser") or ""),
            user_agent=str(data.get("User-Agent") or ""),
            cdp_url=configured,
        )
    except Exception as exc:  # noqa: BLE001 - surface any connection failure cleanly
        return BrowserStatus(reachable=False, error=str(exc), cdp_url=configured)


def open_target_ids() -> set[str] | None:
    """Target ids of the browser's open tabs, or ``None`` when it is unreachable.

    ``/json/list`` ids are the same targetIds ``target_id`` records, so this tells
    whether a retained application tab still exists — one HTTP call, no Playwright,
    safe while a fill owns the browser. ``None`` means unknown, not "no tabs".
    """
    if extension_mode():
        try:
            infos = _relay_call("Target.getTargets")["targetInfos"]
        except Exception:  # noqa: BLE001 - unknown (or busy) is safer than an empty list
            return None
        return {str(row["targetId"]) for row in infos if row.get("type") == "page"}
    try:
        resp = httpx.get(f"{effective_cdp_url()}/json/list", timeout=1.0)
        resp.raise_for_status()
        targets = resp.json()
    except Exception:  # noqa: BLE001 - unreachable browser is an expected state
        return None
    if not isinstance(targets, list):
        return None
    return {
        str(target["id"]) for target in targets
        if isinstance(target, dict) and target.get("type") == "page" and target.get("id")
    }


def _tab_gone() -> bool:
    """After a fill error in relay mode: did the selected tab go away?

    The relay drops the fill's connection when the tab closes or DevTools opens, so a
    probe then finds no tab. While the fill is still connected the probe gets
    `RELAY_BUSY`, which reads as reachable, and the original error stands.
    """
    return extension_mode() and not browser_status().reachable


@contextmanager
def cdp_browser() -> Iterator[Any]:
    """Connect to the host browser over CDP; yield a Playwright ``Browser``.

    Raises ``RuntimeError`` with a clear message when the endpoint is unreachable.
    """
    status = browser_status()
    if not status.reachable:
        if extension_mode():
            raise RuntimeError(
                f"Extension relay unavailable at {status.cdp_url}: {status.error}. "
                "Start the relay and choose Use this tab for Fill in the extension."
            )
        raise RuntimeError(
            f"Browser CDP unreachable at {status.cdp_url}: {status.error}. "
            "Launch a debug-enabled browser (Edge recommended) with "
            "--remote-debugging-port=9222 and a dedicated --user-data-dir "
            "(see README Automation)."
        )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed. pip install playwright "
            "(Chromium download is not required for CDP)."
        ) from exc

    # sync_playwright must not run on a thread that already has an asyncio loop.
    connect_url = effective_cdp_url(config.CHROME_CDP_URL)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        try:
            yield browser
        except Exception as exc:
            if _tab_gone():
                raise RuntimeError(TAB_GONE) from exc
            raise
        finally:
            browser.close()


def cdp_http_origin() -> str:
    """Return the HTTP origin used for ``/json/version`` probes."""
    parsed = urlparse(effective_cdp_url())
    return f"{parsed.scheme}://{parsed.netloc}"


def target_id(context: Any, page: Any) -> str:
    """Read a stable CDP target id for a page without changing browser focus."""
    session = context.new_cdp_session(page)
    try:
        info = session.send("Target.getTargetInfo")
        return str(info.get("targetInfo", {}).get("targetId") or "")
    finally:
        session.detach()


def find_target(context: Any, expected_id: str) -> Any | None:
    """Return the existing tab; URLs are insufficient because postings can repeat."""
    if not expected_id:
        return None
    for page in context.pages:
        if page.is_closed():
            continue
        try:
            if target_id(context, page) == expected_id:
                return page
        except Exception:  # noqa: BLE001
            continue
    return None


def focus_target(expected_id: str) -> str:
    """Focus a recorded application tab and return its current URL."""
    with cdp_browser() as connected:
        for context in connected.contexts:
            page = find_target(context, expected_id)
            if page is not None:
                page.bring_to_front()
                return str(page.url)
    raise RuntimeError("The review tab is closed. Use Reopen and fill if you want to start again.")


@asynccontextmanager
async def async_cdp_browser():
    """Async CDP connection for the deadline-bounded verified Apply engine."""
    status = browser_status()
    if not status.reachable:
        raise RuntimeError(f"Browser CDP unreachable at {status.cdp_url}: {status.error}")
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is not installed") from exc
    async with async_playwright() as playwright:
        connected = await playwright.chromium.connect_over_cdp(effective_cdp_url())
        try:
            yield connected
        except Exception as exc:
            if _tab_gone():
                raise RuntimeError(TAB_GONE) from exc
            raise
        finally:
            await connected.close()


async def async_target_id(context: Any, page: Any) -> str:
    """Read a stable CDP target id without bringing its tab forward."""
    session = await context.new_cdp_session(page)
    try:
        info = await session.send("Target.getTargetInfo")
        return str(info.get("targetInfo", {}).get("targetId") or "")
    finally:
        await session.detach()


async def async_find_target(context: Any, expected_id: str) -> Any | None:
    """Reconnect to an existing tab by target id, never by a repeated URL."""
    if not expected_id:
        return None
    for page in context.pages:
        if page.is_closed():
            continue
        try:
            if await async_target_id(context, page) == expected_id:
                return page
        except Exception:  # noqa: BLE001
            continue
    return None


async def open_background_page(connected: Any, context: Any, *, timeout: float = 10) -> tuple[Any, str]:
    """Create a CDP tab without deliberately activating it over a review tab."""
    session = await connected.new_browser_cdp_session()
    try:
        created = await session.send("Target.createTarget", {"url": "about:blank", "background": True})
        expected_id = str(created.get("targetId") or "")
    finally:
        await session.detach()
    if not expected_id:
        raise RuntimeError("Browser did not return a target id for the new tab")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        page = await async_find_target(context, expected_id)
        if page is not None:
            return page, expected_id
        await asyncio.sleep(0.1)
    raise TimeoutError("New background application tab did not appear")
