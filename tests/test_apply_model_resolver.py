"""Model proposals are IDs, never executable selectors or invented facts."""

from __future__ import annotations

from resume_tailor.apply import model_resolver
from resume_tailor.apply.field_types import FieldObservation, ObservedOption


def _field():
    return FieldObservation(
        snapshot_id="snapshot", field_id="observed-1", frame_id="frame-1",
        document_generation="generation-1", label="State", control_kind="native_select",
        options=[
            ObservedOption(option_id="option-1", label="California"),
            ObservedOption(option_id="option-2", label="Nevada"),
        ],
    )


def test_unknown_field_or_option_is_rejected():
    field = _field()
    known = {field.field_id: field}
    facts = {"state": "California"}
    for field_id, option_id in (("invented", "option-1"), ("observed-1", "invented")):
        proposal = model_resolver.ControlProposal(
            field_id=field_id, option_id=option_id, fact_id="state", action="select_option",
        )
        assert model_resolver.validate(proposal, known, facts) is None


def test_supported_fact_must_match_observed_option():
    field = _field()
    proposal = model_resolver.ControlProposal(
        field_id=field.field_id, option_id="option-1", fact_id="state", action="select_option",
    )
    assert model_resolver.validate(proposal, {field.field_id: field}, {"state": "California"}) == (field, "California")
    assert model_resolver.validate(proposal, {field.field_id: field}, {"state": "Nevada"}) is None
    field.current_value = "User answer"
    assert model_resolver.validate(proposal, {field.field_id: field}, {"state": "California"}) is None


def test_fact_cannot_be_used_on_a_semantically_unrelated_field():
    field = _field()
    field.label = "Favorite office location"
    proposal = model_resolver.ControlProposal(
        field_id=field.field_id, option_id="option-1", fact_id="state", action="select_option",
    )
    assert model_resolver.validate(proposal, {field.field_id: field}, {"state": "California"}) is None


def test_safe_facts_excludes_demographics_legal_and_salary():
    facts = model_resolver.safe_facts({
        "state": "California", "race": "Asian", "salary_expectation": "$80,000",
        "authorized_to_work": "Yes", "workday_password": "secret",
    })
    assert facts == {"state": "California"}
