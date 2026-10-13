"""Fill handoff messages and the wizard-loop sentinels shared by `_FillRun`'s step layers."""

from __future__ import annotations

import re
from typing import Any

from . import fill_buttons

#: Workday screens that mean the session ended while a form was open (plan P4-E14).
#: A timed-out session lands on any of these mid-application (Create Account included:
#: Workday shows its Create Account/Sign In step again, live 2026-10-12).
SIGNED_OUT_STATES = frozenset({"sign_in", "auth_chooser", "create_account"})

#: The fill found only the page's own chrome (a language picker), never the form.
NO_FORM_MSG = (
    "Couldn't reach the application form: open it in this tab (it may need a sign-in), "
    "then Continue fill"
)

SESSION_EXPIRED_MSG = (
    "Workday signed you out partway through (the session timed out). Sign in again in "
    "this tab, then Continue fill; the steps you already saved are kept."
)

#: A fill's time budget: four minutes to start, pushed out by `PROGRESS_GRACE_S` whenever it
#: makes forward progress (a step, a row, a skill, an upload), never past `HARD_CAP_S`.
BASE_BUDGET_S = 240
PROGRESS_GRACE_S = 75
HARD_CAP_S = 600

#: Progress lines that mean the fill moved forward (not "needs review", not scanning).
_FORWARD = re.compile(
    r"^(?:Workday: (?:filled|added skill)|scanning form step|uploading )"
    r"|language list; removed",
)


def is_forward_progress(message: str) -> bool:
    return bool(_FORWARD.search(message))


def extended_deadline(deadline: float, started: float, now: float) -> float:
    """``deadline`` pushed to at least ``now + PROGRESS_GRACE_S``, capped at the hard cap."""
    return min(started + HARD_CAP_S, max(deadline, now + PROGRESS_GRACE_S))


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
