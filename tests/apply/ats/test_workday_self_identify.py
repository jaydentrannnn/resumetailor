"""Workday's Self Identify / Voluntary Disclosures answers and Languages rows, run in
installed Edge against Workday-shaped DOM (ids and automation ids as Workday renders them).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.ats import ats_hints, workday_flow, workday_repeaters


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


def _date_section(control: str, section: str, placeholder: str) -> str:
    # The spinbutton's display div takes the click and focuses the input.
    return (f'<div id="{control}-{section}-display" '
            f'onclick="document.getElementById(this.id.replace(\'-display\', \'-input\')).focus()">{placeholder}</div>'
            f'<input type="text" id="{control}-{section}-input">')


_DISABILITY = [
    "Yes, I have a disability, or have had one in the past",
    "No, I do not have a disability and have not had one in the past",
    "I do not want to answer",
]


def _checkboxes(field: str, question: str, options: list[str]) -> str:
    boxes = "".join(
        f'<div><input type="checkbox" id="{field}-{index}"><label for="{field}-{index}">{text}</label></div>'
        for index, text in enumerate(options)
    )
    return f'<div data-automation-id="formField-{field}"><fieldset><legend>{question}</legend>{boxes}</fieldset></div>'


_SELF_IDENTIFY = f"""
<div data-automation-id="applyFlowPage">
  <div data-automation-id="formField-name"><label for="sid--name">Name*</label><input type="text" id="sid--name"></div>
  <div data-automation-id="formField-employeeId"><label for="sid--employeeId">Employee ID</label>
    <input type="text" id="sid--employeeId"></div>
  <div data-automation-id="formField-dateSignedOn"><label>Date*</label>
    {_date_section("sid--dateSignedOn", "dateSectionMonth", "MM")}
    {_date_section("sid--dateSignedOn", "dateSectionDay", "DD")}
    {_date_section("sid--dateSignedOn", "dateSectionYear", "YYYY")}</div>
  {_checkboxes("disabilityStatus", "Please check one of the boxes below:*", _DISABILITY)}
</div>
"""


def _ticked(page) -> list[str]:
    return page.evaluate("""() => [...document.querySelectorAll("input[type='checkbox']:checked")]
      .map(b => document.querySelector(`label[for="${b.id}"]`).innerText)""")


@pytest.mark.parametrize(("answer", "expected"), [
    ("No", _DISABILITY[1]), ("Yes", _DISABILITY[0]), ("decline", _DISABILITY[2]),
])
def test_self_identify_ticks_the_disability_answer_and_signs(page, answer, expected):
    page.set_content(_SELF_IDENTIFY)
    fields = {"disability_status": answer, "full_name": "Jordan Rivera"}
    review: list[str] = []
    ticked = workday_flow.fill_choice_checkboxes(page, fields, review=review)
    signed = workday_flow.fill_self_identify(page, fields, today=date(2026, 9, 24), review=review)

    assert _ticked(page) == [expected]
    assert [item["key"] for item in ticked] == ["disability_status"]
    assert page.locator("[id='sid--name']").input_value() == "Jordan Rivera"
    assert page.locator("[id='sid--employeeId']").input_value() == ""
    assert [page.locator(f"[id='sid--dateSignedOn-{part}-input']").input_value()
            for part in ("dateSectionMonth", "dateSectionDay", "dateSectionYear")] == ["09", "24", "2026"]
    assert {item["key"] for item in signed} == {"full_name", "signature_date"}
    assert review == []


def test_an_answered_disability_group_and_a_typed_name_are_kept(page):
    page.set_content(_SELF_IDENTIFY)
    page.locator("[id='disabilityStatus-2']").check()
    page.locator("[id='sid--name']").fill("J. Rivera")
    fields = {"disability_status": "No", "full_name": "Jordan Rivera"}
    assert workday_flow.fill_choice_checkboxes(page, fields) == []
    workday_flow.fill_self_identify(page, fields, today=date(2026, 9, 24))
    assert _ticked(page) == [_DISABILITY[2]]
    assert page.locator("[id='sid--name']").input_value() == "J. Rivera"


def test_no_matching_disability_option_is_reviewed_not_guessed(page):
    page.set_content(_checkboxes("disabilityStatus", "Disability", _DISABILITY[:2]))
    review: list[str] = []
    workday_flow.fill_choice_checkboxes(page, {"disability_status": "decline"}, review=review)
    assert _ticked(page) == []
    # The review says what was wanted and what the form offered.
    assert review == [f"Disability: no option for decline (no match; options: {_DISABILITY[0]} | {_DISABILITY[1]})"]


def test_race_checkboxes_pick_the_option_starting_with_the_answer(page):
    options = ["Asian (United States of America)", "White (United States of America)", "I do not wish to answer"]
    page.set_content(f'<div data-automation-id="applyFlowPage">{_checkboxes("ethnicity", "Race/Ethnicity", options)}</div>')
    workday_flow.fill_choice_checkboxes(page, {"race": "Asian", "race_detail": "Southeast Asian"})
    assert _ticked(page) == [options[0]]


def test_veteran_radios_take_the_long_form_of_no(page):
    options = ["I am not a protected veteran", "I identify as one or more of the classifications of protected veteran",
               "I don't wish to answer"]
    radios = "".join(f'<input type="radio" name="v" id="v{i}"><label for="v{i}">{text}</label>' for i, text in enumerate(options))
    page.set_content(f'<div data-automation-id="formField-veteranStatus"><fieldset><legend>Veteran Status*</legend>{radios}</fieldset></div>')
    committed = workday_flow.fill_radios(page, {"veteran_status": "not_veteran"},
                                         company="Acme", employers=[])
    assert page.locator("[id='v0']").is_checked()
    assert committed[0]["value"] == options[0]


def test_a_veteran_question_no_option_answers_is_reviewed_with_its_options(page):
    # OFCCP sub-categories only: which one applies is not in the profile.
    options = ["Disabled Veteran", "Recently Separated Veteran"]
    radios = "".join(f'<input type="radio" name="v" id="v{i}"><label for="v{i}">{text}</label>' for i, text in enumerate(options))
    page.set_content(f'<div data-automation-id="formField-veteranStatus"><fieldset><legend>Veteran Status*</legend>{radios}</fieldset></div>')
    review: list[str] = []
    committed = workday_flow.fill_radios(page, {"veteran_status": "protected"},
                                         company="Acme", employers=[], review=review)
    assert committed == []
    assert review == ["Veteran Status: no option for protected (no match; options: Disabled Veteran | Recently Separated Veteran)"]


def test_a_yes_no_question_whose_profile_fact_is_blank_is_recorded_not_skipped(page):
    radios = '<input type="radio" name="a" id="a0"><label for="a0">Yes</label><input type="radio" name="a" id="a1"><label for="a1">No</label>'
    question = "Are you currently legally authorized to work in the United States?"
    page.set_content(f'<div data-automation-id="formField-q1"><fieldset><legend>{question}*</legend>{radios}</fieldset></div>')
    blank: list[dict] = []
    committed = workday_flow.fill_radios(page, {}, company="Acme", employers=[], blank=blank)
    assert committed == []
    assert blank == [{"key": "authorized_to_work", "label": question}]


# -- Languages ---------------------------------------------------------------------------

def _listbox(row: str, field: str, label: str) -> str:
    return (f'<div data-automation-id="formField-{field}"><label>{label}</label>'
            f'<button type="button" aria-haspopup="listbox" id="{row}{field}">Select One</button></div>')


def _language_row(n: int) -> str:
    row = f"language-{n}--"
    return (f'<div class="row">{_listbox(row, "language", "Language*")}'
            f'<div><input type="checkbox" id="{row}native"><label for="{row}native">I am fluent in this language.</label></div>'
            + "".join(_listbox(row, f"languageProficiency-{i}", label)
                      for i, label in enumerate(("Reading*", "Speaking*", "Writing*")))
            + "</div>")


_LANGUAGES = f"""
<div data-automation-id="applyFlowPage"><div><h3>Languages</h3><div id="rows"></div>
  <button data-automation-id="add-button" onclick="addLanguage()">Add</button>
