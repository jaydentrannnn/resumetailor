"""Unit and mock tests for Hybrid Form Filling and Workday Auth."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import (
    hybrid_resolver,
    page_blockers,
    resolver_types,
    widget_actions,
)
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.ats import workday_auth
from resume_tailor.apply.funnel.packet_models import Packet
from resume_tailor.infra import llm


def test_phone_code_choice_requires_explicit_region():
    options = ["United States +1", "Canada +1", "American Samoa +1", "United Kingdom +44"]
    assert widget_actions._phone_option(options, "+1", "") is None  # noqa: SLF001
    assert widget_actions._phone_option(options, "+1", "United States") == "United States +1"  # noqa: SLF001
    assert widget_actions._phone_option(options, "+1", "Canada") == "Canada +1"  # noqa: SLF001
    assert widget_actions._phone_option(options, "+1", "United Kingdom") is None  # noqa: SLF001


def test_declared_greenhouse_option_aliases_are_exact_and_unambiguous():
    match = widget_actions._option_match  # noqa: SLF001
    assert match(["University of California, Irvine", "Other"], "University of California - Irvine", key="school") == "University of California, Irvine"
    assert match(["Bachelor's Degree", "Master's Degree"], "Bachelors", key="degree_level") == "Bachelor's Degree"
    assert match(["South Asian", "Asian"], "Asian", key="race") == "Asian"
    assert match(["Southeast Asian", "Asian"], "Southeast Asian", key="race") == "Southeast Asian"
    assert match(["Asian", "ASIAN"], "Asian", key="race") is None
    assert match(["Not applicable"], "No", key="hispanic_latino") is None


def test_greenhouse_degree_search_uses_bachelor_root(monkeypatch):
    page = MagicMock()
    trigger = page.locator.return_value.first
    trigger.count.return_value = 1
    trigger.is_visible.return_value = True
    trigger.evaluate.return_value = "input"
    option = MagicMock()
    option.is_visible.return_value = True
    option.inner_text.return_value = "Bachelor's Degree"
    monkeypatch.setattr(
        widget_actions, "_selected_combobox_text", MagicMock(side_effect=["", "Bachelor's Degree"])
    )
    monkeypatch.setattr(
        widget_actions,
        "_menu_choices",
        lambda _page, _trigger: [option] if trigger.fill.call_args and trigger.fill.call_args.args[0] == "bachelor" else [],
    )

    assert widget_actions._select_combobox_option(page, "#degree", "Bachelors", key="degree_level")  # noqa: SLF001
    trigger.fill.assert_called_once_with("bachelor")
    option.click.assert_called_once()


def test_greenhouse_phone_code_verifies_selected_country_option(monkeypatch):
    page = MagicMock()
    trigger = page.locator.return_value.first
    trigger.count.return_value = 1
    trigger.is_visible.return_value = True
    trigger.evaluate.return_value = "input"
    us = MagicMock()
    us.is_visible.return_value = True
    us.inner_text.return_value = "United States +1"
    us.get_attribute.side_effect = ["false", "true"]
    canada = MagicMock()
    canada.is_visible.return_value = True
    canada.inner_text.return_value = "Canada +1"
    monkeypatch.setattr(widget_actions, "_selected_combobox_text", lambda _trigger: "+1")
    monkeypatch.setattr(widget_actions, "_menu_choices", lambda _page, _trigger: [us, canada])

    assert widget_actions._select_combobox_option(  # noqa: SLF001
        page, "#country", "+1", key="phone_country_code", phone_region="United States",
    )
    us.click.assert_called_once()
    canada.click.assert_not_called()


def test_workday_password_compliance():
    """Generated passwords meet Workday complexity without a shared constant."""
    pwd = workday_auth.generate_compliant_password()
    assert len(pwd) >= 8
    assert any(c.isupper() for c in pwd)
    assert any(c.islower() for c in pwd)
    assert any(c.isdigit() for c in pwd)
    assert any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in pwd)
    assert pwd != workday_auth.generate_compliant_password()


def test_workday_vault_storage(tmp_path, monkeypatch):
    """Ensure tenant credentials load, save, and persist across calls, honoring profile overrides."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    profile = ApplicantProfile(email="test@example.com")
    url = "https://nvidia.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/123"

    email1, pwd1 = workday_auth.get_tenant_credentials(url, profile)
    assert email1 == "test@example.com"
    assert len(pwd1) >= 8

    # Second call returns identical saved credentials
    email2, pwd2 = workday_auth.get_tenant_credentials(url, profile)
    assert email1 == email2
    assert pwd1 == pwd2

    # Override with custom workday_email and workday_password
    override_profile = ApplicantProfile(
        email="general@example.com",
        workday_email="workday_specific@example.com",
        workday_password="@CustomPassword99",
    )
    url_apple = "https://apple.myworkdayjobs.com/Apple_Careers"
    email_custom, pwd_custom = workday_auth.get_tenant_credentials(url_apple, override_profile)
    assert email_custom == "workday_specific@example.com"
    assert pwd_custom == "@CustomPassword99"
    email2, pwd2 = workday_auth.get_tenant_credentials(url, profile)
    assert email1 == email2
    assert pwd1 == pwd2


