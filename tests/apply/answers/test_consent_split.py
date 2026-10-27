"""Plain notices and binding agreements are separate choices, and facts an older profile
defaulted to "No" without asking start unanswered (audit #31, #32)."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import form_facts
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.answers import questions as q
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.forms import form_routes
from resume_tailor.apply.funnel import packet_fields, packet_profile_fields
from resume_tailor.content.data import Contact, MasterResume

PRIVACY = "I consent to the processing of my personal data for this application"
ARBITRATION = "I have read and agree to the Mutual Arbitration Agreement"
ACCURACY = "I certify that the information in my application is true and complete"
SIGNATURE = "Electronic signature (type your full name)"


def _facts(**profile):
    resume = MasterResume(contact=Contact(name="Test Applicant", email="test@example.test"))
    return q.facts_for(packet_fields.build_fields(ApplicantProfile(**profile), resume))


def _answer(text, facts, kind="choice", options=("Yes", "No")):
    question = q.Question(text, kind=kind, options=options)
    match = q.classify(question)
    return match.key if match else None, q.answers(match, question, facts)


@pytest.mark.parametrize(("text", "binding"), [
    (PRIVACY, False),
    ("I acknowledge the EEO statement", False),
    ("I authorize a background check", False),
    (ARBITRATION, True),
    (ACCURACY, True),
    ("I agree to the Terms and Conditions", True),
    (SIGNATURE, True),
])
def test_agreements_are_told_apart_from_notices(text, binding):
    assert form_facts.agreement(text) is binding


def test_notices_alone_leave_agreements_for_the_applicant():
    facts = _facts()  # the defaults: notices on, agreements off
    assert _answer(PRIVACY, facts) == (form_facts.ACKNOWLEDGEMENT, ["Yes"])
    assert _answer(ARBITRATION, facts) == (form_facts.ACKNOWLEDGEMENT, [])
    assert _answer(ACCURACY, facts) == (form_facts.ACKNOWLEDGEMENT, [])


def test_agreements_alone_leave_plain_notices_for_the_applicant():
    facts = _facts(auto_accept_notices=False, auto_accept_agreements=True)
    assert _answer(PRIVACY, facts) == (form_facts.ACKNOWLEDGEMENT, [])
    assert _answer(ARBITRATION, facts) == (form_facts.ACKNOWLEDGEMENT, ["Yes"])


def test_a_typed_signature_needs_agreements():
    key, answers = _answer(SIGNATURE, _facts(first_name="Test", last_name="Applicant"), kind="text",
                           options=())
    assert key == form_facts.TYPED_CONSENT and answers == []
    _key, signed = _answer(SIGNATURE, _facts(first_name="Test", last_name="Applicant",
                                             auto_accept_agreements=True), kind="text", options=())
    assert signed == ["Test Applicant"]


def _box(label):
    return {"label": label, "context": label, "required": True, "enabled": True, "visible": True}


def test_workday_consent_boxes_follow_each_choice():
    rows = [_box(PRIVACY), _box(ARBITRATION)]
    accepted, left = form_routes.consent_candidates(rows, consent=form_facts.Consent(True, False))
    assert [row["label"] for row in accepted] == [PRIVACY] and left == [ARBITRATION]
    accepted, left = form_routes.consent_candidates(rows)
    assert accepted == [] and left == [PRIVACY, ARBITRATION]


@pytest.mark.parametrize(("legacy", "notices"), [(True, True), (False, False)])
def test_the_old_single_switch_becomes_the_notices_choice(legacy, notices):
    profile = ApplicantProfile.model_validate({"auto_accept_routine_acknowledgements": legacy})
    assert (profile.auto_accept_notices, profile.auto_accept_agreements) == (notices, False)


def test_a_missing_agreement_is_reported_under_its_own_switch():
    blank = [{"key": "routine_acknowledgement", "label": ARBITRATION, "required": True},
             {"key": "routine_acknowledgement", "label": PRIVACY, "required": True}]
    keys = {item["key"] for item in packet_profile_fields.missing_profile(blank, set())}
    assert keys == {"auto_accept_agreements", "auto_accept_notices"}


# -- #31: no guessed "No" ------------------------------------------------------------------


def test_unanswered_government_and_conflict_questions_are_left_blank():
    fields = packet_fields.build_fields(
        ApplicantProfile(), MasterResume(contact=Contact(name="A B", email="a@example.test"))
    )
    assert "government_employee" not in fields and "conflict_of_interest" not in fields
    answered = packet_fields.build_fields(
        ApplicantProfile(government_employee=False, conflict_of_interest=True),
        MasterResume(contact=Contact(name="A B", email="a@example.test")),
    )
    assert answered["government_employee"] == "No" and answered["conflict_of_interest"] == "Yes"


@pytest.fixture
def profile_file(tmp_path, monkeypatch):
    path = tmp_path / "applicant_profile.json"
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", path)
    return path


def test_an_older_profiles_default_no_becomes_unanswered_once(profile_file):
    profile_file.write_text(json.dumps({
        "first_name": "Test", "government_employee": False, "conflict_of_interest": True,
    }), encoding="utf-8")
    profile, _seeded = profile_mod.load_profile()
    assert profile.government_employee is None and profile.conflict_of_interest is True
    stored = json.loads(profile_file.read_text(encoding="utf-8"))
    assert stored["answers_version"] == profile_mod.ANSWERS_VERSION
    assert list(profile_file.parent.glob("*.bak.json"))  # the old file is kept
    # A "No" the applicant confirms afterwards stays.
    profile_mod.save_profile(profile.model_copy(update={"government_employee": False}))
    assert profile_mod.load_profile()[0].government_employee is False
