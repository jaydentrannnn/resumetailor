"""Fill handoff messages and the wizard-loop sentinels shared by `_FillRun`'s step layers."""

from __future__ import annotations

from typing import Any

from . import fill_buttons

#: Workday screens that mean the session ended while a form was open (plan P4-E14).
SIGNED_OUT_STATES = frozenset({"sign_in", "auth_chooser"})

#: The fill found only the page's own chrome (a language picker), never the form.
NO_FORM_MSG = (
    "Couldn't reach the application form: open it in this tab (it may need a sign-in), "
    "then Continue fill"
)

SESSION_EXPIRED_MSG = (
    "Workday signed you out partway through (the session timed out). Sign in again in "
    "this tab, then Continue fill; the steps you already saved are kept."
)

#: One pass more than the steps a fill may advance: a blank Workday step is rescanned once.
_MAX_WIZARD_STEPS = 9

#: `_FillRun` step outcomes that steer the wizard loop.
_BREAK = "break"
_CONTINUE = "continue"


def _attached_filename(upload_target: Any, sel: str) -> Any:
    """The file a control already holds (a Continue fill's earlier upload), or ""."""
    try:
        existing_control = upload_target.locator(sel).first
        return (
            existing_control.evaluate(
                "el => el.files && el.files[0] ? el.files[0].name : ''",
                timeout=500,
            )
            if fill_buttons._locator_exists(existing_control) else ""
        )
    except Exception:  # noqa: BLE001
        return ""
