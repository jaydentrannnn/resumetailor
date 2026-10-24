"""Answers typed on the page into questions the fill left are saved to the Answer book."""

from __future__ import annotations

import os

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import answer_memory
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.forms.field_types import FieldObservation
from resume_tailor.apply.funnel import answer_harvest as harvest
from resume_tailor.apply.funnel import store_models


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    profile_mod.save_profile(profile_mod.ApplicantProfile(first_name="Ada"))


def _field(label, value, kind="text", **extra):
    return FieldObservation(
        snapshot_id="s", field_id=label, frame_id="0:1", document_generation="g",
        label=label, control_kind=kind, current_value=value, **extra,
    )


def _fill():
    return store_models.FillResult(
        field_outcomes=[
            {"field_id": "a", "label": "Which team interests you?", "state": "unanswered"},
            {"field_id": "b", "label": "Preferred office", "state": "verified_filled"},
            {"field_id": "c", "label": "Password", "state": "unanswered"},
        ],
        leftovers=[{"label": "Middle Name", "reason": "needs_review"}],
        required_empty=["Are you willing to travel?*"],
    )


def test_left_for_you_reads_every_kind_of_handoff():
    assert harvest.left_for_you(_fill()) == {
        "which team interests you", "middle name", "password", "are you willing to travel",
    }


def test_only_questions_the_fill_left_are_saved():
    fields = [
        _field("Which team interests you?", "Payments"),
        _field("Preferred office", "Austin"),  # the fill answered it: a correction, not ours
        _field("Password", "secret", constraints={"type": "password"}),
        _field("Middle Name", "Lovelace"),
        _field("Are you willing to travel?", "Yes", kind="combobox", selection_state="committed"),
        _field("Resume", "cv.pdf", kind="file"),
    ]
    app = store_models.Application(
        source="s", source_job_id="j", company="Acme", role="Analyst", ats="workday",
    )
    assert harvest.from_review(app, _fill(), fields) == 3
    saved = {(a.label, a.answer, a.source, a.ats) for a in answer_memory.list_answers()}
    assert saved == {
        ("Which team interests you?", "Payments", "page", "workday"),
        ("Are you willing to travel?", "Yes", "page", "workday"),
    }
    assert profile_mod.load_profile()[0].middle_name == "Lovelace"
    # Seen again on the next pass: nothing new to save.
    assert harvest.from_review(app, _fill(), fields) == 0
    assert len(answer_memory.list_answers()) == 2


def test_an_uncommitted_dropdown_is_not_an_answer():
    fields = [_field("Are you willing to travel?", "Ye", kind="combobox", selection_state="typed")]
    assert harvest.from_fields(fields) == []


def test_a_workday_row_holds_an_entry_not_an_answer():
    """Leidos (2026-10-24): "Company* = VNPT Group" saved from one row filled the next."""
    fields = [
        _field("Company*", "VNPT Group", constraints={"id": "workExperience-4--companyName"}),
        _field("Year", "2027", constraints={"id": "education-5--lastYearAttended-dateSectionYear-input"}),
        _field("Company you admire most?", "Acme", constraints={"id": "q1"}),
    ]
    assert harvest.from_fields(fields) == [harvest.Typed("Company you admire most?", "Acme")]


def test_listener_entries_are_read_by_label():
    raw = {"Which team interests you?*": {"value": " Payments ", "kind": "text"}, "Empty": {}}
    typed = harvest.from_listener(raw)
    assert typed == [harvest.Typed("Which team interests you?*", "Payments")]
    assert harvest.save(typed, harvest.left_for_you(_fill())) == 1


@pytest.fixture
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True, channel="msedge")
            except Exception:
                path = os.environ.get("PW_CHROMIUM_PATH")
                browser = playwright.chromium.launch(headless=True, executable_path=path or None)
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - no local browser: skip, as test_filler_dom does
        pytest.skip(f"no browser: {exc}")


