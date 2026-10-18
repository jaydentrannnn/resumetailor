"""Fill never enters an application through another site's account ("Apply with
LinkedIn"): the entry finder skips those routes and the click guard refuses them."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import fill_buttons, wizards

_FIXTURE = (Path(__file__).parents[2] / "fixtures/forms/breezy_social_apply.html").read_text(encoding="utf-8")


@pytest.fixture
def page():
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True, channel="msedge")
            except Exception:
                browser = playwright.chromium.launch(
                    headless=True, executable_path=os.environ.get("PW_CHROMIUM_PATH") or None
                )
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


@pytest.mark.parametrize("text", [
    "Apply with LinkedIn", "Apply using Indeed", "Continue with Google", "Sign in with Apple",
    "Autofill with   LinkedIn", "Import from LinkedIn", "Apply via your LinkedIn",
])
def test_social_routes_are_recognised(text):
    assert clicks.is_social_apply(text)


@pytest.mark.parametrize("text", ["Apply", "LinkedIn", "Apply now", "LinkedIn Profile URL",
                                  "How did you hear about us? LinkedIn", "Submit application"])
def test_ordinary_controls_are_not(text):
    assert not clicks.is_social_apply(text)


class _Loc:
    def __init__(self, text: str) -> None:
        self.text, self.clicked = text, False

    def evaluate(self, _script, timeout=None):
        return self.text

    def click(self, **_kwargs):
        self.clicked = True


@pytest.mark.parametrize("purpose", ["enter", "advance", "select", "auth", "dismiss"])
def test_the_click_guard_refuses_a_social_route_for_every_purpose(purpose):
    loc = _Loc("Apply with LinkedIn")
    with pytest.raises(clicks.SocialApplyRefused):
        clicks.safe_click(loc, purpose=purpose)
    assert not loc.clicked
    plain = _Loc("LinkedIn")  # a "How did you hear" option
    clicks.safe_click(plain, purpose="select")
    assert plain.clicked


@pytest.mark.parametrize("ats", ["other", "greenhouse", "lever"])
def test_entry_skips_social_routes_for_the_plain_apply_control(page, ats):
    # Greenhouse's and Lever's hints include ``text=Apply``, a substring match.
    page.set_content(_FIXTURE)
    fill_buttons.find_and_click_apply(page, ats)
    assert page.evaluate("window.clicked") == "apply"


def test_a_page_with_only_social_routes_gets_no_entry_click(page):
    page.set_content(_FIXTURE)
    page.evaluate("document.querySelector('a[onclick*=apply]:not(.linkedin)').remove()")
    fill_buttons.find_and_click_apply(page, "other")
    assert page.evaluate("window.clicked") is None


def test_wizard_entry_skips_a_social_control_titled_apply(page):
    page.set_content(_FIXTURE.replace(">Apply</a>", ">Apply for this job online</a>"))
    page.evaluate("document.querySelector('.linkedin').setAttribute('title', 'Apply')")
    assert wizards.IcimsWizard().enter(page) is True
    assert page.evaluate("window.clicked") == "apply"
