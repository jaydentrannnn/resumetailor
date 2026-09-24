"""Workday state machine and authentication, driven by screens captured from a live tenant.

`tests/fixtures/workday/screens.json` holds the visible automation-id markers of each real
screen; a hand-written fake page replays them so every rule is checked without a browser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from resume_tailor import config
from resume_tailor.apply import store, workday_auth, workday_flow
from resume_tailor.apply.profile import ApplicantProfile

_SCREENS = json.loads(
    (Path(__file__).parent / "fixtures" / "workday" / "screens.json").read_text(encoding="utf-8")
)
_SCREENS.pop("_source")
_SCREENS["verify_email"] = {
    "ids": ["header", "utilityButtonSignIn"],
    "text": "Please verify your account. We sent a verification email to your address.",
}
_SCREENS["create_account_exists"] = {
    **_SCREENS["create_account"],
    "alerts": ["An account with this email address already exists."],
}
_SCREENS["sign_in_rejected"] = {**_SCREENS["sign_in"], "alerts": ["Wrong email address or password."]}
_SCREENS["create_account_terms"] = {
    **_SCREENS["create_account"],
    "ids": [*_SCREENS["create_account"]["ids"], "createAccountCheckbox"],
}
_SCREENS["blank"] = {"ids": ["header"], "text": ""}

_LABELS = {
    "createAccountSubmitButton": "Create Account",
    "signInSubmitButton": "Sign In",
    "createAccountLink": "Create Account",
    "signInLink": "Sign In",
    "adventureButton": "Apply",
    "applyManually": "Apply Manually",
    "SignInWithEmailButton": "Sign in with email",
}
_SUBMITS = {"createAccountSubmitButton", "signInSubmitButton"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


class _FakeLocator:
    def __init__(self, page: _FakePage, selector: str) -> None:
        self.page = page
        aid = re.search(r"data-automation-id='([^']+)'", selector)
        aria = re.search(r"aria-label='([^']+)'", selector)
        self.aid = aid.group(1) if aid else selector
        self.aria = aria.group(1) if aria else ""

    @property
    def first(self) -> _FakeLocator:
        return self

    def _present(self) -> bool:
        ids = set(self.page.snap().get("ids", []))
        if self.aid == "click_filter":
            return "click_filter" in ids and self.aria == self.page.overlay_label()
        return self.aid in ids

    def count(self) -> int:
        return int(self._present())

    def is_visible(self) -> bool:
        return self._present()

    def is_checked(self) -> bool:
        return self.aid in self.page.checked

    def check(self, timeout: int | None = None) -> None:
        if self.aid not in self.page.stuck_checkboxes:
            self.page.checked.add(self.aid)

    def get_attribute(self, name: str) -> str | None:
        return None

    def inner_text(self) -> str:
        return _LABELS.get(self.aid, "")

    def click(self, timeout: int | None = None) -> None:
        key = f"click_filter:{self.aria}" if self.aid == "click_filter" else self.aid
        self.page.clicks.append(key)
        if self.aid in _SUBMITS and "click_filter" in self.page.snap().get("ids", []):
            raise TimeoutError("<div data-automation-id=click_filter> intercepts pointer events")
        nxt = self.page.transitions.get((self.page.screen, key))
        if nxt:
            self.page.screen = nxt

    def fill(self, value: str, timeout: int | None = None) -> None:
        self.page.fills[self.aid] = value


class _FakePage:
    def __init__(self, screen: str, transitions: dict[tuple[str, str], str] | None = None, *, clock: _Clock) -> None:
        self.screen = screen
        self.transitions = transitions or {}
        self.clock = clock
        self.clicks: list[str] = []
        self.fills: dict[str, str] = {}
        self.checked: set[str] = set()
        #: Checkboxes whose styled widget ignores every way of ticking it.
        self.stuck_checkboxes: set[str] = set()
        #: Fake time at which Workday paints the submit's click overlay (it can lag the form).
        self.overlay_at = 0.0

    @property
    def url(self) -> str:
        return self.snap().get("url") or "https://tenant.wd5.myworkdayjobs.com/site/job/City/R1"

    def snap(self) -> dict:
        snap = _SCREENS[self.screen]
        if self.clock.now < self.overlay_at:
            snap = {**snap, "ids": [i for i in snap.get("ids", []) if i != "click_filter"]}
        return snap

    def overlay_label(self) -> str:
        ids = set(self.snap().get("ids", []))
        return next((_LABELS[s] for s in _SUBMITS if s in ids), "")

    def evaluate(self, script: str, arg: object = None) -> object:
        if script == workday_flow.SNAPSHOT_JS:
            return {"ids": [], "text": "", "alerts": [], **self.snap()}
        if script == workday_flow.AUTH_FORM_JS:
            ids = set(self.snap().get("ids", []))
            if not ({*arg["inputs"], arg["submit"]} <= ids):
                return {"ready": False, "top": ""}
            return {"ready": True, "top": "click_filter" if "click_filter" in ids else "button", "rect": [1, 2, 3, 4]}
        return None

    def wait_for_timeout(self, ms: int) -> None:
        self.clock.now += ms / 1000

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)


@pytest.fixture
def clock(monkeypatch, tmp_path):
    fake = _Clock()
    fake_time = SimpleNamespace(monotonic=fake.monotonic)
    monkeypatch.setattr(workday_flow, "time", fake_time)
    monkeypatch.setattr(workday_auth, "time", fake_time)
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    return fake


def _profile(**overrides) -> ApplicantProfile:
    return ApplicantProfile(email="applicant@example.com", **overrides)


def _tenant_vault() -> dict:
    return workday_auth._load_vault().get("tenant.wd5.myworkdayjobs.com", {})  # noqa: SLF001


def _known_site() -> None:
    """This tool has signed in to the tenant before, so it goes straight to Sign In."""
    workday_auth._mark_signed_in("tenant.wd5.myworkdayjobs.com")  # noqa: SLF001


# -- screen recognition --------------------------------------------------------------


@pytest.mark.parametrize(
    ("screen", "state"),
    [
        ("posting_signed_in", "posting"),
        ("posting_signed_out", "posting"),
        ("posting_with_draft", "posting"),
        ("start_dialog", "start_dialog"),
        ("create_account", "create_account"),
        ("sign_in", "sign_in"),
        ("my_information", "apply_form"),
        ("verify_email", "verify_email"),
        ("auth_chooser", "auth_chooser"),
        # The sign-in step's progress bar paints before its form: not an application form.
        ("auth_step_loading", "unknown"),
        ("blank", "unknown"),
    ],
)
def test_classify_recognises_captured_screens(screen, state):
    assert workday_flow.classify(_SCREENS[screen]) == state


def test_classify_special_pages():
    assert workday_flow.classify({"ids": ["header"], "text": "The page you are looking for doesn't exist."}) == "unavailable"
    assert workday_flow.classify({"ids": ["jobPostingPage"], "text": "You've already applied for this job"}) == "already_applied"
    assert workday_flow.classify({"ids": ["header"], "otp_input": True}) == "otp"


def test_signed_in_needs_account_menu_and_no_auth_form():
    assert workday_flow.signed_in(_SCREENS["posting_signed_in"])
    assert workday_flow.signed_in(_SCREENS["my_information"])
    assert not workday_flow.signed_in(_SCREENS["posting_signed_out"])
    assert not workday_flow.signed_in(_SCREENS["create_account"])


def test_active_step_strips_progress_prefix():
    assert workday_flow.active_step(_SCREENS["my_information"]) == "My Information"
    assert workday_flow.active_step({"active_step": "step 2 of 6 My Experience"}) == "My Experience"


# -- entering the application ----------------------------------------------------------


def test_enter_application_clicks_apply_then_apply_manually_only(clock):
    page = _FakePage("posting_signed_in", {
        ("posting_signed_in", "adventureButton"): "start_dialog",
        ("start_dialog", "applyManually"): "my_information",
    }, clock=clock)
    resulting, state = workday_flow.enter_application(page, None, deadline=clock.now + 60)
    assert resulting is page
    assert state == "apply_form"
    assert page.clicks == ["adventureButton", "applyManually"]


def test_enter_application_resumes_a_saved_draft(clock):
    page = _FakePage("posting_with_draft", {
        ("posting_with_draft", "continueButton"): "my_information",
    }, clock=clock)
    _page, state = workday_flow.enter_application(page, None, deadline=clock.now + 60)
    assert state == "apply_form"
    assert page.clicks == ["continueButton"]


def test_enter_application_resumes_from_the_open_dialog(clock):
    page = _FakePage("start_dialog", {("start_dialog", "applyManually"): "sign_in"}, clock=clock)
    _page, state = workday_flow.enter_application(page, None, deadline=clock.now + 60)
    assert state == "sign_in"
    assert page.clicks == ["applyManually"]


def test_enter_application_leaves_a_form_alone(clock):
    page = _FakePage("my_information", clock=clock)
    assert workday_flow.enter_application(page, None, deadline=clock.now + 60)[1] == "apply_form"
    assert page.clicks == []


# -- authentication --------------------------------------------------------------------


def test_existing_session_is_authenticated_without_credentials(clock):
    page = _FakePage("my_information", clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "authenticated"
    assert page.fills == {} and page.clicks == []
    assert _tenant_vault() == {}


def test_create_account_goes_through_the_click_filter_overlay(clock):
    page = _FakePage("create_account", {
        ("create_account", "click_filter:Create Account"): "my_information",
    }, clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "authenticated"
    assert page.clicks == ["click_filter:Create Account"]
    assert page.fills["email"] == "applicant@example.com"
    assert page.fills["password"] == page.fills["verifyPassword"]
    assert "beecatcher" not in page.fills
    assert _tenant_vault()["created"] is True


def test_sign_in_screen_switches_to_create_account_for_an_unknown_tenant(clock):
    page = _FakePage("sign_in", {
        ("sign_in", "createAccountLink"): "create_account",
        ("create_account", "click_filter:Create Account"): "verify_email",
    }, clock=clock)
    store.upsert(store.Application(source="simplify", source_job_id="app-1", company="Acme", role="Intern", status="ready"))
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "verification_needed"
    assert page.clicks == ["createAccountLink", "click_filter:Create Account"]
    assert _tenant_vault()["created"] is True
    app = store.get("app-1")
    assert app is not None and app.status == "awaiting_otp"
    assert app.otp_prompt == workday_auth.AUTH_HANDOFF["verification_needed"]


def test_existing_account_with_unknown_password_is_handed_over(clock):
    page = _FakePage("create_account", {
        ("create_account", "click_filter:Create Account"): "create_account_exists",
    }, clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "account_exists_other_password"
    assert page.clicks == ["click_filter:Create Account"]  # no guessed sign-in afterwards
    assert not _tenant_vault().get("created")


def test_sign_in_chooser_uses_email_never_google_or_linkedin(clock):
    page = _FakePage("auth_chooser", {
        ("auth_chooser", "SignInWithEmailButton"): "sign_in",
        ("sign_in", "createAccountLink"): "create_account",
        ("create_account", "click_filter:Create Account"): "my_information",
    }, clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "authenticated"
    assert page.clicks == ["SignInWithEmailButton", "createAccountLink", "click_filter:Create Account"]


def test_a_loading_sign_in_step_is_not_taken_for_a_session(clock):
    page = _FakePage("auth_step_loading", clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "failed"
    assert page.fills == {}


def test_known_account_signs_in_through_the_overlay(clock):
    workday_auth._save_vault({"tenant.wd5.myworkdayjobs.com": {  # noqa: SLF001
        "email": "applicant@example.com", "password": "Saved!Pass1", "created": True,
    }})
    page = _FakePage("create_account", {
        ("create_account", "signInLink"): "sign_in",
        ("sign_in", "click_filter:Sign In"): "my_information",
    }, clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "authenticated"
    assert page.clicks == ["signInLink", "click_filter:Sign In"]
    assert page.fills == {"email": "applicant@example.com", "password": "Saved!Pass1"}


def test_sign_in_waits_for_a_late_overlay_instead_of_clicking_the_bare_button(clock):
    _known_site()
    # Live 2026-09-23: the form painted before its click overlay; the bare button has no
    # handler, so clicking it did nothing and the run blamed the password.
    page = _FakePage("sign_in", {("sign_in", "click_filter:Sign In"): "my_information"}, clock=clock)
    page.overlay_at = clock.now + 1.2
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "authenticated"
    assert page.clicks == ["click_filter:Sign In"]


def test_create_account_waits_for_a_late_overlay(clock):
    page = _FakePage("create_account", {
        ("create_account", "click_filter:Create Account"): "my_information",
    }, clock=clock)
    page.overlay_at = clock.now + 1.2
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "authenticated"
    assert page.clicks == ["click_filter:Create Account"]


def test_an_ignored_sign_in_click_is_retried_once_then_handed_over_honestly(clock):
    _known_site()
    page = _FakePage("sign_in", clock=clock)  # nothing the tool clicks has any effect
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "no_response"
    assert page.clicks == ["click_filter:Sign In", "click_filter:Sign In"]


def test_a_retry_that_lands_signs_in(clock, monkeypatch):
    _known_site()
    page = _FakePage("sign_in", clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    original = _FakeLocator.click

    def second_click_works(self, timeout=None):
        original(self, timeout)
        if self.page.clicks.count("click_filter:Sign In") == 2:
            self.page.screen = "my_information"

    monkeypatch.setattr(_FakeLocator, "click", second_click_works)
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "authenticated"
    assert page.clicks == ["click_filter:Sign In", "click_filter:Sign In"]


def test_a_submit_that_reached_workday_is_never_clicked_twice(clock, monkeypatch):
    _known_site()
    # Live AmFam 2026-09-23: the rejection took ~20s; a second click is a second failed
    # password attempt toward the lockout.
    page = _FakePage("sign_in", clock=clock)
    listeners: list = []
    page.on = lambda event, handler: listeners.append(handler)
    page.remove_listener = lambda event, handler: listeners.remove(handler)
    original = _FakeLocator.click

    def click_sends_a_request(self, timeout=None):
        original(self, timeout)
        for handler in list(listeners):
            handler(SimpleNamespace(method="POST", url="https://tenant.wd5.myworkdayjobs.com/signin"))

    monkeypatch.setattr(_FakeLocator, "click", click_sends_a_request)
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "no_response"
    assert page.clicks == ["click_filter:Sign In"]
    assert listeners == []


def test_profile_password_is_used_for_a_manually_created_account(clock):
    _known_site()
    page = _FakePage("sign_in", {("sign_in", "click_filter:Sign In"): "sign_in_rejected"}, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "sign_in_failed"
    assert page.fills["password"] == "Mine!Pass9"


def test_a_new_site_creates_the_account_even_with_a_profile_password(clock):
    # Live 2026-09-24 (Excellus, lthc): a saved profile password sent a first visit
    # straight to Sign In, where no account existed yet.
    page = _FakePage("sign_in", {
        ("sign_in", "createAccountLink"): "create_account",
        ("create_account", "click_filter:Create Account"): "my_information",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "authenticated"
    assert page.clicks == ["createAccountLink", "click_filter:Create Account"]
    assert page.fills["verifyPassword"] == "Mine!Pass9"
    assert _tenant_vault().get("created")


def test_an_existing_account_gets_one_sign_in_with_the_profile_password(clock):
    page = _FakePage("create_account", {
        ("create_account", "click_filter:Create Account"): "create_account_exists",
        ("create_account_exists", "signInLink"): "sign_in",
        ("sign_in", "click_filter:Sign In"): "my_information",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "authenticated"
    assert page.clicks == ["click_filter:Create Account", "signInLink", "click_filter:Sign In"]
    assert _tenant_vault().get("signed_in")


def test_an_existing_account_under_another_password_is_handed_over_after_one_try(clock):
    page = _FakePage("create_account", {
        ("create_account", "click_filter:Create Account"): "create_account_exists",
        ("create_account_exists", "signInLink"): "sign_in",
        ("sign_in", "click_filter:Sign In"): "sign_in_rejected",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    result = workday_auth.handle_workday_auth(page, "app-1", profile)
    assert result == "account_exists_other_password"
    assert page.clicks.count("click_filter:Sign In") == 1
    assert "Forgot Password" in workday_auth.AUTH_HANDOFF[result]


def test_account_terms_are_ticked_then_the_account_is_created(clock):
    page = _FakePage(
        "create_account_terms",
        {("create_account_terms", "click_filter:Create Account"): "my_information"},
        clock=clock,
    )
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "authenticated"
    assert "createAccountCheckbox" in page.checked
    assert page.clicks[-1] == "click_filter:Create Account"


def test_terms_that_will_not_tick_are_handed_over_unsubmitted(clock):
    page = _FakePage("create_account_terms", clock=clock)
    page.stuck_checkboxes.add("createAccountCheckbox")
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "terms_needed"
    assert "click_filter:Create Account" not in page.clicks


def test_unrecognised_screen_is_not_proof_of_login(clock):
    page = _FakePage("blank", clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == "failed"


def test_missing_email_needs_credentials(clock):
    page = _FakePage("create_account", clock=clock)
    assert workday_auth.handle_workday_auth(page, "app-1", ApplicantProfile()) == "credentials_needed"


def test_every_handoff_has_readable_text():
    outcomes = set(workday_auth.AuthResult.__args__) - {"authenticated"}
    assert outcomes <= set(workday_auth.AUTH_HANDOFF)


# -- dropdowns -------------------------------------------------------------------------


class _DropdownPage:
    def __init__(self, items: list[dict]) -> None:
        self.items = items

    def evaluate(self, script: str, arg: object = None) -> object:
        assert script == workday_flow.DROPDOWNS_JS
        return [dict(item) for item in self.items]

    def wait_for_timeout(self, ms: int) -> None:
        pass


def test_fill_dropdowns_corrects_country_first_and_leaves_unknowns():
    from resume_tailor.apply import ats_hints

    page = _DropdownPage([
        {"selector": "#source--source", "label": "How Did You Hear About Us?", "current": "Select One"},
        {"selector": "#phoneNumber--phoneType", "label": "Phone Device Type", "current": "Select One"},
        {"selector": "#country--country", "label": "Country", "current": "Vietnam"},
        {"selector": "#address--countryRegion", "label": "State", "current": "Select One"},
        {"selector": "#q1", "label": "Favourite colour", "current": "Select One"},
        {"selector": "#q2", "label": "Desired salary", "current": "Select One"},
    ])
    calls: list[tuple[str, str, str]] = []

    def select(_page, selector, value, *, key):
        calls.append((selector, value, key))
        for item in page.items:
            if item["selector"] == selector:
                item["current"] = value
        return True

    fields = {"country": "United States", "state": "California", "how_heard": "LinkedIn", "salary_expectation": "100"}
    committed = workday_flow.fill_dropdowns(page, fields, synonyms=ats_hints.SYNONYMS, select=select)
    assert calls[0] == ("#country--country", "United States", "country")
    assert ("#address--countryRegion", "California", "state") in calls
    assert ("#source--source", "LinkedIn", "how_heard") in calls
    assert not any(selector in {"#q1", "#q2", "#phoneNumber--phoneType"} for selector, _v, _k in calls)
    assert {item["key"] for item in committed} == {"country", "state", "how_heard"}


def test_fill_dropdowns_keeps_an_existing_choice():
    from resume_tailor.apply import ats_hints

    page = _DropdownPage([{"selector": "#address--countryRegion", "label": "State", "current": "Texas"}])
    calls: list = []
    workday_flow.fill_dropdowns(
        page, {"state": "California"}, synonyms=ats_hints.SYNONYMS,
        select=lambda *a, **k: calls.append(a) or True,
    )
    assert calls == []


class _PromptPage:
    def __init__(self, prompts: list[dict]) -> None:
        self.prompts = prompts

    def evaluate(self, script: str, arg: object = None) -> object:
        assert script == workday_flow.PROMPTS_JS
        return [dict(item) for item in self.prompts]


def test_fill_prompts_answers_only_empty_prompts_with_a_profile_fact():
    from resume_tailor.apply import ats_hints

    page = _PromptPage([
        {"input_id": "source--source", "label": "How Did You Hear About Us?", "chips": 0},
        {"input_id": "q--hobby", "label": "Favourite hobby", "chips": 0},
        {"input_id": "q--done", "label": "How did you hear about this role?", "chips": 1},
    ])
    calls: list[tuple[str, str, str]] = []

    def select(_page, input_id, value, *, key):
        calls.append((input_id, value, key))
        return True

    committed = workday_flow.fill_prompts(
        page, {"how_heard": "LinkedIn"}, synonyms=ats_hints.SYNONYMS, select=select,
    )
    assert calls == [("source--source", "LinkedIn", "how_heard")]
    assert committed[0]["label"] == "How Did You Hear About Us?"


class _SearchPromptPage:
    """A hierarchical prompt whose search lists the same leaf under two categories."""

    def __init__(self) -> None:
        self.chips: list[str] = []
        self.results = ["LinkedIn", "LinkedIn"]

    def evaluate(self, script: str, arg: object = None) -> object:
        return list(self.chips)

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def locator(self, selector: str) -> SimpleNamespace:
        page = self
        if "promptOption" in selector:
            assert "selectedItem" in selector  # committed chips are not choices
            return SimpleNamespace(
                all_inner_texts=lambda: list(page.results),
                nth=lambda i: SimpleNamespace(click=lambda timeout=None: page.chips.append(page.results[i])),
            )
        box = SimpleNamespace(fill=lambda value, timeout=None: None, press=lambda key: None)
        return SimpleNamespace(first=box)


def test_select_prompt_treats_a_leaf_listed_twice_as_one_answer():
    page = _SearchPromptPage()
    assert workday_flow.select_prompt(page, "source--source", "LinkedIn", key="how_heard")
    assert page.chips == ["LinkedIn"]


class _ListboxPage:
    """A Workday listbox button that only gains aria-controls once its list has opened."""

    def __init__(self) -> None:
        self.reads = 0
        self.text = "Select One"
        self.options = [
            {"id": "select-one", "label": "Select One", "disabled": True},
            {"id": "opt-yes", "label": "Yes", "disabled": False},
            {"id": "opt-no", "label": "No", "disabled": False},
        ]

    def evaluate(self, script: str, arg: object = None) -> object:
        assert script == workday_flow._OPTIONS_JS  # noqa: SLF001
        return [dict(o) for o in self.options] if arg == "dmlbo" else None

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def locator(self, selector: str) -> SimpleNamespace:
        page = self
        if selector.startswith("[id='opt-"):
            label = next(o["label"] for o in self.options if f"'{o['id']}'" in selector)
            return SimpleNamespace(first=SimpleNamespace(click=lambda timeout=None: setattr(page, "text", label)))

        def aria_controls(_name: str) -> str | None:
            page.reads += 1
            return "dmlbo" if page.reads >= 3 else None

        trigger = SimpleNamespace(
            click=lambda timeout=None: None, get_attribute=aria_controls,
            inner_text=lambda: page.text, press=lambda key: None,
        )
        return SimpleNamespace(first=trigger)


def test_select_listbox_waits_for_the_list_to_open():
    page = _ListboxPage()
    assert workday_flow.select_listbox(page, "#q", "No", key="requires_sponsorship_future")
    assert page.text == "No"


def test_fill_prompts_leaves_the_skills_prompt_to_fill_skills():
    from resume_tailor.apply import ats_hints

    page = _PromptPage([{"input_id": "skills--skills", "field": "formField-skills", "label": "Skills", "chips": 0}])
    calls: list = []
    workday_flow.fill_prompts(
        page, {"skills": "Python"}, synonyms=[*ats_hints.SYNONYMS, (r"skill", "skills")],
        select=lambda *a, **k: calls.append(a) or True,
    )
    assert calls == []
