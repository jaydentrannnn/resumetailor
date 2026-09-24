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
from typing import Any, Literal

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
_VERIFY_EMAIL = re.compile(
    r"verify your (?:account|email)|verification (?:email|link) (?:has been|was) sent|"
    r"check your email to (?:verify|activate)",
    re.I,
)
#: Workday's own failure page ("Something went wrong ... Error Code: VPS|...").
SITE_ERROR = re.compile(r"something went wrong\s+please refresh the page", re.I)
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
            return "unknown"
        return "apply_form"
    if _VERIFY_EMAIL.search(text):
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
        page.mouse.click(point["x"], point["y"])
        return "overlay-point"
    label = (button.first.inner_text() or "").strip()
    if label:
        overlay = page.locator(
            f"[data-automation-id='click_filter'][aria-label='{label}']"
        )
        if _visible(overlay):
            overlay.first.click(timeout=timeout_ms)
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
    button.first.click(timeout=timeout_ms)
    return "button"


#: How long an auth submit waits for Workday's click overlay before using the bare button.
_OVERLAY_GRACE_MS = 2000

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


def _new_tab(page: Any, context: Any, before: list[Any], deadline: float) -> Any:
    """Follow Apply into a new tab when a tenant opens one; otherwise stay put."""
    try:
        opened = [item for item in context.pages if item not in before and not item.is_closed()]
    except Exception:  # noqa: BLE001 - no context to inspect
        return page
    if len(opened) != 1:
        return page
    with contextlib.suppress(Exception):  # the state wait that follows decides
        opened[0].wait_for_load_state("domcontentloaded", timeout=_remaining_ms(deadline, 15000))
    return opened[0]


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
        entry.first.click(timeout=_remaining_ms(deadline, 5000))
        page.wait_for_timeout(300)
        if context is not None:
            page = _new_tab(page, context, before, deadline)
        state = wait_for_state(page, terminal | {"start_dialog"}, timeout_s=15, deadline=deadline)
    if state == "start_dialog":
        progress("Workday: choosing Apply Manually")
        manual = page.locator("[data-automation-id='applyManually']")
        if not _visible(manual):
            return page, state
        manual.first.click(timeout=_remaining_ms(deadline, 5000))
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


def wait_for_step_change(page: Any, before: str, *, deadline: float, timeout_s: float = 15) -> bool:
    """After Save and Continue, wait for the progress bar to move past ``before``.

    Returns False once validation errors are showing on the unchanged step (they appear
    within about a second) or at the timeout.
    """
    stop = min(deadline, time.monotonic() + timeout_s)
    started = time.monotonic()
    while time.monotonic() < stop:
        snap = snapshot(page)
        step = active_step(snap)
        if step and step != before:
            return True
        ids = set(snap.get("ids") or [])
        if time.monotonic() - started > 2 and ({"errorMessage", "inputAlert"} & ids or snap.get("alerts")):
            return False
        page.wait_for_timeout(250)
    return False


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


def select_listbox(page: Any, selector: str, value: str, *, key: str = "") -> bool:
    """Commit one option of a Workday listbox button, verified by the button's new text.

    Options are read in a single evaluate (country lists have ~250 entries) and matched
    with the same exact/alias rules as every other choice (`field_matcher.match_option`).
    Workday updates the button text a few hundred ms after the click, so the result is
    polled rather than read once.
    """
    from resume_tailor.apply.hybrid_resolver import _option_match  # noqa: PLC0415

    trigger = page.locator(selector).first
    try:
        trigger.click(timeout=3000)
        options = None
        for _ in range(12):
            # Workday sets aria-controls only once the list has opened, so it is re-read.
            list_id = trigger.get_attribute("aria-controls") or ""
            options = page.evaluate(_OPTIONS_JS, list_id) if list_id else None
            if options:
                break
            page.wait_for_timeout(250)
        usable = [o for o in options or [] if not o["disabled"] and not _PLACEHOLDER.match(o["label"])]
        # "Bachelor of Science (B.S)" is matched on its name; the abbreviation is decoration.
        bare = [re.sub(r"\s*\([^)]*\)\s*$", "", o["label"]) for o in usable]
        chosen = _option_match([o["label"] for o in usable], value, key=key)
        if not chosen:
            by_bare = _option_match(bare, value, key=key)
            if by_bare and bare.count(by_bare) == 1:
                chosen = usable[bare.index(by_bare)]["label"]
        if not chosen:
            trigger.press("Escape")
            return False
        option_id = next(o["id"] for o in usable if o["label"] == chosen)
        page.locator(f"[id='{option_id}']").first.click(timeout=3000)
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


def key_for_label(label: str, synonyms: list[tuple[str, str]]) -> str | None:
    low = label.casefold()
    if "future" in low and "sponsor" in low:
        return "requires_sponsorship_future"
    for pattern, key in synonyms:
        if re.search(pattern, low, re.I):
            return key
    return None


