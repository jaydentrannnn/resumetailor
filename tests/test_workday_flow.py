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
# Live 2026-09-24 (Jabil): an account created earlier whose verification link was never clicked.
_SCREENS["sign_in_unverified"] = {
    **_SCREENS["sign_in"],
    "alerts": ["Verify your account before you sign in or request a verification email."],
}
_SCREENS["create_account_terms"] = {
    **_SCREENS["create_account"],
    "ids": [*_SCREENS["create_account"]["ids"], "createAccountCheckbox"],
}
_SCREENS["blank"] = {"ids": ["header"], "text": ""}
# Live 2026-09-24 (CACI): Workday's error page inside the apply flow. The progress bar
# stays, the form and its footer are gone.
_SCREENS["site_error"] = {
    "ids": ["header", "utilityButtonAccountTasksMenu", "applyFlowPage", "backToJobPosting",
            "jobTitleHeading", "progressBar", "progressBarActiveStep", "progressBarInactiveStep"],
    "active_step": "current step 1 of 6 My Information",
    "text": "Software Engineering Intern - Summer 2027\nMy Information\nSomething went wrong\n"
            "Please refresh the page and then try again.\n"
            "Error Code: VPS|3c46db7c-2f27-4611-9115-06007c7d5e6b",
}
# Live 2026-09-24 (Excellus, window under ~800px): the progress bar drops its step names,
# so the Create Account step's shell has no label for ~3s before its form paints.
_SCREENS["auth_step_shell_unlabelled"] = {**_SCREENS["auth_step_loading"], "active_step": ""}

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

    def get_attribute(self, name: str, timeout: int | None = None) -> str | None:
        return self.page.hrefs.get(self.aid) if name == "href" else None

    def inner_text(self, timeout: int | None = None) -> str:
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
        #: Screens shown by successive reloads; an empty queue reloads the same screen.
        self.after_reload: list[str] = []
        self.reloads = 0
        #: href of a link by automation id; a link listed here is followed, not clicked.
        self.hrefs: dict[str, str] = {}
        self.gotos: list[str] = []

    def goto(self, url: str, **_kwargs: object) -> None:
        self.gotos.append(url)
        nxt = self.transitions.get((self.screen, f"goto:{url}"))
        if nxt:
            self.screen = nxt

    def reload(self, **_kwargs: object) -> None:
        self.reloads += 1
        if self.after_reload:
            self.screen = self.after_reload.pop(0)

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
        # Nor is a bare shell with no step name, no field and no footer.
        ("auth_step_shell_unlabelled", "unknown"),
        ("blank", "unknown"),
    ],
)
def test_classify_recognises_captured_screens(screen, state):
    assert workday_flow.classify(_SCREENS[screen]) == state


def test_classify_special_pages():
    assert workday_flow.classify({"ids": ["header"], "text": "The page you are looking for doesn't exist."}) == "unavailable"
    assert workday_flow.classify({"ids": ["jobPostingPage"], "text": "You've already applied for this job"}) == "already_applied"
    assert workday_flow.classify({"ids": ["header"], "otp_input": True}) == "otp"


def test_a_verify_message_in_the_auth_step_is_verify_email():
    shell = {**_SCREENS["auth_step_loading"], "text": "Please verify your account. Check your inbox."}
    assert workday_flow.classify(shell) == "verify_email"
    assert workday_flow.classify(_SCREENS["sign_in_unverified"]) == "sign_in"


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


def test_apply_manually_href_is_navigated_not_clicked(clock):
    """A background tab never sees the animating dialog stable, so the link is followed."""
    page = _FakePage("start_dialog", {
        ("start_dialog", "goto:https://tenant.wd5.myworkdayjobs.com/site/job/City/R1/apply/applyManually"): "sign_in",
    }, clock=clock)
    page.hrefs["applyManually"] = "/site/job/City/R1/apply/applyManually"  # relative: resolved
    _page, state = workday_flow.enter_application(page, None, deadline=clock.now + 60)
    assert state == "sign_in"
    assert page.gotos == ["https://tenant.wd5.myworkdayjobs.com/site/job/City/R1/apply/applyManually"]
    assert page.clicks == []


