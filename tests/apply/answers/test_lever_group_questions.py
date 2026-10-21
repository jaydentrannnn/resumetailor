"""Lever's multiple-choice questions reach the resolver under their own question, not an
option's text (Batch 3, 2026-10-21: it was asked to answer "yes" and "Intern"), and a
required "check all that apply" list is one question with its options."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import page_blockers, widget_actions

_FIXTURE = Path(__file__).parents[2] / "fixtures/forms/lever_card_questions.html"


@pytest.fixture
def page():
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True, channel="msedge")
            except Exception:
                browser = playwright.chromium.launch(
                    headless=True, executable_path=os.environ.get("PW_CHROMIUM_PATH") or None
                )
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.abort())
                page.set_content(_FIXTURE.read_text(encoding="utf-8"))
                yield page
            finally:
                browser.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def test_radio_groups_carry_their_question(page):
    radios = [
        item for item in page_blockers.extract_page_blockers(page)["unresolved"]
        if item["type"] == "radiogroup"
    ]
    labels = {item["label"] for item in radios}
    assert "If offered a position at Acme, will you be able to start within 3 weeks?" in labels
    assert not labels & {"yes", "no", "Yes", "No", "Intern"}
    start = next(item for item in radios if item["label"].startswith("If offered"))
    assert start["options"] == ["yes", "no"]


def test_a_required_checkbox_list_is_one_question(page):
    groups = [
        item for item in page_blockers.extract_page_blockers(page)["unresolved"]
        if item["type"] == "checkboxgroup"
    ]
    assert len(groups) == 1
    languages = groups[0]
    assert languages["label"] == "Language Skill(s) (Check all that apply)"
    assert "English (ENG)" in languages["options"]
    assert widget_actions._check_options(page, languages["selector"], ["English (ENG)"])  # noqa: SLF001
    assert page.locator(languages["selector"]).first.is_checked()


def test_a_wrapped_radio_is_chosen_by_its_label(page):
    radios = [
        item for item in page_blockers.extract_page_blockers(page)["unresolved"]
        if item["type"] == "radiogroup" and item["label"].startswith("If offered")
    ]
    assert widget_actions._choose_radio_option(page, radios[0]["selector"], "no")  # noqa: SLF001
