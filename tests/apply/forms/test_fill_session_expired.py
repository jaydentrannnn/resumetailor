"""A Workday session that times out mid-application signs in again instead of handing off.

Live 2026-10-12: tabs left for hours came back on Workday's Create Account/Sign In step
after a refresh, and the fill treated the password boxes as unrecognised fields.
"""

from __future__ import annotations

import time

import pytest

from resume_tailor.apply.ats import workday_auth, workday_flow, workday_page
from resume_tailor.apply.forms import fill_ats_steps, fill_outcomes
from resume_tailor.apply.funnel.store_models import FillResult


class _Run(fill_ats_steps._FillAtsSteps):
    def __init__(self) -> None:  # no packet, page or store: only the step-ready check
        self.page = object()
        self.source_job_id = "app"
        self.profile = object()
        self.deadline = time.monotonic() + 60
        self.lines: list[str] = []

    def progress(self, message: str) -> None:
        self.lines.append(message)

    def recover_site_error(self) -> bool:
        return True

    def _handoff(self, reason: str, **kwargs) -> FillResult:
        return FillResult(status=kwargs.get("status", "awaiting_review"), handoff_reason=reason)


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(workday_page, "detect_state", lambda _page: "create_account")
    monkeypatch.setattr(workday_flow, "wait_for_state", lambda *_a, **_k: "apply_form")
    monkeypatch.setattr(workday_flow, "wait_for_step_ready", lambda *_a, **_k: True)
    return _Run()


def test_a_timed_out_session_signs_in_again_and_carries_on(run, monkeypatch):
    calls = []
    monkeypatch.setattr(
        workday_auth, "handle_workday_auth",
        lambda *_a, **_k: calls.append(1) or "authenticated",
    )
    assert run._workday_step_ready(2) is None
    assert calls == [1]
    assert "signing in again" in run.lines[0]
    # A second time-out in the same fill is handed over: no sign-in loop.
    result = run._workday_step_ready(3)
    assert result is not None and result.handoff_reason == fill_outcomes.SESSION_EXPIRED_MSG
    assert calls == [1]


def test_a_failed_sign_in_hands_over_with_its_reason(run, monkeypatch):
    monkeypatch.setattr(workday_auth, "handle_workday_auth", lambda *_a, **_k: "verification_needed")
    result = run._workday_step_ready(1)
    assert result is not None and result.status == "awaiting_otp"
    assert result.handoff_reason == workday_auth.AUTH_HANDOFF["verification_needed"]
