"""The generic fill's question pipeline against captured application forms.

``filler.js`` reads each question (scan mode), `questions.plan_for` decides its key and
answer, and the filler sets them — the path `fill._fill_frame` runs. Each page under
``tests/fixtures/forms/`` is a sanitized capture of a live form whose fill went wrong
(2026-09); a new failure adds a page and rows here, not a per-site branch.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply import ats_hints, field_matcher, questions

_ROOT = Path(__file__).parents[1]
_FILLER = (_ROOT / "src/resume_tailor/apply/filler.js").read_text(encoding="utf-8")
_FORMS = Path(__file__).parent / "fixtures" / "forms"
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


def test_consent_is_never_answered(quora):
    scanned, plan, result = quora
    assert _planned(scanned, plan, "Check Yes or No to indicate your agreement")["key"] is None
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
