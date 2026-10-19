"""Page-level fill helpers: injected scripts, form-step signatures, submit confirmation."""

from __future__ import annotations

import contextlib
import json
import time
from importlib import resources
from pathlib import Path
from typing import Any

from resume_tailor.apply.ats import ats_hints

from . import fill_buttons

#: Where a page script takes the shared helpers of ``dom_common.js``.
DOM_COMMON_MARKER = "/*DOM_COMMON*/"


def with_dom_common(script: str) -> str:
    """``script`` with ``dom_common.js`` put in place of its marker, inside its own
    function, so the helpers use that script's ``isVisible`` and ``labelFor``."""
    common = (
        resources.files("resume_tailor.apply.forms")
        .joinpath("dom_common.js")
        .read_text(encoding="utf-8")
    )
    return script.replace(DOM_COMMON_MARKER, common, 1)


def _load_filler_js() -> str:
    """Read the packaged filler script."""
    return with_dom_common(
        resources.files("resume_tailor.apply.forms")
        .joinpath("filler.js")
        .read_text(encoding="utf-8")
    )

def _load_readiness_js() -> str:
    """Read the packaged required-empty checker, if present."""
    path = resources.files("resume_tailor.apply.forms").joinpath("filler_readiness.js")
    try:
        return with_dom_common(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError):
        return "( ) => ({ required_empty: [] })"

def _scanned_nothing(merged: dict[str, Any], filled_start: int) -> bool:
    """True when this step's passes neither filled nor even saw a single control."""
    return len(merged.get("filled") or []) == filled_start and not any(
        merged.get(key) for key in ("leftovers", "long_text", "file_inputs", "required_empty")
    )

def _form_questions(merged: dict[str, Any]) -> list[dict[str, Any]]:
    """What the fill saw that is part of an application: a keyed or labelled control, not
    a page's unlabelled chrome (a footer language picker) it only observed."""
    return [
        item
        for key in ("filled", "leftovers", "long_text")
        for item in merged.get(key) or []
        if isinstance(item, dict)
        and (item.get("label") or item.get("key") not in {None, "", "existing"})
    ]

def _only_unrecognized(merged: dict[str, Any]) -> bool:
    """Nothing filled or written and every control seen unrecognised: a careers page's own
    "Search by Keyword" box or "Save job" button (Capgemini, Qualtrics 2026-10), not a form."""
    if merged.get("filled") or merged.get("long_text"):
        return False
    left = [item for item in merged.get("leftovers") or [] if isinstance(item, dict)]
    return bool(left) and all(item.get("reason") == "Unrecognized field" for item in left)

def _synonym_payload() -> list[list[str]]:
    """Serialise ``SYNONYMS`` for the page evaluate argument."""
    return [[pat, key] for pat, key in ats_hints.SYNONYMS]

def _hint_selector(hints: dict[str, str], special: str) -> str | None:
    """Return the CSS selector mapped to a reserved hint value like ``submit``."""
    if special in hints and special not in ats_hints.CANONICAL_FIELD_KEYS:
        return special
    for selector, value in hints.items():
        if value == special:
            return selector
    return None

def _form_step_signature(page: Any) -> tuple[str, tuple[str, ...]] | None:
    """Identify visible controls so a disabled or ineffective Next cannot loop forever."""
    try:
        controls = page.locator("input:visible, select:visible, textarea:visible").evaluate_all(
            "els => els.map(el => [el.tagName, el.id, el.name, el.getAttribute('aria-label')].join(':'))"
        )
        if isinstance(controls, list) and all(isinstance(item, str) for item in controls):
            return (str(page.url), tuple(controls))
    except Exception:  # noqa: BLE001
        pass
    return None

_REFUSAL_SHOWN_JS = """() => Array.from(document.querySelectorAll(
  '[aria-invalid="true"], [role="alert"], [data-automation-id="errorMessage"]'))
  .some(el => el.getClientRects().length > 0)"""


def wait_for_new_step(page: Any, before: Any, *, timeout_ms: float) -> bool:
    """After an advance click: until the visible controls differ from ``before`` and hold
    still across two reads (the next step has painted), or the unchanged step shows a
    validation refusal, at most ``timeout_ms``. True when the step changed."""
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000
    started, last = time.monotonic(), None
    while True:
        now = _form_step_signature(page)
        if now is None and before is None:  # unreadable controls: the old fixed settle
            page.wait_for_timeout(min(1000, max(timeout_ms, 0)))
            return False
        if now is not None and now != before and now == last and now[1]:
            return True
        if now == before and time.monotonic() - started >= 0.5:
            with contextlib.suppress(Exception):
                if page.evaluate(_REFUSAL_SHOWN_JS) is True:
                    return False
        if time.monotonic() >= deadline:
            return now is not None and now != before
        last = now
        page.wait_for_timeout(250)


