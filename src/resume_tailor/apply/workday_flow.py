"""Workday navigation as an observed state machine (sync Playwright, legacy fill path).

Every Workday screen is recognised from its visible ``data-automation-id`` markers
(captured from live tenants in 2026-09; fixtures in ``tests/fixtures/workday``), and every
action waits for the next screen instead of sleeping a fixed time. ``classify`` is pure so
the recognition rules are unit-tested without a browser.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any, Literal
from urllib.parse import urljoin

from resume_tailor.apply import clicks, field_matcher, questions

WorkdayState = Literal[
    "posting", "start_dialog", "auth_chooser", "sign_in", "create_account", "otp", "verify_email",
    "apply_form", "already_applied", "unavailable", "unknown",
]

#: One evaluate call returns everything ``classify`` needs.
SNAPSHOT_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const ids = [...new Set([...document.querySelectorAll('[data-automation-id]')]
    .filter(vis).map(e => e.getAttribute('data-automation-id')))];
  const active = document.querySelector("[data-automation-id='progressBarActiveStep']");
  const dialog = [...document.querySelectorAll("[role='dialog']")].find(vis);
  const text = (document.body ? document.body.innerText : '').slice(0, 20000);
  const otp = [...document.querySelectorAll(
    "input[autocomplete='one-time-code'], input[name*='verificationCode' i]")].some(vis);
  const alerts = [...document.querySelectorAll(
    "[data-automation-id='errorMessage'], [role='alert'], [data-automation-id*='error' i]")]
    .filter(vis).map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 5);
  return {
    url: location.href, ids,
    active_step: active ? (active.innerText || '').trim() : '',
    dialog_label: dialog ? (dialog.getAttribute('aria-label') || '') : '',
    otp_input: otp, alerts, text,
  };
}"""

_UNAVAILABLE = re.compile(
    r"page you are looking for doesn.t exist|this job (?:posting )?is no longer available|"
    r"job (?:posting )?(?:has been|is) (?:closed|filled)",
    re.I,
)
_ALREADY_APPLIED = re.compile(r"you(?:'ve| have) already applied", re.I)
VERIFY_EMAIL = re.compile(
    r"verify your (?:account|email)|verification (?:email|link) (?:has been|was) sent|"
    r"check your email to (?:verify|activate)",
    re.I,
)
#: Workday's own failure page ("Something went wrong ... Error Code: VPS|...").
SITE_ERROR = re.compile(r"something went wrong\s+please refresh the page|error code:\s*vps\|", re.I)
#: Reloads one ``recover_site_error`` call may spend before handing the tab over.
SITE_ERROR_RELOADS = 3
_AUTH_IDS = {
    "SignInWithEmailButton", "password", "verifyPassword", "signInSubmitButton",
    "createAccountSubmitButton",
}


def classify(snap: dict[str, Any]) -> WorkdayState:
    """Name the Workday screen from one ``SNAPSHOT_JS`` result."""
    ids = set(snap.get("ids") or [])
    text = str(snap.get("text") or "")
    if snap.get("otp_input") or ids & {"verificationCode", "securityCode"}:
        return "otp"
    if "verifyPassword" in ids:
        return "create_account"
    if "password" in ids or "signInSubmitButton" in ids:
        return "sign_in"
    if ids & {"applyManually", "autofillWithResume", "useMyLastApplication"}:
        return "start_dialog"
    # Some tenants first offer Google / LinkedIn / "Sign in with email".
    if "SignInWithEmailButton" in ids:
        return "auth_chooser"
    if "applyFlowPage" in ids or "progressBar" in ids:
        # The Create Account/Sign In step paints its progress bar before its form; until
        # the form shows, this is not an application form.
        if "signInContent" in ids or re.search(r"create account|sign in", active_step(snap), re.I):
            return "verify_email" if VERIFY_EMAIL.search(text) else "unknown"
        # Below ~800px wide the progress bar drops its step names, so an empty shell cannot
        # be told from a loading Create Account step by its label. A form step has a footer
        # or a field; the bare shell is still loading.
        if ids & {"pageFooter", "pageFooterNextButton", "pageFooterSubmitButton"} or any(
            item.startswith("formField-") for item in ids
        ):
            return "apply_form"
        # Create Account can leave the auth step with only "verify your account" in it.
        return "verify_email" if VERIFY_EMAIL.search(text) else "unknown"
    if VERIFY_EMAIL.search(text):
        return "verify_email"
    if _ALREADY_APPLIED.search(text):
        return "already_applied"
    if ids & {"adventureButton", "continueButton"}:  # Apply, or Continue Application (a saved draft)
        return "posting"
    if _UNAVAILABLE.search(text):
        return "unavailable"
    return "unknown"


def signed_in(snap: dict[str, Any]) -> bool:
    """The header account menu replaces the Sign In button once a session exists."""
    ids = set(snap.get("ids") or [])
    return "utilityButtonAccountTasksMenu" in ids and not ids & _AUTH_IDS


def active_step(snap: dict[str, Any]) -> str:
    """``current step 2 of 6 My Experience`` -> ``My Experience``."""
    raw = str(snap.get("active_step") or "")
    return re.sub(r"^(?:current\s+)?step\s+\d+\s+of\s+\d+\s*", "", raw, flags=re.I).strip()


def is_review_step(snap: dict[str, Any]) -> bool:
    """Recognize the final Review or Review and Submit progress step."""
    return bool(re.match(r"^review(?:\s|$)", active_step(snap), re.I))


def snapshot(page: Any) -> dict[str, Any]:
    try:
        snap = page.evaluate(SNAPSHOT_JS)
    except Exception:  # noqa: BLE001 - a navigating page has no snapshot yet
        return {"ids": [], "text": "", "url": str(getattr(page, "url", ""))}
    return snap if isinstance(snap, dict) else {"ids": [], "text": ""}


def detect_state(page: Any) -> WorkdayState:
    return classify(snapshot(page))


def wait_for_state(
    page: Any,
    allowed: Iterable[str],
    *,
    timeout_s: float,
    deadline: float | None = None,
    poll_ms: int = 250,
) -> WorkdayState:
    """Poll until the screen is one of ``allowed``; return the last state seen."""
    wanted = set(allowed)
    stop = time.monotonic() + timeout_s
    if deadline is not None:
        stop = min(stop, deadline)
    state = detect_state(page)
    while state not in wanted and time.monotonic() < stop:
        page.wait_for_timeout(poll_ms)
        state = detect_state(page)
    return state


def _visible(locator: Any) -> bool:
    try:
        return bool(locator.count()) and bool(locator.first.is_visible())
    except Exception:  # noqa: BLE001
        return False


