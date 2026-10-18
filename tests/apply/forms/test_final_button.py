"""The final-button finder and the click guard agree on what submits an application."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import fill_buttons

_FIXTURE = (Path(__file__).parents[2] / "fixtures/forms/jobvite_send_application.html").read_text(encoding="utf-8")

FINAL = ["Submit", "Submit Application", "Submit my application", "Send Application",
         "Send my application", "Complete Application", "Complete my application",
         "Complete your application", "Complete and submit application",
         "Complete and submit my application", "Apply and submit", "Finish",
         "Finish application", "Finish your application"]
NOT_FINAL = ["Save and finish later", "Review and submit", "Next", "Apply", "Submit later",
             "Submit a referral", "Continue"]


@pytest.mark.parametrize("name", FINAL)
def test_every_final_name_reads_as_submit_to_the_guard(name):
    assert clicks.FINAL_SUBMIT_NAME.match(name)
    assert clicks.reads_as_submit(name)


@pytest.mark.parametrize("name", NOT_FINAL)
def test_other_buttons_are_not_the_final_button(name):
    assert not clicks.FINAL_SUBMIT_NAME.match(name)


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


def test_a_final_button_with_a_next_class_is_never_an_advance(page):
    page.set_content('<form><button class="btn-next">Complete my application</button></form>')
    found = fill_buttons._find_submit_button(page, {})
    assert found is not None
    assert fill_buttons._find_advance_button(page) is None
    with pytest.raises(clicks.SubmitRefused):
        clicks.safe_click(found, purpose="advance")


def test_send_application_is_found_and_finish_later_is_not(page):
    page.set_content(_FIXTURE)
    found = fill_buttons._find_submit_button(page, {})
    assert found is not None and found.inner_text() == "Send Application"
    assert clicks.is_submit_like(found)
    assert fill_buttons._find_advance_button(page) is None
