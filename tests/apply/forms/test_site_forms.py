"""Captured application forms that filled nothing (Batch 2): each fixture is replayed with
``filler.js`` and must yield its questions and fill them."""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import education, questions, widget_actions
from resume_tailor.apply.forms import (
    field_matcher,
    fill_answers,
    fill_buttons,
    fill_page,
    fill_widgets,
)

_FORMS = Path(__file__).parents[2] / "fixtures/forms"


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
    try:
        yield page
    finally:
        page.close()


def _run(page, fixture: str, fields: dict[str, str] | None = None, *, scan: bool = False) -> dict:
    page.set_content((_FORMS / fixture).read_text(encoding="utf-8"), wait_until="domcontentloaded")
    fields = fields or {}
    args = {"fields": fields, "hints": {}, "synonyms": fill_page._synonym_payload(),  # noqa: SLF001
            "eeo": field_matcher.eeo_patterns(fields), "educationAliases": education.LEVEL_BY_ALIAS,
            "scan": scan}
    return page.evaluate(fill_page._load_filler_js(), args)  # noqa: SLF001


def test_jobvite_fields_wrapped_in_a_control_class_are_questions(page):
    labels = [q["label"] for q in _run(page, "jobvite_apply_form.html", scan=True)["questions"]]
    assert labels == ["First Name*", "Last Name*", "Email*", "Cell Phone*", "Country*", "State*",
                      "Zip Code*"]


def test_jobvite_fields_are_filled(page):
    fields = {"first_name": "Zyxta", "last_name": "Quorvel", "email": "z@quorvel.example",
              "country": "United States", "state": "California", "postal_code": "95814"}
    result = _run(page, "jobvite_apply_form.html", fields)
    assert {item["key"] for item in result["filled"]} >= set(fields)
    assert page.input_value("#jv-field-a6") == "California"


def test_jobvite_location_gate_takes_the_english_all_locations_option(page):
    scanned = _run(page, "jobvite_location_gate.html", scan=True)["questions"]
    plan = questions.plan_for(scanned, questions.facts_for({"country": "United States"},
                                                          today=date(2026, 10, 18)))
    assert [entry["key"] for entry in plan.values()] == ["residence_language"]
    args = {"fields": {}, "hints": {}, "synonyms": fill_page._synonym_payload(), "eeo": {},  # noqa: SLF001
            "educationAliases": education.LEVEL_BY_ALIAS, "plan": plan}
    page.evaluate(fill_page._load_filler_js(), args)  # noqa: SLF001
    assert page.eval_on_selector("#jv-country-select", "el => el.selectedOptions[0].text") == (
        "All Locations (English)")


def _select(page, selector: str, value: str, **kwargs) -> bool:
    return widget_actions._select_combobox_option(page, selector, value, **kwargs)  # noqa: SLF001


def test_rippling_dropdowns_commit_by_input_value_and_div_text(page):
    labels = [q["label"] for q in _run(page, "rippling_dropdowns.html", scan=True)["questions"]]
    assert labels[2:] == ["Are you legally authorized to work in the United States?*", "Gender"]
    assert _select(page, "#field-24", "They/them/theirs")
    assert page.input_value("#field-24") == "They/them/theirs"
    assert _select(page, "#field-59", "Yes", key="authorized_to_work")
    assert page.inner_text("#field-59") == "Yes"
    assert page.get_attribute("#field-59", "aria-expanded") == "false"


def test_a_div_dropdown_showing_its_choice_is_kept(page):
    page.set_content((_FORMS / "rippling_dropdowns.html").read_text(encoding="utf-8"))
    page.evaluate("document.querySelector('#field-72').textContent = 'Female'")
    args = {"fields": {}, "hints": {}, "synonyms": fill_page._synonym_payload()}  # noqa: SLF001
    result = page.evaluate(fill_page._load_filler_js(), args)  # noqa: SLF001
    kept = {item["selector"]: item["value"] for item in result["filled"] if item.get("preserved")}
    assert kept == {"#field-72": "Female"}  # "+1 US" sits in an input that takes typing


def test_rippling_phone_codes_name_the_region_by_its_short_code(page):
    _run(page, "rippling_dropdowns.html", scan=True)
    assert _select(page, "#field-38", "+1", key="phone_country_code", phone_region="United States")
    assert page.input_value("#field-38") == "+1 US"  # already the profile's; left alone
    assert _select(page, "#field-38", "+44", key="phone_country_code", phone_region="UK")
    assert page.input_value("#field-38") == "+44 GB"