#: The button's centre if a ``click_filter`` overlay is the element on top there, else null.
_COVERED_BY_OVERLAY_JS = r"""(el) => {
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const top = document.elementFromPoint(x, y);
  return top && top !== el && top.closest("[data-automation-id='click_filter']") ? {x, y} : null;
}"""


ClickMethod = Literal["overlay-point", "overlay-label", "button", ""]


def _overlay_click(page: Any, button: Any, timeout_ms: int) -> ClickMethod:
    try:
        point = button.first.evaluate(_COVERED_BY_OVERLAY_JS)
    except Exception:  # noqa: BLE001 - no geometry: use the label fallback
        point = None
    if isinstance(point, dict):
        clicks.mouse_click(page, point["x"], point["y"], purpose="auth")
        return "overlay-point"
    label = (button.first.inner_text() or "").strip()
    if label:
        overlay = page.locator(
            f"[data-automation-id='click_filter'][aria-label='{label}']"
        )
        if _visible(overlay):
            clicks.safe_click(overlay.first, purpose="auth", timeout=timeout_ms)
            return "overlay-label"
    return ""


def click_control(
    page: Any, automation_id: str, *, timeout_ms: int = 5000, expect_overlay: bool = False,
) -> ClickMethod:
    """Click a Workday button, going through its ``click_filter`` overlay when present.

    Workday lays a transparent ``div[data-automation-id=click_filter]`` (role=button) over
    its auth submit buttons and only the overlay carries the click handler, so a click on
    the bare button does nothing. The overlay's aria-label varies by tenant ("Sign In" on
    one, "Submit" on another), so it is found by what actually sits on top of the button's
    centre; the label match is a fallback. The overlay can paint after the button, so
    ``expect_overlay`` keeps looking for it for a moment before settling for the button.
    Returns how the click was made ("" when the control is not there).
    """
    button = page.locator(f"[data-automation-id='{automation_id}']")
    if not _visible(button):
        return ""
    method = _overlay_click(page, button, timeout_ms)
    waited = 0
    while not method and expect_overlay and waited < _OVERLAY_GRACE_MS:
        page.wait_for_timeout(250)
        waited += 250
        method = _overlay_click(page, button, timeout_ms)
    if method:
        return method
    clicks.safe_click(button.first, purpose="auth", timeout=timeout_ms)
    return "button"


#: How long an auth submit waits for Workday's click overlay before using the bare button.
_OVERLAY_GRACE_MS = 2000

#: Whether a dropdown/prompt popup is left open, whether a real dialog is up, and a
#: corner point where a full-viewport ``click_filter`` (the popup's dismiss layer) sits,
#: and whether focus is in a prompt's search box (whose results list only Tab closes).
_STRAY_POPUP_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  // A prompt's chips sit in an always-visible role=listbox (selectedItemList): not a popup.
  const POPUP = "[role='listbox']:not([data-automation-id='selectedItemList']), "
    + "[data-automation-id='activeListContainer'], "
    + "[data-automation-id='promptOption']:not([data-automation-id='selectedItem'] *)";
  const popup = [...document.querySelectorAll(POPUP)].some(vis)
    || [...document.querySelectorAll("[aria-haspopup='listbox'][aria-expanded='true']")].some(vis);
  const dialog = [...document.querySelectorAll("[role='dialog'], [aria-modal='true']")]
    .some(d => vis(d) && !d.querySelector(POPUP));
  const top = document.elementFromPoint(2, innerHeight - 2);
  const filter = top && top.closest("[data-automation-id='click_filter']");
  const focused = document.activeElement;
  const prompt = !!focused && (focused.getAttribute('data-automation-id') === 'searchBox'
    || !!focused.closest("[data-automation-id='multiselectInputContainer']"));
  return {popup, dialog, prompt, filter: filter ? {x: 2, y: innerHeight - 2} : null};
}"""


def close_stray_popups(page: Any, *, attempts: int = 3) -> bool:
    """Close a dropdown or prompt popup the fill left open; True when none is left.

    Fill steps close their popups with a best-effort Escape on the trigger, which can
    miss; an open popup keeps Workday's full-viewport ``click_filter`` up, and that layer
    swallows the applicant's mouse wheel after handoff. Escape goes to the page, and when
    it does not land a click on the dismiss layer's corner closes the popup the way a
    click outside would. A prompt's results list (Skills, How Did You Hear) has no dismiss
    layer and ignores Escape; Tab out of its search box closes it without choosing
    anything (CACI 2026-09-28: the list covered the Add buttons). A real dialog (Start
    Your Application, OTP, terms) is left alone.
    """
    for _ in range(attempts):
        try:
            probe = page.evaluate(_STRAY_POPUP_JS)
        except Exception:  # noqa: BLE001 - a navigating page has nothing to close
            return False
        if not isinstance(probe, dict) or not probe.get("popup"):
            return True
        if probe.get("dialog"):
            return False
        with contextlib.suppress(Exception):
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            again = page.evaluate(_STRAY_POPUP_JS)
            point = isinstance(again, dict) and again.get("popup") and again.get("filter")
            if point:
                clicks.mouse_click(page, point["x"], point["y"], purpose="dismiss")
                page.wait_for_timeout(200)
            elif isinstance(again, dict) and again.get("popup") and again.get("prompt"):
                page.keyboard.press("Tab")
                page.wait_for_timeout(200)
    try:
        probe = page.evaluate(_STRAY_POPUP_JS)
    except Exception:  # noqa: BLE001
        return False
    return not (isinstance(probe, dict) and probe.get("popup"))

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
            overlay_late = (time.monotonic() - started) * 1000 < _OVERLAY_GRACE_MS
            if current[0] == "click_filter" or not overlay_late:
                return str(current[0])
        if time.monotonic() >= stop:
            return ""
        page.wait_for_timeout(250)


def _remaining_ms(deadline: float, cap: int) -> int:
    return max(500, min(cap, int((deadline - time.monotonic()) * 1000)))


def is_site_error(snap: dict[str, Any]) -> bool:
    """Workday's "Something went wrong ... Error Code: VPS|..." page."""
    return bool(SITE_ERROR.search(str(snap.get("text") or "")))


