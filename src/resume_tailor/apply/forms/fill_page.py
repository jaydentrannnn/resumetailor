"""Page-level fill helpers: injected scripts, form-step signatures, submit confirmation."""

from __future__ import annotations

import contextlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

from resume_tailor.apply.ats import ats_hints

from . import fill_buttons


def _load_filler_js() -> str:
    """Read the packaged filler script."""
    return (
        resources.files("resume_tailor.apply.forms")
        .joinpath("filler.js")
        .read_text(encoding="utf-8")
    )

def _load_readiness_js() -> str:
    """Read the packaged required-empty checker, if present."""
    path = resources.files("resume_tailor.apply.forms").joinpath("filler_readiness.js")
    try:
        return path.read_text(encoding="utf-8")
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
