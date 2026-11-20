"""The Oracle Candidate Experience email form that precedes the application."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from resume_tailor.apply.answers import form_facts
from resume_tailor.apply.driver import clicks

_EMAIL = 'input[type="email"][name="primary-email"][id^="primary-email-"]'
_NEXT = 'button.apply-flow-pagination__button[type="submit"][data-bind*="isNextButtonEnabled"]'
_PRIVACY_BOX = "#legal-disclaimer-checkbox"
_PRIVACY_LABEL = 'label[for="legal-disclaimer-checkbox"]'

EMAIL_REVIEW = (
    "Complete Oracle's email step in the opened tab, then choose Continue fill"
)
PRIVACY_REVIEW = (
    "Review and accept Oracle's privacy statement in the opened tab, then choose Continue fill"
)


def is_step(url: str) -> bool:
    path = urlsplit(url).path.rstrip("/").casefold()
    return path.startswith("/hcmui/candidateexperience/") and path.endswith("/apply/email")


def _accept_privacy(form: Any, fields: dict[str, str]) -> bool:
    box = form.locator(_PRIVACY_BOX)
    if not box.count() or box.is_checked(timeout=1500):
        return True
    label = form.locator(_PRIVACY_LABEL)
    text = label.inner_text(timeout=1500)
    if (
        form_facts.acknowledgement(text) != "routine"
        or not form_facts.Consent.from_fields(fields).accepts(text)
    ):
        return False
    clicks.safe_click(label, purpose="select", timeout=2500, position={"x": 4, "y": 4})
    return box.is_checked(timeout=1500)


def advance(page: Any, fields: dict[str, str], *, timeout_ms: int) -> str | None:
    """Click the email form's own Next once. Return a handoff when it cannot be done."""
    email = page.locator(_EMAIL)
    try:
        email.wait_for(state="visible", timeout=timeout_ms)
        if not email.input_value(timeout=timeout_ms).strip():
            if not fields.get("email"):
                return EMAIL_REVIEW
            email.fill(fields["email"], timeout=timeout_ms)
            # Oracle binds this input on blur. Enter is suppressed on the email control.
            email.press("Tab", timeout=timeout_ms)
        form = email.locator("xpath=ancestor::form[1]")
        if not _accept_privacy(form, fields):
            return PRIVACY_REVIEW
        next_button = form.locator(_NEXT)
        clicks.safe_click(next_button, purpose="advance", timeout=timeout_ms)
    except Exception:  # noqa: BLE001 - keep the email step available for manual completion
        return EMAIL_REVIEW
    return None