def test_workday_detect_auth_state_otp():
    """Verify detection of verification code / OTP input screen."""
    page = MagicMock()
    otp_loc = MagicMock()
    otp_loc.count.return_value = 1
    otp_loc.is_visible.return_value = True
    otp_loc.first = otp_loc

    def _locator(sel):
        if "verificationCode" in sel:
            return otp_loc
        empty = MagicMock()
        empty.count.return_value = 0
        empty.is_visible.return_value = False
        empty.first = empty
        return empty

    page.locator = _locator
    state = workday_auth.detect_auth_state(page)
    assert state == "otp"


def test_workday_detect_auth_state_create_account():
    """Verify detection of Create Account screen."""
    page = MagicMock()
    ca_loc = MagicMock()
    ca_loc.count.return_value = 1
    ca_loc.is_visible.return_value = True
    ca_loc.first = ca_loc

    def _locator(sel):
        if "verifyPassword" in sel:
            return ca_loc
        empty = MagicMock()
        empty.count.return_value = 0
        empty.is_visible.return_value = False
        empty.first = empty
        return empty

    page.locator = _locator
    state = workday_auth.detect_auth_state(page)
    assert state == "create_account"


def test_hybrid_resolver_action_execution():
    """The resolver can fill answers but cannot request arbitrary clicks."""
    page = MagicMock()
    mock_el = MagicMock()
    mock_el.count.return_value = 1
    mock_el.is_visible.return_value = True
    page.locator.return_value.first = mock_el

    action_fill = resolver_types.FieldAction(
        selector="#custom-input",
        label="Custom Field",
        action="fill_text",
        value="My Answer",
    )
    assert widget_actions.execute_action(page, action_fill)
    assert mock_el.fill.called

    with pytest.raises(ValueError):
        resolver_types.FieldAction(
            selector="#custom-btn",
            label="Custom Button",
            action="click_element",
            value="",
        )


# -- a stuck field is retried alone, not the whole page ---------------------------------


class _FakeMessages:
    def __init__(self, replies: list, calls: list) -> None:
        self.replies = replies
        self.calls = calls

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.replies.pop(0))


class _FakeClient:
    timeout = 60.0

    def __init__(self, replies: list, calls: list) -> None:
        self.messages = _FakeMessages(replies, calls)


def _field(selector: str, label: str, **extra) -> dict:
    return {"type": "combobox", "selector": selector, "label": label, "current": "Select One", **extra}


