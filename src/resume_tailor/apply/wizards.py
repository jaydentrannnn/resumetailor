"""Name the screen of a multi-step ATS application (plan P4-A: AD1, AD3-AD5).

A wizard platform (Workday, iCIMS, Taleo, SuccessFactors, Oracle Cloud) puts a sign-in,
an emailed code, several form steps and a review page between the posting and the
submit. The fill loop fills form steps; every other screen is the applicant's. So each
adapter answers one question from one page snapshot: which screen is this?

``classify`` is pure, so the rules are unit-tested on snapshot dicts without a browser.
Workday keeps its own observed state machine (`workday_flow`, captured from live
tenants); `WorkdayWizard` only maps its states onto the shared names. The other
platforms share one text-and-structure classifier with a few words of their own. Their
rules come from each platform's public wording, not captured tenants, so they are
conservative: when unsure, the fill loop keeps filling and never submits.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from typing import Any, Literal

from resume_tailor.apply import form_guards, workday_flow

WizardState = Literal[
    "posting",
    "sign_in",
    "create_account",
    "otp",
    "verify_email",
    "apply_form",
    "review",
    "confirmation",
    "already_applied",
    "unavailable",
    "unknown",
]

#: One evaluate call returns everything the shared ``classify`` reads.
SNAPSHOT_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const texts = sel => [...document.querySelectorAll(sel)].filter(vis)
    .map(e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim())
    .filter(Boolean);
  const inputs = [...document.querySelectorAll('input, select, textarea')].filter(vis);
  const kind = e => (e.getAttribute('type') || e.tagName).toLowerCase();
  const current = document.querySelector(
    "[aria-current='step'], .progress-bar .active, .wizard-steps .active, "
    + "[class*='step' i][class*='active' i], [class*='step' i][class*='current' i]");
  return {
    url: location.href,
    title: document.title || '',
    headings: texts('h1, h2, h3, legend').slice(0, 12),
    buttons: texts("button, input[type='submit'], input[type='button'], a[role='button'], "
      + "a[class*='button' i], a[class*='apply' i]").slice(0, 40),
    password_inputs: inputs.filter(e => kind(e) === 'password').length,
    fields: inputs.filter(e => !['hidden', 'submit', 'button', 'image', 'reset']
      .includes(kind(e))).length,
    otp_input: inputs.some(e => e.getAttribute('autocomplete') === 'one-time-code'
      || /verification.?code|one.?time|passcode|\botp\b/i.test(`${e.name || ''} ${e.id || ''}`)),
    active_step: current ? (current.innerText || '').trim().slice(0, 80) : '',
    text: (document.body ? document.body.innerText : '').slice(0, 20000),
  };
}"""

_CODE_SENT = re.compile(
    r"enter (?:the|your) (?:\d-digit )?(?:verification|security|one-time|access) (?:code|pin)"
    r"|we(?:'ve| have)? (?:sent|emailed) (?:you )?(?:a|an|the) (?:\d-digit )?(?:code|pin|one-time)",
    re.I,
)
_CONFIRMED = re.compile(
    r"thank you for (?:applying|your application|submitting)|thanks for applying"
    r"|(?:your )?application (?:has been|was) (?:successfully )?(?:submitted|received)",
    re.I,
)
_ALREADY_APPLIED = re.compile(
    r"you(?:'ve| have) already (?:applied|submitted an application)", re.I
)
_CREATE_ACCOUNT = re.compile(
    r"create (?:an |your )?account|new (?:user|candidate)|register|sign up|confirm password", re.I
)
#: A whole step name or heading that means the final review page.
_REVIEW = re.compile(
    r"^(?:review(?:\s+(?:and|&)\s+(?:submit|apply))?|review\s+(?:your\s+)?application"
    r"|application\s+summary|summary)$",
    re.I,
)
#: "Step 5 of 6", "current step 5 of 6", "5 -" before a step's name.
_STEP_NUMBER = re.compile(r"^(?:(?:current\s+)?step\s+)?\d+(?:\s+of\s+\d+)?\s*[-:.)]?\s*", re.I)
_APPLY_BUTTON = re.compile(
    r"^\s*apply(?:\s+now|\s+online|\s+for\s+this\s+(?:job|position)(?:\s+online)?)?\s*$", re.I
)
_SUBMIT_BUTTON = re.compile(r"^\s*submit(?:\s+(?:my\s+)?application)?\s*$", re.I)
#: At most this many inputs beside an Apply control is still the posting page.
_POSTING_CHROME_FIELDS = 2
#: Click the first visible control whose text or title is an Apply button's.
_ENTER_JS = r"""(pattern) => {
  const rule = new RegExp(pattern, 'i');
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const control = [...document.querySelectorAll("a, button, input[type='submit'], [role='button']")]
    .filter(vis)
    .find(e => [e.innerText, e.value, e.getAttribute('title')].some(t => t && rule.test(t.trim())));
  if (!control) return false;
  control.click();
  return true;
}"""


