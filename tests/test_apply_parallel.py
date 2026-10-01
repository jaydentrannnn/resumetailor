"""Selected Apply table actions honor their configured worker limits."""

from __future__ import annotations

import threading

import pytest

from resume_tailor.apply.funnel import operations, store
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings, JobSettings


@pytest.fixture
def batch(monkeypatch):
    operations._CANCEL.clear()
    operations._PAUSE.clear()
    operations._RESUME.clear()
    operations._SKIP.clear()
    monkeypatch.setattr(operations, "_persist", lambda _operation: None)
    monkeypatch.setattr(operations.browser, "extension_mode", lambda: False)
    monkeypatch.setattr(operations.submit_guard, "is_paused", lambda: False)
    monkeypatch.setattr(
        operations.workspace,
        "load_settings",
        lambda: {"defaults": JobSettings(max_concurrent_jobs=2).model_dump()},
    )
    apps = {
        key: store.Application(
            source="test",
            source_job_id=key,
            company=key,
            role="Engineer",
            status="ready",
        )
        for key in ("one", "two", "three", "four")
    }
    monkeypatch.setattr(operations.store, "get", apps.get)

    def run(
        action: str = "fill",
        ids: tuple[str, ...] = ("one", "two", "three", "four"),
        settings: ApplySettings | None = None,
        **options,
    ) -> operations.ApplyOperation:
        request = ApplyOperationRequest(
            action=action,
            application_ids=list(ids),
            model_provider="ollama",
            model_name="test",
            **options,
        )
        operation = operations.ApplyOperation(
            operation_id="test",
            action=action,
            state="running",
            application_ids=list(ids),
            total=len(ids),
        )
        operations._dispatch_items(operation, request, settings or ApplySettings(), None)
        return operation

    yield run
    operations._CANCEL.clear()
    operations._PAUSE.clear()
    operations._RESUME.clear()
    operations._SKIP.clear()


