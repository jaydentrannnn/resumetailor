"""Offline form replays verify the Python decision layer and browser executor together."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import education, questions
from resume_tailor.apply.forms import fill_page, fill_widgets


@pytest.fixture
def education_page():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, channel="msedge")
        except Exception:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"Local Chromium unavailable: {exc}")
        try:
            yield browser.new_page()
        finally:
            browser.close()


def fill(page, fields, hints=None):
    return fill_widgets._fill_frame(
        page, fill_page._load_filler_js(), fields, hints or {}, questions.facts_for(fields)
    )


def test_completed_and_pursuing_replay(education_page):
    page = education_page
    fixture = Path(__file__).parents[2] / "fixtures/forms/completed_education.html"
    page.set_content(fixture.read_text(encoding="utf-8"))
    result = fill(
        page,
        {
            education.KEY: "High school diploma",
            "degree_level": "Bachelors",
            "degree_name": "Bachelor of Science",
        },
        {"#completed": "degree_level"},
    )
    assert not result["required_empty"]
    assert page.locator("#completed").input_value() == "High school diploma"
    assert page.locator("#mixed").input_value() == "Bachelor of Science"
    assert page.locator("#row").input_value() == "B.S."
    assert page.locator("#helper").input_value() == "Bachelor of Science"
    assert page.locator("#exclude").input_value() == "High school diploma"


@pytest.mark.parametrize(
    "saved,options",
    [
        ("", ["Bachelor's Degree"]),
        ("Bachelors", ["BA", "BS"]),
        ("Bachelors", ["Bachelor's Degree", "BACHELOR'S DEGREE"]),
        ("Bachelors", ["Bachelor's in progress"]),
    ],
)
def test_blank_or_unsupported_education_blocks_required_field(education_page, saved, options):
    page = education_page
    opts = "".join(f"<option>{option}</option>" for option in options)
    page.set_content(
        f'<label for="degree">Highest degree</label><select id="degree" required>'
        f'<option value="">Select</option>{opts}</select>'
    )
    result = fill(
        page,
        {education.KEY: saved, "degree_level": "Bachelors", "degree_name": "Bachelor of Science"},
    )
    assert page.locator("#degree").input_value() == ""
    assert result["required_empty"] == ["Highest degree"]
    assert result["leftovers"][0]["key"] == education.KEY


def test_custom_other_fills_qualification_without_touching_school_followup(education_page):
    page = education_page
    page.set_content("""
      <label for="degree">Highest education completed</label>
      <select id="degree"><option value="">Select</option><option>Other</option></select>
      <label for="detail">If Other, specify your qualification</label><input id="detail">
      <label for="school">If Other, please list the school name</label><input id="school">
    """)
    fields = {}
    education.refresh_fields(fields, "Higher National Diploma")
    fill(page, fields)
    assert page.locator("#degree").input_value() == "Other"
    assert page.locator("#detail").input_value() == "Higher National Diploma"
    assert page.locator("#school").input_value() == ""


def test_radio_duplicate_options_and_existing_selection(education_page):
    page = education_page
    page.set_content("""
      <fieldset><legend>Highest degree</legend>
      <label><input type="radio" name="degree" value="a">Bachelor's Degree</label>
      <label><input type="radio" name="degree" value="b">BACHELOR'S DEGREE</label>
      </fieldset>
    """)
    result = fill(page, {education.KEY: "Bachelors"})
    assert page.locator(":checked").count() == 0
    assert result["leftovers"]
    page.locator('[value="a"]').check()
    fill(page, {education.KEY: "High school diploma"})
    assert page.locator('[value="a"]').is_checked()