@dataclass(frozen=True)
class Stop:
    """A screen the fill loop hands over instead of filling."""

    status: Literal["awaiting_review", "awaiting_otp", "fill_failed"]
    message: str


class WizardAdapter:
    """The shared screen classifier; subclasses add a platform's own wording."""

    platform = "generic"
    label = "the site"
    snapshot_js = SNAPSHOT_JS
    #: Extra headings / step names that mean the final review page.
    review_words: tuple[str, ...] = ()
    #: Extra page text that means a sign-in page (with a password box).
    sign_in_words: tuple[str, ...] = ()

    def snapshot(self, page: Any) -> dict[str, Any]:
        try:
            snap = page.evaluate(self.snapshot_js)
        except Exception:  # noqa: BLE001 - a navigating page has no snapshot yet
            return {"text": "", "url": str(getattr(page, "url", ""))}
        return snap if isinstance(snap, dict) else {"text": ""}

    def detect_state(self, page: Any) -> WizardState:
        return self.classify(self.snapshot(page))

    def is_final_step(self, snap: dict[str, Any]) -> bool:
        return self.classify(snap) == "review"

    def classify(self, snap: dict[str, Any]) -> WizardState:
        text = str(snap.get("text") or "")
        head = text[:3000]
        headings = [str(h) for h in snap.get("headings") or []]
        buttons = [str(b) for b in snap.get("buttons") or []]
        fields = int(snap.get("fields") or 0)
        passwords = int(snap.get("password_inputs") or 0)
        step = str(snap.get("active_step") or "")

        if snap.get("otp_input") or (_CODE_SENT.search(head) and passwords == 0):
            return "otp"
        if workday_flow.VERIFY_EMAIL.search(head) and fields <= 1:
            return "verify_email"
        if _CONFIRMED.search(head) and fields == 0:
            return "confirmation"
        if _ALREADY_APPLIED.search(head):
            return "already_applied"
        account_words = " ".join([*headings, *buttons])
        if passwords >= 2 or (passwords and _CREATE_ACCOUNT.search(account_words)):
            return "create_account"
        if passwords:
            return "sign_in"
        if self._is_review(step, headings, buttons, fields):
            return "review"
        if fields == 0 and form_guards.closed_posting(text):
            return "unavailable"
        # A posting page's own chrome (a language picker, a job search box) is not a form.
        if fields <= _POSTING_CHROME_FIELDS and any(_APPLY_BUTTON.match(b) for b in buttons):
            return "posting"
        if fields:
            return "apply_form"
        return "unknown"

    def enter(self, page: Any) -> bool:
        """Click the posting's own apply control (iCIMS "Apply for this job online");
        False when it has none."""
        try:
            return bool(self._target(page).evaluate(_ENTER_JS, _APPLY_BUTTON.pattern))
        except Exception:  # noqa: BLE001 - a navigating page cannot be clicked yet
            return False

    def _target(self, page: Any) -> Any:
        """The page or frame holding the application."""
        return page

    def _is_review(self, step: str, headings: list[str], buttons: list[str], fields: int) -> bool:
        extra = {w.casefold() for w in self.review_words}
        for raw in (step, *headings):
            name = _STEP_NUMBER.sub("", raw.strip()).strip()
            if name and (_REVIEW.match(name) or name.casefold() in extra):
                return True
        # A page of read-only answers with only a submit control is the review page.
        return fields == 0 and any(_SUBMIT_BUTTON.match(b) for b in buttons)

    def stop_for(self, state: WizardState) -> Stop | None:
        """The handoff for a screen the applicant must handle, else None."""
        site = self.label
        if state == "sign_in":
            return Stop(
                "awaiting_review",
                f"Sign in to {site} in the opened tab (or create the account), then choose "
                "Continue fill",
            )
        if state == "create_account":
            return Stop(
                "awaiting_review",
                f"Create your {site} account in the opened tab, then choose Continue fill",
            )
        if state in {"otp", "verify_email"}:
            return Stop(
                "awaiting_otp",
                f"Enter the code {site} emailed you in the opened tab, then choose Continue fill",
            )
        if state == "already_applied":
            return Stop("awaiting_review", f"{site} says you have already applied to this job")
        if state == "unavailable":
            return Stop("fill_failed", "The posting is closed or no longer available")
        return None