def test_typed_text_with_the_menu_still_open_is_not_a_commit(page):
    page.set_content("""
      <label for="c">Pronouns</label>
      <input id="c" role="combobox" aria-expanded="false" aria-controls="m">
      <ul id="m" role="listbox" hidden><li role="option">They/them/theirs</li></ul>
      <script>
        const c = document.getElementById('c'), m = document.getElementById('m');
        c.onclick = () => { m.hidden = false; c.setAttribute('aria-expanded', 'true'); };
        m.querySelector('li').onclick = () => { c.value = 'They/them/theirs'; };  // never closes
      </script>""")
    assert not _select(page, "#c", "They/them/theirs")


AMBIGUOUS = """
  <label for="c">Gender</label><div id="c" role="combobox" tabindex="0">Select</div>
  <ul role="listbox" id="other"><li role="option">Male</li><li role="option">Female</li></ul>
  <ul role="listbox" id="mine" hidden><li role="option">Male</li><li role="option">Female</li></ul>
  <script>
    const c = document.getElementById('c');
    c.onclick = () => { document.getElementById('mine').hidden = false; };
    document.querySelectorAll('li').forEach(li => li.onclick = () => {
      c.textContent = li.textContent; document.getElementById('mine').hidden = true; });
  </script>"""


def test_the_menu_a_click_opened_is_the_triggers_own(page):
    page.set_content(AMBIGUOUS)
    assert _select(page, "#c", "Female")
    assert page.inner_text("#c") == "Female"


def test_two_menus_opening_at_once_choose_nothing(page):
    page.set_content(AMBIGUOUS.replace("<ul role=\"listbox\" id=\"other\">",
                                       "<ul role=\"listbox\" id=\"other\" hidden>")
                     .replace("document.getElementById('mine').hidden = false;",
                              "document.querySelectorAll('ul').forEach(u => u.hidden = false);"))
    assert not _select(page, "#c", "Female")
    assert page.inner_text("#c") == "Select"


def test_options_that_load_after_the_menu_opens_are_waited_for(page):
    page.set_content("""
      <label for="c">Country</label>
      <input id="c" role="combobox" aria-expanded="false" aria-controls="m" readonly>
      <ul id="m" role="listbox" hidden></ul>
      <script>
        const c = document.getElementById('c'), m = document.getElementById('m');
        c.onclick = () => {
          m.hidden = false; c.setAttribute('aria-expanded', 'true');
          m.innerHTML = '<li>Loading...</li>';
          setTimeout(() => {
            m.innerHTML = '<li>Canada</li><li>United States</li>';
            m.querySelectorAll('li').forEach(li => li.onclick = () => {
              c.value = li.textContent; m.hidden = true; c.setAttribute('aria-expanded', 'false'); });
          }, 1000);
        };
      </script>""")
    assert _select(page, "#c", "United States", key="country")
    assert page.input_value("#c") == "United States"


def test_workable_cookie_banner_is_declined_before_its_dropdowns(page):
    page.set_content((_FORMS / "workable_dropdowns.html").read_text(encoding="utf-8"))
    assert fill_buttons.decline_cookie_banner(page)
    assert page.evaluate("window.consent") == "Decline all"
    assert _select(page, "#input_CA_101_input", "Yes", key="authorized_to_work")
    assert page.input_value("#input_CA_101_input") == "Yes"
    assert page.input_value("input[name='CA_101']") == "0"


@pytest.mark.parametrize("html", [
    '<div class="cookie-bar">We use cookies. <button>Accept all</button></div>',
    '<form><label>Will you relocate?</label><button type="button">Decline</button></form>',
])
def test_only_a_cookie_banners_refusal_is_pressed(page, html):
    page.set_content(html + "<script>document.querySelectorAll('button').forEach(b => "
                     "b.onclick = () => window.pressed = b.textContent)</script>")
    assert not fill_buttons.decline_cookie_banner(page)
    assert page.evaluate("window.pressed") is None


