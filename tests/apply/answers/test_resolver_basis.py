"""The resolver applies a model answer only when the basis it cites supports it."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from resume_tailor.apply.answers import (
    hybrid_resolver,
    page_blockers,
    resolver_basis,
    resolver_types,
    widget_actions,
)
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.funnel.packet_models import Packet

YES_NO = ["Yes", "No"]


def _field(label: str, options=YES_NO, kind: str = "radiogroup") -> dict:
    return {"type": kind, "selector": "#q", "label": label, "options": list(options)}


def _action(value: str, kind: str, key: str = "", verb: str = "choose_radio"):
    return resolver_types.FieldAction(label="q", selector="#q", action=verb, value=value,
                                      basis_kind=kind, basis_key=key)


def _supported(action, field, *, profile=None, packet=None, skills=()):
    return resolver_basis.supported(action, field, profile=profile or {},
                                    packet_fields=packet or {}, skills=skills)


SPONSOR = "Will you require visa sponsorship to work in the U.S.?"


@pytest.mark.parametrize(("label", "action", "packet", "expected"), [
    (SPONSOR, _action("No", "packet", "requires_sponsorship"), {"requires_sponsorship": "No"}, True),
    # The profile's own name for it reads the same packet answer.
    (SPONSOR, _action("No", "profile", "requires_sponsorship_now"), {"requires_sponsorship": "No"}, True),
    # The option must say what the field says.
    (SPONSOR, _action("Yes", "packet", "requires_sponsorship"), {"requires_sponsorship": "No"}, False),
    # A field with no value supports nothing.
    (SPONSOR, _action("No", "packet", "requires_sponsorship"), {}, False),
    # A driver's license says nothing about a nursing license.
    ("Do you hold an active RN nursing license?", _action("Yes", "packet", "drivers_license"),
     {"drivers_license": "Yes"}, False),
    # "Now" does not answer "now or in the future".
    ("Will you now or in the future require sponsorship?",
     _action("No", "packet", "requires_sponsorship"), {"requires_sponsorship": "No"}, False),
    ("Gender", _action("I decline to self-identify", "profile", "eeo.gender"),
     {"gender": "decline"}, True),
    ("Do you have outside employment?", _action("No", "unknown"), {}, False),
])
def test_a_field_supports_only_its_own_question(label, action, packet, expected):
    options = ["Male", "Female", "I decline to self-identify"] if label == "Gender" else YES_NO
    assert _supported(action, _field(label, options), packet=packet) is expected


@pytest.mark.parametrize(("option", "expected"), [
    ("3.75 - 4.0", True), ("3.5+", True), ("Above 3.5", True), ("3.0 - 3.49", False),
    ("Below 3.0", False),
])
def test_a_gpa_falls_in_the_range_an_option_names(option, expected):
    field = _field("What is your overall GPA?", ["Below 3.0", "3.0 - 3.49", option])
    action = _action(option, "packet", "gpa")
    assert _supported(action, field, packet={"gpa": "3.8"}) is expected


def test_only_a_fluent_language_answers_a_fluency_question():
    profile = {"languages": [{"language": "Spanish", "fluent": True},
                             {"language": "French", "fluent": False},
                             {"language": "Tagalog", "levels": {"Overall": "Native"}}]}
    field = _field("In which language(s) are you fluent other than English?",
                   ["Spanish", "French", "German", "Tagalog"], kind="combobox")
    assert _supported(_action("Spanish", "profile", "languages"), field, profile=profile)
    assert _supported(_action("Tagalog", "profile", "languages"), field, profile=profile)
    assert not _supported(_action("French", "profile", "languages"), field, profile=profile)
    assert not _supported(_action("Spanish", "profile", "languages"),
                          _field("Writing*", ["Spanish", "French"]), profile=profile)


@pytest.mark.parametrize(("label", "expected"), [
    ("All offers are contingent on a background check. Do you acknowledge?", True),
    ("I acknowledge that this role is on-site in Chicago.", False),
])
def test_the_standing_agreement_covers_only_routine_notices(label, expected):
    action = _action("Yes", "profile", "auto_accept_routine_acknowledgements")
    profile = {"auto_accept_routine_acknowledgements": True}
    assert _supported(action, _field(label), profile=profile) is expected
    assert not _supported(action, _field(label), profile={})


@pytest.mark.parametrize(("hispanic", "expected"), [("No", True), ("", False), ("Yes", False)])
def test_a_race_option_naming_hispanic_origin_needs_that_field_too(hispanic, expected):
    option = "Asian (Not Hispanic or Latino)"
    field = _field("Ethnicity", ["White (Not Hispanic or Latino)", option, "Hispanic or Latino"])
    packet = {"race": "Asian", "hispanic_latino": hispanic}
    assert _supported(_action(option, "packet", "race"), field, packet=packet) is expected


def test_a_related_field_still_has_to_say_the_option():
    field = _field("U.S. WORK AUTHORIZATION*")
    assert _supported(_action("Yes", "profile", "authorized_to_work"), field,
                      profile={"authorized_to_work": True})
    assert not _supported(_action("No", "profile", "authorized_to_work"), field,
                          profile={"authorized_to_work": True})


def test_the_year_in_school_is_the_class_year_not_the_school():
    from resume_tailor.apply.answers import questions

    for text in ("What year are you currently in school?*", "Current year in college"):
        match = questions.classify(questions.Question(text, kind="choice",
                                                      options=("Junior", "Senior")))
        assert match is not None and match.key == "class_year"
    match = questions.classify(questions.Question("What year did you start in college?",
                                                  kind="text"))
    assert match is None or match.key != "class_year"


def test_a_saved_answer_supports_only_its_own_question():
    profile = {"custom_answers": {"Do you have outside employment?": "No"}}
    action = _action("No", "profile", "custom_answers.Do you have outside employment?")
    assert _supported(action, _field("Do you have outside employment?"), profile=profile)
    assert not _supported(action, _field("Do you serve on a board?"), profile=profile)


@pytest.mark.parametrize(("label", "key", "value", "expected"), [
    ("Do you have experience with Python?", "Python", "Yes", True),
    ("Do you have experience with Python?", "Python", "No", False),
    ("Do you have experience with Java?", "Python", "Yes", False),  # not the skill asked
    ("Do you have experience with Rust?", "Rust", "Yes", False),  # not on the resume
    ("Do you have 3+ years of Python experience?", "Python", "Yes", False),  # how long
    ("Are you an expert in Python?", "Python", "Yes", False),  # how well
    ("Have you used Python?*", "Python", "Yes", True),
    ("Experience with Python", "Python", "Yes", True),
    # Only a plain ask about that one skill: not negated, not with another, not a setting.
    ("Have you never used Python?", "Python", "Yes", False),
    ("Do you lack Python experience?", "Python", "Yes", False),
    ("Have you used both Python and Rust?", "Python", "Yes", False),
    ("Have you used Python or Rust?", "Python", "Yes", False),
    ("Do you have experience with Python in a production environment?", "Python", "Yes", False),
])
def test_the_resume_supports_only_a_skill_it_lists(label, key, value, expected):
    action = _action(value, "resume", key)
    assert _supported(action, _field(label), skills=["Python", "SQL"]) is expected


@pytest.mark.parametrize(("label", "key", "value", "expected"), [
    ("Are you legally authorized to work in the US?", "authorized_to_work", "Yes", True),
    # "Not" turns the fact's answer around; the check cannot tell which way round it is.
    ("Are you not legally authorized to work in the US?", "authorized_to_work", "Yes", False),
    ("Are you legally authorized to work in the US? If not, please explain.",
     "authorized_to_work", "Yes", True),
    # One fact for two asks.
    ("Do you have a valid driver's license and a car?", "drivers_license", "Yes", False),
    ("Are you authorized to work in the US and do you live in Texas?", "authorized_to_work",
     "Yes", False),
])
def test_a_fact_answers_a_question_only_as_worded(label, key, value, expected):
    profile = {"authorized_to_work": True}
    action = _action(value, "profile", key)
    packet = {"drivers_license": "Yes"}
    assert _supported(action, _field(label), profile=profile, packet=packet) is expected


OFFICES = ["San Francisco", "New York", "Austin", "Other"]
VETERAN = ["I am a protected veteran", "I am not a protected veteran", "I decline to self-identify"]


@pytest.mark.parametrize(("label", "options", "key", "value", "expected"), [
    # A note beside the instruction does not change which option is right...
    ("Choose your preferred office location. Placement is not guaranteed.", OFFICES,
     "location_preference", "San Francisco", True),
    ("If you have a preferred office location, please select below. Please note that this "
     "is not a guarantee of placement should a position be offered.*", OFFICES,
     "location_preference", "San Francisco", True),
    ("Select your preferred location. If you do not see your city, select Other.", OFFICES,
     "location_preference", "San Francisco", True),
    ('Please select your veteran status. Choose "I am not a protected veteran" if none of '
     "the categories apply.", VETERAN, "veteran_status", "I am not a protected veteran", True),
    # ...a negation in it does, and so does a second requirement.
    ("Choose the office locations where you cannot work.", OFFICES, "location_preference",
     "San Francisco", False),
    ("Which of these office locations would you be unwilling to relocate to?", OFFICES,
     "location_preference", "San Francisco", False),
    ("Select your preferred location. Do not select a location you cannot commute to.",
     OFFICES, "location_preference", "San Francisco", False),
    ("Which office location do you prefer, and do you have reliable transportation to it?",
     OFFICES, "location_preference", "San Francisco", False),
])
def test_a_pick_stands_for_what_the_question_says_to_pick(label, options, key, value, expected):
    action = _action(value, "packet", key, verb="select_combobox")
    field = _field(label, options, kind="combobox")
    assert _supported(action, field, packet={key: value}) is expected


def test_the_applicants_own_saved_answer_needs_no_rewording():
    label = "Have you never been employed by Acme?"
    profile = {"custom_answers": {label: "Yes"}}
    action = _action("Yes", "profile", f"custom_answers.{label}")
    assert _supported(action, _field(label), profile=profile)


def test_only_listed_skills_are_ticked():
    field = _field("Which of these do you use?", ["Python", "Java", "Go"], kind="checkboxgroup")
    listed = _action("Python | Go", "resume", "Python", verb="check_options")
    unlisted = _action("Python | Java", "resume", "Python", verb="check_options")
    assert _supported(listed, field, skills=["Python", "Go"])
    assert not _supported(unlisted, field, skills=["Python", "Go"])


@pytest.mark.parametrize(("label", "options", "expected"), [
    ("How did you hear about us?", ["LinkedIn", "Job Board", "Referral"], True),
    ("Were you referred by a current employee?", YES_NO, False),
    ("How did you hear about this role? Were you referred?", YES_NO, False),
    ("Would you like to be considered for other positions?", YES_NO, False),
])
def test_no_effect_is_only_a_source_question(label, options, expected):
    action = _action(options[0], "no_effect")
    assert _supported(action, _field(label, options)) is expected


# -- in the resolver --------------------------------------------------------------------


class _FakeClient:
    timeout = 60.0

    def __init__(self, replies: list, calls: list) -> None:
        def parse(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(parsed_output=replies.pop(0))

        self.messages = SimpleNamespace(parse=parse)


@pytest.fixture
def page(monkeypatch):
    """A page of scripted blockers; records executed actions and saved choices."""
    state = SimpleNamespace(unresolved=[], replies=[], calls=[], executed=[], saved=[],
                            sticks=True, in_flight_seen=[])
    client = _FakeClient(state.replies, state.calls)
    monkeypatch.setattr(hybrid_resolver.llm, "client_for", lambda _purpose: client)
    monkeypatch.setattr(page_blockers, "extract_page_blockers", lambda _page: {
        "errors": [], "unresolved": [dict(f) for f in state.unresolved],
        "advance_disabled": False,
    })

    def execute(_page, action):
        state.executed.append(action.selector)
        state.in_flight_seen.append(bool(hybrid_resolver._IN_FLIGHT))  # noqa: SLF001
        if state.sticks:
            state.unresolved = [f for f in state.unresolved if f["selector"] != action.selector]
        return state.sticks

    monkeypatch.setattr(widget_actions, "execute_action", execute)
    monkeypatch.setattr(hybrid_resolver, "_write_choices", state.saved.append)
    state.page = MagicMock()
    return state


def _resolve(state, fields: dict, skills=()):
    return hybrid_resolver.resolve_step_blockers(
        state.page, Packet.model_construct(fields=fields, master_skills=list(skills)),
        ApplicantProfile(), ledger=resolver_types.StepLedger(), max_retries=1,
        on_progress=state.messages.append,
    )


def _reply(*actions):
    return resolver_types.StepResolution(actions=list(actions))


def _pick(selector: str, value: str, kind: str, key: str = ""):
    return resolver_types.FieldAction(label=selector, selector=selector, action="choose_radio",
                                      value=value, basis_kind=kind, basis_key=key)


def test_an_unsupported_answer_is_left_for_the_applicant(page):
    page.unresolved = [{**_field(SPONSOR), "selector": "#sponsor"},
                       {**_field("Do you serve on a board?"), "selector": "#board"}]
    page.replies.append(_reply(_pick("#sponsor", "No", "packet", "requires_sponsorship"),
                               _pick("#board", "No", "profile", "relatives_at_company")))
    page.messages = []
    _resolve(page, {"requires_sponsorship": "No"})
    assert page.executed == ["#sponsor"]
    assert any("leaving them for you: Do you serve on a board?" in m for m in page.messages)
    assert len(page.saved) == 1 and len(page.saved[0]) == 1  # only the supported pick
    # The model saw the resume's skills it may cite.
    assert "<resume_skills>" in page.calls[0]["messages"][0]["content"]


def test_a_pick_is_saved_only_once_it_is_on_the_page(page):
    page.unresolved = [{**_field(SPONSOR), "selector": "#sponsor"}]
    page.replies.append(_reply(_pick("#sponsor", "No", "packet", "requires_sponsorship")))
    page.messages = []
    page.sticks = False
    _resolve(page, {"requires_sponsorship": "No"})
    assert page.executed == ["#sponsor", "#sponsor"]  # tried twice, never stuck
    assert page.saved == []
    assert hybrid_resolver._IN_FLIGHT == {}  # noqa: SLF001 - released all the same


def test_other_tabs_wait_until_the_pick_is_saved(page):
    page.unresolved = [{**_field(SPONSOR), "selector": "#sponsor"}]
    page.replies.append(_reply(_pick("#sponsor", "No", "packet", "requires_sponsorship")))
    page.messages = []
    _resolve(page, {"requires_sponsorship": "No"})
    assert page.in_flight_seen == [True]  # still in flight while it was applied
    assert len(page.saved) == 1
    assert hybrid_resolver._IN_FLIGHT == {}  # noqa: SLF001