@pytest.mark.parametrize("href", [None, "", "#", "javascript:void(0)"])
def test_apply_manually_without_a_usable_href_is_clicked(clock, href):
    page = _FakePage("start_dialog", {("start_dialog", "applyManually"): "sign_in"}, clock=clock)
    if href is not None:
        page.hrefs["applyManually"] = href
    _page, state = workday_flow.enter_application(page, None, deadline=clock.now + 60)
    assert state == "sign_in"
    assert page.gotos == []
    assert page.clicks == ["applyManually"]


@pytest.mark.parametrize(("screen", "aid"), [
    ("posting_signed_in", "adventureButton"),
    ("posting_with_draft", "continueButton"),
])
def test_apply_entry_href_is_navigated_not_clicked(clock, screen, aid):
    url = "https://tenant.wd5.myworkdayjobs.com/site/job/City/R1/apply"
    page = _FakePage(screen, {(screen, f"goto:{url}"): "my_information"}, clock=clock)
    page.hrefs[aid] = url
    _page, state = workday_flow.enter_application(page, None, deadline=clock.now + 60)
    assert state == "apply_form"
    assert page.gotos == [url]
    assert page.clicks == []


def test_enter_application_leaves_a_form_alone(clock):
    page = _FakePage("my_information", clock=clock)
    assert workday_flow.enter_application(page, None, deadline=clock.now + 60)[1] == "apply_form"
    assert page.clicks == []


# -- Workday's "Something went wrong" page ---------------------------------------------


@pytest.mark.parametrize("text", [
    _SCREENS["site_error"]["text"],
    "Something went wrong\n\nPlease refresh the page and then try again.",
    "Oops\nError Code: VPS|0000-1111",
])
def test_site_error_page_is_recognised(text):
    assert workday_flow.is_site_error({"text": text})


def test_a_form_is_not_a_site_error():
    assert not workday_flow.is_site_error(_SCREENS["my_information"])


def test_site_error_is_refreshed_until_the_form_returns(clock):
    page = _FakePage("site_error", clock=clock)
    page.after_reload = ["site_error", "my_information"]
    messages: list[str] = []
    assert workday_flow.recover_site_error(page, deadline=clock.now + 120, progress=messages.append) == (True, 2)
    assert page.reloads == 2
    assert page.screen == "my_information"
    assert messages[-1] == "Workday page recovered after refreshing"


def test_site_error_stops_refreshing_after_its_attempts(clock):
    page = _FakePage("site_error", clock=clock)
    assert workday_flow.recover_site_error(page, deadline=clock.now + 600, attempts=3) == (False, 3)
    assert page.reloads == 3


def test_site_error_recovery_leaves_a_healthy_page_alone(clock):
    page = _FakePage("my_information", clock=clock)
    assert workday_flow.recover_site_error(page, deadline=clock.now + 60) == (True, 0)
    assert page.reloads == 0


def test_enter_application_refreshes_a_site_error_tab(clock):
    """Continue fill on a tab left on the error page reloads it instead of stalling."""
    page = _FakePage("site_error", clock=clock)
    page.after_reload = ["my_information"]
    assert workday_flow.enter_application(page, None, deadline=clock.now + 60)[1] == "apply_form"
    assert page.reloads == 1
    assert page.clicks == []


def test_enter_application_refreshes_an_error_after_apply_manually(clock):
    page = _FakePage("start_dialog", {("start_dialog", "applyManually"): "site_error"}, clock=clock)
    page.after_reload = ["my_information"]
    assert workday_flow.enter_application(page, None, deadline=clock.now + 120)[1] == "apply_form"
    assert page.reloads == 1


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