</div></div>
<script>
  const template = {_language_row(7)!r};
  function addLanguage() {{
    const n = document.querySelectorAll('.row').length + 7;
    document.getElementById('rows').insertAdjacentHTML('beforeend', template.replaceAll('language-7--', `language-${{n}}--`));
  }}
</script>
"""


def _fake_select(page, selector: str, value: str, *, key: str = "") -> bool:
    """Workday's listbox, reduced to its committed text: records the requested option."""
    page.locator(selector).evaluate("(el, v) => { el.innerText = v; }", f"{value} [{key}]")
    return True


def test_languages_add_a_row_and_fill_language_fluency_and_levels(page):
    page.set_content(_LANGUAGES)
    packet = SimpleNamespace(experience=[], education=[], languages=[SimpleNamespace(
        language="Vietnamese", fluent=True, levels={"Reading": "Advanced", "Speaking": "Fluent", "Writing": "Intermediate"},
    )])
    filled, review = workday_repeaters.fill(page, packet, lambda _m: None, select=_fake_select)

    assert review == []
    assert filled == [{"label": "Language: Vietnamese", "value": "Vietnamese"}]
    assert page.locator("[id='language-7--native']").is_checked()
    texts = [page.locator(f"[id='language-7--{f}']").inner_text() for f in
             ("language", "languageProficiency-0", "languageProficiency-1", "languageProficiency-2")]
    assert texts == ["Vietnamese [language]", "Advanced [language_level]", "Fluent [language_level]",
                     "Intermediate [language_level]"]


def test_a_filled_language_row_is_reused_and_a_missing_level_is_reviewed(page):
    page.set_content(_LANGUAGES)
    page.locator("[data-automation-id='add-button']").click()
    page.locator("[id='language-7--language']").evaluate("el => { el.innerText = 'Vietnamese'; }")
    packet = SimpleNamespace(experience=[], education=[], languages=[SimpleNamespace(
        language="Vietnamese", fluent=False, levels={"Reading": "Advanced"},
    )])
    _filled, review = workday_repeaters.fill(page, packet, lambda _m: None, select=_fake_select)

    assert page.locator(".row").count() == 1
    assert not page.locator("[id='language-7--native']").is_checked()
    assert review == ["Language: Vietnamese (Speaking, Writing)"]


def test_a_step_without_a_languages_section_skips_languages(page):
    page.set_content('<div data-automation-id="applyFlowPage"><h3>Education</h3></div>')
    packet = SimpleNamespace(experience=[], education=[], languages=[SimpleNamespace(language="English", fluent=True, levels={})])
    assert workday_repeaters.fill(page, packet, lambda _m: None, select=_fake_select) == ([], [])
