"""`filler.js` against real DOM shapes captured from live forms (runs in installed Edge)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.ats import ats_hints
from resume_tailor.apply.forms import field_matcher

_FILLER = (Path(__file__).parents[3] / "src/resume_tailor/apply/forms/filler.js").read_text(encoding="utf-8")
_READINESS = (Path(__file__).parents[3] / "src/resume_tailor/apply/forms/filler_readiness.js").read_text(
    encoding="utf-8"
)
_SYNONYMS = [list(pair) for pair in ats_hints.SYNONYMS]


def _launch(playwright):
    """Installed Edge, else Playwright's Chromium (``PW_CHROMIUM_PATH`` names its binary)."""
    try:
        return playwright.chromium.launch(headless=True, channel="msedge")
    except Exception:
        path = os.environ.get("PW_CHROMIUM_PATH")
        return playwright.chromium.launch(headless=True, executable_path=path or None)


@pytest.fixture
def page():
    try:
        with sync_playwright() as playwright:
            browser = _launch(playwright)
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
        "first_name": "Alex Jordan", "last_name": "Doe", "preferred_name": "AJ",
        "email": "a@example.com", "how_heard": "LinkedIn",
        "education_start_month": "2023-09", "graduation_month": "2027-06",
        "gender": "I don't wish to answer",
    })
    assert page.locator("input[name='questions.first_name']").input_value() == "Alex Jordan"
    assert page.locator("input[name='questions.last_name']").input_value() == "Doe"
    assert page.locator("input[name='questions.preferred_name']").input_value() == "AJ"
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
    _fill(page, {"degree_level": "Bachelors", "degree_name": "Bachelor of Science",
                 "highest_education_obtained": "Bachelors"})
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


#: CACI's veteran question (2026-09): the VEVRAA preamble, then four answers.
_VEVRAA_LABEL = ("If you believe you belong to any of the categories of protected veterans listed above "
                 "(including veterans entitled to compensation), please indicate by checking the appropriate box.")


def test_a_four_way_veteran_select_takes_the_profile_category(page):
    page.set_content(f"""
      <label for="vet">{_VEVRAA_LABEL}</label>
      <select id="vet"><option value="">Select One</option>
        <option>I IDENTIFY AS ONE OR MORE OF THE CLASSIFICATIONS OF PROTECTED VETERANS</option>
        <option>I IDENTIFY AS A VETERAN, JUST NOT A PROTECTED VETERAN</option>
        <option>I AM NOT A VETERAN</option><option>I DO NOT WISH TO SELF-IDENTIFY</option></select>
    """)
    _fill(page, {"veteran_status": "not_veteran", "salary_expectation": "100000"})
    assert page.locator("#vet").input_value() == "I AM NOT A VETERAN"


def test_veteran_checkboxes_fall_back_a_tier_without_ticking_two(page):
    # No "I am not a veteran" box: the non-veteran is "not a protected veteran", and the
    # quoted "compensation" does not make the question a salary box.
    page.set_content(f"""
      <fieldset><legend>{_VEVRAA_LABEL}</legend>
        <input type="checkbox" id="v0"><label for="v0">I identify as one or more of the classifications of protected veteran</label>
        <input type="checkbox" id="v1"><label for="v1">I am not a protected veteran</label>
        <input type="checkbox" id="v2"><label for="v2">I don't wish to answer</label>
      </fieldset>
    """)
    _fill(page, {"veteran_status": "not_veteran", "salary_expectation": "100000"})
    assert [page.locator(f"#v{i}").is_checked() for i in range(3)] == [False, True, False]


def test_decline_selects_the_forms_decline_option(page):
    page.set_content("""
      <label for="dis">Disability status</label>
      <select id="dis"><option value="">Select</option><option>Yes, I have a disability</option>
        <option>No, I do not have a disability</option><option>I do not want to answer</option></select>
    """)
    _fill(page, {"disability_status": "decline"})
    assert page.locator("#dis").input_value() == "I do not want to answer"


