"""The generic fill's question pipeline against captured application forms.

``filler.js`` reads each question (scan mode), `questions.plan_for` decides its key and
answer, and the filler sets them — the path `fill_widgets._fill_frame` runs. Each page under
``tests/fixtures/forms/`` is a sanitized capture of a live form whose fill went wrong
(2026-09); a new failure adds a page and rows here, not a per-site branch.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import questions
from resume_tailor.apply.ats import ats_hints
from resume_tailor.apply.forms import field_matcher
from resume_tailor.apply.funnel import packet_profile_fields

_ROOT = Path(__file__).parents[3]
_FILLER = (_ROOT / "src/resume_tailor/apply/forms/filler.js").read_text(encoding="utf-8")
_FORMS = Path(__file__).parents[2] / "fixtures" / "forms"
_TODAY = date(2026, 9, 27)

FIELDS = {
    "first_name": "Alex", "last_name": "Doe", "full_name": "Alex Doe", "email": "alex@example.com",
    "phone": "(555) 010-0000", "city": "Fountain Valley", "state": "California",
    "country": "United States", "school": "State University", "major": "Computer Science",
    "degree_level": "Bachelors", "degree_name": "Bachelor of Science",
    "graduation_month": "2027-06", "education_start_month": "2023-09", "gpa": "3.7/4.0",
    "authorized_to_work": "Yes", "requires_sponsorship": "No", "requires_sponsorship_future": "No",
    "requires_sponsorship_any": "No", "willing_to_relocate": "Yes", "noncompete": "No",
    "gender": "Male", "race": "Asian", "hispanic_latino": "No", "veteran_status": "not_veteran",
    "disability_status": "No", "linkedin_url": "https://www.linkedin.com/in/alex-doe/",
    "how_heard": "LinkedIn",
}

# A captured page has no React: a pressed toggle button is what its click handler would do.
_TOGGLE_SHIM = """() => document.querySelectorAll("button[aria-pressed]").forEach((button) =>
  button.addEventListener("click", () => {
    button.parentElement.querySelectorAll(":scope > button[aria-pressed]")
      .forEach((other) => other.setAttribute("aria-pressed", "false"));
    button.setAttribute("aria-pressed", "true");
  }))"""


def _launch(playwright):
    try:
        return playwright.chromium.launch(headless=True, channel="msedge")
    except Exception:
        return playwright.chromium.launch(headless=True)


@pytest.fixture(scope="module")
def browser():
    try:
        with sync_playwright() as playwright:
            launched = _launch(playwright)
            try:
                yield launched
            finally:
                launched.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def _run(browser, form: str, company: str) -> tuple[list[dict], dict, dict]:
    """(scanned questions, plan, fill result) for one captured form."""
    page = browser.new_page()
    try:
        page.set_content((_FORMS / form).read_text(encoding="utf-8"))
        page.evaluate(_TOGGLE_SHIM)
        args = {
            "fields": FIELDS, "hints": {}, "synonyms": [list(pair) for pair in ats_hints.SYNONYMS],
            "eeo": field_matcher.eeo_patterns(FIELDS),
        }
        scanned = page.evaluate(_FILLER, {**args, "scan": True})["questions"]
        facts = questions.facts_for(
            FIELDS, company=company, role="Software Engineer Intern",
            experience_titles=["Software Engineer Intern"], today=_TODAY,
        )
        plan = questions.plan_for(scanned, facts)
        result = page.evaluate(_FILLER, {**args, "plan": plan})
        selectors = [item["selector"] for key in ("filled", "leftovers") for item in result[key] if item.get("selector")]
        result["matches"] = page.evaluate(
            "(selectors) => selectors.map((selector) => [selector, document.querySelectorAll(selector).length])",
            selectors,
        )
        return scanned, plan, result
    finally:
        page.close()


def _by_label(items: list[dict], start: str) -> list[dict]:
    return [item for item in items if str(item.get("label") or "").startswith(start)]


def _filled(result: dict, start: str) -> list[str]:
    return [str(item["value"]) for item in _by_label(result["filled"], start) if item.get("key") != "existing"]


def _planned(scanned: list[dict], plan: dict, start: str) -> dict:
    hits = [plan[item["qid"]] for item in scanned if item["label"].startswith(start)]
    assert hits, f"no scanned question starts {start!r}"
    return hits[0]


@pytest.mark.browser
@pytest.mark.parametrize(("leftover", "expected"), [("14", "2027"), ("142027", "2027"), ("2028", "2028")])
def test_workday_year_text_replaces_leftover_value(browser, leftover, expected):
    """A malformed year left by an earlier fill (MPC's "142027") is replaced; a
    well-formed year is the applicant's own answer and is kept."""
    page = browser.new_page()
    try:
        label = "If selected for a full-time opportunity post graduation, when would you be available to start? (Year-XXXX)"
        page.set_content(f'<label for="start">{label}</label><input id="start" type="text" value="{leftover}" required>')
        fields = {"earliest_start": "2027-06"}
        args = {"fields": fields, "hints": {}, "synonyms": [list(pair) for pair in ats_hints.SYNONYMS], "eeo": {}}
        scanned = page.evaluate(_FILLER, {**args, "scan": True})["questions"]
        plan = questions.plan_for(scanned, questions.facts_for(fields))
        result = page.evaluate(_FILLER, {**args, "plan": plan})
        assert page.locator("#start").input_value() == expected
        if expected != leftover:
            assert _filled(result, "If selected for a full-time opportunity") == [expected]
    finally:
        page.close()


@pytest.mark.browser
def test_blank_school_email_is_reported_without_filling_personal_email(browser):
    page = browser.new_page()
    try:
        label = "Please provide your current school-issued email address"
        page.set_content(f'<label for="school-email">{label}</label><input id="school-email" type="email" required>')
        fields = {"email": "alex@example.com"}
        args = {"fields": fields, "hints": {}, "synonyms": [list(pair) for pair in ats_hints.SYNONYMS], "eeo": {}}
        scanned = page.evaluate(_FILLER, {**args, "scan": True})["questions"]
        plan = questions.plan_for(scanned, questions.facts_for(fields))
        result = page.evaluate(_FILLER, {**args, "plan": plan})
        assert page.locator("#school-email").input_value() == ""
        blanks = [
            item
            for item in result["leftovers"]
            if item.get("reason") == packet_profile_fields.BLANK_PROFILE_REASON
        ]
        assert packet_profile_fields.missing_profile(blanks, set())[0]["key"] == "school_email"
    finally:
        page.close()


@pytest.fixture(scope="module")
def quora(browser):
    return _run(browser, "ashby_quora.html", "Quora")


@pytest.fixture(scope="module")
def ramp(browser):
    return _run(browser, "ashby_ramp.html", "Ramp")


@pytest.fixture(scope="module")
def gcm(browser):
    return _run(browser, "greenhouse_gcm.html", "GCM Grosvenor")


def test_ashby_radio_groups_are_one_question_each(quora):
    scanned, _plan, _result = quora
    gender = _by_label(scanned, "How would you describe your gender identity?")
    assert len(gender) == 1
    assert gender[0]["kind"] == "choice"
    assert "Male" in gender[0]["options"]
    race = _by_label(scanned, "What race and/or ethnic identities")
    assert len(race) == 1 and race[0]["kind"] == "multi"


def test_ashby_identity_answers_are_picked(quora):
    _scanned, _plan, result = quora
    assert _filled(result, "How would you describe your gender identity?") == ["Male"]
    assert _filled(result, "US candidates only: Are you a veteran") == ["No"]
    assert _filled(result, "US candidates only: Do you live with a disability") == ["No"]
    assert _filled(result, "Degree") == ["Bachelor's Degree"]


def test_ashby_toggle_buttons_answer_yes_no_questions(quora):
    _scanned, _plan, result = quora
    assert _filled(result, "Are you legally authorized to work") == ["Yes"]
    assert _filled(result, "Will you now or in the future require sponsorship") == ["No"]


def test_ashby_date_picker_gets_the_first_of_the_month(quora):
    # "2027-06" typed raw is parsed as UTC midnight: May 31st west of Greenwich.
    _scanned, _plan, result = quora
    assert _filled(result, "Graduation Date") == ["06/01/2027"]


def test_ashby_location_and_school_are_searched_with_planned_text(quora):
    scanned, plan, result = quora
    assert _planned(scanned, plan, "Location") == {"key": "location", "value": "Fountain Valley, California"}
    leftovers = {item["label"]: item for item in result["leftovers"] if item.get("type") == "combobox"}
    assert leftovers["Location"]["value"] == "Fountain Valley, California"
    assert leftovers["School"]["key"] == "school"


def test_routine_consent_without_preference_is_not_answered(quora):
    scanned, plan, result = quora
    step = _planned(scanned, plan, "Check Yes or No to indicate your agreement")
    assert step == {"key": "routine_acknowledgement", "value": None}
    assert not _filled(result, "Check Yes or No to indicate your agreement")


def test_ashby_split_education_dates(ramp):
    _scanned, _plan, result = ramp
    assert _filled(result, "Start Date") == ["September", "2023"]
    assert _filled(result, "End Date") == ["June", "2027"]


def test_ashby_derived_and_sponsorship_questions(ramp):
    _scanned, _plan, result = ramp
    assert _filled(result, "Are you currently located in, or willing to relocate to") == ["Yes"]
    assert _filled(result, "Requesting visa sponsorship?") == ["No"]


@pytest.mark.parametrize("form", ["quora", "ramp", "gcm"])
def test_every_selector_names_one_control(form, request):
    # Ramp (2026-09): a path selector shared by two inputs put the school into Phone.
    _scanned, _plan, result = request.getfixturevalue(form)
    radios = {item["selector"] for item in result["filled"] + result["leftovers"] if "name=" in item.get("selector", "")}
    assert [pair for pair in result["matches"] if pair[1] != 1 and pair[0] not in radios] == []


def test_greenhouse_education_months_are_keyed_by_part(gcm):
    scanned, plan, result = gcm
    assert _planned(scanned, plan, "Start date month") == {"key": "education_start_month", "value": "September"}
    assert _planned(scanned, plan, "End date month") == {"key": "graduation_month", "value": "June"}
    assert _filled(result, "Start date year") == ["2023"]
    assert _filled(result, "End date year") == ["2027"]


def test_greenhouse_sponsorship_questions_get_their_own_keys(gcm):
    scanned, plan, _result = gcm
    assert _planned(scanned, plan, "Do you currently require employer-sponsored")["key"] == "requires_sponsorship"
    assert _planned(scanned, plan, "If currently authorized to work legally")["key"] == "requires_sponsorship_any"
    assert _planned(scanned, plan, "To your knowledge are you currently subject to any non-")["key"] == "noncompete"


def test_follow_up_questions_take_no_profile_fact(gcm):
    scanned, plan, result = gcm
    assert _planned(scanned, plan, "If Other for Education")["key"] is None
    assert not _filled(result, "If Other for Education")


def _ashby_date(field: str, label: str, month: str, year: str) -> str:
    months = "".join(
        f'<option value="{name}"{" selected" if name == month else ""}>{name}</option>'
        for name in ("January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December")
    )
    years = "".join(
        f'<option value="{y}"{" selected" if str(y) == year else ""}>{y}</option>' for y in range(2030, 2015, -1)
    )
    return (
        f'<div><label for="_systemfield_education_history-{field}">{label}</label>'
        f'<div id="_systemfield_education_history-{field}">'
        f'<div><select><option value="">Month</option>{months}</select></div>'
        f'<div><select><option value="">Year</option>{years}</select></div></div></div>'
    )


@pytest.mark.browser
def test_ashby_education_date_selects_preset_to_today_are_overwritten(browser):
    """Ashby's education month/year selects arrive set to today (Ramp, 2026-09: both
    dates stayed "September 2026"); the resume's dates replace them."""
    page = browser.new_page()
    try:
        page.set_content(
            "<form><h3>Education</h3>"
            + _ashby_date("startDate", "Start Date", "September", "2026")
            + _ashby_date("endDate", "End Date", "September", "2026")
            + "</form>"
        )
        args = {"fields": FIELDS, "hints": {}, "synonyms": [list(pair) for pair in ats_hints.SYNONYMS],
                "eeo": field_matcher.eeo_patterns(FIELDS)}
        scanned = page.evaluate(_FILLER, {**args, "scan": True})["questions"]
        plan = questions.plan_for(scanned, questions.facts_for(FIELDS, today=_TODAY))
        page.evaluate(_FILLER, {**args, "plan": plan})
        values = page.evaluate("() => [...document.querySelectorAll('select')].map(s => s.selectedOptions[0].text)")
        assert values == ["September", "2023", "June", "2027"]
    finally:
        page.close()
