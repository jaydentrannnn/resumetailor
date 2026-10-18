"""A statement about the applicant is ticked only when the profile says what it says."""

from __future__ import annotations

import pytest

from resume_tailor.apply.answers import form_facts
from resume_tailor.apply.answers import questions as q

FACTS = q.facts_for({
    "auto_accept_routine_acknowledgements": "Yes", "authorized_to_work": "Yes",
    "requires_sponsorship": "No", "requires_sponsorship_future": "No",
    "requires_sponsorship_any": "No", "willing_to_relocate": "Yes", "noncompete": "No",
})


def _plan(text, facts=FACTS, notices=None):
    items = [{"qid": "box", "label": text, "kind": "checkbox"},
             {"qid": "choice", "label": text, "kind": "choice", "options": ["Yes", "No"]}]
    plan = q.plan_for(items, facts, notices=notices)
    return plan["box"]["value"], plan["choice"]["value"]


@pytest.mark.parametrize(("text", "box", "choice"), [
    ("I confirm that I am legally authorized to work in the United States.", "Yes", "Yes"),
    # One negation flips the fact; the box stays unticked and the Yes/No says No.
    ("I am not authorized to work in the United States.", None, "No"),
    ("I do not require sponsorship now or in the future.", "Yes", "Yes"),
    ("I acknowledge the E-Verify notice and confirm that I am not subject to any "
     "non-compete agreement.", "Yes", "Yes"),
    # A qualifier ("without", "unless") is more than the fact says: left for the applicant.
    ("I confirm that I am authorized to work in the U.S. without sponsorship.", None, ""),
])
def test_statements_are_answered_as_worded(text, box, choice):
    assert _plan(text) == (box, choice)


def test_a_statement_with_no_profile_fact_is_left_for_the_applicant():
    facts = q.facts_for({"auto_accept_routine_acknowledgements": "Yes"})
    assert _plan("I am not authorized to work in the United States.", facts)[0] is None


def test_questions_are_answered_from_the_fact_as_before():
    assert _plan("Are you authorized to work in the US?")[1] == "Yes"
    assert _plan("Do you require sponsorship?")[1] == "No"


def test_a_notice_the_model_reads_as_a_claim_is_never_ticked_from_a_loose_key():
    """"Does not include relocation assistance" keys as willing_to_relocate; a willing
    applicant's Yes does not make the statement theirs."""
    text = "I understand that this internship does not include relocation assistance."
    assert form_facts.acknowledgement(text) == "unclear"
    box, _choice = _plan(text, notices=lambda pending: {
        form_facts.notice_key(*pair): "fact" for pair in pending
    })
    assert box is None
