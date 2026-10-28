"""When a finished application's retained tab may be closed: only when it is safe.

A submitted or skipped application's tab holds a whole ATS page in memory, so the
watcher (`answer_harvest`) closes it, but only when nothing of the applicant's can be
there (audit #4: a tab taken to another page, with a draft in it, was closed):

1. the application is done: submitted with a confirmation the app saw, or skipped in
   this session (a restart never closes a tab);
2. the tab still shows that application (`identity.retained_tab`), on the URL it
   showed when the close was armed;
3. the applicant has not typed or clicked there since it was armed (the listener's
   ``__rtLastInput``; unreadable means touched). Arming marks every frame's document
   with a token (`ARM_JS`): a frame without it, or without the listener, was reloaded
   or replaced since, so input there is unknown and the tab stays;
4. they did not press Keep open (`keep`).

The close waits `GRACE_S` after it is armed; the app shows the countdown (`pending`).
Every decision is recorded (`tab_events`).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from resume_tailor.apply.discovery import identity
from resume_tailor.apply.funnel import store_models, tab_events

GRACE_S = 30.0
_TIMEOUT_S = 10.0
#: When this server process started: a row skipped before then is not closed now.
_STARTED = store_models._now_iso()

#: Marks the document a close was armed on (a reload or another page drops it).
ARM_JS = "(token) => { window.__rtCloseArm = token; return true; }"
#: When the applicant last typed or clicked in the frame, its clock, and whether it is
#: still the document the close was armed on, with the input listener in it.
CHECK_JS = (
    "(token) => [window.__rtLastInput || 0, Date.now(),"
    " !!window.__rtTypedInstalled && window.__rtCloseArm === token]"
)

_LOCK = threading.Lock()
#: Applications whose tab the applicant chose to keep; never closed automatically.
KEPT: set[str] = set()


@dataclass
class Pending:
    """A close counting down."""

    due: float  # time.monotonic()
    url: str
    company: str
    target: str
    #: The page's clock (ms) when the close was armed; None when it could not be read.
    armed_page_ms: float | None
    #: What `ARM_JS` marked the tab's documents with.
    token: str = ""


_PENDING: dict[str, Pending] = {}


def refusal(app: store_models.Application, fill: store_models.FillResult) -> str:
    """Why this finished application's tab stays open, or "" when it may close."""
    if app.source_job_id in KEPT:
        return "You chose to keep it open"
    if app.status == "submitted" and not fill.confirmed:
        return "Marked submitted without a confirmation the app saw"
    if app.status == "skipped":
        change = app.status_history[-1] if app.status_history else None
        if change is None or change.status != "skipped" or change.at < _STARTED:
            return "Skipped before this session"
    return ""


def step(
    app: store_models.Application, fill: store_models.FillResult, target: str, url: str,
    now: float,
) -> bool:
    """Advance this finished application's tab close; True while its countdown runs."""
    application_id = app.source_job_id
    with _LOCK:
        pending = _PENDING.get(application_id)
    if pending is None:
        why = refusal(app, fill)
        if why:
            tab_events.record(application_id, "kept", why, url=url)
            return False
        token = uuid.uuid4().hex
        armed = Pending(
            due=now + GRACE_S, url=url, company=app.company, target=target,
            armed_page_ms=_arm(target, token), token=token,
        )
        with _LOCK:
            _PENDING[application_id] = armed
        return True
    if now < pending.due:
        return True
    with _LOCK:
        _PENDING.pop(application_id, None)
    if application_id in KEPT:
        return False  # `keep` recorded it
    why = refusal(app, fill) or _due_refusal(app, fill, url, pending)
    if why:
        tab_events.record(application_id, "kept", why, url=url)
        return False
    from resume_tailor.apply.driver import browser  # noqa: PLC0415

    closed = browser.close_target(target)
    tab_events.record(
        application_id, "closed" if closed else "kept",
        f"{app.status.capitalize()}; closed after the countdown" if closed
        else "The browser did not close it", url=url,
    )
    return False


def _due_refusal(
    app: store_models.Application, fill: store_models.FillResult, url: str, pending: Pending
) -> str:
    if url != pending.url:
        return "The tab moved to another page"
    known = (fill.browser_url, app.final_url, app.posting_url)
    shown = identity.retained_tab(url, known)
    if shown == "different":
        return "The tab shows another page"
    # Another page of the same site (Workday's candidate profile) can hold the
    # applicant's own work: only a page the app itself left or saw the tab on closes.
    seen = {_page(item) for item in (*known, fill.confirmation_evidence.get("url", "")) if item}
    if shown == "unknown" and _page(url) not in seen:
        return "Could not tell that the tab still shows this application"
    if pending.armed_page_ms is None:
        return "Could not check the tab for your input"
    last = _last_input(pending.target, pending.token)
    if last is None:
        return "Could not check the tab for your input"
    if last > pending.armed_page_ms:
        return "You used the tab"
    return ""


def _page(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/")


def pending() -> list[dict[str, Any]]:
    """Closes counting down, for the app's countdown notice."""
    now = time.monotonic()
    with _LOCK:
        return [
            {"id": key, "company": item.company, "due_in": max(0.0, round(item.due - now, 1))}
            for key, item in _PENDING.items()
        ]


def keep(application_id: str) -> bool:
    """Keep this application's tab open (Keep open); True when a close was pending."""
    with _LOCK:
        KEPT.add(application_id)
        item = _PENDING.pop(application_id, None)
    tab_events.record(application_id, "kept", "You chose to keep it open",
                      url=item.url if item else "")
    return item is not None


def forget(application_id: str) -> None:
    with _LOCK:
        _PENDING.pop(application_id, None)


# -- reading the page (one short CDP connection) ------------------------------------------


def _arm(target: str, token: str) -> float | None:
    """Install the input listener and mark every frame with ``token``; the page's clock
    now (ms), or None when a frame could not be marked."""
    reading = _read(target, token, arm=True)
    return reading[1] if reading else None


def _last_input(target: str, token: str) -> float | None:
    """When the applicant last typed or clicked in the tab (page ms; 0 if never); None
    when a frame is no longer the document armed with ``token``."""
    reading = _read(target, token, arm=False)
    return reading[0] if reading else None


def _read(target: str, token: str, *, arm: bool) -> tuple[float, float] | None:
    try:
        return asyncio.run(asyncio.wait_for(_read_async(target, token, arm), _TIMEOUT_S))
    except Exception:  # noqa: BLE001 - unreadable reads as touched: the tab stays
        return None


async def _read_async(target: str, token: str, arm: bool) -> tuple[float, float] | None:
    from resume_tailor.apply.driver import browser  # noqa: PLC0415
    from resume_tailor.apply.funnel import answer_harvest  # noqa: PLC0415

    async with browser.async_cdp_browser(target_id=target) as connected:
        for context in connected.contexts:
            page = await browser.async_find_target(context, target)
            if page is None:
                continue
            if arm:
                await answer_harvest.install(page)
                for frame in page.frames:
                    with contextlib.suppress(Exception):
                        await frame.evaluate(ARM_JS, token)
            last, clock = 0.0, None
            for frame in page.frames:
                # A frame that cannot be read, reloaded since (its listener and mark are
                # gone) or added since may hold input: the tab stays.
                try:
                    frame_last, frame_now, same = await frame.evaluate(CHECK_JS, token)
                except Exception:  # noqa: BLE001
                    return None
                if not same:
                    return None
                last = max(last, float(frame_last or 0))
                clock = max(clock or 0.0, float(frame_now))
            return (last, clock) if clock is not None else None
    return None
