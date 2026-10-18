"""`wizards.GenericScreens`: the screens a site with no adapter can show that the
applicant must handle (sign in, create an account, a code, a closed posting), each on
clear evidence only."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.forms import wizards

_FORMS = Path(__file__).parents[2] / "fixtures/forms"


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


@pytest.mark.parametrize(("fixture", "state"), [
    ("avature_login.html", "sign_in"),
    ("eightfold_code_text.html", "apply_form"),  # code wording in the text, no code box
    ("generic_code_boxes.html", "otp"),
    ("greenhouse.html", "apply_form"),
])
def test_generic_screen_on_captured_pages(page, fixture, state):
    page.set_content((_FORMS / fixture).read_text(encoding="utf-8"))
    assert wizards.GenericScreens().detect_state(page) == state


@pytest.mark.parametrize("ats", ["oracle", "icims", "taleo", "successfactors"])
def test_platform_adapters_see_split_code_boxes_too(page, ats):
    adapter = wizards.for_fill(ats)
    page.set_content((_FORMS / "generic_code_boxes.html").read_text(encoding="utf-8"))
    assert adapter.detect_state(page) == "otp"
    page.set_content((_FORMS / "greenhouse.html").read_text(encoding="utf-8"))
    assert adapter.detect_state(page) != "otp"


def test_code_boxes_count_as_one_control(page):
    page.set_content((_FORMS / "generic_code_boxes.html").read_text(encoding="utf-8"))
    snap = page.evaluate(wizards.GENERIC_SNAPSHOT_JS)
    assert snap["code_control"] and snap["code_inputs"] == snap["fields"] == 6


def _snap(**values):
    return {"text": "", "fields": 0, "password_inputs": 0, "headings": [], "buttons": [], **values}


@pytest.mark.parametrize(("snap", "state"), [
    (_snap(fields=3, password_inputs=2, headings=["Register"]), "create_account"),
    (_snap(fields=2, password_inputs=1, headings=["Create your account"], buttons=["Continue"]),
     "create_account"),
    (_snap(fields=2, password_inputs=1, headings=["Create your account"], buttons=["Sign in"]),
     "sign_in"),
    # A long form that happens to hold a password box is still a form.
    (_snap(fields=12, password_inputs=1), "apply_form"),
    (_snap(fields=9, code_control=True, code_inputs=1), "apply_form"),
    (_snap(text="This job is no longer available."), "unavailable"),
    (_snap(text="This job is no longer available.", fields=5), "apply_form"),
    (_snap(text="You have already applied for this position."), "already_applied"),
    (_snap(text="Summary\nReview your application"), "unknown"),
])
def test_generic_classify_needs_clear_evidence(snap, state):
    assert wizards.GenericScreens().classify(snap) == state


def test_sites_without_an_adapter_get_the_generic_screens():
    assert isinstance(wizards.for_fill("lever"), wizards.GenericScreens)
    assert not isinstance(wizards.for_fill("oracle"), wizards.GenericScreens)
    assert wizards.GenericScreens().enter(None) is False
