"""`filler.js` against real DOM shapes captured from live forms (runs in installed Edge)."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply import ats_hints, field_matcher

_FILLER = (Path(__file__).parents[1] / "src/resume_tailor/apply/filler.js").read_text(encoding="utf-8")
_SYNONYMS = [list(pair) for pair in ats_hints.SYNONYMS]


@pytest.fixture
def page():
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, channel="msedge")
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def _fill(page, fields: dict[str, str], hints: dict[str, str] | None = None) -> dict:
    return page.evaluate(_FILLER, {"fields": fields, "hints": hints or {}, "synonyms": _SYNONYMS,
                                   "eeo": field_matcher.eeo_patterns(fields)})


# Epic Games' careers form (2026-09): no <label for>, no aria, placeholder "Enter"; the
# question is bare text beside the control, with U+2060 around the required star.
_EPIC = """
<div><h3>Application Information</h3>
  <div><div>First Name⁠*⁠:</div><div><div><input type="text" name="questions.first_name" placeholder="Enter"></div></div></div>
  <div><div>Last Name⁠*⁠:</div><div><div><input type="text" name="questions.last_name" placeholder="Enter"></div></div></div>
  <div><div>Preferred First Name⁠⁠:</div><div><div><input type="text" name="questions.preferred_name" placeholder="Enter"></div></div></div>
  <div><div>Email⁠*⁠:</div><div><div><input type="text" name="questions.email" placeholder="Enter"></div></div></div>
  <div><div>How did you hear about this job posting?⁠*⁠:</div>
    <div class="dropdown-autocomplete"><div class="css-l772dy-control"><div class="css-1-placeholder">Select</div>
      <div><input type="text" id="react-select-3-input"></div></div></div>
    <div class="helper-text error">This section is required</div>
    <span aria-live="polite">0 results available.</span></div>
  <div><div>Have you previously worked for Epic Games or any of its subsidiaries in any capacity (e.g., as a contractor)?⁠*⁠:</div>
    <div class="dropdown-autocomplete"><div class="css-l772dy-control"><div class="css-1-placeholder">Select</div>
      <div><input type="text" id="react-select-2-input"></div></div></div></div>
  <div><h3>Education</h3>
    <div><div>Start Date (Year)⁠*⁠:</div><input type="number" name="educations[0].start_date.year" placeholder="YYYY"></div>
    <div><div>Start Date (Month)⁠⁠:</div><input type="number" name="educations[0].start_date.month" placeholder="MM"></div>
    <div><div>End Date (Year)⁠*⁠:</div><input type="number" name="educations[0].end_date.year" placeholder="YYYY"></div>
  </div>
  <div><div>Gender Identity⁠*⁠:</div>
    <div><label><input type="radio" name="demographicQuestions.optionID1" value="1">Man</label></div>
    <div><label><input type="radio" name="demographicQuestions.optionID1" value="2">I don't wish to answer</label></div>
  </div>
