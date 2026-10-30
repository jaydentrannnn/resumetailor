"""`smartrecruiters_flow` recovering from what made live fills differ (2026-10-30): a form
drawn late, entries reopened by going Back, repeat stints, the time budget read per entry,
questions an answer reveals, hidden copies and the privacy-notice consent.

Same captured markup and component stand-in as `test_smartrecruiters_flow.py`; the
follow-up and consent controls are built from the captured select and checkbox.
"""

# ruff: noqa: F811 - the `browser` and `no_memory` fixtures are imported from the flow tests

from __future__ import annotations

import time

import pytest

from resume_tailor.apply.ats import smartrecruiters_entries, smartrecruiters_page
from resume_tailor.apply.ats import smartrecruiters_screening as screening
from resume_tailor.apply.forms import fill_page
from resume_tailor.apply.funnel.packet_models import PacketExperience
from tests.apply.ats.test_smartrecruiters_flow import (  # noqa: F401 - fixtures
    _SCREENING_FIELDS,
    _fixture,
    _no_progress,
    _open,
    _packet,
    browser,
    no_memory,
)

_CONTAINER = '<div class="spl-mt-2" data-test="question-container">'
_DEGREE = "question_89501da0-cb06-433c-a168-316a602e3644"
_DECLARATION = "spl-form-element_100"
_WORK = "spl-form-element_75"  # "Are you authorized to work ...?", answered Yes
_CITIZENSHIP = (
    "Do you hold Citizenship or Permanent Residency status from any of the following "
    "countries or administrative regions? Please select one."
)


def _container(control_id: str) -> str:
    """The captured screening container holding ``control_id``."""
    page = _fixture("screening_resultant.html")
    at = page.index(f'id="{control_id}"')
    return page[page.rindex(_CONTAINER, 0, at):page.index(_CONTAINER, at)]


def _select(new_id: str, question: str) -> str:
    """The captured degree select, asking ``question`` under the id ``new_id``."""
    html = _container(_DEGREE).replace(_DEGREE, new_id)
    return html.replace("What is your current or most recently completed degree type?", question)


def _consent_box(wording: str) -> str:
    """The captured declaration checkbox as the privacy-notice consent below the questions."""
    html = _container(_DECLARATION)
    box = html[html.index("<spl-checkbox"):html.index("</spl-checkbox>") + len("</spl-checkbox>")]
    box = box.replace(_DECLARATION, "consent-1")
    box = box.replace("<spl-checkbox ", '<spl-checkbox data-test="consent-box" ', 1)
    start = box.index('<span slot="label-content">')
    end = box.index("</span>", start)
    return f'{box[:start]}<span slot="label-content"> {wording} </span>{box[end + len("</span>"):]}'


def _add(page, html: str) -> None:
    page.evaluate("""(html) => {
      const holder = document.createElement('div');
      holder.setHTMLUnsafe(html);
      document.querySelector('main').appendChild(holder);
    }""", html)


def _checked(page, host_id: str) -> bool:
    return page.locator(f'spl-checkbox[id="{host_id}"] input[type=checkbox]').first.is_checked()


# --- The form drawn after its URL changes ------------------------------------------------


def test_the_scan_waits_for_a_form_drawn_late(browser):
    page = browser.new_page()
    page.set_content("""<main></main><script>setTimeout(() => {
      document.querySelector('main').innerHTML = '<input id="first-name-input">';
    }, 600);</script>""")
    started = time.monotonic()
    assert smartrecruiters_page.wait_for_form(page, 5000)
    assert time.monotonic() - started < 4


def test_a_hidden_form_control_is_not_a_drawn_form(browser):
    page = browser.new_page()
    page.set_content('<main><input id="first-name-input" style="display:none"></main>')
    started = time.monotonic()
    assert not smartrecruiters_page.wait_for_form(page, 800)
    assert time.monotonic() - started < 3


# --- Entries -----------------------------------------------------------------------------


