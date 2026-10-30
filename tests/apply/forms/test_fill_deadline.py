"""A fill's deadline leaves out the time it spent queued for shared work (audit #28)."""

from __future__ import annotations

import time

from resume_tailor.apply.forms import fill_outcomes, fill_state
from resume_tailor.infra import wait_clock


class _Waited(wait_clock.Tally):
    def __init__(self, seconds: float) -> None:
        super().__init__()
        self.seconds = seconds

    @property
    def total(self) -> float:
        return self.seconds


def _state() -> fill_state._FillState:
    state = object.__new__(fill_state._FillState)
    state.started = time.monotonic()
    state.on_deadline = None
    state.deadline = state.started + fill_outcomes.BASE_BUDGET_S
    return state


def test_time_queued_moves_the_deadline_and_the_hard_cap_out():
    state = _state()
    budget, cap = state.deadline, state.hard_deadline()
    state.waits = _Waited(90.0)
    assert state.deadline == budget + 90.0
    assert state.hard_deadline() == cap + 90.0


def test_an_extension_keeps_the_credit():
    state = _state()
    state.waits = _Waited(30.0)
    before = state.deadline
    state.deadline = before + 10
    state.waits.seconds = 50.0
    assert state.deadline == before + 10 + 20


def test_only_confirmed_smartrecruiters_steps_extend_the_budget():
    assert fill_outcomes.is_forward_progress("SmartRecruiters: added experience Data Intern at Acme")
    assert fill_outcomes.is_forward_progress("SmartRecruiters: answered Are you 18? = Yes")
    assert not fill_outcomes.is_forward_progress("SmartRecruiters: adding experience Data Intern")
    assert not fill_outcomes.is_forward_progress(
        "SmartRecruiters: the form step did not finish loading"
    )