# A web-component form (SmartRecruiters' apply page): every input sits in an open shadow
# root, with its <label for> beside it inside the same root.
_SHADOW = """
<form>
  <label for="light">Email</label><input id="light" type="email">
  <spl-field id="first"></spl-field>
  <spl-field id="phone"></spl-field>
  <spl-choice id="auth"></spl-choice>
  <spl-closed id="secret"></spl-closed>
</form>
<script>
  const open = (host, html) => { host.attachShadow({ mode: "open" }).innerHTML = html; };
  open(document.getElementById("first"),
       '<label for="f">First name</label><input id="f" required>');
  open(document.getElementById("phone"),
       '<span id="ph-label">Phone number</span><input id="p" aria-labelledby="ph-label">');
  open(document.getElementById("auth"),
       '<div><div>Are you legally authorized to work in the United States?</div>' +
       '<label><input type="radio" name="auth" id="ay" value="yes">Yes</label>' +
       '<label><input type="radio" name="auth" id="an" value="no">No</label></div>');
  document.getElementById("secret").attachShadow({ mode: "closed" }).innerHTML =
    '<label for="s">Last name</label><input id="s">';
</script>
"""


def test_shadow_dom_inputs_are_labelled_and_filled(page):
    page.set_content(_SHADOW)
    result = _fill(page, {
        "email": "a@example.com", "first_name": "Alex", "phone": "555 010 0000",
        "last_name": "Doe", "authorized_to_work": "Yes",
    })
    # Playwright's CSS locators pierce open roots, so the reported selectors resolve.
    assert page.locator("#light").input_value() == "a@example.com"
    assert page.locator("#f").input_value() == "Alex"
    assert page.locator("#p").input_value() == "555 010 0000"
    assert page.locator("#ay").is_checked()
    labels = {item["label"]: item["selector"] for item in result["filled"]}
    assert labels["First name"] == "#f"
    assert labels["Phone number"] == "#p"
    # A closed root stays hidden, as it is from the page's own scripts.
    assert "Last name" not in labels
    assert not any(item["label"] == "Last name" for item in result["leftovers"])


def test_readiness_sees_empty_required_fields_in_shadow_roots(page):
    page.set_content(_SHADOW)
    assert page.evaluate(_READINESS, {}) == ["First name"]
    page.locator("#f").fill("Alex")
    assert page.evaluate(_READINESS, {}) == []


_PHONES = """
<label for="plain">Phone</label><input id="plain" type="tel">
<label for="intl">Phone (include country code)</label><input id="intl" type="tel">
<label for="pattern">Mobile</label><input id="pattern" type="tel" pattern="^\\+[0-9]{8,15}$">
<div class="phone-group">
  <label for="code">Country code</label>
  <select id="code"><option value="">Select</option><option>+1</option><option>+44</option></select>
  <label for="split">Phone number</label><input id="split" type="tel">
</div>
"""


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("plain", "(555) 010-0000"),
        ("intl", "+15550100000"),
        ("pattern", "+15550100000"),
        ("split", "5550100000"),
    ],
)
def test_phone_takes_the_shape_the_input_asks_for(page, field, expected):
    page.set_content(_PHONES)
    for other in {"plain", "intl", "pattern", "split"} - {field}:
        page.evaluate(f"document.getElementById('{other}').remove()")
    if field != "split":
        page.evaluate("document.querySelector('.phone-group').remove()")
    _fill(page, {
        "phone": "(555) 010-0000", "phone_country_code": "+1",
        "phone_e164": "+15550100000", "phone_national": "5550100000",
    })
    assert page.input_value(f"#{field}") == expected


_OFFICES = """
<fieldset><legend>Which offices would you like to be considered for? (select all that apply)</legend>
  <label><input type="checkbox" name="offices" value="ny" {req}>New York, NY</label>
  <label><input type="checkbox" name="offices" value="sf">San Francisco, CA</label>
  <label><input type="checkbox" name="offices" value="ldn">London (Hybrid)</label>
</fieldset>
"""


def _ticked(page) -> list[str]:
    return page.eval_on_selector_all("input[name=offices]:checked", "els => els.map(e => e.value)")


def test_location_list_ticks_every_preferred_office(page):
    page.set_content(_OFFICES.format(req=""))
    result = _fill(page, {"location_preference": "San Francisco or London; open to remote"})
    assert _ticked(page) == ["sf", "ldn"]
    rows = [row for row in result["filled"] if row["key"] == "location_preference"]
    assert len(rows) == 1 and rows[0]["label"].startswith("Which offices")
    assert not any(row.get("review") for row in result["leftovers"])


def test_location_list_falls_back_to_the_postings_city(page):
    page.set_content(_OFFICES.format(req=""))
    _fill(page, {"location_preference": "Chicago", "posting_location": "New York, New York, United States"})
    assert _ticked(page) == ["ny"]