</div>
"""


def test_epic_form_fills_names_from_bare_text_labels(page):
    page.set_content(_EPIC)
    result = _fill(page, {
        "first_name": "Alex Jordan Lee", "last_name": "Tran", "preferred_name": "Jayden",
        "email": "a@example.com", "how_heard": "LinkedIn",
        "education_start_month": "2023-09", "graduation_month": "2027-06",
        "gender": "I don't wish to answer",
    })
    assert page.locator("input[name='questions.first_name']").input_value() == "Alex Jordan Lee"
    assert page.locator("input[name='questions.last_name']").input_value() == "Tran"
    assert page.locator("input[name='questions.preferred_name']").input_value() == "Jayden"
    assert page.locator("input[name='questions.email']").input_value() == "a@example.com"
    # Education dates split into year/month boxes, never the availability answer.
    assert page.locator("input[name='educations[0].start_date.year']").input_value() == "2023"
    assert page.locator("input[name='educations[0].start_date.month']").input_value() == "9"
    assert page.locator("input[name='educations[0].end_date.year']").input_value() == "2027"
    # A radio option's text is its wrapping <label>.
    assert page.locator("input[value='2']").is_checked()
    labels = {item["label"] for item in result["filled"]}
    assert {"First Name", "Last Name", "Preferred First Name", "Email"} <= labels
    # React Select without role=combobox is a dropdown left for the observed-option pass.
    dropdown = next(item for item in result["leftovers"] if item["selector"] == "#react-select-3-input")
    assert dropdown["type"] == "combobox"
    assert dropdown["key"] == "how_heard"
    assert dropdown["label"] == "How did you hear about this job posting?"
    # A long question that says "capacity" is not the City field.
    previous = next(item for item in result["leftovers"] if item["selector"] == "#react-select-2-input")
    assert previous["key"] is None
    assert previous["label"].startswith("Have you previously worked for Epic Games")


def test_workday_generic_upload_reports_its_hint_and_section(page):
    page.set_content("""
      <div><h3>Resume/CV</h3><div data-automation-id="attachments-FileUpload">
        <label for="f">Upload a file (5MB max)*</label>
        <input id="f" type="file" data-automation-id="file-upload-input-ref"></div></div>
    """)
    result = _fill(page, {}, {"input[data-automation-id='file-upload-input-ref']": "resume_upload"})
    [upload] = result["file_inputs"]
    assert upload["hint_key"] == "resume_upload"
    assert upload["section"] == "Resume/CV"


def test_how_heard_without_linkedin_picks_other_and_specifies(page):
    page.set_content("""
      <label for="src">How did you hear about us?</label>
      <select id="src"><option value="">Select</option><option>Indeed</option><option>Other</option></select>
      <label for="spec">If other, please specify</label><input id="spec">
      <label for="race">Race</label><select id="race"><option value="">Select</option><option>Other</option></select>
      <label for="race-spec">If other, please specify</label><input id="race-spec">
    """)
    _fill(page, {"how_heard": "LinkedIn", "how_heard_detail": "LinkedIn"})
    assert page.locator("#src").input_value() == "Other"
    assert page.locator("#spec").input_value() == "LinkedIn"
    # "Please specify" after any other question is not the source detail.
    assert page.locator("#race-spec").input_value() == ""


def test_degree_select_takes_the_abbreviation_of_the_named_degree(page):
    page.set_content("""
      <label for="deg">Degree</label>
      <select id="deg"><option value="">Select</option><option>HS</option><option>BA</option>
        <option value="bs">B.S.</option><option>MS</option></select>
      <label for="lvl">Highest degree</label>
      <select id="lvl"><option value="">Select</option><option>Associate's Degree</option>
        <option>Bachelor's Degree</option><option>Master's Degree</option></select>
    """)
    _fill(page, {"degree_level": "Bachelors", "degree_name": "Bachelor of Science"})
    assert page.locator("#deg").input_value() == "bs"
    assert page.locator("#lvl").input_value() == "Bachelor's Degree"


def test_a_recognised_question_with_a_blank_profile_fact_names_its_field(page):
    page.set_content("""
      <label for="auth">Are you legally authorized to work in the United States?</label>
      <select id="auth" required><option value="">Select</option><option>Yes</option><option>No</option></select>
    """)
    [leftover] = _fill(page, {})["leftovers"]
    assert leftover["key"] == "authorized_to_work"
    assert leftover["reason"] == "Profile field is blank"
    assert page.locator("#auth").input_value() == ""


def test_eligibility_selects_answer_from_the_profile_not_the_country(page):
    """The same patterns run as JavaScript regexes in the page."""
    page.set_content("""
      <label for="age">Are you over the age of 18?</label>
      <select id="age"><option value="">Select</option><option>Yes</option><option>No</option></select>
      <label for="perm">Are you legally permitted to work in the country where this job is located?</label>
      <select id="perm"><option value="">Select</option><option>Yes</option><option>No</option></select>
      <label for="proof">If hired, can you provide proof of eligibility?</label>
      <select id="proof"><option value="">Select</option><option>Yes</option><option>No</option></select>
      <label for="minor">Are you under 18?</label>
      <select id="minor"><option value="">Select</option><option>Yes</option><option>No</option></select>
    """)
    _fill(page, {"over_18": "Yes", "authorized_to_work": "Yes", "country": "United States"})
    assert page.locator("#age").input_value() == "Yes"
    assert page.locator("#perm").input_value() == "Yes"
    assert page.locator("#proof").input_value() == "Yes"
    assert page.locator("#minor").input_value() == ""


def test_disability_checkboxes_tick_only_the_answer(page):
    # Workday's CC-305 form: one unnamed checkbox per answer, not yes/no switches.
    page.set_content("""
      <input type="checkbox" id="d0"><label for="d0">Yes, I have a disability, or have had one in the past</label>
      <input type="checkbox" id="d1"><label for="d1">No, I do not have a disability and have not had one in the past</label>
      <input type="checkbox" id="d2"><label for="d2">I do not want to answer</label>
    """)
    _fill(page, {"disability_status": "No"})
    assert [page.locator(f"#d{i}").is_checked() for i in range(3)] == [False, True, False]


def test_a_named_checkbox_group_ticks_the_matching_option(page):
    page.set_content("""
      <fieldset><legend>Veteran status</legend>
        <label><input type="checkbox" name="vet" value="a">I am not a protected veteran</label>
        <label><input type="checkbox" name="vet" value="b">I identify as a protected veteran</label>
      </fieldset>
      <label for="g">Gender</label><input id="g" type="text">
    """)
    _fill(page, {"veteran_status": "No", "gender": "decline"})
    assert page.locator("input[value='a']").is_checked()
    assert not page.locator("input[value='b']").is_checked()
    # Declining is a choice, never typed into a text box.
    assert page.locator("#g").input_value() == ""


def test_decline_selects_the_forms_decline_option(page):
    page.set_content("""
      <label for="dis">Disability status</label>
      <select id="dis"><option value="">Select</option><option>Yes, I have a disability</option>
        <option>No, I do not have a disability</option><option>I do not want to answer</option></select>
    """)
    _fill(page, {"disability_status": "decline"})
    assert page.locator("#dis").input_value() == "I do not want to answer"
