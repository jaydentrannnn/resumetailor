"""A Workday form that says the job needs citizenship stops a visa holder's fill."""

from __future__ import annotations

import pytest

from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.ats import workday_page
from resume_tailor.apply.forms import fill_ats_steps
from resume_tailor.apply.funnel import store_models

_CMU = (
    "Application Questions 2 of 2 This position requires a U.S. Department of War Security "
    "Clearance, which requires citizenship. Are you a U.S. Citizen?* Select One"
)


class _Page:
    url = "https://cmu.wd115.myworkdayjobs.com/en-US/sei/job/X/apply/applyManually"


def _run(monkeypatch, text: str, authorization: str):
    monkeypatch.setattr(workday_page, "snapshot", lambda _page: {"text": text})
    saved: list[str] = []
    monkeypatch.setattr(
        fill_ats_steps.store, "set_status",
        lambda app, status, note="": saved.append(status) or setattr(app, "status", status),
    )
    monkeypatch.setattr(fill_ats_steps.store, "upsert", lambda app: app)
    run = fill_ats_steps._FillAtsSteps.__new__(fill_ats_steps._FillAtsSteps)
    run.page, run.progress, run.target_id = _Page(), lambda _m: None, "T1"
    run.profile = ApplicantProfile(email="a@example.com", work_authorization=authorization)
    run.app = store_models.Application(
        source="t", source_job_id="x", company="CMU", role="Intern", status="filling",
    )
    return run._workday_citizenship_stop(), saved  # noqa: SLF001


def test_visa_holder_is_stopped_and_screened_out(monkeypatch):
    result, saved = _run(monkeypatch, _CMU, "visa_holder")
    assert result is not None
    assert "security clearance" in result.handoff_reason
    assert saved == ["screened_out"]


@pytest.mark.parametrize("authorization", ["citizen", "permanent_resident", ""])
def test_other_profiles_continue(monkeypatch, authorization):
    assert _run(monkeypatch, _CMU, authorization) == (None, [])


@pytest.mark.parametrize("text", [
    "Are you a U.S. citizen?* Yes No",  # asked for records, not a requirement
    "Have you held an active U.S. security clearance within the last 2 years?* Select One",
])
def test_a_plain_citizenship_question_does_not_stop(monkeypatch, text):
    assert _run(monkeypatch, text, "visa_holder") == (None, [])
