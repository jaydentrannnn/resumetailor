"""Workday navigation as an observed state machine (sync Playwright, legacy fill path).

Every Workday screen is recognised from its visible ``data-automation-id`` markers
(captured from live tenants in 2026-09; fixtures in ``tests/fixtures/workday``), and every
action waits for the next screen instead of sleeping a fixed time. ``classify`` is pure so
the recognition rules are unit-tested without a browser.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urljoin

from resume_tailor.apply.driver import clicks

from . import workday_page


def wait_for_state(
    page: Any,
    allowed: Iterable[str],
    *,
    timeout_s: float,
    deadline: float | None = None,
    poll_ms: int = 250,
) -> workday_page.WorkdayState:
    """Poll until the screen is one of ``allowed``; return the last state seen."""
    wanted = set(allowed)
    stop = time.monotonic() + timeout_s
    if deadline is not None:
        stop = min(stop, deadline)
    state = workday_page.detect_state(page)
    while state not in wanted and time.monotonic() < stop:
        page.wait_for_timeout(poll_ms)
        state = workday_page.detect_state(page)
    return state

#: Whether an auth form is fully painted: its inputs, its submit, and what sits on the submit.
AUTH_FORM_JS = r"""(ids) => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const get = id => document.querySelector(`[data-automation-id='${id}']`);
  if (!ids.inputs.every(id => vis(get(id)))) return {ready: false, top: ''};
  const button = get(ids.submit);
  if (!vis(button)) return {ready: false, top: ''};
  const r = button.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  const top = !hit ? '' : hit.closest("[data-automation-id='click_filter']") ? 'click_filter'
    : (hit === button || button.contains(hit)) ? 'button' : 'other';
  return {ready: true, top, rect: [r.left, r.top, r.width, r.height].map(Math.round)};
}"""


def wait_for_auth_form_ready(
    page: Any, submit_id: str, inputs: tuple[str, ...], *, deadline: float, timeout_s: float = 8,
) -> str:
    """Wait until an auth form's inputs and submit are painted and stable.

    Workday swaps Create Account / Sign In in place and paints the submit's click overlay
    last; filling and clicking before then clicks a button with no handler. Ready means the
    same thing sits on the submit (at the same place) for three polls, and preferably that
    thing is the overlay; a tenant with no overlay is accepted after the grace period.
    Returns what sits on the submit ("click_filter", "button", ...) or "" on timeout.
    """
    stop = min(time.monotonic() + timeout_s, deadline)
    started = time.monotonic()
    last: tuple[Any, ...] | None = None
    stable = 0
    while True:
        try:
            probe = page.evaluate(AUTH_FORM_JS, {"inputs": list(inputs), "submit": submit_id})
        except Exception:  # noqa: BLE001 - a re-rendering page has no answer yet
            probe = None
        probe = probe if isinstance(probe, dict) else {}
        current = (probe.get("top"), tuple(probe.get("rect") or ())) if probe.get("ready") else None
        stable = stable + 1 if current is not None and current == last else 0
        last = current
        if current is not None and stable >= 2:
            overlay_late = (time.monotonic() - started) * 1000 < workday_page._OVERLAY_GRACE_MS
            if current[0] == "click_filter" or not overlay_late:
                return str(current[0])
        if time.monotonic() >= stop:
            return ""
        page.wait_for_timeout(250)


def _remaining_ms(deadline: float, cap: int) -> int:
    return max(500, min(cap, int((deadline - time.monotonic()) * 1000)))


def is_site_error(snap: dict[str, Any]) -> bool:
    """Workday's "Something went wrong ... Error Code: VPS|..." page."""
    return bool(workday_page.SITE_ERROR.search(str(snap.get("text") or "")))


