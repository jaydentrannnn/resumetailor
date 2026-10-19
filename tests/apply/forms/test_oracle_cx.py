"""Oracle Recruiting "Candidate Experience" dropdowns (grid popups) and its address chain:
Country, then the postal-code lookup that fills City, County and State. Replays the
anonymised capture in installed Edge, offline, with a made-up applicant."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import questions, widget_actions
from resume_tailor.apply.forms import fill_answers, fill_page, fill_widgets

_FORM = Path(__file__).parents[2] / "fixtures/forms/oracle_cx_address.html"
_FIELDS = {
    "first_name": "Zyxta", "last_name": "Quorvel", "country": "United States",
    "address_line1": "100 Capitol Mall", "city": "Sacramento", "state": "California",
    "postal_code": "95814", "gender": "Female",
}


@pytest.fixture(scope="module")
def browser():
    try:
        with sync_playwright() as playwright:
            try:
                launched = playwright.chromium.launch(headless=True, channel="msedge")
            except Exception:
                launched = playwright.chromium.launch(
                    headless=True, executable_path=os.environ.get("PW_CHROMIUM_PATH") or None
                )
            try:
                yield launched
            finally:
                launched.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.route("**/*", lambda route: route.abort())
    page.set_content(_FORM.read_text(encoding="utf-8"))
    try:
        yield page
    finally:
        page.close()


def test_a_grid_dropdown_commits_its_option(page):
    assert widget_actions._select_combobox_option(  # noqa: SLF001
        page, "#US-STANDARD-ORA_GENDER-STANDARD-11", "Female", key="gender")
    assert page.input_value("#US-STANDARD-ORA_GENDER-STANDARD-11") == "Female"
    assert page.get_attribute("#US-STANDARD-ORA_GENDER-STANDARD-11", "aria-expanded") == "false"


@pytest.mark.parametrize(("rows", "context", "chosen"), [
    (["95814, Sacramento, Sacramento, CA", "95815, Sacramento, Sacramento, CA"], {},
     "95814, Sacramento, Sacramento, CA"),
    (["95814, Sacramento, Sacramento, CA", "95814, Davis, Yolo, CA"], {"city": "Davis"},
     "95814, Davis, Yolo, CA"),
    (["95814, Sacramento, Sacramento, CA", "95814, Davis, Yolo, CA"], {}, None),
    (["95814, Sacramento, Sacramento, CA"], {}, "95814, Sacramento, Sacramento, CA"),
])
def test_a_postal_lookup_row_is_the_profiles_code_and_city(rows, context, chosen):
    target = "95814-1234" if len(rows) == 1 else "95814"
    assert widget_actions._postal_option(rows, target, context) == chosen  # noqa: SLF001


def _run(page) -> fill_answers._FillAnswers:
    run = fill_answers._FillAnswers.__new__(fill_answers._FillAnswers)
    run.page, run.frames, run.fields, run.hints = page, page.frames, _FIELDS, {}
    run.filler_js = fill_page._load_filler_js()  # noqa: SLF001
    run.facts = questions.facts_for(_FIELDS, today=date(2026, 10, 18))
    run.needs_review, run.other_chosen, run.ats_name = [], False, "oracle"
    run._stop_if_out_of_time = lambda _note: False  # noqa: SLF001
    result = fill_widgets._fill_frame(page, run.filler_js, _FIELDS, {}, run.facts)  # noqa: SLF001
    run.merged = {key: list(result.get(key) or []) for key in (
        "filled", "leftovers", "long_text", "file_inputs", "required_empty")}
    return run


def test_country_then_postal_code_fill_the_address_chain(page):
    run = _run(page)
    keys = [item.get("key") for item in run.merged["leftovers"]]
    assert keys.index("city") < keys.index("postal_code")  # page order: City first
    run._resolve_leftovers()  # noqa: SLF001
    shown = {sel: page.input_value(sel) for sel in (
        "#country-14", "#postalCode-32", "#city-28", "#region1-30", "#region2-31")}
    assert shown == {"#country-14": "United States", "#postalCode-32": "95814",
                     "#city-28": "Sacramento", "#region1-30": "Sacramento",
                     "#region2-31": "CA"}
    kept = {item["selector"] for item in run.merged["filled"] if item.get("preserved")}
    assert "#region1-30" in kept  # County: set by the postal code, no profile answer
    assert not [item for item in run.merged["required_empty"]
                if "County" in item or "Postal" in item or "City" in item]
    assert run.needs_review == []