_ENTRY_READY_JS = """() => Array.from(document.querySelectorAll(
  'input:not([type="hidden"]), select, textarea, button, a[href], [role="button"]'))
  .some(el => el.getClientRects().length > 0 && (el.matches('input, select, textarea')
    || /apply|interested/i.test(el.innerText || el.getAttribute('aria-label') || '')))"""


def wait_for_entry(page: Any, *, timeout_ms: float) -> None:
    """After the posting loads: until it shows a form control or an Apply control, then
    a short network settle (at most 2 s, for script-built pages), all within
    ``timeout_ms`` (the fixed 10 s network wait this replaces)."""
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000
    while time.monotonic() < deadline:
        ready = None
        with contextlib.suppress(Exception):
            ready = page.evaluate(_ENTRY_READY_JS)
        if ready is True:
            break
        if not isinstance(ready, bool):  # unreadable page: the old network wait alone
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=max(timeout_ms, 1))
            return
        page.wait_for_timeout(250)
    left_ms = (deadline - time.monotonic()) * 1000
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=max(min(2000, left_ms), 1))


#: What each ATS shows after a successful submit: page selectors, and phrases that
#: must be new on the page (absent before the click). Any one signal confirms. Generic
#: markers apply to every ATS; the packet's ``confirmation_text`` hint is added too.
_CONFIRMATION_MARKERS: dict[str, dict[str, tuple[str, ...]]] = {
    "": {
        "selectors": (
            "[data-automation-id='applicationSubmitted']",
            "[data-testid='application-submitted']",
            ".application-confirmation",
        ),
        "texts": (),
        "urls": (),
    },
    "greenhouse": {
        "selectors": ("#application_confirmation",),
        "texts": ("thank you for applying", "application has been submitted"),
        "urls": ("/confirmation",),
    },
    "lever": {
        "selectors": (".application-confirmation", ".thanks"),
        "texts": ("application submitted", "thanks for applying"),
        "urls": ("/thanks",),
    },
    "ashby": {
        "selectors": (),
        "texts": ("thanks for applying", "application was successfully submitted"),
        "urls": (),
    },
    "icims": {
        "selectors": (),
        "texts": ("thank you for applying", "thank you for your interest"),
        "urls": ("/confirmation",),
    },
    "smartrecruiters": {
        "selectors": (),
        "texts": ("thank you for applying", "application has been sent"),
        "urls": ("/confirmation",),
    },
    "taleo": {
        "selectors": (),
        "texts": ("thank you for submitting", "application has been submitted"),
        "urls": (),
    },
}

def confirmation_markers(ats: str) -> dict[str, tuple[str, ...]]:
    """The generic markers plus ``ats``'s own."""
    generic = _CONFIRMATION_MARKERS[""]
    own = _CONFIRMATION_MARKERS.get((ats or "").lower(), {})
    return {
        name: generic[name] + tuple(own.get(name, ()))
        for name in ("selectors", "texts", "urls")
    }

def _submission_confirmed(
    page: Any,
    *,
    before_url: str,
    before_body: str,
    confirmation_text: str,
    ats: str = "",
) -> bool:
    """Require a post-click confirmation signal that was absent before submission."""
    markers = confirmation_markers(ats)
    try:
        submitted_marker = page.locator(", ".join(markers["selectors"])).first
        if fill_buttons._is_locator_present_and_visible(submitted_marker):
            return True
    except Exception:  # noqa: BLE001
        pass
    after_url = _page_url(page).casefold()
    if any(
        fragment in after_url and fragment not in (before_url or "").casefold()
        for fragment in markers["urls"]
    ):
        return True
    after_body = page.inner_text("body").casefold()
    before = (before_body or "").casefold()
    phrases = [confirmation_text.casefold().strip(), *markers["texts"]]
    return any(
        phrase and phrase in after_body and phrase not in before for phrase in phrases
    )

def _page_url(page: Any) -> str:
    try:
        return str(page.url)
    except Exception:  # noqa: BLE001
        return ""

def _record_submit_evidence(
    page: Any, folder: Path, phase: str, payload: dict[str, Any], *, required: bool = False,
) -> None:
    """Write ``<phase>.json`` and a full-page ``<phase>.png`` to a submit's audit folder.

    The JSON before a submit is ``required``: if it cannot be written, the submit does
    not happen. The screenshot is always best-effort.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{phase}.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
    except OSError as exc:
        if required:
            raise RuntimeError(f"Could not record submit evidence: {exc}") from exc
    with contextlib.suppress(Exception):
        page.screenshot(path=str(folder / f"{phase}.png"), full_page=True)


def _page_title(page: Any) -> str:
    try:
        value = page.title()
    except Exception:  # noqa: BLE001
        return ""
    return value if isinstance(value, str) else ""


def _page_lang(page: Any) -> str:
    """The form's ``<html lang>``; "" when unset or unreadable."""
    try:
        value = page.locator("html").first.get_attribute("lang", timeout=2_000)
    except Exception:  # noqa: BLE001
        return ""
    return value if isinstance(value, str) else ""
