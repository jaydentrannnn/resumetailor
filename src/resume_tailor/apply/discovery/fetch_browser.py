"""Read a posting page's visible text in the host browser over CDP (`fetch_jd`'s last resort).

Opens a tab in the CDP browser and reads what a reader can see (`_VISIBLE_TEXT_JS`). A
custom careers site behind a bot check (Tesla's) never goes network-idle and may reload
once the check passes, so neither ends the read. A page that hands over to LinkedIn or
Indeed (an Adzuna link through appcast) is stopped before that page loads: the backend
never visits them (`apply/CLAUDE.md`).
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.driver.browser import cdp_browser
from resume_tailor.apply.forms import form_guards
from resume_tailor.pipeline import posting_guard

#: ``innerText`` already skips ``display:none``/``visibility:hidden``; this removes what it
#: keeps but a reader cannot see (zero opacity or font size, transparent text that is not
#: a gradient fill, off-screen or clipped boxes) and returns the removed text for
#: scanning. Outermost hidden element only; page code is never walked.
_VISIBLE_TEXT_JS = """() => {
  const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG']);
  const hidden = [];
  const isHidden = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return true;
    if (parseFloat(s.opacity) === 0 || parseFloat(s.fontSize) === 0) return true;
    const clear = s.color === 'transparent' || s.color === 'rgba(0, 0, 0, 0)';
    const gradient = s.backgroundClip === 'text' || s.webkitBackgroundClip === 'text';
    if (clear && !gradient) return true;
    if ((s.clipPath || '').startsWith('inset(100%')) return true;
    const r = el.getBoundingClientRect();
    if (r.right < -999 || r.bottom < -999) return true;
    return (r.width === 0 || r.height === 0) && s.overflow === 'hidden';
  };
  const walk = (el) => {
    for (const child of Array.from(el.children)) {
      if (skip.has(child.tagName.toUpperCase())) continue;
      if (isHidden(child)) hidden.push(child); else walk(child);
    }
  };
  if (!document.body) return {text: '', hidden: []};
  walk(document.body);
  const texts = hidden.map((el) => (el.textContent || '').trim()).filter(Boolean);
  for (const el of hidden) el.remove();
  return {text: document.body.innerText, hidden: texts};
}"""

#: Requests the read never lets out: hosts whose pages the backend must not fetch.
_NEVER_VISIT = re.compile(r"^https?://(?:[^/]*\.)?(?:linkedin|indeed)\.com(?::\d+)?(?:/|$)", re.I)
#: How long the read waits for the description to arrive once the page has loaded.
_READ_SECONDS = 15.0
_IDLE_MS = 10_000


def read(url: str) -> fetch_jd.FetchResult:
    """Open ``url`` in the CDP browser and read the visible text.

    Some pages (Workday among them) report "loaded" before the description text arrives,
    so the read is retried until it is long enough or `_READ_SECONDS` pass. The posting
    is closed when the page says so (`form_guards.closed_posting`).
    """
    with cdp_browser() as browser:
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        sent_to: list[str] = []

        def refuse(route: Any) -> None:
            with contextlib.suppress(Exception):
                if route.request.is_navigation_request() and route.request.frame == page.main_frame:
                    sent_to.append(route.request.url)
            route.abort()

        try:
            page.route(_NEVER_VISIT, refuse)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                if not sent_to:
                    raise
            if sent_to:
                return _sent_to_board(sent_to[0])
            # A page that never goes quiet (analytics, a bot check's beacons) is still readable.
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=_IDLE_MS)
            text, hidden = _read_visible(page)
            if sent_to:
                return _sent_to_board(sent_to[0])
            if (found := fetch_jd._removed.get()) is not None and hidden:  # noqa: SLF001
                found.append(posting_guard.Stripped(
                    "", "\n".join(hidden), [t[:120] for t in hidden]
                ))
            final_url = page.url
            ats = fetch_jd.detect_ats(final_url)
            closed = form_guards.closed_posting(text, final_url=final_url, requested_url=url)
            if closed:
                return fetch_jd._closed(final_url, ats, closed)  # noqa: SLF001
            if len(text) < fetch_jd._MIN_JD_CHARS:  # noqa: SLF001
                return fetch_jd.FetchResult(
                    final_url=final_url,
                    ats=ats,
                    text=text,
                    method="failed",
                    error=f"Browser extraction too short ({len(text)} chars)",
                )
            return fetch_jd.FetchResult(final_url=final_url, ats=ats, text=text, method="browser")
        finally:
            page.close()


def _read_visible(page: Any) -> tuple[str, list[str]]:
    """The page's visible text and the hidden text removed from it, read until the text is
    long enough or time runs out. A bot check that reloads the page mid-read destroys the
    read's context; the read waits for the new document and goes on."""
    text = ""
    hidden: list[str] = []
    deadline = time.monotonic() + _READ_SECONDS
    while True:
        try:
            got = page.evaluate(_VISIBLE_TEXT_JS) or {}
        except Exception as exc:
            if "Execution context was destroyed" not in str(exc) or time.monotonic() >= deadline:
                raise
            with contextlib.suppress(Exception):
                page.wait_for_load_state("domcontentloaded", timeout=_IDLE_MS)
            continue
        text = str(got.get("text") or "").strip()
        hidden += [str(t) for t in got.get("hidden") or []]
        framed, framed_hidden = _embedded_postings(page)
        text = "\n\n".join([text, *framed]).strip()
        hidden += framed_hidden
        if (
            len(text) >= fetch_jd._MIN_JD_CHARS  # noqa: SLF001
            or form_guards.closed_posting(text)  # a closed page stays short: stop waiting
            or time.monotonic() >= deadline
        ):
            return text, hidden
        page.wait_for_timeout(500)


#: Frame hosts that are not an ATS posting: ads, captchas, trackers, and the job boards.
_NOT_A_POSTING = frozenset({"other", "unknown", "linkedin", "indeed", "handshake"})


def _embedded_postings(page: Any) -> tuple[list[str], list[str]]:
    """Visible and hidden text of frames the page embeds from an ATS. A careers page may
    show its posting in one (SeatGeek's Greenhouse board), out of the page's own text."""
    texts: list[str] = []
    hidden: list[str] = []
    for frame in page.frames:
        if frame is page.main_frame or fetch_jd.detect_ats(frame.url) in _NOT_A_POSTING:
            continue
        with contextlib.suppress(Exception):  # a frame that detaches mid-read is skipped
            got = frame.evaluate(_VISIBLE_TEXT_JS) or {}
            texts.append(str(got.get("text") or "").strip())
            hidden += [str(t) for t in got.get("hidden") or []]
    return [t for t in texts if t], hidden


def _sent_to_board(target: str) -> fetch_jd.FetchResult:
    """The page tried to open LinkedIn or Indeed; the tab never loaded it."""
    ats = fetch_jd.detect_ats(target)
    name = "LinkedIn" if ats == "linkedin" else "Indeed"
    return fetch_jd.FetchResult(
        final_url=target,
        ats=ats,
        text="",
        method="failed",
        error=(
            f"This posting sends applicants to {name}; open it there and save it with the"
            " browser extension"
        ),
    )
