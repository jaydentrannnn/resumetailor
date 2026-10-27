"""One owner per application: aliases resolve to one id, and a row the applicant settles
by hand leaves the batch holding it (audit #7, #8, #20, #23)."""

from __future__ import annotations

import threading
import time

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import operations, preparation, store, store_models
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Rows ``one``..``three``; Prepare and Fill each wait on ``gates[id]``. A fill
    returns early when its ``should_cancel`` turns true (recorded in ``cancelled``)."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(operations, "_ACTIVE", {})
    monkeypatch.setattr(operations, "_CONTROLS", {})
    monkeypatch.setattr(operations, "_AT_WORK", set())
    monkeypatch.setattr(operations, "_EDITING_ROWS", set())
    monkeypatch.setattr(operations.browser, "extension_mode", lambda: False)
    monkeypatch.setattr(operations.submit_guard, "is_paused", lambda: False)
    settings = {"value": ApplySettings()}
    monkeypatch.setattr(operations, "_captured_settings", lambda _request: settings["value"])
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
        for key in ("one", "two", "three")
    }
    aliases = {f"gh:{key}": key for key in rows}
    monkeypatch.setattr(operations.store, "get", lambda key: rows.get(aliases.get(key, key)))
    monkeypatch.setattr(operations.store, "app_id", lambda key: aliases.get(key, key))
    gates = {key: threading.Event() for key in rows}
    started: list[str] = []
    cancelled: list[str] = []
    watched: list[str] = []

    def fake_prepare(application_id, *, should_stop, **_kwargs):
        while not gates[application_id].wait(0.02):
            if should_stop():
                raise operations.PrepareInterrupted()
        return rows[application_id]

    def fake_fill(application_id, *, should_cancel, **_kwargs):
        started.append(application_id)
        while not gates[application_id].wait(0.02):
            if should_cancel():
                cancelled.append(application_id)
                return store_models.FillResult(status="awaiting_review")
        return store_models.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.daily, "prepare_application", fake_prepare)
    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    monkeypatch.setattr(operations.answer_harvest, "watch", watched.append)
    yield type("Env", (), {
        "rows": rows, "gates": gates, "started": started, "cancelled": cancelled,
        "watched": watched, "settings": settings,
    })
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


def test_an_alias_of_a_held_row_is_the_same_row(env):
    prepare = _start("prepare", ["one"])
    with pytest.raises(RuntimeError, match="already in another running Apply task"):
        _start("fill", ["gh:one"])
    fill = _start("fill", ["two", "gh:two"])
    assert fill.application_ids == ["two"]
    for gate in env.gates.values():
        gate.set()
    _finished(fill)
    _finished(prepare)


def test_marking_a_filling_row_submitted_stops_its_worker(env):
    fill = _start("fill", ["gh:two"])
    _until(lambda: env.started == ["two"])
    assert operations.revoke("gh:two", "You marked it submitted")
    done = _finished(fill)
    assert env.cancelled == ["two"]
    assert env.watched == []  # no watcher on a row the applicant took over
    assert done.failed == 0 and done.processed == 1
    assert done.held_ids == []
    assert not operations.row_busy("two")


def test_a_pending_row_marked_submitted_is_dropped(env):
    env.settings["value"] = ApplySettings(max_parallel_fills=1)
    fill = _start("fill", ["one", "two"])
    _until(lambda: env.started == ["one"])
    operations.revoke("two", "You marked it skipped")
    env.gates["one"].set()
    done = _finished(fill)
    assert env.started == ["one"]
    assert done.processed == 2 and done.failed == 0


def test_a_prepare_item_stops_when_its_row_is_settled(env):
    prepare = _start("prepare", ["one"])
    _until(lambda: bool(prepare.in_flight))
    operations.revoke("one", "You marked it skipped")
    done = _finished(prepare)
    assert done.processed == 1 and done.failed == 0
    assert done.held_ids == []


def test_a_row_settled_before_its_turn_is_not_filled(env):
    env.rows["three"].status = "submitted"
    done = _finished(_start("fill", ["three"]))
    assert env.started == []
    assert done.completed == 1 and done.failed == 0


def test_revoke_without_a_holder_is_a_no_op(env):
    assert operations.revoke("one", "You marked it submitted") is False


def test_editing_rows_waits_only_for_those_rows(env):
    prepare = _start("prepare", ["one"])
    with pytest.raises(RuntimeError, match="running Apply task"), operations.rows_idle(["gh:one"]):
        pass
    with operations.rows_idle(["two"]):
        with pytest.raises(RuntimeError, match="already in another running Apply task"):
            _start("fill", ["two"])
    fill = _start("fill", ["two"])  # free again once the edit is done
    for gate in env.gates.values():
        gate.set()
    _finished(fill)
    _finished(prepare)


@pytest.fixture
def stranded(monkeypatch):
    monkeypatch.setattr(operations, "_ACTIVE", {})
    monkeypatch.setattr(operations, "_AT_WORK", set())
    monkeypatch.setattr(operations.daily_progress, "daily_busy", lambda: False)
    monkeypatch.setattr(operations, "_PROCESS_STARTED", "2026-10-26T12:00:00+00:00")

    def row(key: str, at: str) -> None:
        app = store_models.Application(
            source="test", source_job_id=key, company=key, role="Intern", status="filling",
            job_id=f"job-{key}",
        )
        app.status_history.append(store_models.StatusChange(status="filling", at=at))
        store.upsert(app)

    return row


def test_a_stranded_fill_says_why_it_stopped(stranded):
    """Audit #23: a fill that died in this process was reported as a server restart."""
    stranded("before", "2026-10-26T11:00:00+00:00")
    stranded("after", "2026-10-26T12:30:00+00:00")
    operations.list_recent()
    before, after = store.get("before"), store.get("after")
    assert before.status == after.status == "ready"
    assert before.status_history[-1].note == "Fill interrupted by server restart"
    assert after.status_history[-1].note == "Fill stopped without finishing"


def test_a_fill_still_running_is_not_repaired(stranded, monkeypatch):
    stranded("live", "2026-10-26T12:30:00+00:00")
    monkeypatch.setattr(operations.answer_harvest, "FILLING", {"live"})
    operations.list_recent()
    assert store.get("live").status == "filling"
