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
    """)
    page.evaluate(harvest.LISTENER_JS)
    page.fill("#t", "Payments")
    page.check("text=No")
    page.select_option("#s", "Remote")
    page.fill("#p", "secret")
    page.locator("#p").dispatch_event("change")
    typed = {t.label: t.value for t in harvest.from_listener(page.evaluate("window.__rtTyped"))}
    assert typed == {
        "Which team interests you?": "Payments", "Willing to travel?": "No", "Office": "Remote",
    }