def test_fill_uses_exactly_two_workers(batch, monkeypatch):
    barrier = threading.Barrier(2, timeout=3)
    lock = threading.Lock()
    active = peak = 0

    def fake_fill(_application_id, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait()
        with lock:
            active -= 1
        return store.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    operation = batch(settings=ApplySettings(max_parallel_fills=2))
    assert (peak, operation.processed, operation.completed, operation.failed) == (2, 4, 4, 0)
    assert operation.in_flight == []


@pytest.mark.parametrize("extension, blocker", [(True, "continue"), (False, "pause")])
def test_fill_serial_modes(batch, monkeypatch, extension, blocker):
    monkeypatch.setattr(operations.browser, "extension_mode", lambda: extension)
    active = peak = 0

    def fake_fill(_application_id, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        active -= 1
        return store.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    operation = batch(settings=ApplySettings(max_parallel_fills=4), blocker_mode=blocker)
    assert (peak, operation.completed, operation.failed) == (1, 4, 0)


def test_raising_fill_does_not_stop_other_rows(batch, monkeypatch):
    def fake_fill(application_id, **_kwargs):
        if application_id == "one":
            raise RuntimeError("site failed")
        return store.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    operation = batch()
    assert (operation.processed, operation.completed, operation.failed) == (4, 3, 1)
    assert [(item.application_id, item.kind, item.message) for item in operation.attention if item.kind == "failed"] == [("one", "failed", "site failed")]


@pytest.mark.parametrize("result,kind,message", [
    (store.FillResult(status="awaiting_review", ready_to_submit=True), "ready_for_review", "Ready to submit — final check"),
    (store.FillResult(status="awaiting_otp", handoff_reason="Email code required"), "needs_input", "Email code required"),
    (store.FillResult(status="fill_failed", error="Form crashed"), "failed", "Form crashed"),
])
def test_fill_attention_records_real_outcome(batch, monkeypatch, result, kind, message):
    monkeypatch.setattr(operations.fill, "fill_application", lambda *_args, **_kwargs: result)
    operation = batch(ids=("one",))
    assert len(operation.attention) == 1
    assert (operation.attention[0].kind, operation.attention[0].message) == (kind, message)


def test_prepare_attention_records_blocked_and_missing(batch, monkeypatch):
    monkeypatch.setattr(operations.daily, "prepare_application", lambda *_args, **_kwargs: store.Application(
        source="test", source_job_id="one", company="one", role="Engineer", status="needs_browser", error="Sign in first",
    ))
    operation = batch(action="prepare", ids=("one", "missing"))
    assert {(item.application_id, item.kind, item.message) for item in operation.attention} == {
        ("one", "blocked", "Sign in first"),
        ("missing", "failed", "Application no longer exists"),
    }


def test_pause_resume_removes_attention_for_retried_item(batch, monkeypatch):
    replies = iter([
        store.FillResult(status="awaiting_otp", handoff_reason="Email code required"),
        store.FillResult(status="submitted"),
    ])
    monkeypatch.setattr(operations.fill, "fill_application", lambda *_args, **_kwargs: next(replies))
    monkeypatch.setattr(operations, "_wait_if_paused", lambda _operation: "resume")
    operation = batch(ids=("one",), blocker_mode="pause")
    assert operation.needs_input == operation.blocked == 0
    assert operation.attention == []


def test_auto_submit_reservation_caps_parallel_fills(batch, monkeypatch):
    barrier = threading.Barrier(2, timeout=3)
    modes: list[str] = []
    lock = threading.Lock()

    def fake_fill(_application_id, **kwargs):
        with lock:
            modes.append(kwargs["submit_mode"])
            first_wave = len(modes) <= 2
        if first_wave:
            barrier.wait()
        if kwargs["submit_mode"] == "auto_submit":
            return store.FillResult(status="submitted")
        return store.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    operation = batch(
        settings=ApplySettings(max_parallel_fills=2, auto_submit_max_per_run=1),
        auto_submit=True,
    )
    assert modes.count("auto_submit") == 1
    assert (operation.submitted, operation.completed, operation.failed) == (1, 4, 0)


def test_prepare_uses_tailor_job_concurrency(batch, monkeypatch):
    barrier = threading.Barrier(2, timeout=3)
    lock = threading.Lock()
    active = peak = 0

    def fake_prepare(application_id, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait()
        with lock:
            active -= 1
        return store.Application(
            source="test",
            source_job_id=application_id,
            company=application_id,
            role="Engineer",
            status="ready",
        )

    monkeypatch.setattr(operations.daily, "prepare_application", fake_prepare)
    operation = batch(action="prepare")
    assert (peak, operation.processed, operation.completed, operation.failed) == (2, 4, 4, 0)


def test_same_group_prepares_serially(batch, monkeypatch):
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    monkeypatch.setattr(
        operations.store,
        "get",
        lambda key: store.Application(
            source="test",
            source_job_id=key,
            company="Acme",
            role="Engineer",
            status="ready",
        ),
    )

    def fake_prepare(application_id, **_kwargs):
        if application_id == "one":
            first_started.set()
            assert release_first.wait(3)
        else:
            second_started.set()
        return store.Application(
            source="test",
            source_job_id=application_id,
            company="Acme",
            role="Engineer",
            status="ready",
        )

    monkeypatch.setattr(operations.daily, "prepare_application", fake_prepare)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(batch(action="prepare", ids=("one", "two")))
    )
    worker.start()
    assert first_started.wait(3)
    assert not second_started.wait(0.1)
    release_first.set()
    worker.join(3)
    assert not worker.is_alive()
    assert second_started.is_set()
    assert results[0].completed == 2


def test_pause_holds_new_dispatch_after_in_flight_fills(batch, monkeypatch):
    both_started = threading.Barrier(3, timeout=3)
    release = threading.Event()
    paused = threading.Event()
    visited: list[str] = []
    original_event = operations._event

    def observe_event(operation, stage, message, application_id=""):
        original_event(operation, stage, message, application_id)
        if stage == "paused_by_user":
            paused.set()

    def fake_fill(application_id, **_kwargs):
        visited.append(application_id)
        if application_id in {"one", "two"}:
            both_started.wait()
            assert release.wait(3)
        return store.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations, "_event", observe_event)
    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            batch(ids=("one", "two", "three"), settings=ApplySettings(max_parallel_fills=2))
        )
    )
    worker.start()
    both_started.wait()
    operations._PAUSE.set()
    release.set()
    assert paused.wait(3)
    assert "three" not in visited
    operations._RESUME.set()
    worker.join(3)
    assert not worker.is_alive()
    assert results[0].completed == 3