def test_entries_reopened_by_going_back_are_saved_and_the_missing_one_added(browser):
    page = _open(browser)
    smartrecruiters_entries.fill_experience(page, _packet(), _no_progress)
    page.evaluate("window.__sr.reopen()")
    assert page.locator("[data-test=experience-edit-form]").count() == 1
    tutor = PacketExperience(title="Tutor", employer="Library", start="2024-01", end="2024-05")
    packet = _packet(experience=[*_packet().experience, tutor])
    filled, review = smartrecruiters_entries.fill_experience(page, packet, _no_progress)
    assert review == []
    assert [item.get("state") for item in filled] == ["preserved", None]
    assert page.locator("[data-test=experience-edit-form]").count() == 0
    assert [entry["title"] for entry in smartrecruiters_entries._entries(page, "experience")] == [
        "Data Intern", "Tutor",
    ]


def test_a_reopened_education_entry_is_saved_not_added_again(browser):
    page = _open(browser)
    smartrecruiters_entries.fill_education(page, _packet(), _no_progress)
    page.evaluate("window.__sr.reopen()")
    filled, review = smartrecruiters_entries.fill_education(page, _packet(), _no_progress)
    assert review == []
    assert filled[0]["state"] == "preserved"
    assert len(smartrecruiters_entries._entries(page, "education")) == 1


def test_an_open_entry_holding_something_else_is_left_alone(browser):
    page = _open(browser)
    smartrecruiters_entries.fill_experience(page, _packet(), _no_progress)
    page.evaluate("window.__sr.reopen()")
    other = PacketExperience(title="Tutor", employer="Library", start="2024-01", end="2024-05")
    filled, review = smartrecruiters_entries.fill_experience(
        page, _packet(experience=[other]), _no_progress
    )
    assert filled == []
    assert review == ["Experience: an entry is open for editing; finish it, then Continue fill"]
    assert page.locator("[data-test=experience-edit-form]").count() == 1


def test_a_repeat_stint_at_the_same_company_is_its_own_entry(browser):
    page = _open(browser)
    first = PacketExperience(
        title="Data Intern", employer="Acme Corp", start="2024-06", end="2024-09"
    )
    again = PacketExperience(
        title="Data Intern", employer="Acme Corp", start="2025-06", end="2025-09"
    )
    filled, review = smartrecruiters_entries.fill_experience(
        page, _packet(experience=[first, again]), _no_progress
    )
    assert review == []
    assert [item.get("state") for item in filled] == [None, None]
    assert page.evaluate("window.__sr.saves") == 2


def test_the_time_left_is_read_before_each_entry(browser):
    page = _open(browser)
    tutor = PacketExperience(title="Tutor", employer="Library", start="2024-01", end="2024-05")
    budget = [time.monotonic() + 120]
    progress: list[str] = []

    def spent(message: str) -> None:
        progress.append(message)
        if message.startswith("SmartRecruiters: added "):
            budget[0] = 0.0  # a model wait used the rest of the fill's time

    filled, review = smartrecruiters_entries.fill_experience(
        page, _packet(experience=[*_packet().experience, tutor]), spent, deadline=lambda: budget[0]
    )
    assert [item["label"] for item in filled] == ["Experience 1 (Data Intern at Acme Corp)"]
    assert review == ["Experience 2 (Tutor at Library)"]
    assert "SmartRecruiters: added experience Data Intern at Acme Corp" in progress


# --- Screening ---------------------------------------------------------------------------


def _reveal_citizenship(page) -> None:
    """Answering the work question reveals a country list, plus a hidden copy of it as
    the app renders for the branch not taken."""
    hidden = f'<div style="display:none">{_select("question_hidden", "Hidden copy of the list")}</div>'
    page.evaluate("""([group, html, id]) => {
      window.__sr.reveals = {[group]: {value: '1', html}};
      window.__sr.selects[id] = [['vn', 'Vietnam'], ['cn', 'China (PRC, including Hong Kong and Macau)'],
                                 ['none', 'None of these']];
      window.__sr.selects['question_hidden'] = [['x', 'Anything']];
    }""", [_WORK, _select("question_citizenship", _CITIZENSHIP) + hidden, "question_citizenship"])