@pytest.fixture
def resolver_page(monkeypatch):
    """A page whose blockers are scripted per scan; records which dropdowns were opened."""
    state = SimpleNamespace(unresolved=[], opened=[], replies=[], calls=[])
    shared = _FakeClient(state.replies, state.calls)  # one queue across every call
    monkeypatch.setattr(hybrid_resolver.llm, "client_for", lambda _purpose: shared)
    monkeypatch.setattr(
        page_blockers, "extract_page_blockers",
        lambda _page: {"errors": [], "unresolved": [dict(f) for f in state.unresolved], "advance_disabled": False},
    )
    monkeypatch.setattr(widget_actions, "_menu_choices", lambda _page, trigger: [])
    monkeypatch.setattr(widget_actions, "_is_upload_widget", lambda _locator: False)

    def execute(_page, action):
        state.unresolved = [f for f in state.unresolved if f["selector"] != action.selector]
        return True

    monkeypatch.setattr(widget_actions, "execute_action", execute)
    page = MagicMock()
    page.locator.side_effect = lambda selector: SimpleNamespace(first=SimpleNamespace(
        click=lambda timeout=None: state.opened.append(selector),
        press=lambda key: None,
    ))
    state.page = page
    return state


def _resolve(state, ledger, messages=None, **kwargs):
    from resume_tailor.apply.funnel.packet_models import Packet

    return hybrid_resolver.resolve_step_blockers(
        state.page, Packet.model_construct(fields={}), ApplicantProfile(),
        ledger=ledger, max_retries=1, on_progress=(messages if messages is not None else []).append, **kwargs,
    )


def test_transient_model_failure_is_recorded_for_review(resolver_page, monkeypatch):
    state = resolver_page
    state.unresolved = [_field("#state", "State"), _field("#vet", "Veteran status")]

    class FailingMessages:
        def parse(self, **_kwargs):
            raise llm.LLMError("https://example.test returned HTTP 503 for 'test': high demand")

    monkeypatch.setattr(hybrid_resolver.llm, "client_for", lambda _purpose: SimpleNamespace(
        messages=FailingMessages(), timeout=60.0,
    ))
    ledger = resolver_types.StepLedger()
    messages: list[str] = []

    assert _resolve(state, ledger, messages) is False
    assert ledger.model_unavailable is True
    assert "[hybrid-resolver] Autofill model unavailable (HTTP 503); leaving 2 question(s) for review" in messages


def test_a_second_pass_on_the_step_touches_only_the_new_gap(resolver_page):
    state = resolver_page
    state.unresolved = [_field("#state", "State"), _field("#vet", "Veteran status")]
    # The model answers State; Veteran status it cannot answer.
    state.replies.append(resolver_types.StepResolution(actions=[resolver_types.FieldAction(
        label="State", selector="#state", action="select_combobox", value="California")]))
    # The observed option list must contain the answer for it to be executed.
    ledger = resolver_types.StepLedger(options={"#state": ["California", "Texas"]})
    _resolve(state, ledger)
    assert len(state.calls) == 1
    assert state.opened == ["#vet"]  # State's options were already known

    # Same step, the field the model skipped: sent once more, alone; nothing is reopened.
    state.replies.append(resolver_types.StepResolution(actions=[]))
    _resolve(state, ledger)
    assert len(state.calls) == 2
    sent = state.calls[1]["messages"][0]["content"]
    assert "#vet" in sent and "#state" not in sent
    assert state.opened == ["#vet"]

    # Skipped twice: it is the applicant's; the model is not asked a third time.
    messages: list[str] = []
    _resolve(state, ledger, messages)
    assert len(state.calls) == 2
    assert any("still need input" in m for m in messages)

    # A field revealed later on the same step is the only thing sent.
    state.unresolved.append(_field("#reloc", "Willing to relocate"))
    state.replies.append(resolver_types.StepResolution(actions=[]))
    messages = []
    _resolve(state, ledger, messages)
    assert len(state.calls) == 3
    sent = state.calls[2]["messages"][0]["content"]
    assert "#reloc" in sent and "#vet" not in sent and "#state" not in sent
    assert any("retrying 1 unfilled field(s): Willing to relocate" in m for m in messages)