def test_a_profile_password_signs_in_first_and_creates_the_account_when_rejected(clock):
    # Workday answers "wrong email or password" when no account exists yet; that one
    # rejection on a site the tool never used leads to Create Account, not a handoff.
    page = _FakePage("create_account", {
        ("create_account", "signInLink"): "sign_in",
        ("sign_in", "click_filter:Sign In"): "sign_in_rejected",
        ("sign_in_rejected", "createAccountLink"): "create_account",
        ("create_account", "click_filter:Create Account"): "my_information",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    started = clock.now
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "authenticated"
    assert page.clicks == [
        "signInLink", "click_filter:Sign In", "createAccountLink", "click_filter:Create Account",
    ]
    assert page.fills["verifyPassword"] == "Mine!Pass9"
    assert _tenant_vault().get("created")
    # The rejection is read from the form's error, not waited out for 30s.
    assert clock.now - started < 20


def test_an_existing_account_signs_in_with_the_profile_password(clock):
    page = _FakePage("create_account", {
        ("create_account", "signInLink"): "sign_in",
        ("sign_in", "click_filter:Sign In"): "my_information",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "authenticated"
    assert page.clicks == ["signInLink", "click_filter:Sign In"]
    assert _tenant_vault().get("signed_in")


def test_an_existing_account_under_another_password_is_handed_over_after_one_try(clock):
    page = _FakePage("sign_in", {
        ("sign_in", "click_filter:Sign In"): "sign_in_rejected",
        ("sign_in_rejected", "createAccountLink"): "create_account",
        ("create_account", "click_filter:Create Account"): "create_account_exists",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    result = workday_auth.handle_workday_auth(page, "app-1", profile)
    assert result == "account_exists_other_password"
    assert page.clicks.count("click_filter:Sign In") == 1
    assert "Forgot Password" in workday_auth.AUTH_HANDOFF[result]


def test_an_unverified_account_hands_over_for_the_email_link_without_creating_again(clock):
    # Live Jabil 2026-09-24: this read as a wrong password, so the run tried Create Account
    # for an account that already existed and waited it out.
    store.upsert(store.Application(source="simplify", source_job_id="app-1", company="Jabil", role="Intern", status="ready"))
    page = _FakePage("auth_chooser", {
        ("auth_chooser", "SignInWithEmailButton"): "sign_in",
        ("sign_in", "click_filter:Sign In"): "sign_in_unverified",
        ("sign_in_unverified", "createAccountLink"): "create_account",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "verification_needed"
    assert "createAccountLink" not in page.clicks
    assert _tenant_vault().get("created")
    app = store.get("app-1")
    assert app is not None and app.status == "awaiting_otp"
    assert "verification email" in (app.otp_prompt or "")


@pytest.mark.parametrize(("after_sign_in", "result"), [
    ("my_information", "authenticated"),
    ("sign_in_unverified", "verification_needed"),
])
def test_create_account_back_on_the_login_chooser_signs_the_new_account_in(clock, after_sign_in, result):
    # Live Jabil 2026-09-24: Create Account returned to the chooser, which was not a screen
    # the run waited for; it waited 30s and gave up without recording the account.
    page = _FakePage("create_account", {
        ("create_account", "click_filter:Create Account"): "auth_chooser",
        ("auth_chooser", "SignInWithEmailButton"): "sign_in",
        ("sign_in", "click_filter:Sign In"): after_sign_in,
    }, clock=clock)
    started = clock.now
    assert workday_auth.handle_workday_auth(page, "app-1", _profile()) == result
    assert page.clicks == ["click_filter:Create Account", "SignInWithEmailButton", "click_filter:Sign In"]
    assert page.fills["password"] == page.fills["verifyPassword"]
    assert _tenant_vault().get("created")
    assert clock.now - started < 20


def test_create_account_after_a_spent_sign_in_never_signs_in_twice(clock):
    page = _FakePage("sign_in", {
        ("sign_in", "click_filter:Sign In"): "sign_in_rejected",
        ("sign_in_rejected", "createAccountLink"): "create_account",
        ("create_account", "click_filter:Create Account"): "auth_chooser",
    }, clock=clock)
    profile = _profile(workday_password="Mine!Pass9")
    assert workday_auth.handle_workday_auth(page, "app-1", profile) == "verification_needed"
    assert page.clicks.count("click_filter:Sign In") == 1


def test_an_unlabelled_auth_shell_waits_for_the_create_account_form(clock):
    # Live 2026-09-24 (Excellus): the unlabelled shell read as the application form, so
    # sign-in was skipped and the generic filler typed only the email into Create Account.
    page = _FakePage("start_dialog", {("start_dialog", "applyManually"): "auth_step_shell_unlabelled"}, clock=clock)
    original = page.wait_for_timeout

    def paint_form_later(ms):
        original(ms)
        if page.screen == "auth_step_shell_unlabelled" and clock.now >= 1003:
            page.screen = "create_account"

    page.wait_for_timeout = paint_form_later
    assert workday_flow.enter_application(page, None, deadline=clock.now + 60)[1] == "create_account"


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
    committed = workday_flow.fill_dropdowns(page, fields, select=select)
    assert calls[0] == ("#country--country", "United States", "country")
    assert ("#address--countryRegion", "California", "state") in calls
    assert ("#source--source", "LinkedIn", "how_heard") in calls
    assert not any(selector in {"#q1", "#q2", "#phoneNumber--phoneType"} for selector, _v, _k in calls)
    assert {item["key"] for item in committed} == {"country", "state", "how_heard"}


def test_fill_dropdowns_records_a_blank_profile_fact_instead_of_skipping_silently():
    from resume_tailor.apply import ats_hints

    page = _DropdownPage([
        {"selector": "#phoneNumber--phoneType", "label": "Phone Device Type", "current": "Select One"},
        {"selector": "#address--countryRegion", "label": "State", "current": "Texas"},
        {"selector": "#q2", "label": "Desired salary", "current": "Select One"},
        {"selector": "#q1", "label": "Favourite colour", "current": "Select One"},
    ])
    blank: list[dict] = []
    workday_flow.fill_dropdowns(
        page, {}, select=lambda *a, **k: True, blank=blank,
    )
    # An already-answered State and the per-posting salary are not blanks to report.
    assert blank == [{"key": "phone_device_type", "label": "Phone Device Type"}]


def test_an_answer_that_reveals_a_follow_up_is_followed_in_the_same_call():
    """"Legally permitted to work" = Yes reveals "proof of eligibility" (a live Workday
    step, 2026-09); both come from the profile, and neither is read as the Country."""
    from resume_tailor.apply import ats_hints

    permitted = "Are you legally permitted to work in the country where this job is located?"
    proof = {"selector": "#proof", "label": "If hired, can you provide proof of eligibility?", "current": "Select One"}
    page = _DropdownPage([
        {"selector": "#age", "label": "Are you over the age of 18?", "current": "Select One"},
        {"selector": "#permitted", "label": permitted, "current": "Select One"},
    ])
    calls: list[tuple[str, str, str]] = []

    def select(_page, selector, value, *, key):
        calls.append((selector, value, key))
        for item in page.items:
            if item["selector"] == selector:
                item["current"] = value
        if selector == "#permitted":
            page.items.append(dict(proof))
        return True

    fields = {"country": "United States", "authorized_to_work": "Yes", "over_18": "Yes"}
    workday_flow.fill_dropdowns(page, fields, select=select)
    assert calls == [
        ("#age", "Yes", "over_18"),
        ("#permitted", "Yes", "authorized_to_work"),
        ("#proof", "Yes", "authorized_to_work"),
    ]
    # Answered "Yes", the question is not a Country that reads wrong.
    assert workday_flow.country_mismatch(page, fields) is None


def test_fill_dropdowns_keeps_an_existing_choice():
    from resume_tailor.apply import ats_hints

    page = _DropdownPage([{"selector": "#address--countryRegion", "label": "State", "current": "Texas"}])
    calls: list = []
    workday_flow.fill_dropdowns(
        page, {"state": "California"},
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
        page, {"how_heard": "LinkedIn"}, select=select,
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


def test_fill_prompts_leaves_the_skills_prompt_to_fill_skills(monkeypatch):
    from resume_tailor.apply import questions

    # Even a Skills prompt keyed to a known fact is `fill_skills`' to fill.
    monkeypatch.setattr(workday_flow.questions, "classify", lambda _q: questions.Match("skills"))
    page = _PromptPage([{"input_id": "skills--skills", "field": "formField-skills", "label": "Skills", "chips": 0}])
    calls: list = []
    workday_flow.fill_prompts(
        page, {"skills": "Python"}, select=lambda *a, **k: calls.append(a) or True,
    )
    assert calls == []


class _TermSearchPage:
    """A Workday prompt whose results depend on the typed term (school search)."""

    def __init__(self, results_by_term: dict[str, list[str]]) -> None:
        self.results_by_term = results_by_term
        self.term = ""
        self.typed: list[str] = []
        self.chips: list[str] = []

    def evaluate(self, script: str, arg: object = None) -> object:
        return list(self.chips)

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def _results(self) -> list[str]:
        return list(self.results_by_term.get(self.term, []))

    def locator(self, selector: str) -> SimpleNamespace:
        page = self
        if "promptOption" in selector:
            return SimpleNamespace(
                all_inner_texts=page._results,
                nth=lambda i: SimpleNamespace(click=lambda timeout=None: page.chips.append(page._results()[i])),
            )

        def fill(value: str, timeout: int | None = None) -> None:
            page.term = value
            if value:
                page.typed.append(value)

        return SimpleNamespace(first=SimpleNamespace(fill=fill, press=lambda key: None))


def test_select_prompt_searches_the_campus_when_the_full_school_name_finds_nothing():
    page = _TermSearchPage({
        "University of California - Irvine": ["No Items."],
        "Irvine": ["Irvine Valley College", "University of California, Irvine"],
    })
    assert workday_flow.select_prompt(page, "education-1--schoolName", "University of California - Irvine", key="school")
    assert page.typed[:2] == ["University of California - Irvine", "Irvine"]
    assert page.chips == ["University of California, Irvine"]


def test_select_prompt_leaves_a_tie_for_review():
    page = _TermSearchPage({
        "Irvine": ["University of California Irvine (UCI)", "University of California Irvine Extension"],
    })
    assert not workday_flow.select_prompt(page, "education-1--schoolName", "University of California - Irvine", key="school")
    assert page.chips == []


def test_fill_prompts_falls_back_to_other_when_the_source_is_not_listed():
    from resume_tailor.apply import ats_hints

    page = _PromptPage([{"input_id": "source--source", "label": "How Did You Hear About Us?", "chips": 0}])
    tried: list[str] = []

    def select(_page, _input_id, value, *, key):
        tried.append(value)
        return value == "Other"

    committed = workday_flow.fill_prompts(
        page, {"how_heard": "LinkedIn"}, select=select,
    )
    assert tried == ["LinkedIn", "Other"]
    assert [item["value"] for item in committed] == ["Other"]


def test_country_mismatch_reads_a_wrong_saved_country():
    from resume_tailor.apply import ats_hints

    def page_with(current: str) -> SimpleNamespace:
        items = [{"selector": "#country--country", "label": "Country", "current": current, "required": True}]
        return SimpleNamespace(evaluate=lambda script, arg=None: [dict(i) for i in items])

    fields = {"country": "United States"}
    assert workday_flow.country_mismatch(page_with("Vietnam"), fields) == "Vietnam"
    assert workday_flow.country_mismatch(page_with("United States of America"), fields) is None
    assert workday_flow.country_mismatch(page_with("Select One"), fields) is None
    assert workday_flow.country_mismatch(page_with("Vietnam"), {}) is None


def test_fill_dropdowns_reports_a_country_it_could_not_change():
    from resume_tailor.apply import ats_hints

    class _Page:
        def evaluate(self, script, arg=None):
            assert script == workday_flow.DROPDOWNS_JS
            return [{"selector": "#country", "label": "Country", "current": "Vietnam", "required": True}]

        def wait_for_timeout(self, _ms):
            pass

    review: list[str] = []
    committed = workday_flow.fill_dropdowns(
        _Page(), {"country": "United States"},
        select=lambda *a, **k: False, review=review,
    )
    assert committed == []
    assert review == ["Country is Vietnam; profile says United States"]


class _PhoneCodePage:
    def __init__(self, results: list[str]) -> None:
        self.results = results
        self.chips: list[str] = []

    def evaluate(self, script: str, arg: object = None) -> object:
        assert script == workday_flow.PHONE_CODE_JS
        return {"chips": list(self.chips), "input_id": "phoneNumber--countryPhoneCode"}

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def locator(self, selector: str) -> SimpleNamespace:
        page = self
        if "promptOption" in selector:
            return SimpleNamespace(
                all_inner_texts=lambda: list(page.results),
                nth=lambda i: SimpleNamespace(click=lambda timeout=None: page.chips.append(page.results[i])),
            )
        return SimpleNamespace(fill=lambda value, timeout=None: None, press=lambda key: None)


def test_phone_code_is_the_whole_region_not_any_region_containing_it():
    # Live Oak: "United States" + "+1" also matched the Minor Outlying Islands, so the
    # choice was ambiguous and the required phone code stayed empty.
    page = _PhoneCodePage([
        "United States Minor Outlying Islands (+1)",
        "United States of America (+1)",
    ])
    assert workday_flow.ensure_phone_code(page, "United States", "+1") is True
    assert page.chips == ["United States of America (+1)"]


def test_select_prompt_accepts_the_option_enter_committed_itself():
    # Upbound's Field of Study: Enter on a one-result search commits it with no list.
    page = _TermSearchPage({})
    original = page.locator

    def locator(selector: str) -> SimpleNamespace:
        found = original(selector)
        if "promptOption" in selector:
            return found

        def press(key: str) -> None:
            if key == "Enter" and page.term == "Computer Science":
                page.chips.append("Computer and Information Science")

        return SimpleNamespace(first=SimpleNamespace(fill=found.first.fill, press=press))

    page.locator = locator
    assert workday_flow.select_prompt(page, "education-1--fieldOfStudy", "Computer Science", key="major")
    assert page.chips == ["Computer and Information Science"]


class _SavingPage:
    """A step that saves slowly: the button stays disabled, then the next step shows."""

    def __init__(self, saved_after_ms: int) -> None:
        self.elapsed = 0
        self.saved_after_ms = saved_after_ms

    def evaluate(self, script, *_args):
        if script == workday_flow._SAVING_JS:  # noqa: SLF001
            return self.elapsed < self.saved_after_ms
        step = "Application Questions" if self.elapsed >= self.saved_after_ms else "My Experience"
        return {"ids": ["progressBarActiveStep"], "step": step, "alerts": []}

    def wait_for_timeout(self, ms):
        self.elapsed += ms


def test_a_slow_save_is_waited_for_while_the_button_is_disabled(monkeypatch):
    # F5 (2026-09): My Experience with five rows saved after 15 s.
    monkeypatch.setattr(workday_flow, "snapshot", lambda p: p.evaluate("snapshot"))
    monkeypatch.setattr(workday_flow, "active_step", lambda snap: snap["step"])
    page = _SavingPage(saved_after_ms=25_000)
    monkeypatch.setattr(workday_flow.time, "monotonic", lambda: page.elapsed / 1000)
    assert workday_flow.wait_for_step_change(page, "My Experience", deadline=1e9, timeout_s=15)
    # A save that never finishes still gives up, at three times the timeout.
    stuck = _SavingPage(saved_after_ms=10**9)
    monkeypatch.setattr(workday_flow.time, "monotonic", lambda: stuck.elapsed / 1000)
    assert not workday_flow.wait_for_step_change(stuck, "My Experience", deadline=1e9, timeout_s=15)
    assert stuck.elapsed <= 46_000


class _Tab:
    """A tab in the shared context; ``opener`` is the page that opened it, if any."""

    def __init__(self, opener: object = None) -> None:
        self._opener = opener

    def opener(self) -> object:
        return self._opener

    def is_closed(self) -> bool:
        return False

    def wait_for_load_state(self, *_args: object, **_kwargs: object) -> None:
        return None


def test_new_tab_ignores_a_tab_another_fill_opened(clock):
    """Parallel fills share one context: only a tab this page opened is followed."""
    page, other_fill = _Tab(), _Tab()
    before = [page, other_fill]
    for foreign in (_Tab(opener=other_fill), _Tab(opener=None)):
        context = SimpleNamespace(pages=[*before, foreign])
        assert workday_flow._new_tab(page, context, before, clock.now + 60) is page  # noqa: SLF001
    own = _Tab(opener=page)
    context = SimpleNamespace(pages=[*before, _Tab(opener=other_fill), own])
    assert workday_flow._new_tab(page, context, before, clock.now + 60) is own  # noqa: SLF001