def test_a_question_an_answer_reveals_is_answered_on_the_next_pass(browser, no_memory):
    page = _open(browser, "screening_resultant.html")
    _reveal_citizenship(page)
    fields = {**_SCREENING_FIELDS, "country": "United States", "us_citizen": "Yes"}
    filled, review = screening.fill_screening(page, _packet(fields=fields), _no_progress)
    answered = {item["label"]: item["value"] for item in filled}
    assert answered[screening._short(_CITIZENSHIP)] == "None of these"  # noqa: SLF001
    assert not any("Hidden copy" in line for line in review)
    assert not any("Hidden copy" in label for label in answered)
    # One record per question: the second pass adds the revealed one only.
    assert len(answered) == len(filled)


def test_a_listed_citizenship_is_picked_and_an_unknown_one_left_for_review(browser, no_memory):
    page = _open(browser, "screening_resultant.html")
    _reveal_citizenship(page)
    fields = {**_SCREENING_FIELDS, "country": "United States", "citizenship": "Vietnam"}
    filled, _review = screening.fill_screening(page, _packet(fields=fields), _no_progress)
    assert "Vietnam" in [item["value"] for item in filled]

    # On a visa in the U.S. with no citizenship given: never "None of these".
    page = _open(browser, "screening_resultant.html")
    _reveal_citizenship(page)
    fields = {**_SCREENING_FIELDS, "country": "United States", "us_citizen": "No"}
    filled, review = screening.fill_screening(page, _packet(fields=fields), _no_progress)
    assert not any(item["value"] == "None of these" for item in filled)
    assert any(line.startswith("Do you hold Citizenship") for line in review)


_NOTICE = "You declare that you have read and agree to the privacy notice of Acme."


def test_the_privacy_notice_is_ticked_when_notices_are_accepted(browser, no_memory):
    page = _open(browser, "screening_resultant.html")
    _add(page, _consent_box(_NOTICE))
    fields = {**_SCREENING_FIELDS, "auto_accept_notices": "Yes", "auto_accept_agreements": "No"}
    filled, review = screening.fill_screening(page, _packet(fields=fields), _no_progress)
    assert {"label": _NOTICE, "value": "checked"} in filled
    assert _checked(page, "consent-1")
    # The declaration that every answer is true binds the applicant: agreements only.
    assert not _checked(page, _DECLARATION)
    assert any(line.startswith("*I declare") for line in review)


def test_the_privacy_notice_is_left_when_notices_are_not_accepted(browser, no_memory):
    page = _open(browser, "screening_resultant.html")
    _add(page, _consent_box(_NOTICE))
    fields = {**_SCREENING_FIELDS, "auto_accept_notices": "No"}
    filled, review = screening.fill_screening(page, _packet(fields=fields), _no_progress)
    assert f"{_NOTICE}: read and tick it yourself" in review
    assert not _checked(page, "consent-1")
    assert all(item["label"] != _NOTICE for item in filled)


def test_the_consent_box_is_one_of_the_flows_own_controls(browser):
    page = _open(browser, "screening_resultant.html")
    _add(page, _consent_box(_NOTICE))
    assert "#consent-1" in screening.screening_selectors(page)


def test_answered_selects_are_not_reported_empty(browser, no_memory):
    # Every answered select read as an empty "*" at the final check (2026-10-30).
    page = _open(browser, "screening_resultant.html")
    readiness = fill_page._load_readiness_js()  # noqa: SLF001
    degree = "What is your current or most recently completed degree type?"
    assert degree in page.evaluate(readiness)["required_empty"]
    screening.fill_screening(page, _packet(fields=_SCREENING_FIELDS), _no_progress)
    left = page.evaluate(readiness)["required_empty"]
    assert degree not in left
    assert "*" not in left


@pytest.mark.parametrize(("section", "editor"), [
    ("experience", "experience_editor.html"), ("education", "education_editor.html"),
])
def test_the_generic_pass_leaves_entry_editors_to_the_flow(browser, section, editor):
    # Back reopens saved entries as editors (2026-10-30): read as questions, Description
    # went to the model to draft and Title/Institution were listed for review.
    page = _open(browser, replace={section: _fixture(editor)})
    scan = page.evaluate(fill_page._load_filler_js(), {  # noqa: SLF001
        "fields": {}, "hints": {}, "synonyms": fill_page._synonym_payload(), "scan": True,  # noqa: SLF001
    })
    labels = [question["label"] for question in scan["questions"]]
    assert "First name*" in labels
    assert not {"Title*", "Company", "Description", "Institution*", "Major"} & set(labels)