def _yes_no(selector: str, label: str) -> dict:
    return _field(selector, label)


def _choose(selector: str, label: str, value: str) -> resolver_types.FieldAction:
    return resolver_types.FieldAction(
        label=label, selector=selector, action="select_combobox", value=value
    )


def test_a_question_the_model_skips_is_asked_again_in_the_same_call(resolver_page):
    """American Century (2026-09): of 12 questions the model answered 10; the page showed
    no error yet, so the step was called cleared and two stayed blank on that tab only."""
    state = resolver_page
    board = "Are you a board member of any outside organization?"
    state.unresolved = [_yes_no("#ref", "Were you referred?"), _yes_no("#board", board)]
    state.replies.append(
        resolver_types.StepResolution(actions=[_choose("#ref", "Were you referred?", "No")])
    )
    state.replies.append(resolver_types.StepResolution(actions=[_choose("#board", board, "No")]))
    ledger = resolver_types.StepLedger(options={"#ref": ["Yes", "No"], "#board": ["Yes", "No"]})

    messages: list[str] = []
    assert hybrid_resolver.resolve_step_blockers(
        state.page, Packet.model_construct(fields={}), ApplicantProfile(),
        ledger=ledger, on_progress=messages.append,
    )
    assert len(state.calls) == 2
    retry = state.calls[1]["messages"][0]["content"]
    assert "#board" in retry and "#ref" not in retry
    assert state.unresolved == []


def test_the_same_question_gets_the_same_answer_on_another_tab(resolver_page):
    """A second posting (another tab, or a later run) with the same question and options
    reuses the first answer instead of asking the model again."""
    state = resolver_page
    question = "Have you ever applied for registration with any regulatory authority?"
    state.unresolved = [_yes_no("#reg", question)]
    state.replies.append(resolver_types.StepResolution(actions=[_choose("#reg", question, "No")]))
    _resolve(state, resolver_types.StepLedger(options={"#reg": ["Yes", "No"]}))
    assert len(state.calls) == 1

    executed: list[str] = []
    state.unresolved = [_yes_no("#reg-2", question)]
    original = widget_actions.execute_action

    def record(page, action):
        executed.append(f"{action.selector}={action.value}")
        return original(page, action)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(widget_actions, "execute_action", record)
        messages: list[str] = []
        _resolve(state, resolver_types.StepLedger(options={"#reg-2": ["Yes", "No"]}), messages)
    assert len(state.calls) == 1  # no second model call
    assert executed == ["#reg-2=No"]
    assert any("reusing 1 earlier answer" in m for m in messages)


def test_a_remembered_answer_needs_the_same_options(resolver_page):
    state = resolver_page
    question = "Do you hold a securities license?"
    state.unresolved = [_yes_no("#lic", question)]
    state.replies.append(resolver_types.StepResolution(actions=[_choose("#lic", question, "No")]))
    _resolve(state, resolver_types.StepLedger(options={"#lic": ["Yes", "No"]}))

    # Other options make it another question: the model is asked.
    state.unresolved = [_yes_no("#lic", question)]
    state.replies.append(
        resolver_types.StepResolution(actions=[_choose("#lic", question, "No, never")])
    )
    _resolve(state, resolver_types.StepLedger(options={"#lic": ["Yes, active", "No, never"]}))
    assert len(state.calls) == 2


