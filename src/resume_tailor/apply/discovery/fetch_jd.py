"""Fetch job-description text from an ATS posting URL.

Tries plain HTTP first; falls back to the host browser over CDP when the page is
a JS shell. Never invents content — empty extraction becomes ``needs_browser``.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlparse

import httpx

from resume_tailor.apply.driver.browser import cdp_browser
from resume_tailor.apply.forms import form_guards

#: Minimum extracted characters before we trust an HTTP response as a real JD.
_MIN_JD_CHARS = 400

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

AtsName = Literal[
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "icims",
    "smartrecruiters",
    "taleo",
    "successfactors",
    "oracle",
    "jobvite",
    "bamboohr",
    "linkedin",
    "indeed",
    "handshake",
    "other",
    "unknown",
]


@dataclass
class FetchResult:
    """Outcome of fetching one posting URL."""

    final_url: str
    ats: AtsName
    text: str
    method: Literal["http", "browser", "api", "captured", "failed"]
    error: str = ""
    #: Why the posting looks closed (`form_guards.closed_posting`), or "" when open.
    closed: str = ""


class _TextExtractor(HTMLParser):
    """Strip scripts/styles/nav and collect visible text blocks."""

    def __init__(self) -> None:
        """Initialise skip depth and text buffers."""
        super().__init__()
        self._skip = 0
        self._chunks: list[str] = []
        self._current: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Enter a skip region for non-content tags."""
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        """Leave a skip region; flush a block on block-level closes."""
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
            self._skip = max(0, self._skip - 1)
            return
        if tag in {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "section", "tr"}:
            text = " ".join(self._current).strip()
            if text:
                self._chunks.append(text)
            self._current = []

    def handle_data(self, data: str) -> None:
        """Accumulate text outside skip regions."""
        if self._skip:
            return
        piece = data.strip()
        if piece:
            self._current.append(piece)

    def text(self, *, largest_block_only: bool) -> str:
        """Return the JD text: the largest contiguous chunk (page mode), or all
        chunks joined (fragment mode, for a feed's ``jobDescription``/``content``
        field, which holds nothing but the JD to begin with)."""
        if self._current:
            leftover = " ".join(self._current).strip()
            if leftover:
                self._chunks.append(leftover)
        if not self._chunks:
            return ""
        if not largest_block_only:
            return "\n\n".join(self._chunks)
        # Prefer the longest block (usually the JD body vs chrome).
        largest = max(self._chunks, key=len)
        if len(largest) >= _MIN_JD_CHARS:
            return largest
        return "\n\n".join(self._chunks)


def _extract(html: str, *, largest_block_only: bool) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML still yields partial text
        pass
    return parser.text(largest_block_only=largest_block_only).strip()


def extract_text(html: str) -> str:
    """Strip chrome tags and return the largest text block from ``html``.

    For a *full page* download, where the JD body sits alongside nav/footer chrome
    in the same document. Use `extract_fragment_text` for a feed's JD-only field.
    """
    return _extract(html, largest_block_only=True)


def extract_fragment_text(html: str) -> str:
    """Strip tags and return *all* text from ``html``, joined block by block.

    For an ATS feed's JD-only HTML field (Greenhouse `content`, Ashby
    `descriptionHtml`, Workday `jobDescription`) — the whole fragment is the JD, so
    picking only the largest paragraph (as `extract_text` does for a full page)
    would silently drop most of it, e.g. an EEO paragraph outsizing the actual
    responsibilities/requirements sections.
    """
    return _extract(html, largest_block_only=False)


def detect_ats(final_url: str, html: str = "") -> AtsName:
    """Infer the ATS from the final URL hostname (HTML is unused, reserved)."""
    del html  # reserved for future fingerprinting
    host = urlparse(final_url).hostname or ""
    host = host.lower()
    path = urlparse(final_url).path.lower()
    if "greenhouse" in host or "boards.greenhouse" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    if "myworkdayjobs.com" in host or "workday" in host:
        return "workday"
    if "icims.com" in host:
        return "icims"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if host.endswith("taleo.net"):
        return "taleo"
    if "successfactors" in host:
        return "successfactors"
    if "oraclecloud.com" in host and "/hcmui/" in path:
        return "oracle"
    if "jobvite.com" in host:
        return "jobvite"
    if host.endswith("bamboohr.com"):
        return "bamboohr"
    # Job boards whose own apply flow is assist-only (`fill_buttons.ASSIST_ONLY_ATS`).
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    if host == "indeed.com" or host.endswith(".indeed.com"):
        return "indeed"
    if host.endswith("joinhandshake.com"):
        return "handshake"
    if host and ("jobs." in host or "/careers" in path or "/job" in path):
        return "other"
    return "unknown"


