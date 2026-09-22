"""CDP connection to the user's host browser (Edge recommended — see README) for
JD fetch and form fill.

Sync Playwright only — call from a worker thread, never the asyncio event loop.

Chromium's DevTools HTTP endpoint rejects a ``Host`` header that is neither an IP
nor ``localhost``. From Docker, ``CHROME_CDP_URL`` is typically
``http://host.docker.internal:9222``, which fails that check — so we resolve
the hostname to an IP before probing or connecting.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager
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


def effective_cdp_url(cdp_url: str | None = None) -> str:
    """Return a CDP base URL Chrome will accept from this process.

    Resolves ``host.docker.internal`` (and similar gateway names) to an IP so
    the HTTP ``Host`` header is an address Chrome allows. Leaves ``localhost`` /
    literal IPs unchanged.
    """
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


@contextmanager
def cdp_browser() -> Iterator[Any]:
    """Connect to the host browser over CDP; yield a Playwright ``Browser``.

    Raises ``RuntimeError`` with a clear message when the endpoint is unreachable.
    """
    status = browser_status()
    if not status.reachable:
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
        finally:
            browser.close()


def cdp_http_origin() -> str:
    """Return the HTTP origin used for ``/json/version`` probes."""
    parsed = urlparse(effective_cdp_url())
    return f"{parsed.scheme}://{parsed.netloc}"
