"""A fill stuck on questions waits at the back of its batch and comes back (`come_back`)."""

from __future__ import annotations

import threading
import time

import pytest

from resume_tailor.apply.funnel import come_back, operations, store_models
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings

_STUCK = store_models.FillResult(
    status="awaiting_review", browser_target_id="tab", handoff_reason="Answer 2 questions",
)
_DONE = store_models.FillResult(status="awaiting_review", ready_to_submit=True)


@pytest.fixture
def batch(monkeypatch):
    """A Fill batch over rows ``one``..``three`` whose retained tabs stay open."""
    operations._CONTROLS.clear()
    operations._ACTIVE.clear()
    monkeypatch.setattr(operations, "_persist", lambda _operation: None)
    monkeypatch.setattr(operations.browser, "extension_mode", lambda: False)
    monkeypatch.setattr(operations.browser, "open_target_ids", lambda: {"tab"})
    monkeypatch.setattr(operations.submit_guard, "is_paused", lambda: False)
    monkeypatch.setattr(operations.answer_harvest, "watch", lambda _id: None)
    monkeypatch.setattr(operations.answer_harvest, "collect", lambda _id: 0)
    monkeypatch.setattr(operations.come_back, "ready_to_continue", lambda _id: False)
    rows = {
        key: store_models.Application(
            source="test", source_job_id=key, company=key, role="Intern", status="ready",
        )
        for key in ("one", "two", "three")
    }
    monkeypatch.setattr(operations.store, "get", rows.get)
    calls: list[tuple[str, str]] = []

    def fills(replies: dict[str, list[store_models.FillResult]]) -> None:
        """Each row answers with its replies in turn (the last one repeats)."""

        def fake_fill(application_id, **kwargs):
            calls.append((application_id, kwargs["fill_mode"]))
            queue = replies.get(application_id, [_DONE])
            result = queue.pop(0) if len(queue) > 1 else queue[0]
            rows[application_id].status = result.status
            rows[application_id].fill = result
            return result

        monkeypatch.setattr(operations.fill, "fill_application", fake_fill)

    def dispatch(operation, ids, settings, wait, options) -> None:
        monkeypatch.setattr(operations.come_back, "wait_seconds", lambda _settings: wait)
        request = ApplyOperationRequest(
            action="fill", application_ids=list(ids), model_provider="ollama",
            model_name="test", **options,
        )
        operations._dispatch_items(
            operation, request, settings or ApplySettings(max_parallel_fills=1), None
        )

    def new_operation(ids) -> operations.ApplyOperation:
        return operations.ApplyOperation(
            operation_id="test", action="fill", state="running",
            application_ids=list(ids), total=len(ids), held_ids=list(ids),
        )

    def run(
        ids=("one",), settings: ApplySettings | None = None, wait: float = 0.0, **options
    ) -> operations.ApplyOperation:
        operation = new_operation(ids)
        dispatch(operation, ids, settings, wait, options)
        return operation

    def start(ids=("one",), wait: float = 30.0):
        """``run`` on its own thread, registered so `operations.control` reaches it;
        returns once the first application waits to come back."""
        operation = new_operation(ids)
        operations._ACTIVE[operation.operation_id] = operation
        worker = threading.Thread(
            target=dispatch, args=(operation, ids, None, wait, {}), daemon=True
        )
        worker.start()
        _until(lambda: operation.waiting)
        return operation, worker

    yield type("Batch", (), {"rows": rows, "calls": calls, "fills": fills, "run": run, "start": start})
    operations._CONTROLS.clear()
    operations._ACTIVE.clear()