def recover_site_error(
    page: Any,
    *,
    deadline: float,
    progress: Callable[[str], None] = lambda _msg: None,
    attempts: int = workday_page.SITE_ERROR_RELOADS,
) -> tuple[bool, int]:
    """Reload while Workday shows its error page, as the page itself asks.

    The error is usually transient and a reload restores the saved draft. After each
    reload, waits until the page is either a recognisable screen or the error again, so a
    half-painted shell is not mistaken for recovery. Returns ``(recovered, reloads)``;
    ``recovered`` is True as soon as the error page is gone (at once when it never showed).
    """
    reloads = 0
    while is_site_error(workday_page.snapshot(page)):
        if reloads >= attempts or time.monotonic() >= deadline:
            return False, reloads
        reloads += 1
        progress(f"Workday showed 'Something went wrong' (error code); refreshing the page ({reloads}/{attempts})")
        with contextlib.suppress(Exception):  # the snapshot below decides
            page.reload(wait_until="domcontentloaded", timeout=_remaining_ms(deadline, 30000))
        page.wait_for_timeout(500 * reloads)  # back off a little more each time
        stop = min(deadline, time.monotonic() + 15)
        while time.monotonic() < stop:
            snap = workday_page.snapshot(page)
            if is_site_error(snap) or workday_page.classify(snap) != "unknown":
                break
            page.wait_for_timeout(250)
    if reloads:
        progress("Workday page recovered after refreshing")
    return True, reloads


def _new_tab(page: Any, context: Any, before: list[Any], deadline: float) -> Any:
    """Follow Apply into a new tab when a tenant opens one; otherwise stay put.

    Only a tab this page opened counts: a parallel fill's new tab is in the same context.
    """
    try:
        opened = [
            item for item in context.pages
            if item not in before and not item.is_closed() and item.opener() == page
        ]
    except Exception:  # noqa: BLE001 - no context to inspect
        return page
    if len(opened) != 1:
        return page
    with contextlib.suppress(Exception):  # the state wait that follows decides
        opened[0].wait_for_load_state("domcontentloaded", timeout=_remaining_ms(deadline, 15000))
    return opened[0]


def _follow_href_or_click(page: Any, locator: Any, *, deadline: float) -> None:
    """Navigate to a link's own href, else click it.

    A parallel fill's tab sits in the background, where Edge throttles animation frames and
    Playwright's "stable" check never passes while the start dialog animates in. Reading
    ``href`` needs no actionability check, so a real link is followed with ``goto``.
    """
    href = ""
    with contextlib.suppress(Exception):  # no attribute: fall back to the click
        href = (locator.get_attribute("href", timeout=2000) or "").strip()
    if href and href != "#" and not href.lower().startswith("javascript:"):
        page.goto(urljoin(page.url, href), timeout=_remaining_ms(deadline, 15000), wait_until="domcontentloaded")
        return
    clicks.safe_click(locator, purpose="enter", timeout=_remaining_ms(deadline, 5000))


def enter_application(
    page: Any,
    context: Any,
    *,
    deadline: float,
    progress: Callable[[str], None] = lambda _msg: None,
) -> tuple[Any, workday_page.WorkdayState]:
    """From wherever the tab is, reach the application form or its auth screen.

    Clicks only Apply and Apply Manually. Never "Autofill with Resume" or "Use My Last
    Application" — those import data Workday parsed, which the fill cannot verify.
    """
    past_entry = {"auth_chooser", "sign_in", "create_account", "otp", "verify_email", "apply_form"}
    terminal = past_entry | {"already_applied", "unavailable"}
    recover_site_error(page, deadline=deadline, progress=progress)
    state = wait_for_state(
        page, terminal | {"posting", "start_dialog"}, timeout_s=15, deadline=deadline,
    )
    if state == "posting":
        progress("Workday: opening the application")
        try:
            before = list(context.pages) if context is not None else []
        except Exception:  # noqa: BLE001
            before = []
        # A saved draft replaces Apply with "Continue Application", which resumes it.
        draft = page.locator("[data-automation-id='continueButton']")
        entry = (
            draft
            if workday_page._visible(draft)
            else page.locator("[data-automation-id='adventureButton']")
        )
        if workday_page._visible(draft):
            progress("Workday: resuming the saved application draft")
        _follow_href_or_click(page, entry.first, deadline=deadline)
        page.wait_for_timeout(300)
        if context is not None:
            page = _new_tab(page, context, before, deadline)
        state = wait_for_state(page, terminal | {"start_dialog"}, timeout_s=15, deadline=deadline)
    if state == "start_dialog":
        progress("Workday: choosing Apply Manually")
        manual = page.locator("[data-automation-id='applyManually']")
        if not workday_page._visible(manual):
            return page, state
        _follow_href_or_click(page, manual.first, deadline=deadline)
        state = wait_for_state(page, terminal, timeout_s=20, deadline=deadline)
    if state not in terminal:
        # The error page can also replace the form right after Apply / Apply Manually.
        recovered, reloads = recover_site_error(page, deadline=deadline, progress=progress)
        if recovered and reloads:
            state = wait_for_state(page, terminal, timeout_s=20, deadline=deadline)
    return page, state


