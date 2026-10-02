"""Workday page primitives: state classification, snapshots, overlay-safe clicks, popups."""

from __future__ import annotations

import contextlib
import re
from typing import Any, Literal

from resume_tailor.apply.driver import clicks

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