def recover_site_error(
    page: Any,
    *,
    deadline: float,
    progress: Callable[[str], None] = lambda _msg: None,
    attempts: int = SITE_ERROR_RELOADS,
) -> tuple[bool, int]:
    """Reload while Workday shows its error page, as the page itself asks.

    The error is usually transient and a reload restores the saved draft. After each
    reload, waits until the page is either a recognisable screen or the error again, so a
    half-painted shell is not mistaken for recovery. Returns ``(recovered, reloads)``;
    ``recovered`` is True as soon as the error page is gone (at once when it never showed).
    """
    reloads = 0
    while is_site_error(snapshot(page)):
        if reloads >= attempts or time.monotonic() >= deadline:
            return False, reloads
        reloads += 1
        progress(f"Workday showed 'Something went wrong' (error code); refreshing the page ({reloads}/{attempts})")
        with contextlib.suppress(Exception):  # the snapshot below decides
            page.reload(wait_until="domcontentloaded", timeout=_remaining_ms(deadline, 30000))
        page.wait_for_timeout(500 * reloads)  # back off a little more each time
        stop = min(deadline, time.monotonic() + 15)
        while time.monotonic() < stop:
            snap = snapshot(page)
            if is_site_error(snap) or classify(snap) != "unknown":
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
) -> tuple[Any, WorkdayState]:
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
        entry = draft if _visible(draft) else page.locator("[data-automation-id='adventureButton']")
        if _visible(draft):
            progress("Workday: resuming the saved application draft")
        _follow_href_or_click(page, entry.first, deadline=deadline)
        page.wait_for_timeout(300)
        if context is not None:
            page = _new_tab(page, context, before, deadline)
        state = wait_for_state(page, terminal | {"start_dialog"}, timeout_s=15, deadline=deadline)
    if state == "start_dialog":
        progress("Workday: choosing Apply Manually")
        manual = page.locator("[data-automation-id='applyManually']")
        if not _visible(manual):
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
        snap = snapshot(page)
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
        snap = snapshot(page)
        step = active_step(snap)
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
    step = active_step(snapshot(page))
    return bool(step and step != before)


# -- My Information / questionnaire dropdowns -------------------------------------------