def wait_for_step_ready(page: Any, *, deadline: float, timeout_s: float = 20) -> bool:
    """Wait until the current apply step has rendered its fields.

    Workday paints the apply-flow shell (header, progress bar) before the step's form
    fields, then renders them in stages (Country first; the rest after Workday applies
    its locale default). A step is ready once its footer button and a field container
    are visible and the set of visible markers has not changed for ``stable_polls`` polls.
    """
    stop = min(deadline, time.monotonic() + timeout_s)
    stable_polls = 4
    previous: frozenset[str] | None = None
    unchanged = 0
    while True:
        snap = workday_page.snapshot(page)
        ids = frozenset(snap.get("ids") or [])
        has_field = any(item.startswith("formField-") for item in ids)
        footer = "pageFooterNextButton" in ids or "pageFooterSubmitButton" in ids
        unchanged = unchanged + 1 if ids == previous else 0
        previous = ids
        # The Review step has no field containers, only the footer.
        if footer and (has_field or unchanged >= 2 * stable_polls) and unchanged >= stable_polls:
            return True
        if time.monotonic() >= stop:
            return footer
        page.wait_for_timeout(250)


#: Whether Workday is still saving the step: its Save and Continue button is disabled
#: while the request is in flight.
_SAVING_JS = r"""() => {
  const b = document.querySelector("[data-automation-id='pageFooterNextButton']");
  return !!(b && (b.disabled || b.getAttribute('aria-disabled') === 'true'));
}"""


def wait_for_step_change(page: Any, before: str, *, deadline: float, timeout_s: float = 15) -> bool:
    """After Save and Continue, wait for the progress bar to move past ``before``.

    Returns False once validation errors are showing on the unchanged step (they appear
    within about a second) or at the timeout. A save still in flight (the button
    disabled) extends the wait to three times ``timeout_s``: F5's My Experience with five
    rows (2026-09) saved after the fill had already reported "did not advance".
    """
    started = time.monotonic()
    stop = min(deadline, started + timeout_s)
    hard_stop = min(deadline, started + 3 * timeout_s)
    while time.monotonic() < stop:
        snap = workday_page.snapshot(page)
        step = workday_page.active_step(snap)
        if step and step != before:
            return True
        ids = set(snap.get("ids") or [])
        if time.monotonic() - started > 2 and ({"errorMessage", "inputAlert"} & ids or snap.get("alerts")):
            return False
        page.wait_for_timeout(250)
        if time.monotonic() >= stop and stop < hard_stop:
            try:
                saving = bool(page.evaluate(_SAVING_JS))
            except Exception:  # noqa: BLE001 - navigating: look again
                saving = True
            if saving:
                stop = min(hard_stop, time.monotonic() + 2)
    # One last look: the step can land on the very tick the wait runs out.
    step = workday_page.active_step(workday_page.snapshot(page))
    return bool(step and step != before)