def test_an_unknown_decision_is_final_and_never_remembered(resolver_page):
    """"unknown" is the model's answer, not an omission: the field is left for the
    applicant without a second call, and nothing is cached for the next posting."""
    state = resolver_page
    question = "Do you serve on a municipal retirement plan board?"
    state.unresolved = [_yes_no("#board", question)]
    state.replies.append(
        resolver_types.StepResolution(actions=[_choose("#board", question, "unknown")])
    )
    ledger = resolver_types.StepLedger(options={"#board": ["Yes", "No"]})
    messages: list[str] = []
    hybrid_resolver.resolve_step_blockers(
        state.page, Packet.model_construct(fields={}), ApplicantProfile(),
        ledger=ledger, on_progress=messages.append,
    )
    assert len(state.calls) == 1
    assert "#board" in ledger.asked and "#board" not in ledger.done
    assert any("does not answer 1 question(s)" in m for m in messages)
    assert hybrid_resolver._read_choices() == {}  # noqa: SLF001


def test_a_tab_waits_for_the_answer_another_tab_is_fetching(resolver_page):
    """Two tabs, one question: the second waits for the first tab's call and reuses it."""
    import threading

    state = resolver_page
    question = "Is any immediate family member employed by a competitor?"
    profile = ApplicantProfile()
    digest = hybrid_resolver.hashlib.sha256(
        hybrid_resolver.json.dumps(profile.model_dump(exclude={"workday_password", "workday_email"}, mode="json"),
                                   sort_keys=True).encode("utf-8"),
    ).hexdigest()
    field = {**_yes_no("#fam", question), "options": ["Yes", "No"]}
    key = hybrid_resolver._choice_key(field, digest)  # noqa: SLF001
    event = threading.Event()
    hybrid_resolver._IN_FLIGHT[key] = event  # noqa: SLF001 - "another tab" is asking it

    def other_tab_answers() -> None:
        hybrid_resolver._write_choices({key: {"action": "select_combobox", "value": "No", "label": question}})  # noqa: SLF001
        hybrid_resolver._IN_FLIGHT.pop(key, None)  # noqa: SLF001
        event.set()

    timer = threading.Timer(0.05, other_tab_answers)
    timer.start()
    try:
        state.unresolved = [_yes_no("#fam", question)]
        messages: list[str] = []
        assert hybrid_resolver.resolve_step_blockers(
            state.page,
            Packet.model_construct(fields={}),
            profile,
            ledger=resolver_types.StepLedger(options={"#fam": ["Yes", "No"]}),
            on_progress=messages.append,
        )
    finally:
        timer.join()
        hybrid_resolver._IN_FLIGHT.pop(key, None)  # noqa: SLF001
    assert state.calls == []  # this tab never asked the model
    assert any("reusing 1 earlier answer" in m for m in messages)


def test_an_answer_landing_during_the_cache_read_is_not_asked_again(resolver_page, monkeypatch):
    """The other tab writes its answer and leaves `_IN_FLIGHT` right after this tab's
    cache read missed (the Windows CI interleaving, 2026-10-05): reuse, never re-ask."""
    import threading

    state = resolver_page
    question = "Is any immediate family member employed by a competitor?"
    profile = ApplicantProfile()
    digest = hybrid_resolver.hashlib.sha256(
        hybrid_resolver.json.dumps(profile.model_dump(exclude={"workday_password", "workday_email"}, mode="json"),
                                   sort_keys=True).encode("utf-8"),
    ).hexdigest()
    field = {**_yes_no("#fam", question), "options": ["Yes", "No"]}
    key = hybrid_resolver._choice_key(field, digest)  # noqa: SLF001
    event = threading.Event()
    hybrid_resolver._IN_FLIGHT[key] = event  # noqa: SLF001
    real_remembered = hybrid_resolver._remembered  # noqa: SLF001

    def remembered_then_other_tab_finishes(keys, observed):
        stale = real_remembered(keys, observed)
        if not event.is_set():
            hybrid_resolver._write_choices({key: {"action": "select_combobox", "value": "No", "label": question}})  # noqa: SLF001
            with hybrid_resolver._CHOICES_LOCK:  # noqa: SLF001
                hybrid_resolver._IN_FLIGHT.pop(key, None)  # noqa: SLF001
                event.set()
        return stale

    monkeypatch.setattr(hybrid_resolver, "_remembered", remembered_then_other_tab_finishes)
    try:
        state.unresolved = [_yes_no("#fam", question)]
        messages: list[str] = []
        assert hybrid_resolver.resolve_step_blockers(
            state.page,
            Packet.model_construct(fields={}),
            profile,
            ledger=resolver_types.StepLedger(options={"#fam": ["Yes", "No"]}),
            on_progress=messages.append,
        )
    finally:
        hybrid_resolver._IN_FLIGHT.pop(key, None)  # noqa: SLF001
    assert state.calls == []
    assert any("reusing 1 earlier answer" in m for m in messages)


