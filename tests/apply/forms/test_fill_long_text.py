"""Written answers: a model failure costs one question, not the fill, and review notes
with a reason survive the end-of-fill reconciliation."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import answer, answer_memory, model_fallback
from resume_tailor.apply.forms import fill_answers, fill_finish, fill_widgets
from resume_tailor.infra import llm

QUESTION = "Why do you want this role?"


def _run() -> fill_answers._FillAnswers:
    run = fill_answers._FillAnswers.__new__(fill_answers._FillAnswers)
    run.app = SimpleNamespace(company="Acme")
    run.pkt = SimpleNamespace(company="Acme")
    run.ats_name = "greenhouse"
    run.resume = run.bullets = run.requirements = run.profile = None
    run.jd_text = ""
    run.needs_review = []
    run.long_text_answers = {}
    run.lines = []
    run.on_progress = run.lines.append
    run.on_deadline = None
    run.should_cancel = None
    run.started = time.monotonic()
    run.deadline = run.started + 240
    run.typed = []
    run._fill_if_empty = lambda item, text: run.typed.append(text)
    return run


@pytest.fixture(autouse=True)
def _no_saved_answer(monkeypatch):
    monkeypatch.setattr(answer_memory, "recall", lambda *a, **k: None)


def _broken(*_a, **_k):
    raise TimeoutError("read timed out")


@pytest.mark.parametrize("required", [True, False])
def test_a_model_error_leaves_only_that_question(monkeypatch, required):
    monkeypatch.setattr(answer, "answer_question", _broken)
    run = _run()
    run._answer_one_long_text({"label": QUESTION, "required": required}, QUESTION)
    assert run.typed == []
    assert run.needs_review == ([f"{QUESTION}: {fill_answers.NOT_DRAFTED_NOTE}"] if required else [])
    assert run.lines == [f"could not draft an answer for {QUESTION} (TimeoutError)"]


def test_out_of_time_defers_to_the_step_deadline_check(monkeypatch):
    monkeypatch.setattr(answer, "answer_question", _broken)
    run = _run()
    run.deadline = time.monotonic() - 1
    run._answer_one_long_text({"label": QUESTION, "required": True}, QUESTION)
    assert run.needs_review == [] and run.lines == []


def test_heavy_at_its_limit_is_answered_by_light(monkeypatch):
    seen: list[str] = []

    def ask(*_a, **_k):
        model = config.model_for("answer")
        seen.append(model)
        if model == "gemini-3.5-flash":
            raise llm.LLMError("HTTP 429", status=429)
        return answer.AnswerResult(answer="Because.", warnings=[], source="model", offenders=[])

    monkeypatch.setattr(answer, "answer_question", ask)
    run = _run()
    route = model_fallback.Fallback(heavy="gemini:gemini-3.5-flash", light="gemini:gemini-3.5-flash-lite")
    with model_fallback.pin(route):
        run._answer_one_long_text({"label": QUESTION, "required": True}, QUESTION)
    assert seen == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
    assert run.typed == ["Because."] and run.needs_review == []


def test_a_shortened_saved_answer_keeps_its_note_after_reconcile(monkeypatch):
    long_answer = "First sentence here. " + "More words. " * 40
    monkeypatch.setattr(
        answer_memory, "recall", lambda *a, **k: answer_memory.Recall(answer=long_answer, id=1)
    )
    run = _run()
    run._answer_one_long_text({"label": QUESTION, "required": True, "maxlength": 40}, QUESTION)
    note = f"{QUESTION}: {fill_answers.SHORTENED_NOTE}"
    assert run.needs_review == [note] and run.typed

    finish = fill_finish._FillFinish.__new__(fill_finish._FillFinish)
    finish.merged = {
        "filled": [{"label": QUESTION, "selector": "#why"}, {"label": "Phone", "selector": "#p"}],
        "leftovers": [],
    }
    finish.completed_step_outcomes = {}
    finish.page = finish.filler_js = finish.hints = None
    finish.needs_review = [note, "Phone"]
    monkeypatch.setattr(
        fill_widgets, "_observe_fields",
        lambda *_a: {
            (0, "#why"): {"label": QUESTION, "value": run.typed[0]},
            (0, "#p"): {"label": "Phone", "value": "555"},
        },
    )
    finish._reconcile_observed()
    # The blank-field flag is resolved by the observed value; the shortened note is not.
    assert finish.needs_review == [note]
