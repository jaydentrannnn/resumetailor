"""Wizard screen names (`apply/wizards.py`, plan P4-A): pure rules over page snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from resume_tailor.apply.ats import workday_page
from resume_tailor.apply.forms import wizards

_FIXTURES = Path(__file__).parents[2] / "fixtures"
_SCREENS = json.loads((_FIXTURES / "wizards" / "screens.json").read_text(encoding="utf-8"))
_SCREENS.pop("_source")
_WORKDAY = json.loads((_FIXTURES / "workday" / "screens.json").read_text(encoding="utf-8"))
_WORKDAY.pop("_source")

_CASES = [
    pytest.param(ats, snap, id=f"{ats}/{name}")
    for ats, screens in _SCREENS.items()
    for name, snap in screens.items()
]


@pytest.mark.parametrize(("ats", "snap"), _CASES)
def test_platform_screens(ats, snap):
    adapter = wizards.for_ats(ats) or wizards.WizardAdapter()
    assert adapter.classify(snap) == snap["expect"]
    assert adapter.is_final_step(snap) == (snap["expect"] == "review")


@pytest.mark.parametrize("name", sorted(_WORKDAY))
def test_workday_keeps_its_own_rules(name):
    """No behaviour change: the adapter only renames `workday_page.classify`'s states."""
    snap = _WORKDAY[name]
    state = workday_page.classify(snap)
    expected = {"start_dialog": "posting", "auth_chooser": "sign_in"}.get(state, state)
    assert wizards.WorkdayWizard().classify(snap) == expected


def test_workday_review_step_is_final():
    snap = {**_WORKDAY["my_information"], "active_step": "current step 6 of 6 Review"}
    assert workday_page.classify(snap) == "apply_form"
    assert wizards.WorkdayWizard().classify(snap) == "review"
    assert wizards.WorkdayWizard().is_final_step(snap)


def test_single_page_forms_have_no_wizard():
    for ats in ("greenhouse", "lever", "ashby", "smartrecruiters", "", "other"):
        assert wizards.for_ats(ats) is None
    assert isinstance(wizards.for_ats("Taleo"), wizards.TaleoWizard)


@pytest.mark.parametrize(
    ("state", "status", "words"),
    [
        ("sign_in", "awaiting_review", "Sign in to Taleo"),
        ("create_account", "awaiting_review", "Create your Taleo account"),
        ("otp", "awaiting_otp", "code Taleo emailed"),
        ("verify_email", "awaiting_otp", "code Taleo emailed"),
        ("unavailable", "fill_failed", "no longer available"),
    ],
)
def test_screens_the_applicant_handles(state, status, words):
    stop = wizards.TaleoWizard().stop_for(state)
    assert stop is not None
    assert stop.status == status
    assert words in stop.message


@pytest.mark.parametrize("state", ["apply_form", "review", "posting", "confirmation", "unknown"])
def test_screens_the_fill_loop_handles(state):
    assert wizards.TaleoWizard().stop_for(state) is None


class _Frame:
    def __init__(self, snap):
        self.snap = snap

    def evaluate(self, _script):
        return self.snap


class _Page(_Frame):
    url = "https://acme.icims.com/jobs/1/job"

    def __init__(self, snap, frame=None):
        super().__init__(snap)
        self._frame = frame

    def frame(self, name):
        assert name == "icims_content_iframe"
        return self._frame


def test_icims_reads_the_form_frame():
    outer = {"fields": 0, "text": "Careers at Acme", "buttons": []}
    inner = _SCREENS["icims"]["sign_in"]
    assert wizards.IcimsWizard().detect_state(_Page(outer, _Frame(inner))) == "sign_in"
    assert wizards.IcimsWizard().detect_state(_Page(outer)) == "unknown"


def test_a_page_that_cannot_be_read_is_unknown():
    class _Navigating:
        url = "https://acme.taleo.net/"

        def evaluate(self, _script):
            raise RuntimeError("Execution context was destroyed")

    assert wizards.TaleoWizard().detect_state(_Navigating()) == "unknown"


def _launch(playwright):
    try:
        return playwright.chromium.launch(headless=True, channel="msedge")
    except Exception:
        path = os.environ.get("PW_CHROMIUM_PATH")
        return playwright.chromium.launch(headless=True, executable_path=path or None)


@pytest.fixture
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as playwright:
            browser = _launch(playwright)
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def test_snapshot_script_reads_a_real_page(page):
    page.set_content("""
      <ol class="wizard-steps"><li>1 - Personal Information</li>
        <li class="active">5 - Review and Submit</li></ol>
      <h2>Review and Submit</h2>
      <label>E-signature <input name="sig"></label>
      <input type="hidden" name="token">
      <button>Submit</button>
    """)
    adapter = wizards.TaleoWizard()
    snap = adapter.snapshot(page)
    assert snap["active_step"] == "5 - Review and Submit"
    assert snap["fields"] == 1
    assert "Submit" in snap["buttons"]
    assert adapter.classify(snap) == "review"

    page.set_content("""
      <h2>Returning User</h2><input name="user"><input type="password" name="pw">
      <button>Log In</button>
    """)
    assert adapter.detect_state(page) == "sign_in"


def test_a_posting_page_with_a_language_picker_is_still_the_posting(page):
    # iCIMS (2026-09): the footer language select made the job page look like the form,
    # so the fill never pressed "Apply for this job online".
    page.set_content("""
      <h1>Research Intern, 2027 Summer</h1>
      <a class="iCIMS_Anchor iCIMS_ApplyOnlineButton" title="Apply for this job online"
         href="#" onclick="document.body.dataset.applied = 'yes'; return false;">Apply for this job online</a>
      <select id="footer-language-selector"><option>English</option></select>
    """)
    adapter = wizards.IcimsWizard()
    assert adapter.detect_state(page) == "posting"
    assert adapter.enter(page) is True
    assert page.evaluate("document.body.dataset.applied") == "yes"


def test_a_page_without_an_apply_control_cannot_be_entered(page):
    page.set_content("<h1>Careers</h1><select><option>English</option></select>")
    assert wizards.IcimsWizard().enter(page) is False
