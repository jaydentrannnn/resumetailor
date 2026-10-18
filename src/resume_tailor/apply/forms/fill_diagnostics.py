"""`FillResult.diagnostics`: how one fill went, so an old failure can be told from a current one.

Counts and categories only, never a value: the app version, the platform the posting URL
and the landed page point to, how the fill ended, its elapsed time and the model requests
it made. ``corrections`` is added later by `answer_harvest` when the applicant changes an
answer the fill gave.
"""

from __future__ import annotations

import re
from typing import Any

from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.funnel.store_models import FillResult

_SIGN_IN = re.compile(r"\bsign in\b|\blog ?in\b", re.I)
_ACCOUNT = re.compile(r"create (?:your |an )?.{0,20}account", re.I)
_CLOSED = re.compile(r"closed|no longer available|careers home page", re.I)
_CAPTCHA = re.compile(r"captcha|checks for a person|verification wall|refused automated", re.I)
_NO_FORM = re.compile(r"(?:couldn't|could not) (?:reach|find) the application form", re.I)
_TIME = re.compile(r"time limit", re.I)


def _version() -> str:
    from resume_tailor.infra import desktop_update  # noqa: PLC0415

    return str(getattr(desktop_update, "CURRENT", "") or "dev")


def end_category(result: FillResult, needs_review: list[str] | None = None) -> str:
    """One word for how the fill ended (stable names; the eval scripts count them)."""
    reason = result.handoff_reason or ""
    if result.status in {"submitted", "submit_unconfirmed"}:
        return result.status
    if result.status == "awaiting_otp":
        return "handoff_code"
    if result.status == "fill_failed":
        if _CLOSED.search(reason):
            return "closed"
        return "stalled" if "stopped responding" in reason else "failed"
    for pattern, name in (
        (_NO_FORM, "no_form"), (_ACCOUNT, "handoff_account"), (_SIGN_IN, "handoff_sign_in"),
        (_CAPTCHA, "handoff_captcha"), (_CLOSED, "closed"),
    ):
        if reason and pattern.search(reason):
            return name
    if any(_TIME.search(line) for line in needs_review or []):
        return "time_limit"
    if result.ready_to_submit:
        return "ready"
    if result.required_empty:
        return "review_missing"
    return "review"


def build(
    result: FillResult, *, posting_url: str, landed_url: str, elapsed_s: float,
    model_calls: int, needs_review: list[str] | None = None, landed_platform: str = "",
) -> dict[str, Any]:
    return {
        "app_version": _version(),
        "platform": {
            "posting": fetch_jd.detect_ats(posting_url or ""),
            "landed": landed_platform or (fetch_jd.detect_ats(landed_url) if landed_url else ""),
        },
        "end_category": end_category(result, needs_review),
        "elapsed_s": round(elapsed_s, 1),
        "model_calls": model_calls,
    }