#: Workday single-select dropdowns: a ``button[aria-haspopup=listbox]`` whose
#: ``aria-controls`` names a ``ul[role=listbox]`` of ``li[role=option]``.
DROPDOWNS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const labelOf = b => {
    if (b.id) {
      const l = document.querySelector(`label[for="${CSS.escape(b.id)}"]`);
      if (l) return (l.innerText || '').trim();
    }
    const field = b.closest("[data-automation-id^='formField-']");
    const l = field && field.querySelector('label, legend');
    return l ? (l.innerText || '').trim() : (b.getAttribute('aria-label') || '');
  };
  return [...document.querySelectorAll("button[aria-haspopup='listbox']")]
    .filter(b => vis(b) && b.closest("[data-automation-id='applyFlowPage']"))
    .filter(b => !b.closest("[data-automation-id='utilityButtonBar']"))
    .map(b => ({
      selector: b.id ? `#${CSS.escape(b.id)}` : '',
      label: labelOf(b).replace(/\*\s*$/, '').trim(),
      current: (b.innerText || '').trim(),
      required: /\*\s*$/.test(labelOf(b)) ||
        /\bRequired\b/.test(b.getAttribute('aria-label') || ''),
    }))
    .filter(item => item.selector);
}"""

_PLACEHOLDER = re.compile(r"^\s*(select one|select|choose one|--)\s*$", re.I)


def dropdowns(page: Any) -> list[dict[str, Any]]:
    try:
        found = page.evaluate(DROPDOWNS_JS)
    except Exception:  # noqa: BLE001
        return []
    return [item for item in found or [] if isinstance(item, dict)]


_OPTIONS_JS = r"""(id) => {
  const list = document.getElementById(id);
  if (!list) return null;
  return [...list.querySelectorAll("[role='option']")].map(o => ({
    id: o.id, label: (o.innerText || '').trim(),
    disabled: o.getAttribute('aria-disabled') === 'true',
  }));
}"""


def _pick_listbox_option(options: list[dict[str, Any]], value: str, key: str) -> tuple[str, str] | None:
    """(label, id) of the one option meaning ``value``, or None."""
    from resume_tailor.apply.hybrid_resolver import _option_match  # noqa: PLC0415

    usable = [o for o in options if not o["disabled"] and not _PLACEHOLDER.match(o["label"])]
    # "Bachelor of Science (B.S)" is matched on its name; the abbreviation is decoration.
    bare = [re.sub(r"\s*\([^)]*\)\s*$", "", o["label"]) for o in usable]
    chosen = _option_match([o["label"] for o in usable], value, key=key)
    if not chosen:
        by_bare = _option_match(bare, value, key=key)
        if by_bare and bare.count(by_bare) == 1:
            chosen = usable[bare.index(by_bare)]["label"]
    if not chosen:
        return None
    return chosen, next(o["id"] for o in usable if o["label"] == chosen)


#: What the last `select_listbox` call saw: its options and why it did not commit, so a
#: failed required choice is reported with the form's own wording (CACI's veteran list,
#: 2026-09, failed with nothing but its label in ``required_empty``).
last_listbox: dict[str, Any] = {}


def _options_text(options: list[str], limit: int = 8) -> str:
    shown = [option[:80] for option in options[:limit]]
    return " | ".join(shown) + (f" | … ({len(options) - limit} more)" if len(options) > limit else "")


def choice_failure(label: str, value: str, options: list[str], status: str = "no_match") -> str:
    """One review line for a profile fact no option named: the value, why, and the options."""
    seen = f"; options: {_options_text(options)}" if options else "; no options were read"
    return f"{label}: no option for {value} ({status.replace('_', ' ')}{seen})"


def select_listbox(page: Any, selector: str, value: str, *, key: str = "") -> bool:
    """Commit one option of a Workday listbox button, verified by the button's new text.

    Options are read in a single evaluate (country lists have ~250 entries, all rendered)
    and matched with the same exact/alias rules as every other choice
    (`field_matcher.match_option`). Workday updates the button text a few hundred ms
    after the click, so the result is polled rather than read once.
    """
    trigger = page.locator(selector).first
    last_listbox.clear()
    last_listbox.update(selector=selector, value=value, options=[], status="not_opened")
    try:
        clicks.safe_click(trigger, purpose="select", timeout=3000)
        options = None
        for _ in range(12):
            # Workday sets aria-controls only once the list has opened, so it is re-read.
            list_id = trigger.get_attribute("aria-controls") or ""
            options = page.evaluate(_OPTIONS_JS, list_id) if list_id else None
            if options:
                break
            page.wait_for_timeout(250)
        labels = [str(o.get("label") or "") for o in options or [] if not _PLACEHOLDER.match(str(o.get("label") or ""))]
        last_listbox.update(options=labels, status="no_match" if labels else "no_options")
        picked = _pick_listbox_option(options or [], value, key)
        if picked is None:
            trigger.press("Escape")
            return False
        last_listbox["status"] = "unverified"
        chosen, option_id = picked
        clicks.safe_click(page.locator(f"[id='{option_id}']").first, purpose="select", timeout=3000)
        for _ in range(12):
            if (trigger.inner_text() or "").strip() == chosen:
                return True
            page.wait_for_timeout(250)
        return False
    except Exception:  # noqa: BLE001 - an unverified choice is left for review
        with contextlib.suppress(Exception):
            trigger.press("Escape")
        return False


def _same_option(current: str, value: str, key: str) -> bool:
    """True when a committed option already means ``value`` (e.g. "United States of America")."""
    from resume_tailor.apply.hybrid_resolver import _option_match  # noqa: PLC0415

    return _option_match([current], value, key=key) is not None


def key_for_label(label: str) -> str | None:
    """The fact a question label asks for (`questions.classify`, shared by every fill)."""
    match = questions.classify(questions.Question(label))
    return match.key if match else None


def country_mismatch(page: Any, fields: dict[str, str]) -> str | None:
    """The Country dropdown's current text when it disagrees with the profile, else None.

    Checked again just before a step advances: Live Oak's and Upbound's Country read
    "Vietnam" (the account's saved address, 2026-09) after the fill, although the choice
    commits correctly when made — so the step is re-checked, not trusted.
    """
    value = fields.get("country", "")
    if not value:
        return None
    for item in dropdowns(page):
        if key_for_label(item["label"]) != "country":
            continue
        current = str(item.get("current") or "")
        if current and not _PLACEHOLDER.match(current) and not _same_option(current, value, "country"):
            return current
    return None


#: Keys these passes leave alone on purpose: salary is a per-posting answer, and the
#: phone code has its own step (`ensure_phone_code`).
_BLANK_EXEMPT = frozenset({"salary_expectation", "phone_country_code"})


def _note_blank(blank: list[dict[str, str]] | None, key: str, label: str, unanswered: bool) -> None:
    """Record an unanswered control whose profile fact is empty."""
    if blank is not None and unanswered:
        blank.append({"key": key, "label": label})


def fill_dropdowns(
    page: Any,
    fields: dict[str, str],
    *,
    select: Callable[..., bool],
    progress: Callable[[str], None] = lambda _msg: None,
    deadline: float | None = None,
    review: list[str] | None = None,
    blank: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Select known profile facts in Workday dropdowns; return what was committed.

    A blank dropdown whose label maps to a profile fact the profile leaves empty is
    recorded in ``blank`` (`fill._missing_profile`), not skipped silently.

    Blank ("Select One") dropdowns only — except Country, which Workday pre-fills from
    the browser locale rather than from the applicant, and which re-renders the whole
    name/address block, so it is corrected first. A dropdown whose label does not map
    to a profile fact, or whose options have no unique match, is left for the resolver.
    """
    committed: list[dict[str, Any]] = []
    tried: set[str] = set()
    facts = questions.facts_for(fields)
    for _pass in range(3):
        progressed = False
        items = dropdowns(page)
        items.sort(key=lambda item: 0 if key_for_label(item["label"]) == "country" else 1)
        for item in items:
            if deadline is not None and time.monotonic() >= deadline:
                return committed
            selector = item["selector"]
            if selector in tried:
                continue
            question = questions.Question(item["label"], kind="choice")
            match = questions.classify(question)
            key = match.key if match else None
            answers = questions.answers(match, question, facts)
            value = answers[0] if answers else ""
            current = str(item.get("current") or "")
            is_blank = not current or bool(_PLACEHOLDER.match(current))
            if not key or key in _BLANK_EXEMPT:
                continue
            if not value:
                _note_blank(blank, questions.profile_field(key), item["label"], is_blank)
                continue
            if not is_blank and not (key == "country" and not _same_option(current, value, key)):
                continue
            tried.add(selector)
            for candidate in answers:
                if select(page, selector, candidate, key=key):
                    progress(f"Workday: selected {item['label']} = {candidate}")
                    committed.append(
                        {"key": key, "label": item["label"], "value": candidate, "selector": selector}
                    )
                    progressed = True
                    break
            if key == "country" and not progressed and review is not None:
                # A wrong country re-labels every name/address field and empties the
                # phone code; it must not pass silently.
                review.append(
                    f"Country: no option matching {value}" if is_blank
                    else f"Country is {current}; profile says {value}"
                )
                progress(f"Workday: could not change Country from {current or 'blank'} to {value}")
            elif not progressed and is_blank:
                # A profile fact no option named is a gap with a cause, not a bare label.
                # Always in the log; a review line only for self-identification, which the
                # resolver does not answer from the profile (other keys it often fills).
                seen = last_listbox if last_listbox.get("selector") == selector else {}
                line = choice_failure(item["label"], value, list(seen.get("options") or []),
                                      str(seen.get("status") or "no_match"))
                progress(f"Workday: {line}")
                if review is not None and key in field_matcher.EEO_KEYS:
                    review.append(line)
            if progressed and key == "country":
                page.wait_for_timeout(800)  # the form re-renders under the new country
                break
        if not progressed:
            break
    return committed


# -- Yes/No radio questions -------------------------------------------------------------

#: Unanswered radio groups inside Workday form fields, with their legend question.
RADIOS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const out = [];
  for (const field of document.querySelectorAll("[data-automation-id^='formField-']")) {
    const radios = [...field.querySelectorAll("input[type='radio']")].filter(vis);
    if (!radios.length || radios.some(r => r.checked)) continue;
    const legend = field.querySelector('legend');
    out.push({
      field: field.getAttribute('data-automation-id'),
      question: (legend ? legend.innerText : '').replace(/\*\s*$/, '').trim(),
      options: radios.map(r => {
        const l = r.id && document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
        return {id: r.id, label: l ? (l.innerText || '').trim() : (r.value || '')};
      }).filter(o => o.id),
    });
  }
  return out;
}"""

def _norm_company(value: str) -> str:
    value = re.sub(r"[^a-z0-9 ]+", " ", value.casefold())
    value = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co|group)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def previously_employed(company: str, employers: Iterable[str]) -> bool:
    """True only when the posting company is one of the applicant's own employers."""
    target = _norm_company(company)
    if not target:
        return False
    return any(
        (name := _norm_company(employer)) and (name == target or re.search(rf"\b{re.escape(target)}\b", name))
        for employer in employers
    )


