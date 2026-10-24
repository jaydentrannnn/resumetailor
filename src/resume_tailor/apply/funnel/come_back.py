"""A fill stuck on questions goes to the back of its batch and comes back later.

With `ApplySettings.come_back_stuck` on (the default), a fill handed back because it
needs the applicant (unanswered or invalid questions, an email code, a CAPTCHA) keeps its
tab and the batch moves on. The application comes back as a Continue fill once the
applicant has answered every required question it left and stopped typing
(`ready_to_continue`), or after `come_back_after_min` minutes, whichever is first. After
`MAX_COMEBACKS` it is left in Needs you, exactly as with the setting off.

Decisions only; the dispatcher in `operations` acts on them. What the applicant did in
the tab arrives from `answer_harvest`'s watcher pass (`note`, `note_settled`).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from pydantic import BaseModel

from resume_tailor.apply.funnel import store_models
from resume_tailor.web.schemas import ApplySettings

MAX_COMEBACKS = 2
#: No typing or clicking in the tab for this long once everything is answered: the
#: applicant is done there, so the fill may take the tab back.
QUIET_S = 30.0

#: Statuses of a fill that handed the application back to the applicant.
_STUCK = frozenset({"awaiting_review", "awaiting_otp"})
#: Row statuses that still wait on the applicant; anything else was settled meanwhile
#: (submitted by hand, skipped, ...).
STILL_WAITING = _STUCK


class WaitingItem(BaseModel):
    """An application waiting to come back, as the Apply page shows it."""

    application_id: str
    label: str = ""
    #: When the timer brings it back (ISO), for the countdown.
    due_at: str = ""
    #: Comebacks used, this wait included.
    comebacks: int = 1
    reason: str = ""
    #: Every required question it left now has an answer; it comes back once typing stops.
    answered: bool = False


def eligible(
    result: store_models.FillResult,
    settings: ApplySettings,
    *,
    blocker_mode: str,
    comebacks: int,
    model_unavailable: str,
) -> bool:
    """Whether this fill's hand-back waits to come back instead of ending in Needs you.

    Never for a form that is ready to submit (it is not stuck), a fill the model's limit
    held back (that has its own refill), a tab that is gone (nothing to continue), or
    under Pause-on-blocker (the whole batch waits for the applicant there)."""
    return (
        settings.come_back_stuck
        and blocker_mode != "pause"
        and result.status in _STUCK
        and not result.ready_to_submit
        and result.handoff_reason != model_unavailable
        and bool(result.browser_target_id)
        and comebacks < MAX_COMEBACKS
    )


def wait_seconds(settings: ApplySettings) -> float:
    return float(settings.come_back_after_min) * 60.0


def is_due(not_before: float | None, now: float, *, ready: bool, retry_now: bool) -> bool:
    """Whether a pending application may be taken now: it never waited, its timer ran
    out, the applicant answered everything it left, or they pressed Retry now."""
    return not_before is None or now >= not_before or ready or retry_now


# -- what the applicant did in the tab (from `answer_harvest`'s watcher) -----------------


@dataclass(frozen=True)
class _Readiness:
    #: Every required question the fill left has an answer; None when it left none.
    answered: bool | None = None
    #: Seconds since the applicant last typed or clicked there, when measured.
    idle_s: float = 0.0
    #: Submitted or skipped by hand, or the tab closed: nothing to wait for.
    settled: bool = False


_READINESS_LOCK = threading.Lock()
_READINESS: dict[str, _Readiness] = {}


def note(application_id: str, *, answered: bool | None, idle_s: float) -> None:
    with _READINESS_LOCK:
        _READINESS[application_id] = _Readiness(answered=answered, idle_s=idle_s)


def note_settled(application_id: str) -> None:
    with _READINESS_LOCK:
        _READINESS[application_id] = _Readiness(settled=True)


def forget(application_id: str) -> None:
    """Drop what was seen, when the application starts waiting (again)."""
    with _READINESS_LOCK:
        _READINESS.pop(application_id, None)


def answered(application_id: str) -> bool:
    with _READINESS_LOCK:
        state = _READINESS.get(application_id)
    return bool(state and state.answered)


def ready_to_continue(application_id: str) -> bool:
    """Whether a waiting application may come back before its timer: it was settled
    by hand (the dispatcher then counts it without a fill), or everything it left is
    answered and the applicant has been quiet there for `QUIET_S`. The idle time is
    only the measured one, never extrapolated: typing since the last look counts."""
    with _READINESS_LOCK:
        state = _READINESS.get(application_id)
    if state is None:
        return False
    return state.settled or (state.answered is True and state.idle_s >= QUIET_S)