def fill_dropdowns(
    page: Any,
    fields: dict[str, str],
    *,
    synonyms: list[tuple[str, str]],
    select: Callable[..., bool],
    progress: Callable[[str], None] = lambda _msg: None,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    """Select known profile facts in Workday dropdowns; return what was committed.

    Blank ("Select One") dropdowns only — except Country, which Workday pre-fills from
    the browser locale rather than from the applicant, and which re-renders the whole
    name/address block, so it is corrected first. A dropdown whose label does not map
    to a profile fact, or whose options have no unique match, is left for the resolver.
    """
    committed: list[dict[str, Any]] = []
    tried: set[str] = set()
    for _pass in range(3):
        progressed = False
        items = dropdowns(page)
        items.sort(key=lambda item: 0 if key_for_label(item["label"], synonyms) == "country" else 1)
        for item in items:
            if deadline is not None and time.monotonic() >= deadline:
                return committed
            selector = item["selector"]
            if selector in tried:
                continue
            key = key_for_label(item["label"], synonyms)
            value = fields.get(key or "", "")
            if not key or not value or key in {"salary_expectation", "phone_country_code"}:
                continue
            current = str(item.get("current") or "")
            is_blank = not current or bool(_PLACEHOLDER.match(current))
            if not is_blank and not (key == "country" and not _same_option(current, value, key)):
                continue
            tried.add(selector)
            candidates = [fields.get("race_detail", ""), value] if key == "race" else [value]
            for candidate in [c for c in candidates if c]:
                if select(page, selector, candidate, key=key):
                    progress(f"Workday: selected {item['label']} = {candidate}")
                    committed.append(
                        {"key": key, "label": item["label"], "value": candidate, "selector": selector}
                    )
                    progressed = True
                    break
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

_PREVIOUS_WORKER = re.compile(
    r"previous(?:ly)?\s+(?:worked|employed)|ever\s+(?:been\s+)?(?:worked|employed)|"
    r"former\s+employee|current\s+or\s+former|worked\s+(?:for|at)\s+.{0,40}before",
    re.I,
)


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
    synonyms: list[tuple[str, str]],
    company: str,
    employers: Iterable[str],
    progress: Callable[[str], None] = lambda _msg: None,
) -> list[dict[str, Any]]:
    """Answer unanswered Yes/No radio questions from profile facts, and only those.

    "Have you ever been employed by <company>?" is answered from the applicant's own
    experience entries; every other question needs a profile fact whose value equals one
    option label exactly. Anything else stays for the resolver or the applicant.
    """
    try:
        groups = page.evaluate(RADIOS_JS) or []
    except Exception:  # noqa: BLE001
        return []
    employers = list(employers)
    committed: list[dict[str, Any]] = []
    for group in groups:
        question = str(group.get("question") or "")
        options = group.get("options") or []
        if _PREVIOUS_WORKER.search(question) or group.get("field") == "formField-candidateIsPreviousWorker":
            key, value = "previous_worker", "Yes" if previously_employed(company, employers) else "No"
        else:
            key = key_for_label(question, synonyms) or ""
            value = fields.get(key, "")
        if not key or not value or key in {"salary_expectation"}:
            continue
        matches = [opt for opt in options if str(opt.get("label", "")).casefold() == value.casefold()]
        if len(matches) != 1:
            continue
        try:
            page.locator(f"label[for='{matches[0]['id']}']").first.click(timeout=3000)
            checked = page.locator(f"[id='{matches[0]['id']}']").first.is_checked()
        except Exception:  # noqa: BLE001
            checked = False
        if checked:
            progress(f"Workday: answered {question[:60]} = {matches[0]['label']}")
            committed.append({"key": key, "label": question, "value": matches[0]["label"],
                              "selector": f"[id='{matches[0]['id']}']"})
    return committed


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
    """Commit ``value`` in a Workday prompt: search, then click one exactly matching option.

    An existing chip is the applicant's answer: it counts only if it already matches.
    """
    from resume_tailor.apply.hybrid_resolver import _option_match  # noqa: PLC0415

    try:
        chips = page.evaluate(_PROMPT_STATE_JS, input_id)
        if chips is None:
            return False
        if chips:
            return len(chips) == 1 and _option_match(chips, value, key=key) is not None
        box = page.locator(f"[id='{input_id}']").first
        box.fill(value, timeout=3000)
        box.press("Enter")
        options = page.locator(_OPEN_PROMPT_OPTIONS)
        for _ in range(16):
            page.wait_for_timeout(250)
            texts = [str(text).strip() for text in options.all_inner_texts()]
            # One leaf can sit under two categories ("LinkedIn" under Job Board and under
            # Social Media); identical labels are the same answer, not an ambiguity.
            unique = list(dict.fromkeys(texts))
            chosen = _option_match(unique, value, key=key) if unique else None
            if chosen:
                options.nth(texts.index(chosen)).click(timeout=3000)
                break
        else:
            box.press("Escape")
            return False
        for _ in range(8):
            page.wait_for_timeout(250)
            chips = page.evaluate(_PROMPT_STATE_JS, input_id) or []
            if len(chips) == 1:
                return _option_match(chips, value, key=key) is not None
        return False
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
    .filter(p => p.input_id && !/^(workExperience|education)-/.test(p.input_id));
}"""


def fill_prompts(
    page: Any,
    fields: dict[str, str],
    *,
    synonyms: list[tuple[str, str]],
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
        key = key_for_label(str(item.get("label") or ""), synonyms)
        value = fields.get(key or "", "")
        if not key or not value:
            continue
        if choose(page, item["input_id"], value, key=key):
            progress(f"Workday: selected {item['label']} = {value}")
            committed.append({
                "key": key, "label": item["label"], "value": value,
                "selector": f"[id='{item['input_id']}']",
            })
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
    page.locator(_OPEN_PROMPT_OPTIONS).nth(texts.index(option)).click(timeout=3000)
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
    from resume_tailor.apply.field_matcher import match_skill_option  # noqa: PLC0415

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
    try:
        state = page.evaluate(PHONE_CODE_JS)
    except Exception:  # noqa: BLE001
        return None
    if not state:
        return None
    region_aliases = {"united states": ("united states of america", "united states")}
    wanted = region_aliases.get(region.casefold(), (region.casefold(),))

    def _matches(chip: str) -> bool:
        low = chip.casefold()
        return code in chip and any(name in low for name in wanted)

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
            charm.first.click(timeout=3000)
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
                options.nth(exact[0]).click(timeout=3000)
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
