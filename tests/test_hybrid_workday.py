"""Unit and mock tests for Hybrid Form Filling and Workday Auth."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from resume_tailor import config
from resume_tailor.apply import hybrid_resolver, workday_auth
from resume_tailor.apply.profile import ApplicantProfile


def test_phone_code_choice_requires_explicit_region():
    options = ["United States +1", "Canada +1", "American Samoa +1", "United Kingdom +44"]
    assert hybrid_resolver._phone_option(options, "+1", "") is None  # noqa: SLF001
    assert hybrid_resolver._phone_option(options, "+1", "United States") == "United States +1"  # noqa: SLF001
    assert hybrid_resolver._phone_option(options, "+1", "Canada") == "Canada +1"  # noqa: SLF001
    assert hybrid_resolver._phone_option(options, "+1", "United Kingdom") is None  # noqa: SLF001


def test_declared_greenhouse_option_aliases_are_exact_and_unambiguous():
    match = hybrid_resolver._option_match  # noqa: SLF001
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
    monkeypatch.setattr(hybrid_resolver, "_selected_combobox_text", MagicMock(side_effect=["", "Bachelor's Degree"]))
    monkeypatch.setattr(
        hybrid_resolver,
        "_menu_choices",
        lambda _page, _trigger: [option] if trigger.fill.call_args and trigger.fill.call_args.args[0] == "bachelor" else [],
    )

    assert hybrid_resolver._select_combobox_option(page, "#degree", "Bachelors", key="degree_level")  # noqa: SLF001
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
    monkeypatch.setattr(hybrid_resolver, "_selected_combobox_text", lambda _trigger: "+1")
    monkeypatch.setattr(hybrid_resolver, "_menu_choices", lambda _page, _trigger: [us, canada])

    assert hybrid_resolver._select_combobox_option(  # noqa: SLF001
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

    action_fill = hybrid_resolver.FieldAction(
        selector="#custom-input",
        label="Custom Field",
        action="fill_text",
        value="My Answer",
    )
    assert hybrid_resolver.execute_action(page, action_fill)
    assert mock_el.fill.called

    with pytest.raises(ValueError):
        hybrid_resolver.FieldAction(
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
        hybrid_resolver, "extract_page_blockers",
        lambda _page: {"errors": [], "unresolved": [dict(f) for f in state.unresolved], "advance_disabled": False},
    )
    monkeypatch.setattr(hybrid_resolver, "_menu_choices", lambda _page, trigger: [])
    monkeypatch.setattr(hybrid_resolver, "_is_upload_widget", lambda _locator: False)

    def execute(_page, action):
        state.unresolved = [f for f in state.unresolved if f["selector"] != action.selector]
        return True

    monkeypatch.setattr(hybrid_resolver, "execute_action", execute)
    page = MagicMock()
    page.locator.side_effect = lambda selector: SimpleNamespace(first=SimpleNamespace(
        click=lambda timeout=None: state.opened.append(selector),
        press=lambda key: None,
    ))
    state.page = page
    return state


def _resolve(state, ledger, messages=None, **kwargs):
    from resume_tailor.apply.packet import Packet

    return hybrid_resolver.resolve_step_blockers(
        state.page, Packet.model_construct(fields={}), ApplicantProfile(),
        ledger=ledger, max_retries=1, on_progress=(messages if messages is not None else []).append, **kwargs,
    )


def test_a_second_pass_on_the_step_touches_only_the_new_gap(resolver_page):
    state = resolver_page
    state.unresolved = [_field("#state", "State"), _field("#vet", "Veteran status")]
    # The model answers State; Veteran status it cannot answer.
    state.replies.append(hybrid_resolver.StepResolution(actions=[hybrid_resolver.FieldAction(
        label="State", selector="#state", action="select_combobox", value="California")]))
    # The observed option list must contain the answer for it to be executed.
    ledger = hybrid_resolver.StepLedger(options={"#state": ["California", "Texas"]})
    _resolve(state, ledger)
    assert len(state.calls) == 1
    assert state.opened == ["#vet"]  # State's options were already known

    # Same step, same stuck field: nothing is reopened and the model is not asked again.
    messages: list[str] = []
    _resolve(state, ledger, messages)
    assert len(state.calls) == 1
    assert state.opened == ["#vet"]
    assert any("still need input" in m for m in messages)

    # A field revealed later on the same step is the only thing sent.
    state.unresolved.append(_field("#reloc", "Willing to relocate"))
    state.replies.append(hybrid_resolver.StepResolution(actions=[]))
    messages = []
    _resolve(state, ledger, messages)
    assert len(state.calls) == 2
    sent = state.calls[1]["messages"][0]["content"]
    assert "#reloc" in sent and "#vet" not in sent and "#state" not in sent
    assert any("retrying 1 unfilled field(s): Willing to relocate" in m for m in messages)


def test_after_a_rejected_advance_only_invalid_fields_are_retried(resolver_page):
    state = resolver_page
    state.unresolved = [_field("#a", "Optional pick"), _field("#b", "Required pick", invalid=True)]
    state.replies.append(hybrid_resolver.StepResolution(actions=[]))
    _resolve(state, hybrid_resolver.StepLedger(), only_invalid=True)
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

    monkeypatch.setattr(hybrid_resolver, "execute_action", execute)
    ledger = hybrid_resolver.StepLedger(options={
        "#permitted": ["Yes", "No"], "#proof": ["Yes", "No"], "#other": ["A", "B"],
    })
    state.replies.append(hybrid_resolver.StepResolution(actions=[hybrid_resolver.FieldAction(
        label="Legally permitted to work?", selector="#permitted", action="select_combobox", value="Yes")]))
    state.replies.append(hybrid_resolver.StepResolution(actions=[hybrid_resolver.FieldAction(
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
    state.replies.append(hybrid_resolver.StepResolution(actions=[hybrid_resolver.FieldAction(
        label="State", selector="#state", action="select_combobox", value="California")]))
    _resolve(state, hybrid_resolver.StepLedger(options={"#state": ["California"]}))
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

    monkeypatch.setattr(hybrid_resolver, "execute_action", execute)
    state.unresolved = [{
        "type": "checkboxgroup", "selector": "[data-automation-id=\"firms-CheckboxGroup\"]",
        "label": "Have you worked for any of the listed firms?", "options": _FIRMS, "invalid": True,
    }]
    state.replies.append(hybrid_resolver.StepResolution(actions=[hybrid_resolver.FieldAction(
        label="firms", selector="[data-automation-id=\"firms-CheckboxGroup\"]", action=action, value=value)]))
    _resolve(state, hybrid_resolver.StepLedger())
    assert state.opened == []  # a checkbox group has no menu to open
    assert done == ([value] if executed else [])


def test_errors_with_nothing_actionable_do_not_call_the_model(resolver_page, monkeypatch):
    state = resolver_page
    monkeypatch.setattr(
        hybrid_resolver, "extract_page_blockers",
        lambda _page: {"errors": ["Error: 1 field needs attention"], "unresolved": [], "advance_disabled": False},
    )
    assert _resolve(state, hybrid_resolver.StepLedger()) is False
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