def _until(check, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_a_stuck_fill_goes_to_the_back_and_comes_back_as_a_continue_fill(batch, monkeypatch):
    monkeypatch.setattr(operations.come_back, "ready_to_continue", lambda _id: True)
    batch.fills({"one": [_STUCK, _DONE]})
    operation = batch.run(ids=("one", "two", "three"), wait=30.0)
    assert batch.calls == [
        ("one", "initial"), ("two", "initial"), ("three", "initial"), ("one", "continue"),
    ]
    assert (operation.processed, operation.completed, operation.needs_input) == (3, 3, 0)
    assert operation.waiting == [] and operation.held_ids == []
    assert [e["stage"] for e in operation.events if e["application_id"] == "one"].count("waiting") == 1


def test_it_waits_for_its_timer_until_everything_is_answered(batch, monkeypatch):
    answered = threading.Event()
    monkeypatch.setattr(operations.come_back, "ready_to_continue", lambda _id: answered.is_set())
    batch.fills({"one": [_STUCK, _DONE]})
    operation, worker = batch.start()
    assert operation.waiting[0].reason == "Answer 2 questions"
    assert operation.waiting[0].due_at
    time.sleep(0.3)
    assert batch.calls == [("one", "initial")]
    answered.set()
    worker.join(3)
    assert not worker.is_alive()
    assert batch.calls == [("one", "initial"), ("one", "continue")]
    assert operation.completed == 1


def test_retry_now_brings_it_back_at_once(batch):
    batch.fills({"one": [_STUCK, _DONE]})
    operation, worker = batch.start()
    operations.control(operation.operation_id, "retry_now", "one")
    worker.join(3)
    assert not worker.is_alive()
    assert batch.calls == [("one", "initial"), ("one", "continue")]


def test_leave_it_ends_in_needs_you_without_another_fill(batch):
    batch.fills({"one": [_STUCK]})
    operation, worker = batch.start()
    operations.control(operation.operation_id, "leave", "one")
    worker.join(3)
    assert not worker.is_alive()
    assert batch.calls == [("one", "initial")]
    assert (operation.processed, operation.needs_input, operation.blocked) == (1, 1, 1)
    assert [(a.kind, a.message) for a in operation.attention] == [("needs_input", "Answer 2 questions")]
    assert operation.held_ids == []


def test_control_refuses_an_application_that_is_not_waiting(batch):
    batch.fills({"one": [_STUCK]})
    operation, worker = batch.start()
    with pytest.raises(RuntimeError, match="not waiting"):
        operations.control(operation.operation_id, "retry_now", "two")
    operations.control(operation.operation_id, "cancel")
    worker.join(3)


def test_its_timer_alone_never_takes_the_tab_back(batch):
    """Audit #21: a comeback at the deadline retook a tab the applicant was typing in."""
    batch.fills({"one": [_STUCK, _DONE]})
    operation = batch.run(wait=0.0)
    assert batch.calls == [("one", "initial")]
    assert (operation.processed, operation.needs_input) == (1, 1)
    assert operation.attention[0].message == come_back.STILL_WAITING_NOTE
    assert operation.waiting == [] and operation.held_ids == []


def test_typing_since_the_last_look_puts_the_comeback_off(batch, monkeypatch):
    looks = iter([True, False, True])  # ready when picked; typing on the fresh look
    monkeypatch.setattr(operations.come_back, "ready_to_continue", lambda _id: next(looks, True))
    batch.fills({"one": [_STUCK, _DONE]})
    operation = batch.run(wait=30.0)
    assert batch.calls == [("one", "initial"), ("one", "continue")]
    assert operation.completed == 1


def test_it_gives_up_after_two_comebacks(batch, monkeypatch):
    monkeypatch.setattr(operations.come_back, "ready_to_continue", lambda _id: True)
    batch.fills({"one": [_STUCK]})
    operation = batch.run(wait=30.0)
    assert batch.calls == [("one", "initial"), ("one", "continue"), ("one", "continue")]
    assert (operation.processed, operation.needs_input) == (1, 1)
    assert [a.kind for a in operation.attention] == ["needs_input"]


@pytest.mark.parametrize(
    ("result", "settings", "options"),
    [
        (_STUCK, ApplySettings(max_parallel_fills=1, come_back_stuck=False), {}),
        (_STUCK.model_copy(update={"browser_target_id": ""}), None, {}),
        (_STUCK.model_copy(update={"handoff_reason": operations._MODEL_UNAVAILABLE}), None, {}),
        (store_models.FillResult(status="awaiting_otp", browser_target_id="tab"), None, {"blocker_mode": "pause"}),
    ],
    ids=["setting off", "no tab", "model at its limit", "pause on blocker"],
)
def test_some_hand_backs_never_wait(batch, monkeypatch, result, settings, options):
    monkeypatch.setattr(operations, "_model_exhausted", lambda _settings: True)
    monkeypatch.setattr(operations, "_wait_if_paused", lambda _operation: "skip")
    batch.fills({"one": [result]})
    operation = batch.run(settings=settings, **options)
    assert batch.calls == [("one", "initial")]
    assert operation.needs_input == 1
    assert operation.waiting == []


def test_ready_to_submit_is_not_stuck(batch):
    batch.fills({"one": [_DONE.model_copy(update={"browser_target_id": "tab"})]})
    operation = batch.run()
    assert batch.calls == [("one", "initial")]
    assert operation.ready_for_review == 1


def test_one_submitted_by_hand_while_waiting_is_not_filled_again(batch, monkeypatch):
    settled = threading.Event()
    monkeypatch.setattr(operations.come_back, "ready_to_continue", lambda _id: settled.is_set())
    batch.fills({"one": [_STUCK]})
    operation, worker = batch.start()
    batch.rows["one"].status = "submitted"
    settled.set()
    worker.join(3)
    assert not worker.is_alive()
    assert batch.calls == [("one", "initial")]
    assert (operation.processed, operation.completed, operation.needs_input) == (1, 1, 0)


def test_a_closed_tab_ends_the_wait_in_needs_you(batch, monkeypatch):
    batch.fills({"one": [_STUCK]})
    operation, worker = batch.start()
    monkeypatch.setattr(operations.browser, "open_target_ids", lambda: set())
    operations.control(operation.operation_id, "retry_now", "one")
    worker.join(3)
    assert batch.calls == [("one", "initial")]
    assert operation.needs_input == 1
    assert "tab was closed" in operation.attention[0].message


def test_cancel_drops_the_waiting_fills(batch):
    batch.fills({"one": [_STUCK]})
    operation, worker = batch.start()
    operations.control(operation.operation_id, "cancel")
    worker.join(3)
    assert not worker.is_alive()
    assert batch.calls == [("one", "initial")]
    assert operation.processed == 0


def test_readiness_needs_answers_and_a_quiet_tab():
    come_back.forget("x")
    assert not come_back.ready_to_continue("x")
    come_back.note("x", answered=True, idle_s=5.0)
    assert come_back.answered("x") and not come_back.ready_to_continue("x")
    come_back.note("x", answered=True, idle_s=come_back.QUIET_S)
    assert come_back.ready_to_continue("x")
    come_back.note("x", answered=None, idle_s=600.0)  # nothing was left: timer only
    assert not come_back.ready_to_continue("x")
    come_back.note_settled("x")
    assert come_back.ready_to_continue("x")
    come_back.forget("x")
    assert not come_back.ready_to_continue("x")