def _read_back(page) -> dict[str, str]:
    args = {"fields": {}, "hints": {}, "synonyms": fill_page._synonym_payload()}  # noqa: SLF001
    result = page.evaluate(fill_page._load_filler_js(), args)  # noqa: SLF001
    return {item["selector"]: item["value"] for item in result["filled"]}


def test_committed_input_dropdowns_are_read_back(page):
    page.set_content((_FORMS / "workable_dropdowns.html").read_text(encoding="utf-8"))
    fill_buttons.decline_cookie_banner(page)
    assert _read_back(page) == {}
    assert _select(page, "#input_CA_102_input", "No", key="requires_sponsorship_any")
    assert _read_back(page) == {"#input_CA_102_input": "No"}


def test_a_search_that_finds_nothing_leaves_no_typed_text(page):
    page.set_content((_FORMS / "rippling_dropdowns.html").read_text(encoding="utf-8"))
    assert not _select(page, "#field-24", "Xe/xem/xyrs", key="pronouns")
    assert page.input_value("#field-24") == ""
    assert "#field-24" not in _read_back(page)


PAYLOCITY_FIELDS = {"first_name": "Zyxta", "last_name": "Quorvel", "email": "z@quorvel.example",
                    "phone": "(916) 555-0147"}


def test_answers_a_resume_upload_cleared_are_filled_again(page):
    page.set_content((_FORMS / "paylocity_resume_parse.html").read_text(encoding="utf-8"))
    facts = questions.facts_for(PAYLOCITY_FIELDS, today=date(2026, 10, 18))
    first = fill_widgets._fill_frame(page, fill_page._load_filler_js(), PAYLOCITY_FIELDS, {}, facts)  # noqa: SLF001
    assert page.input_value("[id='info.email']") == "z@quorvel.example"
    page.set_input_files("#btn-resume", {"name": "resume.pdf", "mimeType": "application/pdf",
                                          "buffer": b"%PDF-1.4"})
    assert page.input_value("[id='info.email']") == ""  # the site redrew the form blank

    run = fill_answers._FillAnswers.__new__(fill_answers._FillAnswers)
    messages: list[str] = []
    run.page, run.filler_js, run.fields, run.hints, run.facts = (
        page, fill_page._load_filler_js(), PAYLOCITY_FIELDS, {}, facts)
    run.merged = {"filled": [{**item, "frame_index": 0} for item in first["filled"]]}
    run.progress = messages.append
    run.classify_unkeyed = run.classify_notices = None
    run._refill_emptied()  # noqa: SLF001

    assert page.input_value("[id='info.email']") == "z@quorvel.example"
    assert page.input_value("[id='info.firstName']") == "Zyxta"
    assert len(run.merged["filled"]) == len(first["filled"])  # the same answers, not new ones
    assert messages == [f"filled {len(first['filled'])} answer(s) again after the resume upload cleared them"]


def test_a_verified_pick_in_a_typing_dropdown_is_read_back_but_planned_text_is_not(page):
    page.set_content((_FORMS / "rippling_dropdowns.html").read_text(encoding="utf-8"))
    picked = {"key": "pronouns", "label": "Pronouns", "value": "They/them/theirs",
              "selector": "#field-24"}
    assert "#field-24" not in _read_back(page)
    assert _select(page, "#field-24", "They/them/theirs")
    assert "#field-24" not in _read_back(page)  # filler.js alone never reads typed-in text
    observe = fill_widgets._observe_fields  # noqa: SLF001
    filler = fill_page._load_filler_js()  # noqa: SLF001
    assert observe(page, filler, {}, {(0, "#field-24"): picked})[(0, "#field-24")]["value"] == (
        "They/them/theirs")
    leftover = {**picked, "reason": "Custom dropdown needs an observed selection"}
    assert (0, "#field-24") not in observe(page, filler, {}, {(0, "#field-24"): leftover})


REVEALING = """
<form>
  <label for="country">Country</label>
  <select id="country"><option value="">Select</option><option>Canada</option><option>United States</option></select>
  <div id="state-row" hidden><label for="state">State</label>
    <select id="state"><option value="">Select</option><option>California</option><option>Texas</option></select></div>
  <label for="city">City</label><input id="city">
</form>
<script>
  document.getElementById('country').addEventListener('change', e => {
    document.getElementById('state-row').hidden = e.target.value !== 'United States';
  });
</script>"""