def test_location_list_guesses_only_when_required_and_flags_it(page):
    page.set_content(_OFFICES.format(req=""))
    optional = _fill(page, {})
    assert _ticked(page) == []
    assert [row["reason"] for row in optional["leftovers"]] == [
        "No listed location matches your location preference"
    ]
    assert optional["required_empty"] == []

    page.set_content(_OFFICES.format(req="required"))
    required = _fill(page, {})
    assert _ticked(page) == ["ny"]
    flagged = [row for row in required["leftovers"] if row.get("review")]
    assert [row["reason"] for row in flagged] == ["Picked the first location; check it"]


_PARSED = """
<label for="fn">First Name</label><input id="fn" value="ADA">
<label for="ln">Last Name</label><input id="ln" value="Lovelace-Byron">
<label for="em">Email</label><input id="em" value="old@school.edu">
<label for="ph">Phone</label><input id="ph" type="tel" value="(555) 010-0000">
<label for="li">LinkedIn Profile</label><input id="li" value="linkedin.com/in/ada/">
<label for="cl">Cover letter</label><textarea id="cl" rows="6">Parsed text</textarea>
<label for="ttl">Current title</label><input id="ttl" value="Analyst">
<label for="city">City</label><input id="city" value="">
"""


def test_correct_mode_puts_back_only_contact_facts_the_parser_changed(page):
    page.set_content(_PARSED)
    fields = {
        "first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com",
        "phone": "555 010 0000", "linkedin_url": "https://www.linkedin.com/in/ada",
        "current_title": "Intern", "city": "Irvine",
    }
    result = page.evaluate(_FILLER, {"fields": fields, "hints": {}, "synonyms": _SYNONYMS, "correct": True})
    corrected = {row["key"]: row["previous"] for row in result["filled"]}
    # Case, phone formatting and URL shape are the same fact; the rest is put back.
    assert corrected == {"last_name": "Lovelace-Byron", "email": "old@school.edu"}
    assert all(row["corrected"] for row in result["filled"])
    assert page.locator("#ln").input_value() == "Lovelace"
    assert page.locator("#em").input_value() == "ada@example.com"
    # Not a contact fact, and blanks are not filled in this pass.
    assert page.locator("#ttl").input_value() == "Analyst"
    assert page.locator("#city").input_value() == ""
    assert page.locator("#cl").input_value() == "Parsed text"
    assert result["leftovers"] == [] and result["long_text"] == []


def _lever_card(card: str, title: str, fields: list[dict], body: str) -> str:
    template = json.dumps({"text": title, "fields": fields}).replace('"', "&quot;")
    return f"""
    <li class="application-question custom-question">
      <div class="application-label"><div class="text">{title}<span class="required">✱</span></div></div>
      <div class="application-field">{body}</div>
      <input type="hidden" name="cards[{card}][baseTemplate]" value="{template}">
    </li>"""


# Lever (jobs.lever.co) custom questions, synthetic: the card title is not the question,
# and "required" lives only in the card's JSON.
_LEVER = "<ul>" + _lever_card(
    "8c1c2d3e-aaaa",
    "Eligibility",
    [{"type": "multiple-choice", "text": "Are you legally authorized to work in the United States?",
      "required": True, "options": [{"text": "Yes"}, {"text": "No"}]}],
    """<ul><li><label><input type="radio" name="cards[8c1c2d3e-aaaa][field0]" value="Yes"><span>Yes</span></label></li>
           <li><label><input type="radio" name="cards[8c1c2d3e-aaaa][field0]" value="No"><span>No</span></label></li></ul>""",
) + _lever_card(
    "9d9d-bbbb",
    "Logistics",
    [{"type": "text", "text": "What is your expected graduation date?", "required": False},
     {"type": "text", "text": "Which team interests you most?", "required": True}],
    """<input type="text" name="cards[9d9d-bbbb][field0]">
       <input type="text" name="cards[9d9d-bbbb][field1]">""",
) + "</ul>"


def test_lever_cards_use_the_question_and_required_flag_from_the_template(page):
    page.set_content(_LEVER)
    result = _fill(page, {"authorized_to_work": "Yes", "graduation_month": "2027-06"})
    assert page.locator("input[value='Yes']").is_checked()
    labels = {row["label"] for row in result["filled"]}
    assert "Are you legally authorized to work in the United States?" in labels
    assert "What is your expected graduation date?" in labels
    team = [row for row in result["leftovers"] if row["label"] == "Which team interests you most?"]
    assert team and team[0]["required"] is True
    assert result["required_empty"] == ["Which team interests you most?"]
    assert page.evaluate(_READINESS, {}) == ["Which team interests you most?"]
