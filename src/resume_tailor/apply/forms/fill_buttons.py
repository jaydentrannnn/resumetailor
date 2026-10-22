"""Locating and clicking the Apply, advance and submit controls, plus the submit decision."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

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

def find_and_click_apply(
    page: Any, ats: str, context: Any = None, outcome: dict[str, bool] | None = None,
) -> Any:
    """Find and click the Apply button/link, returning the resulting active page.
    ``outcome["entered"]`` says whether an entry control was clicked."""
    current_page = page
    entered = False

    # 1. ATS-specific hints
    for click_sel in ats_hints.ATS_PRE_FILL_CLICKS.get(ats.lower(), []):
        try:
            loc = _entry_control(current_page.locator(click_sel))
            if loc is not None:
                before = _entry_state(current_page)
                current_page = _click_and_track_popup(
                    current_page, context, lambda loc=loc: clicks.safe_click(loc, purpose="enter", timeout=4000)
                )
                _settle_after_entry(current_page, before, 1000)
                entered = True
                break
        except Exception:  # noqa: BLE001
            pass

    # 2. Semantic role-based button/link discovery ("Apply", SmartRecruiters' "I'm
    # interested", ...). SmartRecruiters' entry hint lands on the form itself, where a
    # second "apply" search could only find the form's own final button.
    # Meta (2026-10) marks its own posting aria-hidden, which hides its visible "Apply
    # now" from role queries; those are looked for once nothing else matched.
    role_entered = False
    passes = ((False, "button"), (False, "link"), (True, "button"), (True, "link"))
    for include_hidden, role in passes:
        if role_entered or (entered and ats.lower() in _HINT_ENTERS_FORM):
            break
        try:
            loc = _entry_control(current_page.get_by_role(
                role, name=ats_hints.APPLY_ENTRY_PATTERN, include_hidden=include_hidden,
            ))
            if loc is not None:
                before = _entry_state(current_page)
                current_page = _enter(current_page, context, loc)
                _settle_after_entry(current_page, before, 1000)
                entered = role_entered = True
        except Exception:  # noqa: BLE001
            pass
    if entered:
        current_page = _guest_route(current_page, context)

    # 3. Workday "Apply Manually" modal handling
    try:
        manual_btn = current_page.get_by_role(
            "button", name=re.compile(r"apply\s+manually", re.IGNORECASE)
        ).first
        if _is_locator_present_and_visible(manual_btn):
            before = _entry_state(current_page)
            current_page = _click_and_track_popup(
                current_page, context, lambda: clicks.safe_click(manual_btn, purpose="enter", timeout=4000)
            )
            _settle_after_entry(current_page, before, 1000)
            entered = True
    except Exception:  # noqa: BLE001
        pass

    if outcome is not None:
        outcome["entered"] = entered
    return current_page

_CONTROL_COUNT_JS = (
    "() => document.querySelectorAll('input:not([type=\"hidden\"]), select, textarea').length"
)


def _entry_state(page: Any) -> tuple[str, int | None]:
    """The page's URL and form-control count before an entry click."""
    count = None
    with contextlib.suppress(Exception):
        found = page.evaluate(_CONTROL_COUNT_JS)
        count = found if isinstance(found, int) else None
    return str(getattr(page, "url", "")), count


