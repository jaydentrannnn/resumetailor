"""Regression tests for retained tabs, Workday verification, and restart recovery."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from resume_tailor import config
from resume_tailor.apply import browser, operations, preparation, store, workday_auth
from resume_tailor.apply.profile import ApplicantProfile
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings


def test_target_lookup_uses_cdp_id_not_url():
    context = MagicMock()
    first = MagicMock(url="https://example.com/apply")
    second = MagicMock(url="https://example.com/apply")
    first.is_closed.return_value = False
    second.is_closed.return_value = False
    context.pages = [first, second]
    context.new_cdp_session.side_effect = lambda page: MagicMock(
        send=lambda _command: {"targetInfo": {"targetId": "first" if page is first else "second"}}
    )
    assert browser.find_target(context, "second") is second
    assert browser.find_target(context, "missing") is None


def test_workday_requires_real_email(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    with pytest.raises(ValueError, match="email is required"):
        workday_auth.get_tenant_credentials("https://company.myworkdayjobs.com/job/1", ApplicantProfile())
    assert not (tmp_path / "workday_vault.json").exists()


def test_interrupted_fill_restores_retryable_status(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(operations, "_ACTIVE_ID", None)
    app = store.Application(
        source="test", source_job_id="app-1", company="Acme", role="Intern",
        status="filling", job_id="job-1",
        fill=store.FillResult(browser_target_id="target-1", status="awaiting_review"),
    )
    store.upsert(app)
    op = operations.ApplyOperation(operation_id="op-1", action="fill", state="running", application_ids=["app-1"])
    operations._save({"op-1": op})  # noqa: SLF001
    recent = operations.list_recent()
    assert recent[0].state == "interrupted"
    restored = store.get("app-1")
    assert restored is not None and restored.status == "awaiting_review"
    assert store.FillResult.model_validate(restored.fill).browser_target_id == "target-1"


def test_interrupted_submission_is_not_refilled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(operations, "_ACTIVE_ID", None)
    app = store.Application(
        source="test", source_job_id="app-1", company="Acme", role="Intern",
        status="filling", job_id="job-1",
        fill=store.FillResult(browser_target_id="target-1", submit_action="submit"),
    )
    store.upsert(app)
    operations._save({"op-1": operations.ApplyOperation(  # noqa: SLF001
        operation_id="op-1", action="fill", state="running", application_ids=["app-1"],
    )})
    operations.list_recent()
    recovered = store.get("app-1")
    assert recovered is not None and recovered.status == "submit_unconfirmed"
    assert "submission_unconfirmed" in preparation.check(recovered).reasons


def test_fill_batch_continues_past_missing_answers_and_workday_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output")
    apps = {
        key: store.Application(source="test", source_job_id=key, company="Acme", role=key, status="ready", job_id=f"job-{key}")
        for key in ("one", "two", "three")
    }
    monkeypatch.setattr(operations.store, "get", apps.get)
    monkeypatch.setattr(operations, "_captured_settings", lambda _request: ApplySettings())
    monkeypatch.setattr(operations.daily, "daily_busy", lambda: False)
    monkeypatch.setattr(
        preparation, "check", lambda _app, **_kwargs: preparation.PreparationEligibility(eligible=True)
    )
    outcomes = {
        "one": store.FillResult(status="awaiting_review", ready_to_submit=False),
        "two": store.FillResult(status="awaiting_otp"),
        "three": store.FillResult(status="awaiting_review", ready_to_submit=True),
    }
    visited: list[str] = []
    def fake_fill(application_id: str, **_kwargs):
        visited.append(application_id)
        return outcomes[application_id]
    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    request = ApplyOperationRequest(
        action="fill", application_ids=["one", "two", "three"], auto_submit=False,
        blocker_mode="continue", model_provider="ollama", model_name="test",
    )
    started = operations.start(request)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = operations.get(started.operation_id)
        if current and current.state not in {"queued", "running", "paused"}:
            break
        time.sleep(0.02)
    finished = operations.get(started.operation_id)
    assert finished is not None
    assert finished.state == "completed_with_issues"
    assert (finished.processed, finished.completed, finished.blocked, finished.failed) == (3, 1, 2, 0)
    assert visited == ["one", "two", "three"]


def _wait_for_state(operation_id: str, states: set[str], timeout: float = 3.0) -> operations.ApplyOperation:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = operations.get(operation_id)
        if current and current.state in states:
            return current
        time.sleep(0.02)
    raise AssertionError(f"operation never reached {states}")


def test_resume_after_pause_continues_in_the_retained_tab(tmp_path, monkeypatch):
    """Resuming a paused Fill must reuse the tab the user just worked in, not open a new one."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output")
    app = store.Application(source="test", source_job_id="one", company="Acme", role="SWE", status="ready", job_id="job-one")
    monkeypatch.setattr(operations.store, "get", {"one": app}.get)
    monkeypatch.setattr(operations, "_captured_settings", lambda _request: ApplySettings())
    monkeypatch.setattr(operations.daily, "daily_busy", lambda: False)
    monkeypatch.setattr(
        preparation, "check", lambda _app, **_kwargs: preparation.PreparationEligibility(eligible=True)
    )
    replies = [
        store.FillResult(status="awaiting_otp"),
        store.FillResult(status="awaiting_review", ready_to_submit=True),
    ]
    modes: list[str] = []

    def fake_fill(_application_id: str, **kwargs):
        modes.append(kwargs["fill_mode"])
        return replies.pop(0)

    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    request = ApplyOperationRequest(
        action="fill", application_ids=["one"], auto_submit=False,
        blocker_mode="pause", model_provider="ollama", model_name="test",
    )
    started = operations.start(request)
    paused = _wait_for_state(started.operation_id, {"paused"})
    assert paused.needs_input == 1

    operations.control(started.operation_id, "resume")
    finished = _wait_for_state(started.operation_id, {"completed", "completed_with_issues", "failed"})

    assert modes == ["initial", "continue"]
    assert finished.state == "completed"
    assert (finished.blocked, finished.needs_input, finished.ready_for_review) == (0, 0, 1)
