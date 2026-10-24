"""Prepare and Fill batches run side by side, each owning its own rows and controls."""

from __future__ import annotations

import threading
import time

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import operations, preparation, store_models
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings


@pytest.fixture
def apply_env(tmp_path, monkeypatch):
    """Rows ``one``..``four``; Prepare waits on ``gates[id]`` before finishing a row."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(operations, "_ACTIVE", {})
    monkeypatch.setattr(operations, "_CONTROLS", {})
    monkeypatch.setattr(operations.browser, "extension_mode", lambda: False)
    monkeypatch.setattr(operations.submit_guard, "is_paused", lambda: False)
    monkeypatch.setattr(operations, "_captured_settings", lambda _request: ApplySettings())
    monkeypatch.setattr(operations.daily_progress, "daily_busy", lambda: False)
    monkeypatch.setattr(
        preparation, "check",
        lambda _app, **_kwargs: preparation.PreparationEligibility(eligible=True),
    )
    rows = {
        key: store_models.Application(
            source="test", source_job_id=key, company=key, role="Intern", status="ready",
            job_id=f"job-{key}",
        )
        for key in ("one", "two", "three", "four")
    }
    monkeypatch.setattr(operations.store, "get", rows.get)
    gates = {key: threading.Event() for key in rows}
    filled: list[str] = []

    def fake_prepare(application_id, *, should_stop, **_kwargs):
        while not gates[application_id].wait(0.02):
            if should_stop():
                raise operations.PrepareInterrupted()
        return rows[application_id]

    def fake_fill(application_id, **_kwargs):
        filled.append(application_id)
        return store_models.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.daily, "prepare_application", fake_prepare)
    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    yield type("Env", (), {"gates": gates, "filled": filled})
    for gate in gates.values():
        gate.set()


def _start(action: str, ids: list[str]) -> operations.ApplyOperation:
    return operations.start(
        ApplyOperationRequest(
            action=action, application_ids=ids, model_provider="ollama", model_name="test",
        )
    )


def _until(check, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def _finished(operation: operations.ApplyOperation) -> operations.ApplyOperation:
    _until(lambda: operation.operation_id not in operations._ACTIVE)
    return operations.get(operation.operation_id)


def test_fill_runs_while_another_batch_is_still_tailoring(apply_env):
    prepare = _start("prepare", ["one", "two"])
    fill = _start("fill", ["three", "four"])
    done = _finished(fill)
    assert done.state == "completed"
    assert sorted(apply_env.filled) == ["four", "three"]
    assert prepare.operation_id in operations._ACTIVE  # still tailoring
    for gate in apply_env.gates.values():
        gate.set()
    assert _finished(prepare).state == "completed"


def test_a_row_another_batch_holds_is_left_out(apply_env):
    prepare = _start("prepare", ["one", "two"])
    fill = _start("fill", ["two", "three"])
    assert fill.application_ids == ["three"]
    assert fill.excluded == {"two": ["in_another_task"]}
    with pytest.raises(RuntimeError, match="already in another running Apply task"):
        _start("fill", ["one"])
    _finished(fill)
    for gate in apply_env.gates.values():
        gate.set()
    _finished(prepare)


def test_a_row_the_batch_finished_tailoring_can_be_filled_at_once(apply_env):
    prepare = _start("prepare", ["one", "two"])
    apply_env.gates["one"].set()
    _until(lambda: "one" not in prepare.held_ids)
    assert prepare.operation_id in operations._ACTIVE
    fill = _start("fill", ["one"])
    assert fill.application_ids == ["one"]
    assert _finished(fill).completed == 1
    apply_env.gates["two"].set()
    _finished(prepare)


def test_find_runs_alone(apply_env, monkeypatch):
    prepare = _start("prepare", ["one"])
    with pytest.raises(RuntimeError, match="already active"):
        operations.start(
            ApplyOperationRequest(action="find", model_provider="ollama", model_name="test")
        )
    apply_env.gates["one"].set()
    _finished(prepare)

    release = threading.Event()
    monkeypatch.setattr(
        operations.daily, "run_daily",
        lambda **_kwargs: release.wait(3) and operations.daily_progress.DailySummary(),
    )
    find = operations.start(
        ApplyOperationRequest(action="find", model_provider="ollama", model_name="test")
    )
    with pytest.raises(RuntimeError, match="already active"):
        _start("fill", ["two"])
    release.set()
    _finished(find)


def test_pausing_one_batch_leaves_the_other_running(apply_env):
    prepare = _start("prepare", ["one"])
    operations.control(prepare.operation_id, "pause")
    _until(lambda: not prepare.in_flight)
    fill = _start("fill", ["two", "three"])
    assert _finished(fill).completed == 2
    assert operations._ACTIVE[prepare.operation_id].state == "paused"
    apply_env.gates["one"].set()
    operations.control(prepare.operation_id, "resume")
    assert _finished(prepare).completed == 1


def test_the_extension_runs_one_kind_at_a_time(apply_env, monkeypatch):
    prepare = _start("prepare", ["one"])
    monkeypatch.setattr(operations.browser, "extension_mode", lambda: True)
    with pytest.raises(RuntimeError, match="browser extension"):
        _start("fill", ["two"])
    second = _start("prepare", ["two"])  # the same kind shares it
    for gate in apply_env.gates.values():
        gate.set()
    _finished(prepare)
    _finished(second)


def test_profile_edits_wait_for_every_batch(apply_env):
    prepare = _start("prepare", ["one"])
    with pytest.raises(RuntimeError, match="running"), operations.registry_edit_idle():
        pass
    apply_env.gates["one"].set()
    _finished(prepare)
    with operations.registry_edit_idle(), pytest.raises(RuntimeError, match="running"):
        _start("fill", ["two"])


def test_a_finished_operation_holds_nothing(apply_env):
    fill = _start("fill", ["two"])
    done = _finished(fill)
    assert done.held_ids == [] and done.waiting == []
    assert operations.active() is None and operations.active_all() == []