def _looks_like_js_shell(html: str, text: str) -> bool:
    """True when the HTTP body is mostly a SPA shell without enough text."""
    if len(text) >= _MIN_JD_CHARS:
        return False
    lowered = html.lower()
    return (
        "id=\"root\"" in lowered
        or "id='root'" in lowered
        or "__next" in lowered
        or "window.__" in lowered
        or len(html) > 500 and len(text) < 200
    )


def _fetch_via_browser(url: str) -> FetchResult:
    """Open ``url`` in the CDP browser and read ``document.body.innerText``.

    Some ATS pages (Workday among them) report "loaded" before the description
    text arrives, so the read is retried for a few seconds rather than taken once.
    """
    with cdp_browser() as browser:
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_load_state("networkidle", timeout=30_000)
            final_url = page.url
            text = ""
            deadline = time.monotonic() + 10.0
            while True:
                text = page.evaluate("() => document.body ? document.body.innerText : ''")
                text = (text or "").strip()
                if len(text) >= _MIN_JD_CHARS or time.monotonic() >= deadline:
                    break
                page.wait_for_timeout(500)
            ats = detect_ats(final_url)
            if len(text) < _MIN_JD_CHARS:
                return FetchResult(
                    final_url=final_url,
                    ats=ats,
                    text=text,
                    method="failed",
                    error=f"Browser extraction too short ({len(text)} chars)",
                )
            return FetchResult(
                final_url=final_url, ats=ats, text=text, method="browser"
            )
        finally:
            page.close()


def fetch_jd(
    url: str,
    *,
    allow_browser: bool = True,
    canonical_key: str | None = None,
) -> FetchResult:
    """Fetch JD text: ATS JSON API first (keyed, or Workday by URL), then HTTP, then CDP."""
    if canonical_key:
        try:
            from resume_tailor.apply.discovery import ats_api

            api_text = ats_api.fetch_posting_text(canonical_key)
        except Exception:  # noqa: BLE001
            api_text = None
        if api_text:
            return FetchResult(
                final_url=url,
                ats=detect_ats(url),
                text=api_text,
                method="api",
            )
    if detect_ats(url) == "workday":
        try:
            from resume_tailor.apply.discovery import ats_api

            workday_text = ats_api.workday_posting_text(url)
        except Exception:  # noqa: BLE001
            workday_text = None
        if workday_text:
            return FetchResult(
                final_url=url,
                ats="workday",
                text=workday_text,
                method="api",
            )
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": _DESKTOP_UA, "Accept": "text/html"},
        )
        gone = form_guards.closed_posting("", status=resp.status_code)
        if gone:
            return FetchResult(
                final_url=str(resp.url), ats=detect_ats(url), text="", method="failed",
                error=gone, closed=gone,
            )
        resp.raise_for_status()
        final_url = str(resp.url)
        html = resp.text
        text = extract_text(html)
        ats = detect_ats(final_url, html)
        closed = form_guards.closed_posting(text, final_url=final_url, requested_url=url)
        if closed:
            return FetchResult(
                final_url=final_url, ats=ats, text=text, method="http", closed=closed
            )
        if len(text) >= _MIN_JD_CHARS and not _looks_like_js_shell(html, text):
            return FetchResult(final_url=final_url, ats=ats, text=text, method="http")
        if allow_browser:
            try:
                return _fetch_via_browser(url)
            except Exception as exc:  # noqa: BLE001
                return FetchResult(
                    final_url=final_url,
                    ats=ats,
                    text=text,
                    method="failed",
                    error=str(exc),
                )
        return FetchResult(
            final_url=final_url,
            ats=ats,
            text=text,
            method="failed",
            error=f"HTTP text too short ({len(text)} chars) and browser disabled",
        )
    except Exception as exc:  # noqa: BLE001
        if allow_browser:
            try:
                return _fetch_via_browser(url)
            except Exception as browser_exc:  # noqa: BLE001
                return FetchResult(
                    final_url=url,
                    ats=detect_ats(url),
                    text="",
                    method="failed",
                    error=f"{exc}; browser: {browser_exc}",
                )
        return FetchResult(
            final_url=url,
            ats=detect_ats(url),
            text="",
            method="failed",
            error=str(exc),
        )


_WS = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace for comparison/tests."""
    return _WS.sub(" ", text).strip()
