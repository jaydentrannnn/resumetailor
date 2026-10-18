"""The notice detector reads every statement: only all-process notices are agreed to."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor.apply.answers import form_facts, questions
from resume_tailor.apply.forms import field_catalog, form_routes
from resume_tailor.apply.forms.field_types import FieldObservation

DEV = Path(__file__).resolve().parents[2] / "fixtures" / "notices" / "dev.json"
CASES = json.loads(DEV.read_text(encoding="utf-8"))["cases"]
#: Routine notices the wording alone cannot settle; the model tie-breaker reads them.
UNCLEAR_ROUTINE = {"syn-017"}

PRIVACY = (
    "Acme collects personal information such as your name, contact details, education, "
    "work experience and immigration status to evaluate your application. We may share it "
    "with service providers who help us recruit. Questions? Contact privacy@acme.example."
)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_dev_corpus(case):
    kind = form_facts.acknowledgement(case["text"])
    if case["label"] == "routine" and case["id"] not in UNCLEAR_ROUTINE:
        assert kind == "routine"
    elif case["label"] == "routine":
        assert kind == "unclear"
    else:
        assert kind != "routine"
    if case["label"] == "optional":
        assert kind == "optional"


@pytest.mark.parametrize(("text", "help_text", "expected"), [
    ("I agree", PRIVACY, "routine"),
    ("Privacy Notice", PRIVACY, "routine"),
    ("I agree to be bound by the terms and conditions.", "", "routine"),
    ("I consent to a criminal background check.", "", "routine"),
    ("I understand that I will be required to pass a drug screen.", "", "routine"),
    ("Do you agree to the terms and conditions above?", "", "routine"),
    # One statement about the applicant decides, wherever it sits.
    ("I have read the privacy notice and I confirm that I am a current student.", "", "fact"),
    ("I confirm I have never worked for Acme before.", "", "fact"),
    # A requirement or term of the role: never agreed to on its wording.
    ("I agree", "Candidates must be authorized to work in the U.S. without sponsorship.",
     "unclear"),
    ("I acknowledge that this role is on-site in Chicago.", "", "unclear"),
    ("I agree to work the hours listed above.", "", "unclear"),
    ("Confirm your mailing address", "", "unclear"),
    ("Certifications", "", "unclear"),
    ("Send me updates about new roles at Acme.", "", "optional"),
])
def test_statements(text, help_text, expected):
    assert form_facts.acknowledgement(text, help_text) == expected


def test_a_question_in_help_text_is_not_put_to_the_applicant():
    assert form_facts.acknowledgement("I acknowledge the E-Verify notice", "Questions?") == "routine"
    assert form_facts.acknowledgement("Are you comfortable with a background check?") == "routine"
    # Each question in a sentence is read on its own.
    assert form_facts.acknowledgement(
        "Have you read the policy, and are you a member of the Scholars Program?"
    ) == "fact"
    assert form_facts.acknowledgement(
        "Do you consent to the processing of your data and to our privacy policy?"
    ) == "routine"


UNCLEAR = "I understand that this internship does not include relocation assistance."


@pytest.mark.parametrize(("verdict", "value"), [("routine", "Yes"), ("fact", None)])
def test_the_plan_reads_an_unclear_notice_by_the_models_verdict(verdict, value):
    asked: list = []

    def notices(pending):
        asked.extend(pending)
        return {form_facts.notice_key(*pair): verdict for pair in pending}

    facts = questions.facts_for({"auto_accept_routine_acknowledgements": "Yes"})
    items = [{"qid": "box", "label": UNCLEAR, "kind": "checkbox"},
             {"qid": "other", "label": "I agree to the Privacy Policy", "kind": "checkbox"}]
    plan = questions.plan_for(items, facts, notices=notices)
    assert asked == [(UNCLEAR, "")]  # only the unclear one is read
    assert plan["box"]["value"] == value and plan["other"]["value"] == "Yes"
    # The verdict holds only for that plan.
    assert form_facts.acknowledgement(UNCLEAR) == "unclear"


@pytest.mark.parametrize("text", ["Confirm your password*", "Applicant Signature*",
                                  "Re-enter your email address to confirm"])
def test_a_fields_caption_is_never_put_to_the_model(text):
    assert form_facts.acknowledgement(text) == "unclear"
    assert not form_facts.needs_reading(text)
    with form_facts.notice_verdicts({form_facts.notice_key(text): "routine"}):
        assert form_facts.acknowledgement(text) == "unclear"


def test_no_notice_is_read_when_the_applicant_does_not_agree_to_notices():
    def notices(_pending):
        raise AssertionError("no model call")

    plan = questions.plan_for([{"qid": "box", "label": UNCLEAR, "kind": "checkbox"}],
                              questions.facts_for({}), notices=notices)
    assert plan["box"]["value"] is None


def _row(label, context=""):
    return {"label": label, "context": f"{label} {context}".strip(), "required": True,
            "enabled": True, "visible": True}


@pytest.mark.parametrize("label", [
    "I confirm that Acme may keep my information to consider me for future roles.",  # optional
    "Confirm your email*",  # unclear
    "I agree to the terms and acknowledge that this is a remote internship.",  # unclear
])
def test_consent_routes_tick_only_routine_notices(label):
    accepted, left = form_routes.consent_candidates([_row(label)], allow_routine=True)
    assert accepted == [] and left == [label]
    leftover = {"type": "checkbox", "required": True, "selector": "#box", "label": label}
    assert not form_routes.is_required_consent(leftover)


def test_the_consent_route_ticks_an_unclear_notice_only_on_a_routine_verdict():
    rows = [_row(UNCLEAR)]
    assert form_routes.unclear_notices(rows) == [(UNCLEAR, "")]
    key = form_facts.notice_key(UNCLEAR)
    accepted, _left = form_routes.consent_candidates(rows, allow_routine=True,
                                                    verdicts={key: "routine"})
    assert len(accepted) == 1
    accepted, left = form_routes.consent_candidates(rows, allow_routine=True,
                                                   verdicts={key: "fact"})
    assert accepted == [] and left == [UNCLEAR]


def test_the_consent_route_reads_the_description_apart_from_the_caption():
    accepted, _left = form_routes.consent_candidates([_row("I agree", PRIVACY)],
                                                    allow_routine=True)
    assert len(accepted) == 1


def test_an_unclear_notice_is_left_for_review_in_the_field_catalog():
    field = FieldObservation(snapshot_id="one", field_id="f", frame_id="main",
                             document_generation="1", label="Confirm your email",
                             control_kind="checkbox")
    assert field_catalog.classify(field) == ("manual_review", "notice_needs_review")