def _stub_run(page, fields):
    run = fill_answers._FillAnswers.__new__(fill_answers._FillAnswers)
    run.page, run.filler_js, run.fields, run.hints = page, fill_page._load_filler_js(), fields, {}  # noqa: SLF001
    run.facts = questions.facts_for(fields, today=date(2026, 10, 18))
    run.frames, run.merged, run.messages = page.frames, {"filled": [], "leftovers": []}, []
    run.progress = run.messages.append
    run.classify_unkeyed = run.classify_notices = None
    run._out_of_time = lambda: False  # noqa: SLF001
    return run


def test_a_question_an_answer_reveals_is_filled_by_one_more_pass(page):
    page.set_content(REVEALING)
    run = _stub_run(page, {"country": "United States", "state": "California", "city": "Sacramento"})
    before = run._question_signature()  # noqa: SLF001
    run.merged["filled"] = fill_widgets._fill_frame(page, run.filler_js, run.fields, {}, run.facts)["filled"]  # noqa: SLF001
    assert page.input_value("#state") == ""  # hidden when the pass began
    run._rescan_changed_questions(before)  # noqa: SLF001
    assert page.eval_on_selector("#state", "el => el.selectedOptions[0].text") == "California"
    assert run.messages == ["1 question(s) appeared or changed; filling them"]


def test_a_step_whose_questions_did_not_change_gets_no_extra_pass(page):
    page.set_content(REVEALING)
    run = _stub_run(page, {"country": "Canada", "city": "Toronto"})
    before = run._question_signature()  # noqa: SLF001
    fill_widgets._fill_frame(page, run.filler_js, run.fields, {}, run.facts)  # noqa: SLF001
    run._rescan_changed_questions(before)  # noqa: SLF001
    assert run.messages == []


def test_a_question_turned_required_is_a_change(page):
    page.set_content('<label for="a">Middle name</label><input id="a">'
                     '<label for="b">Nickname</label><input id="b">')
    run = _stub_run(page, {})
    before = run._question_signature()  # noqa: SLF001
    page.evaluate("document.getElementById('b').required = true")
    assert run._question_signature() != before  # noqa: SLF001


def _timed(fn):
    started = time.monotonic()
    result = fn()
    return result, time.monotonic() - started


def test_an_advance_returns_once_the_next_step_has_painted(page):
    page.set_content('<input id="a"><script>setTimeout(() => document.body.innerHTML ='
                     ' "<input id=b><select id=c></select>", 400)</script>')
    before = fill_page._form_step_signature(page)  # noqa: SLF001
    changed, took = _timed(lambda: fill_page.wait_for_new_step(page, before, timeout_ms=6000))
    assert changed and took < 2.5


def test_a_refused_advance_returns_early_and_a_silent_one_at_the_cap(page):
    page.set_content('<input id="a"><span role="alert">Email is required</span>')
    before = fill_page._form_step_signature(page)  # noqa: SLF001
    changed, took = _timed(lambda: fill_page.wait_for_new_step(page, before, timeout_ms=6000))
    assert not changed and took < 2
    page.set_content('<input id="a">')
    before = fill_page._form_step_signature(page)  # noqa: SLF001
    changed, took = _timed(lambda: fill_page.wait_for_new_step(page, before, timeout_ms=1200))
    assert not changed and took >= 1.2


def test_entry_waits_for_an_apply_control_not_a_fixed_time(page):
    page.set_content('<p>Loading</p><script>setTimeout(() => document.body.insertAdjacentHTML('
                     '"beforeend", "<button>Apply now</button>"), 300)</script>')
    _none, took = _timed(lambda: fill_page.wait_for_entry(page, timeout_ms=10_000))
    assert took < 3.5
    assert page.get_by_role("button", name="Apply now").count() == 1


def test_an_entry_click_settles_when_the_form_appears(page):
    page.set_content('<button id="go">Apply</button><script>document.getElementById("go").onclick ='
                     ' () => setTimeout(() => document.body.insertAdjacentHTML("beforeend",'
                     ' "<input id=first>"), 200)</script>')
    before = fill_buttons._entry_state(page)  # noqa: SLF001
    page.click("#go")
    _none, took = _timed(lambda: fill_buttons._settle_after_entry(page, before, 1500))  # noqa: SLF001
    assert took < 1.2 and page.locator("#first").count() == 1