def _settle_after_entry(page: Any, before: tuple[str, int | None], cap_ms: int) -> None:
    """After an entry click: until it shows its effect on ``page`` (another tab or URL,
    or more form controls than before), at most ``cap_ms``, the fixed wait this replaces.
    A page whose controls cannot be counted gets the fixed wait."""
    url, count = before
    if count is None:
        page.wait_for_timeout(cap_ms)
        return
    for _ in range(max(cap_ms // 250, 1)):
        now_url, now_count = _entry_state(page)
        if now_url != url:
            with contextlib.suppress(Exception):
                page.wait_for_load_state("domcontentloaded", timeout=cap_ms)
            return
        if now_count is not None and now_count > count:
            return
        page.wait_for_timeout(250)


def _enter(page: Any, context: Any, loc: Any) -> Any:
    """Click an entry control; when that leaves the page where it was, take the apply item
    of the menu it opened, else follow the control's own link.

    2026-10: SuccessFactors sites (Capgemini, Royal Caribbean) show "Apply now" as a menu
    toggle whose "Apply Now" item leads to the sign-in; its ``href`` alone redirects home.
    Qualtrics' link sits under a chat widget that intercepts the click."""
    before = str(page.url)
    state = _entry_state(page)
    href = _entry_href(page, loc)
    try:
        landed = _click_and_track_popup(
            page, context, lambda: clicks.safe_click(loc, purpose="enter", timeout=4000)
        )
    except clicks.SubmitRefused:
        raise
    except Exception:  # noqa: BLE001 - intercepted or detached: the link may still work
        landed = page
    if landed is not page:
        return landed
    with contextlib.suppress(Exception):
        _settle_after_entry(page, state, 1500)
    if not _same_page(str(page.url), before):
        return page
    item = _apply_menu_item(page)
    if item is not None:
        try:
            return _click_and_track_popup(
                page, context, lambda: clicks.safe_click(item, purpose="enter", timeout=4000)
            )
        except clicks.SubmitRefused:
            raise
        except Exception:  # noqa: BLE001 - the item vanished: the link may still work
            pass
    if href:
        page.goto(href, wait_until="domcontentloaded", timeout=30_000)
        if _is_site_home(str(page.url)) and not _is_site_home(href):
            # The link needs the page's own script (a session) and bounced to the home
            # page: hand over the posting, not the home page.
            page.goto(before, wait_until="domcontentloaded", timeout=30_000)
    return page


def _guest_route(page: Any, context: Any) -> Any:
    """After an entry click that landed on a chooser with no form controls, its route
    without an account (Dayforce's "Apply without an Account", 2026-10). Sign-in and
    account routes stay with `form_routes`."""
    _url, count = _entry_state(page)
    if count != 0:
        return page
    with contextlib.suppress(Exception):
        for role in ("button", "link"):
            loc = _entry_control(page.get_by_role(role, name=ats_hints.GUEST_ENTRY_PATTERN))
            if loc is not None:
                before = _entry_state(page)
                landed = _enter(page, context, loc)
                _settle_after_entry(landed, before, 1000)
                return landed
    return page


def _apply_menu_item(page: Any) -> Any | None:
    """The visible "Apply" item of a menu the entry click just opened, else None."""
    with contextlib.suppress(Exception):
        return _entry_control(page.get_by_role("menuitem", name=ats_hints.APPLY_ENTRY_PATTERN))
    return None


#: Entry candidates looked at per selector: the first few visible matches.
_ENTRY_CANDIDATES = 8


def _entry_control(matches: Any) -> Any | None:
    """The first visible match that is not a social-account route ("Apply with LinkedIn"
    sits before plain "Apply" on Breezy, and ``text=Apply`` matches both)."""
    try:
        candidates = [matches.nth(index) for index in range(min(matches.count(), _ENTRY_CANDIDATES))]
    except Exception:  # noqa: BLE001 - a locator stand-in with only ``first``
        candidates = [matches.first]
    for loc in candidates:
        if _is_locator_present_and_visible(loc) and not clicks.is_social_control(loc):
            return loc
    return None


def _is_site_home(url: str) -> bool:
    return urlsplit(url).path in {"", "/"}


def _entry_href(page: Any, loc: Any) -> str:
    """The entry control's own link on the posting's site, else ""."""
    href = ""
    with contextlib.suppress(Exception):
        href = loc.get_attribute("href", timeout=2000)
    if not isinstance(href, str):
        return ""
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return ""
    target = urljoin(str(page.url), href)
    if urlsplit(target).scheme not in {"http", "https"} or _site(target) != _site(str(page.url)):
        return ""
    return "" if _same_page(target, str(page.url)) else target


def _site(url: str) -> str:
    return ".".join((urlsplit(url).hostname or "").split(".")[-2:])


def _same_page(a: str, b: str) -> bool:
    return a.split("#", 1)[0].rstrip("/") == b.split("#", 1)[0].rstrip("/")


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
        btn = page.get_by_role("button", name=clicks.FINAL_SUBMIT_NAME).first
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


#: A consent button that refuses optional cookies. "Accept" is never pressed for the
#: applicant, so a banner offering only that is left where it is.
_COOKIE_DECLINE = re.compile(
    r"^\s*(?:decline|reject|refuse|deny)(?:\s+all)?(?:\s+(?:optional\s+|non-essential\s+)?cookies)?\s*$"
    r"|^\s*(?:use\s+)?(?:only\s+)?(?:strictly\s+)?(?:necessary|essential)(?:\s+cookies)?(?:\s+only)?\s*$",
    re.I,
)
#: True when the button sits in a cookie banner: a close ancestor named for cookies or
#: consent, or a short one whose text mentions cookies (never a whole form).
_COOKIE_BANNER_JS = r"""(el) => {
  for (let box = el, depth = 0; box && depth < 8; box = box.parentElement, depth++) {
    const clues = [box.id, String(box.className?.baseVal ?? box.className ?? ''),
      box.getAttribute('data-ui'), box.getAttribute('data-testid'), box.getAttribute('aria-label')];
    if (/cookie|consent|gdpr|onetrust|cookiebot/i.test(clues.join(' '))) return true;
    const text = box.innerText || '';
    if (/\bcookies?\b/i.test(text) && text.length < 1500) return true;
  }
  return false;
}"""


def decline_cookie_banner(page: Any) -> bool:
    """Press a cookie banner's "Decline all" / "Reject all". The banner lies over the form
    and swallows the clicks meant for the controls under it (every Workable dropdown click
    timed out, 2026-10). True when one was pressed."""
    try:
        buttons = page.get_by_role("button", name=_COOKIE_DECLINE).filter(visible=True)
        for index in range(min(buttons.count(), 4)):
            button = buttons.nth(index)
            if button.evaluate(_COOKIE_BANNER_JS, timeout=1000) is True:
                clicks.safe_click(button, purpose="dismiss", timeout=2000)
                page.wait_for_timeout(300)
                return True
    except Exception:  # noqa: BLE001 - unreadable or refused: the banner stays
        pass
    return False