def test_unrelated_questions_do_not_wait_on_another_tab(resolver_page):
    state = resolver_page
    hybrid_resolver._IN_FLIGHT["someone-elses-question"] = hybrid_resolver.threading.Event()  # noqa: SLF001
    try:
        state.unresolved = [_yes_no("#q", "Do you have outside employment?")]
        state.replies.append(
            resolver_types.StepResolution(actions=[_choose("#q", "Outside", "No")])
        )
        started = hybrid_resolver.time.monotonic()
        assert _resolve(state, resolver_types.StepLedger(options={"#q": ["Yes", "No"]}))
        assert hybrid_resolver.time.monotonic() - started < 5
    finally:
        hybrid_resolver._IN_FLIGHT.pop("someone-elses-question", None)  # noqa: SLF001
    assert len(state.calls) == 1
    assert hybrid_resolver._IN_FLIGHT == {}  # noqa: SLF001 - its own key was released


def test_a_choice_that_did_not_stick_is_retried_once(resolver_page, monkeypatch):
    state = resolver_page
    state.unresolved = [_yes_no("#q", "Do you have outside employment?")]
    state.replies.append(resolver_types.StepResolution(actions=[_choose("#q", "Outside", "No")]))
    attempts: list[str] = []

    def flaky(_page, action):
        attempts.append(action.selector)
        if len(attempts) == 1:
            return False  # the list was still opening
        state.unresolved = []
        return True

    monkeypatch.setattr(widget_actions, "execute_action", flaky)
    ledger = resolver_types.StepLedger(options={"#q": ["Yes", "No"]})
    assert _resolve(state, ledger)
    assert attempts == ["#q", "#q"]
    assert "#q" in ledger.done


def test_after_a_rejected_advance_only_invalid_fields_are_retried(resolver_page):
    state = resolver_page
    state.unresolved = [_field("#a", "Optional pick"), _field("#b", "Required pick", invalid=True)]
    state.replies.append(resolver_types.StepResolution(actions=[]))
    _resolve(state, resolver_types.StepLedger(), only_invalid=True)
    sent = state.calls[0]["messages"][0]["content"]
    assert "#b" in sent and "#a" not in sent


def test_a_question_revealed_by_the_models_answer_is_asked_next(resolver_page, monkeypatch):
    """Workday shows no error for a follow-up until Save and Continue: the resolver must
    look for it after its own answer instead of stopping when the page reads clean."""
    state = resolver_page
    state.unresolved = [_field("#permitted", "Legally permitted to work?"), _field("#other", "Optional pick")]
    proof = _field("#proof", "If hired, can you provide proof of eligibility?")

    def execute(_page, action):
        state.unresolved = [f for f in state.unresolved if f["selector"] != action.selector]
        if action.selector == "#permitted":
            state.unresolved.append(dict(proof))
        return True

    monkeypatch.setattr(widget_actions, "execute_action", execute)
    ledger = resolver_types.StepLedger(options={
        "#permitted": ["Yes", "No"], "#proof": ["Yes", "No"], "#other": ["A", "B"],
    })
    state.replies.append(resolver_types.StepResolution(actions=[resolver_types.FieldAction(
        label="Legally permitted to work?", selector="#permitted", action="select_combobox", value="Yes")]))
    state.replies.append(resolver_types.StepResolution(actions=[resolver_types.FieldAction(
        label="Proof", selector="#proof", action="select_combobox", value="Yes")]))
    messages: list[str] = []
    _resolve(state, ledger, messages)  # max_retries=1: the reveal round is extra
    assert len(state.calls) == 2
    second = state.calls[1]["messages"][0]["content"]
    # Only the revealed question; not the field the model already declined.
    assert "#proof" in second and "#other" not in second and "#permitted" not in second
    assert any("revealed 1 new question" in m for m in messages)
    assert "#proof" in ledger.done