def test_listener_records_typed_text_radios_and_selects(page):
    page.set_content("""
      <label for="t">Which team interests you?</label><input id="t">
      <fieldset><legend>Willing to travel?</legend>
        <label><input type="radio" name="r" value="y">Yes</label>
        <label><input type="radio" name="r" value="n">No</label></fieldset>
      <label for="s">Office</label><select id="s"><option>Austin</option><option>Remote</option></select>
      <label for="p">Password</label><input id="p" type="password">
      <label for="workExperience-4--companyName">Company*</label><input id="workExperience-4--companyName">
    """)
    page.evaluate(harvest.LISTENER_JS)
    page.fill("[id='workExperience-4--companyName']", "VNPT Group")
    page.fill("#t", "Payments")
    page.check("text=No")
    page.select_option("#s", "Remote")
    page.fill("#p", "secret")
    page.locator("#p").dispatch_event("change")
    typed = {t.label: t.value for t in harvest.from_listener(page.evaluate("window.__rtTyped"))}
    assert typed == {
        "Which team interests you?": "Payments", "Willing to travel?": "No", "Office": "Remote",
    }


def test_corrections_name_the_answers_the_applicant_changed_never_their_values():
    fill = store_models.FillResult(filled=[
        {"key": "phone", "label": "Phone", "value": "(916) 555-0147"},
        {"key": "earliest_start", "label": "Start date", "value": "06/15/2027"},
        {"key": "city", "label": "City", "value": "Sacramento"},
        {"key": "school", "label": "School", "value": "State University"},
        {"key": "existing", "label": "Country", "value": "United States", "preserved": True},
        {"key": "gpa", "label": "GPA", "value": "3.7"},
    ])
    fields = [
        _field("Phone", "916-555-0147"),  # reformatted, same number
        _field("Start date", "2027-06-15"),  # same date, other order
        _field("City", "Davis"),  # changed
        _field("School", "", kind="text"),  # blank: not counted
        _field("Country", "Canada"),  # the applicant's own answer
        _field("GPA", "3.9", kind="combobox", selection_state="typed"),  # not committed
    ]
    found = harvest.corrections(fill, fields)
    assert found == [{"label": "City", "key": "city"}]
    assert "Davis" not in str(found)


def test_a_repeated_label_is_never_paired_with_another_rows_field():
    fill = store_models.FillResult(filled=[
        {"key": "employer", "label": "Employer", "value": "Acme"},
        {"key": "employer", "label": "Employer", "value": "Globex"},
    ])
    fields = [_field("Employer", "Acme"), _field("Employer", "Globex")]
    assert harvest.corrections(fill, fields) == []


@pytest.mark.parametrize(("given", "shown", "same"), [
    ("3.7", "7.3", False),
    ("3.7", "3.70", True),
    ("$90,000", "90000", True),
    ("2026", "2027", False),
    ("06/2027", "2027-06", True),
    ("(916) 555-0147", "+1 916 555 0147", True),
    ("Apt 12, 3 Main St", "Apt 3, 12 Main St", False),
    ("$90,000", "$900.00", False),
    ("2027-05-06", "2027-06-05", False),
    ("2027-06-05", "June 5, 2027", True),
    ("2027-06-05", "06/05/2027", True),
])
def test_answers_compare_by_their_kind(given, shown, same):
    assert harvest._same_answer(given, shown) is same


def _stuck():
    return store_models.FillResult(
        field_outcomes=[
            {"label": "Which team interests you?", "state": "unanswered", "required": True},
            {"label": "Favourite colour", "state": "ambiguous", "required": False},
        ],
        required_empty=["I agree to the terms*"],
    )


def test_required_left_is_only_the_required_questions():
    assert harvest.required_left(_stuck()) == {"which team interests you", "i agree to the terms"}
    assert harvest.required_left(store_models.FillResult(status="awaiting_otp")) == set()


def test_answered_all_once_every_required_question_has_an_answer():
    typed = [harvest.Typed("Which team interests you?*", "Payments")]
    assert harvest.answered_all(_stuck(), typed) is False  # the box is not ticked yet
    ticked = [_field("I agree to the terms", "checked", kind="checkbox")]
    assert harvest.answered_all(_stuck(), typed, ticked) is True  # optional one may stay empty
    unticked = [_field("I agree to the terms", "", kind="checkbox")]
    assert harvest.answered_all(_stuck(), typed, unticked) is False


def test_answered_all_has_no_say_when_nothing_required_was_left():
    assert harvest.answered_all(store_models.FillResult(status="awaiting_otp"), []) is None


def test_listener_records_when_the_applicant_last_typed(page):
    page.set_content('<label for="t">Team</label><input id="t">')
    page.evaluate(harvest.LISTENER_JS)
    last, _now = page.evaluate(harvest._ACTIVITY_JS)
    assert last == 0
    page.fill("#t", "Payments")
    last, now = page.evaluate(harvest._ACTIVITY_JS)
    assert 0 < last <= now
