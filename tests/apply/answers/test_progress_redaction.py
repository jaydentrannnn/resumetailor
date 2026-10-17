"""Self-identification and credential answers never reach the persisted progress log."""

from __future__ import annotations

import pytest

from resume_tailor.apply.answers import answer_memory
from resume_tailor.apply.funnel import operations

HIDDEN = answer_memory.HIDDEN


@pytest.mark.parametrize(
    ("label", "key", "value", "expected"),
    [
        ("Gender", "", "Female", HIDDEN),
        ("Please select", "veteran_status", "I am not a protected veteran", HIDDEN),
        ("Are you Hispanic or Latino?", "", "No", HIDDEN),
        ("How did you hear about us?", "how_heard", "LinkedIn", "LinkedIn"),
        ("Country", "country", "United States", "United States"),
    ],
)
def test_shown_hides_only_sensitive_answers(label, key, value, expected):
    assert answer_memory.shown(label, value, key=key) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Workday: selected Gender = Female", f"Workday: selected Gender = {HIDDEN}"),
        (
            "Workday: no exact option for Race = Asian; chose Asian (Not Hispanic)",
            f"Workday: no exact option for Race = {HIDDEN}; chose {HIDDEN}",
        ),
        (
            "Workday: Disability Status: no option for Yes (no match; options: A, B)",
            f"Workday: Disability Status: no option for {HIDDEN}",
        ),
        ("Workday: selected Country = United States", "Workday: selected Country = United States"),
        ("scanning form step 2", "scanning form step 2"),
    ],
)
def test_redact_is_a_backstop_for_lines_naming_a_sensitive_question(message, expected):
    assert answer_memory.redact(message) == expected


def test_event_stores_the_redacted_line_everywhere(monkeypatch):
    monkeypatch.setattr(operations, "_persist", lambda _op: None)
    op = operations.ApplyOperation(
        operation_id="op", action="fill", application_ids=["a"], total=1,
        in_flight=[operations.InFlightItem(application_id="a")],
    )
    operations._event(op, "filling", "Workday: selected Gender = Female", "a")
    shown = f"Workday: selected Gender = {HIDDEN}"
    assert op.message == shown
    assert op.current_action_label == shown
    assert op.in_flight[0].action_label == shown
    assert op.events[-1]["message"] == shown
    assert "Female" not in op.model_dump_json()