def test_no_reveal_means_no_extra_model_call(resolver_page):
    state = resolver_page
    state.unresolved = [_field("#state", "State")]
    state.replies.append(resolver_types.StepResolution(actions=[resolver_types.FieldAction(
        label="State", selector="#state", action="select_combobox", value="California")]))
    _resolve(state, resolver_types.StepLedger(options={"#state": ["California"]}))
    assert len(state.calls) == 1


_FIRMS = ["Grant Thornton", "FORVIS", "Deloitte and Touche", "No"]


@pytest.mark.parametrize(("action", "value", "executed"), [
    ("check_options", "No", True),
    ("check_options", "FORVIS | Deloitte and Touche", True),
    # "No" answers the whole question; ticked with a firm it contradicts it.
    ("check_options", "Grant Thornton | No", False),
    ("check_options", "KPMG", False),  # not an option the form showed
    ("select_combobox", "No", False),  # a checkbox group is only ever ticked
])
def test_checkbox_group_answers_are_only_offered_options(resolver_page, monkeypatch, action, value, executed):
    """American Century's required "listed firms" group (2026-09-28) was invisible to both
    layers; the resolver now asks for it, and ticks only what the form offers."""
    state = resolver_page
    done: list[str] = []

    def execute(_page, act):
        done.append(act.value)
        state.unresolved = []
        return True

    monkeypatch.setattr(widget_actions, "execute_action", execute)
    state.unresolved = [{
        "type": "checkboxgroup", "selector": "[data-automation-id=\"firms-CheckboxGroup\"]",
        "label": "Have you worked for any of the listed firms?", "options": _FIRMS, "invalid": True,
    }]
    state.replies.append(resolver_types.StepResolution(actions=[resolver_types.FieldAction(
        label="firms", selector="[data-automation-id=\"firms-CheckboxGroup\"]", action=action, value=value)]))
    _resolve(state, resolver_types.StepLedger())
    assert state.opened == []  # a checkbox group has no menu to open
    assert done == ([value] if executed else [])


def test_errors_with_nothing_actionable_do_not_call_the_model(resolver_page, monkeypatch):
    state = resolver_page
    monkeypatch.setattr(
        page_blockers, "extract_page_blockers",
        lambda _page: {"errors": ["Error: 1 field needs attention"], "unresolved": [], "advance_disabled": False},
    )
    assert _resolve(state, resolver_types.StepLedger()) is False
    assert state.calls == []


def test_skill_choices_are_one_call_and_only_observed_options(monkeypatch):
    calls: list[dict] = []
    reply = hybrid_resolver.SkillPicks(picks=[
        hybrid_resolver.SkillPick(skill="data analysis", option="Data Analytics"),
        hybrid_resolver.SkillPick(skill="machine learning", option="Deep Learning"),  # not offered
        hybrid_resolver.SkillPick(skill="invented", option="Anything"),  # not asked about
    ])
    client = _FakeClient([reply], calls)
    monkeypatch.setattr(hybrid_resolver.llm, "client_for", lambda _purpose: client)
    chosen = hybrid_resolver.choose_skill_options({
        "data analysis": ["Data Analytics", "Data Analysis Tools"],
        "machine learning": ["Machine Learning Engineer"],
    })
    assert chosen == {"data analysis": "Data Analytics", "machine learning": None}
    assert len(calls) == 1
    content = calls[0]["messages"][0]["content"]
    assert "Data Analysis Tools" in content