def fill_radios(
    page: Any,
    fields: dict[str, str],
    *,
    company: str,
    employers: Iterable[str],
    role: str = "",
    experience_titles: Iterable[str] = (),
    progress: Callable[[str], None] = lambda _msg: None,
    blank: list[dict[str, str]] | None = None,
    review: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Answer unanswered Yes/No radio questions from profile facts, and only those.

    A self-identification question no option answers is reported in ``review`` with the
    options it offered (`choice_failure`).

    What a question asks, its answer and the option that says it come from `questions`:
    "Have you ever been employed by <company>?" from the applicant's own experience
    entries, "Are you currently enrolled?" from the graduation date, every other question
    from a profile fact whose value names one option (exactly, or a self-identification
    answer's long form). Anything else stays for the resolver or the applicant.
    """
    try:
        groups = page.evaluate(RADIOS_JS) or []
    except Exception:  # noqa: BLE001
        return []
    facts = questions.facts_for(
        fields, company=company, role=role, employers=employers,
        experience_titles=experience_titles,
    )
    committed: list[dict[str, Any]] = []
    for group in groups:
        question = str(group.get("question") or "")
        options = group.get("options") or []
        labels = [str(opt.get("label", "")) for opt in options]
        asked = questions.Question(question, kind="choice", options=tuple(labels))
        match = (
            questions.Match("previous_worker", question.casefold())
            if group.get("field") == "formField-candidateIsPreviousWorker"
            else questions.classify(asked)
        )
        key = match.key if match else ""
        if not key or key in _BLANK_EXEMPT:
            continue
        answers = questions.answers(match, asked, facts)
        if not answers:
            _note_blank(blank, questions.profile_field(key), question, True)
            continue
        value = answers[0]
        chosen = questions.choose(asked, key, answers)
        matches = [opt for opt in options if str(opt.get("label", "")) == chosen] if chosen else []
        if len(matches) != 1:
            if key in field_matcher.EEO_KEYS and not any(opt.get("checked") for opt in options):
                line = choice_failure(question or key, value, labels)
                progress(f"Workday: {line}")
                if review is not None:
                    review.append(line)
            continue
        try:
            clicks.safe_click(page.locator(f"label[for='{matches[0]['id']}']").first, purpose="select", timeout=3000)
            checked = page.locator(f"[id='{matches[0]['id']}']").first.is_checked()
        except Exception:  # noqa: BLE001
            checked = False
        if checked:
            progress(f"Workday: answered {question[:60]} = {matches[0]['label']}")
            committed.append({"key": key, "label": question, "value": matches[0]["label"],
                              "selector": f"[id='{matches[0]['id']}']"})
    return committed


# -- Self-identification: checkbox answers, Self Identify step ---------------------------

#: Groups of visible checkboxes inside one Workday form field (or fieldset), with the
#: question and each option's label: the disability form ("Yes, I have a disability" /
#: "No, I do not have a disability" / "I do not want to answer") and tenants that render
#: race or veteran status as checkboxes.
CHECKBOX_GROUPS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const root = document.querySelector("[data-automation-id='applyFlowPage']") || document;
  const groups = new Map();
  for (const box of root.querySelectorAll("input[type='checkbox']")) {
    const label = box.id && document.querySelector(`label[for="${CSS.escape(box.id)}"]`);
    if (!box.id || !(vis(box) || vis(label))) continue;
    const container = box.closest("[data-automation-id^='formField-'], fieldset, [role='group']") || box.parentElement;
    if (!groups.has(container)) groups.set(container, []);
    groups.get(container).push({id: box.id, label: label ? (label.innerText || '').trim() : '', checked: box.checked});
  }
  return [...groups].filter(([, options]) => options.length > 1).map(([container, options]) => {
    const legend = container.querySelector("legend, label:not([for])");
    return {question: (legend ? legend.innerText : '').replace(/\*\s*$/, '').trim(), options};
  });
}"""

#: Text and split-date controls of the Self Identify step, by their field label.
SELF_ID_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const root = document.querySelector("[data-automation-id='applyFlowPage']") || document;
  const out = [];
  for (const field of root.querySelectorAll("[data-automation-id^='formField-']")) {
    const label = field.querySelector('label, legend');
    const text = (label ? label.innerText : '').replace(/\*\s*$/, '').trim();
    const month = field.querySelector("input[id$='-dateSectionMonth-input']");
    if (month) {
      const control = month.id.slice(0, -'-dateSectionMonth-input'.length);
      out.push({kind: 'date', label: text, control,
                day: !!field.querySelector("input[id$='-dateSectionDay-input']")});
      continue;
    }
    const input = [...field.querySelectorAll("input[type='text'], input:not([type])")].filter(vis)[0];
    if (input && input.id && !input.closest("[data-automation-id='multiselectInputContainer']")) {
      out.push({kind: 'text', label: text, id: input.id, value: (input.value || '').trim()});
    }
  }
  return out;
}"""

#: The disability form's answers are its own options; its question rarely says so.
_DISABILITY_OPTION = re.compile(r"\bdisabilit", re.I)
_SELF_ID_STEP = re.compile(r"self[\s-]*identif", re.I)
_NAME_LABEL = re.compile(r"^(?:your |full |legal )*name$|^signature$", re.I)
_EMPLOYEE_ID = re.compile(r"employee\s*(?:id|number)", re.I)
_DATE_LABEL = re.compile(r"^(?:today'?s )?date(?: signed)?$", re.I)


def _group_key(group: dict[str, Any]) -> str | None:
    labels = [str(option.get("label") or "") for option in group.get("options") or []]
    if sum(bool(_DISABILITY_OPTION.search(label)) for label in labels) >= 2:
        return "disability_status"
    key = key_for_label(str(group.get("question") or ""))
    return key if key in field_matcher.EEO_KEYS else None


def _tick(page: Any, box_id: str) -> bool:
    box = page.locator(f"[id='{box_id}']").first
    if not box.is_checked():
        try:
            clicks.safe_click(page.locator(f"label[for='{box_id}']").first, purpose="select", timeout=3000)
        except Exception:  # noqa: BLE001 - an unlabelled box takes the click itself
            box.check(timeout=2000)
    return bool(box.is_checked())


def fill_choice_checkboxes(
    page: Any,
    fields: dict[str, str],
    *,
    progress: Callable[[str], None] = lambda _msg: None,
    review: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Tick the one option of each self-identification checkbox group that means the
    profile's answer (`field_matcher.eeo_pattern`: "No" -> "No, I do not have a
    disability..."). A group with a ticked box is the applicant's answer and is kept; no
    unique option is left for review, never guessed.
    """
    try:
        groups = page.evaluate(CHECKBOX_GROUPS_JS) or []
    except Exception:  # noqa: BLE001
        return []
    committed: list[dict[str, Any]] = []
    for group in groups:
        key = _group_key(group)
        options = group.get("options") or []
        if not key or any(option.get("checked") for option in options):
            continue
        question = str(group.get("question") or "") or key.replace("_", " ").capitalize()
        labels = [str(option.get("label") or "") for option in options]
        chosen = None
        for candidate in field_matcher.choice_values(key, fields):
            chosen = field_matcher.closest_option(labels, candidate, key=key)
            if chosen:
                break
        if chosen is None:
            if fields.get(key) and review is not None:
                review.append(choice_failure(question, fields[key], labels))
            continue
        box_id = next(str(option["id"]) for option in options if option.get("label") == chosen)
        try:
            ticked = _tick(page, box_id)
        except Exception:  # noqa: BLE001
            ticked = False
        if ticked:
            progress(f"Workday: ticked {chosen[:70]}")
            committed.append({"key": key, "label": question, "value": chosen, "selector": f"[id='{box_id}']"})
        elif review is not None:
            review.append(f"{question}: could not tick {chosen}")
    return committed


def fill_self_identify(
    page: Any,
    fields: dict[str, str],
    *,
    today: date,
    progress: Callable[[str], None] = lambda _msg: None,
    review: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The Self Identify step's signature: Name (the applicant's full name) and today's
    Date; Employee ID stays blank (applicants are not employees). Existing answers are
    kept. The disability answer is `fill_choice_checkboxes`'s.
    """
    from resume_tailor.apply import workday_repeaters  # noqa: PLC0415

    try:
        controls = page.evaluate(SELF_ID_JS) or []
    except Exception:  # noqa: BLE001
        return []
    committed: list[dict[str, Any]] = []
    name = fields.get("full_name", "")
    for control in controls:
        label = str(control.get("label") or "")
        if control.get("kind") == "text" and _EMPLOYEE_ID.search(label):
            progress("Workday: leaving Employee ID blank")
        elif control.get("kind") == "text" and _NAME_LABEL.match(label) and name:
            if control.get("value"):
                continue
            box = page.locator(f"[id='{control['id']}']").first
            try:
                box.fill(name, timeout=3000)
                ok = str(box.input_value() or "").strip() == name
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                progress(f"Workday: signed {label} = {name}")
                committed.append({"key": "full_name", "label": label, "value": name,
                                  "selector": f"[id='{control['id']}']"})
            elif review is not None:
                review.append(label)
        elif control.get("kind") == "date" and _DATE_LABEL.match(label):
            parts = [("dateSectionMonth", f"{today.month:02d}")]
            if control.get("day"):
                parts.append(("dateSectionDay", f"{today.day:02d}"))
            parts.append(("dateSectionYear", str(today.year)))
            try:
                ok = workday_repeaters.fill_date_sections(page, str(control["control"]), parts)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                progress(f"Workday: dated {label} {today.isoformat()}")
                committed.append({"key": "signature_date", "label": label, "value": today.isoformat(),
                                  "selector": f"[id='{control['control']}-dateSectionMonth-input']"})
            elif review is not None:
                review.append(label)
    return committed


def is_self_identify_step(snap: dict[str, Any]) -> bool:
    """Workday's disability self-identification (CC-305) step."""
    return bool(_SELF_ID_STEP.search(active_step(snap)))


# -- Multiselect prompts (Field of Study, School, ...) -----------------------------------

_PROMPT_STATE_JS = r"""(id) => {
  const input = document.getElementById(id);
  const field = input && input.closest("[data-automation-id^='formField-']");
  if (!field) return null;
  return [...field.querySelectorAll("[data-automation-id='selectedItem']")]
    .map(e => (e.innerText || e.getAttribute('aria-label') || '').trim());
}"""


#: Options of the open prompt popup; committed chips elsewhere (the phone code's
#: "United States of America (+1)") also carry ``promptOption`` and are not choices.
_OPEN_PROMPT_OPTIONS = (
    "[data-automation-id='promptOption']:not([data-automation-id='selectedItem'] *)"
)


def select_prompt(page: Any, input_id: str, value: str, *, key: str = "") -> bool:
    """Commit ``value`` in a Workday prompt: search, then click the one matching option.

    Searches run from the full value to shorter terms (`field_matcher.search_terms`:
    Workday finds "University of California, Irvine" from "Irvine", not from the full
    name), and the option is chosen by `field_matcher.closest_option`. A clicked option
    that opens a category ("Other" under a hierarchical source list) gets one drill-down
    pick. An existing chip is the applicant's answer: it counts only if it already matches.
    """
    def _means(chip: str, chosen: str) -> bool:
        return chip.strip() == chosen.strip() or field_matcher.closest_option([chip], value, key=key) is not None

    def _open_options() -> tuple[Any, list[str]]:
        options = page.locator(_OPEN_PROMPT_OPTIONS)
        return options, [str(text).strip() for text in options.all_inner_texts()]

    def _choose(texts: list[str]) -> str | None:
        # One leaf can sit under two categories ("LinkedIn" under Job Board and under
        # Social Media); identical labels are the same answer, not an ambiguity.
        unique = list(dict.fromkeys(text for text in texts if text and not _NO_ITEMS.match(text)))
        return field_matcher.closest_option(unique, value, key=key) if unique else None

    try:
        chips = page.evaluate(_PROMPT_STATE_JS, input_id)
        if chips is None:
            return False
        if chips:
            return len(chips) == 1 and field_matcher.closest_option(chips, value, key=key) is not None
        box = page.locator(f"[id='{input_id}']").first
        chosen = None
        for term in field_matcher.search_terms(key, value):
            box.fill("", timeout=3000)
            box.fill(term, timeout=3000)
            box.press("Enter")
            for _ in range(16):
                page.wait_for_timeout(250)
                # Enter on a search with a single result commits it without listing it
                # (Upbound's Field of Study: "Computer Science" -> "Computer and
                # Information Science"); the chip is then the answer to check.
                auto = page.evaluate(_PROMPT_STATE_JS, input_id) or []
                if auto:
                    return len(auto) == 1 and field_matcher.closest_option(auto, value, key=key) is not None
                options, texts = _open_options()
                chosen = _choose(texts)
                if chosen:
                    clicks.safe_click(options.nth(texts.index(chosen)), purpose="select", timeout=3000)
                    break
            if chosen:
                break
        if not chosen:
            box.press("Escape")
            return False

        def committed() -> bool | None:
            for _ in range(8):
                page.wait_for_timeout(250)
                chips = page.evaluate(_PROMPT_STATE_JS, input_id) or []
                if len(chips) == 1:
                    return _means(chips[0], chosen)
            return None

        verdict = committed()
        if verdict is not None:
            return verdict
        options, after = _open_options()
        leaf = _choose(after)
        if leaf and leaf != chosen:
            # The click opened a category ("Other" in a hierarchical source list).
            clicks.safe_click(options.nth(after.index(leaf)), purpose="select", timeout=3000)
            chosen = leaf
        else:
            # A single-select prompt (Field of Study) paints its chip once the list closes.
            with contextlib.suppress(Exception):
                box.press("Escape")
        return bool(committed())
    except Exception:  # noqa: BLE001 - an unverified prompt is left for review
        return False


#: Empty-or-not multiselect prompts on the current step, outside the My Experience rows
#: (those belong to ``workday_repeaters``) and the phone code (``ensure_phone_code``).
PROMPTS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  return [...document.querySelectorAll("[data-automation-id^='formField-']")]
    .filter(f => vis(f) && f.closest("[data-automation-id='applyFlowPage']"))
    .filter(f => f.querySelector("[data-automation-id='multiselectInputContainer']"))
    .filter(f => f.getAttribute('data-automation-id') !== 'formField-countryPhoneCode')
    .map(f => {
      const input = f.querySelector('input');
      const l = f.querySelector('label, legend');
      return {
        input_id: input ? input.id : '',
        field: f.getAttribute('data-automation-id'),
        label: (l ? l.innerText : '').replace(/\*\s*$/, '').trim(),
        chips: f.querySelectorAll("[data-automation-id='selectedItem']").length,
      };
    })
    .filter(p => p.input_id && !/^(workExperience|education|language)-/.test(p.input_id));
}"""


def fill_prompts(
    page: Any,
    fields: dict[str, str],
    *,
    select: Callable[..., bool] | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
) -> list[dict[str, Any]]:
    """Commit known profile facts in empty prompts ("How Did You Hear About Us?").

    A prompt that already holds a chip is the applicant's answer and is left alone; one
    whose label maps to no profile fact, or whose search finds no exact option, is left
    for review.
    """
    choose = select or select_prompt
    try:
        found = page.evaluate(PROMPTS_JS) or []
    except Exception:  # noqa: BLE001
        return []
    committed: list[dict[str, Any]] = []
    for item in found:
        if not isinstance(item, dict) or item.get("chips") or is_skills_prompt(item):
            continue
        question = questions.Question(str(item.get("label") or ""), kind="typeahead")
        match = questions.classify(question)
        key = match.key if match else None
        answers = questions.answers(match, question, questions.facts_for(fields))
        value = answers[0] if answers else ""
        if not key or not value:
            continue
        for candidate in answers:
            if choose(page, item["input_id"], candidate, key=key):
                progress(f"Workday: selected {item['label']} = {candidate}")
                committed.append({
                    "key": key, "label": item["label"], "value": candidate,
                    "selector": f"[id='{item['input_id']}']",
                })
                break
        else:
            progress(f"Workday: no exact option for {item['label']} = {value}; left for review")
    return committed


# -- Skills (multi-chip prompt) ----------------------------------------------------------

_SKILLS_LABEL = re.compile(r"^(?:type to add )?skills?$", re.I)
#: Workday's empty-search row, which is not a choice.
_NO_ITEMS = re.compile(r"^no (?:items|results|matches)(?: found)?\.?$", re.I)


def is_skills_prompt(item: dict[str, Any]) -> bool:
    return item.get("field") == "formField-skills" or bool(_SKILLS_LABEL.match(str(item.get("label") or "").strip()))


def _chips(page: Any, input_id: str) -> list[str]:
    try:
        return [str(chip) for chip in page.evaluate(_PROMPT_STATE_JS, input_id) or []]
    except Exception:  # noqa: BLE001
        return []


#: Tag the ``index``-th committed chip of one prompt (the order `_chips` reads) with
#: ``data-rt-chip`` so it can be focused by attribute; False when there is no such chip.
_CHIP_AT_JS = r"""([id, index]) => {
  document.querySelectorAll('[data-rt-chip]').forEach(e => e.removeAttribute('data-rt-chip'));
  const input = document.getElementById(id);
  const field = input && input.closest("[data-automation-id^='formField-']");
  const chips = field ? [...field.querySelectorAll("[data-automation-id='selectedItem']")] : [];
  if (chips[index]) chips[index].setAttribute('data-rt-chip', '1');
  return !!chips[index];
}"""


def remove_duplicate_chips(page: Any, input_id: str, progress: Callable[[str], None] = lambda _msg: None) -> int:
    """Delete repeated chips (same skill text), keeping the first of each; the count removed.

    Workday refuses the whole step with "You cannot enter duplicate skills", and a draft
    saved by an earlier run keeps them (F5, 2026-09). A chip is removed the way its own
    label says ("press delete to clear value"), and each removal is verified.
    """
    from resume_tailor.apply.field_matcher import same_skill_in  # noqa: PLC0415

    removed = 0
    for _ in range(20):
        chips = _chips(page, input_id)
        duplicate = next((index for index, chip in enumerate(chips) if same_skill_in(chips[:index], chip)), None)
        if duplicate is None:
            break
        try:
            if not page.evaluate(_CHIP_AT_JS, [input_id, duplicate]):
                break
            chip = page.locator("[data-rt-chip]").first
            chip.focus(timeout=2000)
            chip.press("Delete", timeout=2000)
            page.wait_for_timeout(300)
        except Exception:  # noqa: BLE001 - left for the applicant
            break
        if len(_chips(page, input_id)) != len(chips) - 1:
            break
        removed += 1
        progress(f"Workday: removed a duplicate skill chip ({chips[duplicate]})")
    return removed


def _search_prompt(page: Any, input_id: str, term: str) -> list[str]:
    """Type one search into a prompt and return its settled options (duplicates kept)."""
    box = page.locator(f"[id='{input_id}']").first
    box.fill("", timeout=3000)
    box.fill(term, timeout=3000)
    box.press("Enter")
    options = page.locator(_OPEN_PROMPT_OPTIONS)
    previous: list[str] | None = None
    texts: list[str] = []
    for _ in range(16):
        page.wait_for_timeout(250)
        texts = [str(text).strip() for text in options.all_inner_texts()]
        texts = [text for text in texts if text and not _NO_ITEMS.match(text)]
        # Results stream in; settled means two identical non-empty reads.
        if texts and texts == previous:
            break
        previous = texts
    return texts


def _click_option(page: Any, input_id: str, texts: list[str], option: str, before: int) -> bool:
    """Click ``option`` in the open results; verified by exactly one new chip."""
    clicks.safe_click(page.locator(_OPEN_PROMPT_OPTIONS).nth(texts.index(option)), purpose="select", timeout=3000)
    for _ in range(8):
        page.wait_for_timeout(250)
        if len(_chips(page, input_id)) == before + 1:
            return True
    return False


def _commit_skill(page: Any, input_id: str, term: str, option: str) -> bool:
    """Search ``term`` again and commit ``option`` from its results."""
    before = len(_chips(page, input_id))
    texts = _search_prompt(page, input_id, term)
    return option in texts and _click_option(page, input_id, texts, option, before)


def fill_skills(
    page: Any,
    skills: list[str],
    *,
    choose_many: Callable[[dict[str, list[str]]], dict[str, str | None]] | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    deadline: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Enter the prepared skills into a Workday Skills prompt, one search per skill.

    Each skill is typed and an option naming it exactly (or by its abbreviation) is
    picked. The skills with no such option are then put to ``choose_many`` in ONE call,
    with the options each search actually showed; a pick outside those options is
    ignored. Chips already on the prompt are kept and not re-added. Returns the committed
    chips and the skills left for the applicant.
    """
    from resume_tailor.apply.field_matcher import match_skill_option, same_skill_in  # noqa: PLC0415

    try:
        prompts = [item for item in page.evaluate(PROMPTS_JS) or [] if isinstance(item, dict)]
    except Exception:  # noqa: BLE001
        return [], []
    prompt = next((item for item in prompts if is_skills_prompt(item)), None)
    if prompt is None or not skills:
        return [], []
    input_id = str(prompt["input_id"])
    label = str(prompt.get("label") or "Skills")
    committed: list[dict[str, Any]] = []
    review: list[str] = []
    unmatched: dict[str, list[str]] = {}

    def out_of_time() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def record(skill: str, option: str, how: str) -> None:
        progress(f"Workday: added skill {skill} -> {option} ({how})")
        committed.append({"key": "skills", "label": label, "value": option,
                          "selector": f"[id='{input_id}']"})

    def on_form(option: str) -> bool:
        # Two skills can resolve to one option ("HuggingFace", "Hugging Face"), and a
        # Continue run finds the first run's chips: Workday rejects the whole step with
        # "You cannot enter duplicate skills" (F5, 2026-09), so an option already
        # committed as a chip is never clicked again.
        return same_skill_in(_chips(page, input_id), option)

    remove_duplicate_chips(page, input_id, progress)
    progress(f"Workday: entering {len(skills)} skill(s) one at a time")
    for skill in dict.fromkeys(s.strip() for s in skills if s.strip()):
        if out_of_time():
            review.append(skill)
            continue
        chips = _chips(page, input_id)
        if match_skill_option(chips, skill):
            continue  # already on the form
        try:
            texts = _search_prompt(page, input_id, skill)
            chosen = match_skill_option(texts, skill)
            if chosen and same_skill_in(chips, chosen):
                continue  # this option is already a chip, under another skill's name
            if chosen and _click_option(page, input_id, texts, chosen, len(chips)):
                record(skill, chosen, "exact")
            elif chosen:
                review.append(skill)
            elif texts:
                unmatched[skill] = list(dict.fromkeys(texts))[:25]
            else:
                review.append(skill)
        except Exception:  # noqa: BLE001 - one bad search does not stop the rest
            review.append(skill)

    if unmatched and choose_many is not None and not out_of_time():
        progress(f"Workday: asking the model about {len(unmatched)} skill(s) with no exact option")
        try:
            picks = choose_many(unmatched)
        except Exception as exc:  # noqa: BLE001
            progress(f"Workday: skill matching failed ({type(exc).__name__}); left for review")
            picks = {}
        used: set[str] = {str(c["value"]) for c in committed}
        for skill, options in unmatched.items():
            pick = picks.get(skill)
            if not pick or pick not in options or pick in used or out_of_time():
                review.append(skill)
                continue
            if on_form(pick):
                continue  # the model chose a skill the form already lists
            try:
                ok = _commit_skill(page, input_id, skill, pick)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                used.add(pick)
                record(skill, pick, "model")
            else:
                review.append(skill)
    else:
        review.extend(unmatched)
    with contextlib.suppress(Exception):
        page.locator(f"[id='{input_id}']").first.press("Escape")
    # Escape on the input can leave the results list (and its full-viewport dismiss
    # layer) open, which then swallows the next clicks: the Add buttons below it.
    close_stray_popups(page)
    return committed, review


