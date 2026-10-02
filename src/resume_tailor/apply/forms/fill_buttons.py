"""Locating and clicking the Apply, advance and submit controls, plus the submit decision."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from typing import Any, Literal

from resume_tailor.apply.ats import ats_hints
from resume_tailor.apply.driver import clicks
from resume_tailor.web.schemas import ApplySettings

from . import fill_page


def _is_locator_present_and_visible(loc: Any) -> bool:
    """Safely check if locator exists and is visible without tripping over MagicMock in tests."""
    try:
        count = loc.count()
        if isinstance(count, int) and count > 0:
            return bool(loc.is_visible())
    except Exception:  # noqa: BLE001
        pass
    return False

def _locator_exists(loc: Any) -> bool:
    """Safely check if locator exists without tripping over MagicMock in tests."""
    try:
        count = loc.count()
        if isinstance(count, int):
            return count > 0
    except Exception:  # noqa: BLE001
        pass
    return False

def _click_and_track_popup(page: Any, context: Any, click_fn: Callable[[], None]) -> Any:
    """Execute click_fn while watching for popups.

    Returns the new active page if a popup was opened. Only a tab this page opened
    counts: parallel fills share the browser's one context, so a context-wide wait
    would adopt another fill's freshly opened tab.
    """
    if not context or not hasattr(page, "expect_popup"):
        click_fn()
        return page
    try:
        with page.expect_popup(timeout=5000) as page_info:
            click_fn()
        new_page = page_info.value
        with contextlib.suppress(Exception):
            new_page.wait_for_load_state("domcontentloaded", timeout=45_000)
        return new_page
    except Exception:  # noqa: BLE001
        return page

#: ATSs whose pre-fill hint opens the application form itself (no second entry click).
_HINT_ENTERS_FORM = frozenset({"smartrecruiters"})

def find_and_click_apply(page: Any, ats: str, context: Any = None) -> Any:
    """Find and click the Apply button/link, returning the resulting active page."""
    current_page = page
    entered = False

    # 1. ATS-specific hints
    for click_sel in ats_hints.ATS_PRE_FILL_CLICKS.get(ats.lower(), []):
        try:
            loc = current_page.locator(click_sel).first
            if _is_locator_present_and_visible(loc):
                current_page = _click_and_track_popup(
                    current_page, context, lambda loc=loc: clicks.safe_click(loc, purpose="enter", timeout=4000)
                )
                current_page.wait_for_timeout(1000)
                entered = True
                break
        except Exception:  # noqa: BLE001
            pass

    # 2. Semantic role-based button/link discovery ("Apply", SmartRecruiters' "I'm
    # interested", ...). SmartRecruiters' entry hint lands on the form itself, where a
    # second "apply" search could only find the form's own final button.
    for role in ("button", "link"):
        if entered and ats.lower() in _HINT_ENTERS_FORM:
            break
        try:
            loc = current_page.get_by_role(role, name=ats_hints.APPLY_ENTRY_PATTERN).first
            if _is_locator_present_and_visible(loc):
                current_page = _click_and_track_popup(
                    current_page, context, lambda loc=loc: clicks.safe_click(loc, purpose="enter", timeout=4000)
                )
                current_page.wait_for_timeout(1000)
                break
        except Exception:  # noqa: BLE001
            pass

    # 3. Workday "Apply Manually" modal handling
    try:
        manual_btn = current_page.get_by_role(
            "button", name=re.compile(r"apply\s+manually", re.IGNORECASE)
        ).first
        if _is_locator_present_and_visible(manual_btn):
            current_page = _click_and_track_popup(
                current_page, context, lambda: clicks.safe_click(manual_btn, purpose="enter", timeout=4000)
            )
            current_page.wait_for_timeout(1000)
    except Exception:  # noqa: BLE001
        pass

    return current_page

def _detect_barriers(page: Any) -> str | None:
    """Detect blocking barriers like Cloudflare walls or interactive CAPTCHAs.

    Invisible reCAPTCHA background badges ('size=invisible') are explicitly ignored
    since they do not block form filling or require user interaction.
    """
    # 1. Cloudflare challenge wall
    for cf_sel in ("#cf-challenge", "div#challenge-running", "div#challenge-stage"):
        try:
            loc = page.locator(cf_sel).first
            if _is_locator_present_and_visible(loc):
                return "Cloudflare challenge detected"
        except Exception:  # noqa: BLE001
            pass

    # 2. Interactive CAPTCHA challenge or checkbox
    try:
        recaptchas = page.locator("iframe[src*='recaptcha']").all()
        if isinstance(recaptchas, list):
            for iframe in recaptchas:
                get_attr = getattr(iframe, "get_attribute", None)
                src = str(get_attr("src") if callable(get_attr) else "")
                if "size=invisible" in src:
                    continue
                if _is_locator_present_and_visible(iframe):
                    return "CAPTCHA detected"
    except Exception:  # noqa: BLE001
        pass

    other_captcha_selectors = [
        "iframe[title*='recaptcha challenge' i]",
        "iframe[src*='hcaptcha'][src*='checkbox']",
        "iframe[src*='hcaptcha'][src*='challenge']",
        "iframe[src*='turnstile']",
        ".g-recaptcha:not([data-size='invisible'])",
        # DataDome's wall (SmartRecruiters' application form, 2026-09): its "Verification
        # Required" slider is the applicant's to pass, never automated.
        "iframe[src*='captcha-delivery.com']",
    ]
    for sel in other_captcha_selectors:
        try:
            loc = page.locator(sel).first
            if _is_locator_present_and_visible(loc):
                return "CAPTCHA detected"
        except Exception:  # noqa: BLE001
            pass

    return None

#: A button that finishes the application is never a wizard "advance". Workday's Review
#: step labels its Submit button with the same `pageFooterNextButton` automation id as
#: Next, and clicking it submitted a Philips application (2026-09-24).
_SUBMIT_TEXT = clicks.SUBMIT_TEXT

_is_submit_like = clicks.is_submit_like

def _find_advance_button(page: Any) -> Any | None:
    """Find wizard 'Next' / 'Continue' / 'Save & Continue' button if present.

    Never returns a button whose text reads as submitting the application.
    """
    patterns = [
        re.compile(r"^\s*(next|continue|save\s*(?:&|and)\s*continue|proceed)\s*$", re.IGNORECASE),
    ]
    for pat in patterns:
        try:
            btn = page.get_by_role("button", name=pat).first
            if _is_locator_present_and_visible(btn) and not _is_submit_like(btn):
                return btn
        except Exception:  # noqa: BLE001
            pass

    advance_selectors = [
        "button[data-automation-id='pageFooterNextButton']",
        "button[data-automation-id='bottom-navigation-next-button']",
        "button[data-automation-id='page-footer-next-button']",
        "button[data-test-id='next-button']",
        "button.next-button",
        "button.btn-next",
    ]
    for sel in advance_selectors:
        try:
            loc = page.locator(sel).first
            if _is_locator_present_and_visible(loc) and not _is_submit_like(loc):
                return loc
        except Exception:  # noqa: BLE001
            pass
    return None

def _find_submit_button(page: Any, hints: dict[str, str]) -> Any | None:
    """Find the final submit button."""
    submit_sel = fill_page._hint_selector(hints, "submit")
    if submit_sel:
        try:
            loc = page.locator(submit_sel).first
            if _is_locator_present_and_visible(loc):
                return loc
        except Exception:  # noqa: BLE001
            pass
    try:
        btn = page.get_by_role(
            "button",
            name=re.compile(r"^\s*(submit|submit\s+application)\s*$", re.IGNORECASE),
        ).first
        if _is_locator_present_and_visible(btn):
            return btn
    except Exception:  # noqa: BLE001
        pass
    return None

#: Platforms that are filled but never submitted automatically, whatever the settings:
#: Workday's Review page has submitted by accident before, and the job boards' own
#: apply flows (LinkedIn Easy Apply, Indeed Apply, Handshake) forbid automation.
#: SmartRecruiters' one-click form sits behind a DataDome verification wall (2026-09) and
#: has no live dry-run record yet: filled for review only.
ASSIST_ONLY_ATS = frozenset({"workday", "linkedin", "indeed", "handshake", "smartrecruiters"})

def decide_submit_action(
    *,
    ats: str,
    settings: ApplySettings,
    ready_to_submit: bool,
    submit_mode: Literal["auto_submit", "awaiting_review"] | None = None,
) -> Literal["auto_submit", "awaiting_review"]:
    """Return ``auto_submit`` when policy allows it, else ``awaiting_review``."""
    if submit_mode == "awaiting_review":
        return "awaiting_review"
    if ats.lower() in ASSIST_ONLY_ATS:
        return "awaiting_review"
    if submit_mode == "auto_submit" and not settings.auto_submit_enabled:
        return "awaiting_review"
    auto = settings.auto_submit_enabled and ats.lower() in {
        a.lower() for a in settings.auto_submit_ats
    }
    if auto and ready_to_submit:
        return "auto_submit"
    return "awaiting_review"