class WorkdayWizard(WizardAdapter):
    """Workday's observed state machine (`workday_flow.classify`), under the shared names."""

    platform = "workday"
    label = "Workday"
    snapshot_js = workday_flow.SNAPSHOT_JS

    _STATES: dict[str, WizardState] = {
        "posting": "posting",
        "start_dialog": "posting",
        "auth_chooser": "sign_in",
        "sign_in": "sign_in",
        "create_account": "create_account",
        "otp": "otp",
        "verify_email": "verify_email",
        "apply_form": "apply_form",
        "already_applied": "already_applied",
        "unavailable": "unavailable",
        "unknown": "unknown",
    }

    def classify(self, snap: dict[str, Any]) -> WizardState:
        state = self._STATES[workday_flow.classify(snap)]
        if state == "apply_form" and workday_flow.is_review_step(snap):
            return "review"
        return state


class IcimsWizard(WizardAdapter):
    """iCIMS: email-first login, then Candidate Profile, questions, EEO and a review page.

    The form often sits in the ``icims_content_iframe`` frame; the fill loop already walks
    every frame, and the snapshot is taken of the frame holding the form.
    """

    platform = "icims"
    label = "iCIMS"
    review_words = ("Review and Submit", "Submit Application", "Review Your Application")

    def snapshot(self, page: Any) -> dict[str, Any]:
        return super().snapshot(self._target(page))

    def _target(self, page: Any) -> Any:
        frame = None
        with contextlib.suppress(Exception):
            frame = page.frame(name="icims_content_iframe")
        return frame if frame is not None else page


class TaleoWizard(WizardAdapter):
    """Oracle Taleo: Returning/New User login, numbered steps ending in Review and Submit."""

    platform = "taleo"
    label = "Taleo"
    review_words = ("Review and Submit", "Review & Submit")


class SuccessFactorsWizard(WizardAdapter):
    """SAP SuccessFactors: sign in or create an account, then one long application page."""

    platform = "successfactors"
    label = "SuccessFactors"
    review_words = ("Review and Apply", "Review Application")


class OracleWizard(WizardAdapter):
    """Oracle Cloud HCM: email, then an emailed code, then the application sections."""

    platform = "oracle"
    label = "Oracle"
    review_words = ("Review and Submit", "Review Your Application")


_BY_ATS: dict[str, type[WizardAdapter]] = {
    "workday": WorkdayWizard,
    "icims": IcimsWizard,
    "taleo": TaleoWizard,
    "successfactors": SuccessFactorsWizard,
    "oracle": OracleWizard,
}


def for_ats(ats: str) -> WizardAdapter | None:
    """The wizard adapter for ``ats``, or None for a single-page form."""
    cls = _BY_ATS.get((ats or "").lower())
    return cls() if cls else None