# -- Phone country code (multiselect prompt) --------------------------------------------

PHONE_CODE_JS = r"""() => {
  const field = document.querySelector("[data-automation-id='formField-countryPhoneCode']");
  if (!field) return null;
  const chips = [...field.querySelectorAll("[data-automation-id='selectedItem']")]
    .map(e => (e.innerText || e.getAttribute('aria-label') || '').trim());
  const input = field.querySelector('input');
  return {chips, input_id: input ? input.id : ''};
}"""


def ensure_phone_code(
    page: Any,
    region: str,
    code: str,
    *,
    progress: Callable[[str], None] = lambda _msg: None,
) -> bool | None:
    """Make the phone-code prompt hold exactly ``<region> (<code>)``.

    Returns None when the step has no such prompt, True when the committed chip matches,
    False when it could not be verified (left for review).
    """
    from resume_tailor.apply.hybrid_resolver import _phone_option  # noqa: PLC0415

    try:
        state = page.evaluate(PHONE_CODE_JS)
    except Exception:  # noqa: BLE001
        return None
    if not state:
        return None

    def _matches(chip: str) -> bool:
        # The whole region name must agree: "United States Minor Outlying Islands (+1)"
        # also contains "United States" and "+1", and made the choice ambiguous.
        return _phone_option([chip], code, region) is not None

    chips = state.get("chips") or []
    if len(chips) == 1 and _matches(chips[0]):
        return True
    if not region or not code or not state.get("input_id"):
        return False
    field = page.locator("[data-automation-id='formField-countryPhoneCode']")
    try:
        for _ in chips:
            charm = field.locator("[data-automation-id='DELETE_charm']")
            if not _visible(charm):
                break
            clicks.safe_click(charm.first, purpose="select", timeout=3000)
            page.wait_for_timeout(200)
        box = page.locator(f"[id='{state['input_id']}']")
        box.fill(region, timeout=3000)
        box.press("Enter")
        options = page.locator("[data-automation-id='promptOption']")
        for _ in range(12):
            page.wait_for_timeout(250)
            texts = [str(t).strip() for t in options.all_inner_texts()]
            exact = [i for i, text in enumerate(texts) if _matches(text)]
            if len(exact) == 1:
                clicks.safe_click(options.nth(exact[0]), purpose="select", timeout=3000)
                break
        else:
            box.press("Escape")
            return False
        page.wait_for_timeout(300)
        after = page.evaluate(PHONE_CODE_JS) or {}
        ok = len(after.get("chips") or []) == 1 and _matches(after["chips"][0])
        if ok:
            progress(f"Workday: phone country code set to {after['chips'][0]}")
        return ok
    except Exception:  # noqa: BLE001
        return False
