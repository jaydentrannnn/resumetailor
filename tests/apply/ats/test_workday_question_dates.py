"""Workday's captured required graduation date, including its hidden spinbuttons."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.ats import workday_dates
from resume_tailor.apply.forms import fill_widgets

_CONTROL = "primaryQuestionnaire--e2195e91707810003428d6cc5ab70000"
_SECTIONS = ["dateSectionMonth", "dateSectionDay", "dateSectionYear"]
_FIXTURE = Path(__file__).parents[2] / "fixtures/forms/workday_graduation_date.html"


class _Page:
    def __init__(self, values=(), label="Expected Graduation Date"):
        self.values = list(values or ["", "", ""])
        self.label = label
        self.frames = [self]

    def evaluate(self, script, _arg=None):
        if script == workday_dates._QUESTION_DATES_JS:  # noqa: SLF001
            return [{"control": _CONTROL, "label": self.label,
                     "parts": _SECTIONS, "values": self.values}]
        # A generic scan cannot observe the date as a whole, even with one input filled.
        return {"filled": [{"selector": f"[id='{_CONTROL}-dateSectionMonth-input']",
                            "key": "existing", "value": self.values[0]}]}

    def locator(self, selector):
        index = next(i for i, part in enumerate(_SECTIONS) if part in selector)
        return SimpleNamespace(count=lambda: 1,
                               first=SimpleNamespace(input_value=lambda: self.values[index]))

    def bring_to_front(self):
        self.front = True


def _fill(monkeypatch, page, fields=None, *, succeeds=True):
    typed = []

    def type_parts(_page, control, parts):
        typed.append((control, parts))
        if succeeds:
            page.values = [value for _part, value in parts]
        return succeeds

    monkeypatch.setattr(workday_dates, "fill_date_sections", type_parts)
    blank, review = [], []
    filled = workday_dates.fill_question_dates(
        page, fields if fields is not None else {"graduation_month": "2027-06-01"},
        blank=blank, review=review,
    )
    return filled, typed, blank, review


def test_required_graduation_date_uses_profile_and_types_all_sections(monkeypatch):
    page = _Page()
    filled, typed, blank, review = _fill(monkeypatch, page)
    assert typed == [(_CONTROL, list(zip(_SECTIONS, ["06", "01", "2027"], strict=True)))]
    assert filled[0]["key"] == "graduation_month"
    assert filled[0]["value"] == "2027-06-01"
    assert blank == review == []
    item = {**filled[0], "frame_index": 0}
    identity = (0, item["selector"])
    observed = fill_widgets._observe_fields(page, "generic", {}, {identity: item})  # noqa: SLF001
    assert observed[identity]["value"] == "2027-06-01"
    page.values[1] = ""
    assert fill_widgets._observe_fields(page, "generic", {}, {identity: item}) == {}  # noqa: SLF001


@pytest.mark.parametrize("fields", [{}, {"graduation_month": "2027"}, {"graduation_month": "2027-06"}])
def test_missing_date_parts_are_reported_without_guessing(monkeypatch, fields):
    filled, typed, blank, review = _fill(monkeypatch, _Page(), fields)
    assert filled == typed == review == []
    assert blank == [{"key": "graduation_month", "label": "Expected Graduation Date"}]


@pytest.mark.parametrize("values", [["05", "25", "2028"], ["", "25", "2028"]])
def test_manual_date_is_kept_without_partially_changing_it(monkeypatch, values):
    filled, typed, blank, review = _fill(monkeypatch, _Page(values))
    assert filled == typed == blank == []
    assert review == ([] if all(values) else ["Expected Graduation Date"])


def test_matching_partial_date_is_completed(monkeypatch):
    filled, typed, blank, review = _fill(monkeypatch, _Page(["6", "", "2027"]))
    assert len(filled) == len(typed) == 1
    assert blank == review == []


def test_failed_typing_is_reviewed_without_claiming_a_fill(monkeypatch):
    filled, typed, blank, review = _fill(monkeypatch, _Page(), succeeds=False)
    assert filled == blank == []
    assert len(typed) == 2
    assert review == ["Expected Graduation Date"]


def test_background_date_typing_retries_once_in_front(monkeypatch):
    page = _Page()
    attempts = []

    def type_parts(_page, _control, parts):
        attempts.append(1)
        if len(attempts) == 1:
            return False
        assert page.front
        page.values = [value for _part, value in parts]
        return True

    monkeypatch.setattr(workday_dates, "fill_date_sections", type_parts)
    filled = workday_dates.fill_question_dates(page, {"graduation_month": "2027-06-01"})
    assert len(attempts) == 2
    assert len(filled) == 1


def test_unrelated_date_is_left_alone(monkeypatch):
    filled, typed, blank, review = _fill(monkeypatch, _Page(label="Date of birth"))
    assert filled == typed == blank == review == []


def test_captured_workday_spinbuttons_fill_and_stay_observable():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, channel="msedge")
        except Exception as exc:
            pytest.skip(f"Local Chromium unavailable: {exc}")
        try:
            page = browser.new_page()
            page.set_content(_FIXTURE.read_text(encoding="utf-8"))
            page.add_style_tag(content="input[role=spinbutton] { width: 0; opacity: 0; }")
            review = []
            filled = workday_dates.fill_question_dates(
                page, {"graduation_month": "2027-06-01"}, review=review,
            )
            assert review == []
            assert len(filled) == 1
            assert [page.locator(f"[id='{_CONTROL}-{part}-input']").input_value()
                    for part in _SECTIONS] == ["06", "01", "2027"]
            assert workday_dates.question_date_matches(page, filled[0])
        finally:
            browser.close()
