"""Hermetic browser regressions for stacked React Select dropdowns (Twitch, 2026-10)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import widget_actions

_FIXTURE = Path(__file__).parents[2] / "fixtures/forms/greenhouse_react_select_stack.html"


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, channel="msedge")
        except Exception:
            try:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=os.environ.get("PW_CHROMIUM_PATH") or None,
                )
            except Exception as exc:
                pytest.skip(f"Local Chromium unavailable: {exc}")
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(_FIXTURE.read_text(encoding="utf-8"))
            yield page
        finally:
            browser.close()


def test_a_failed_search_closes_its_menu_so_the_dropdowns_below_still_answer(page):
    # No relocation option says "Yes": the typed search finds nothing. Clearing it after
    # Escape reopened the menu over the next two questions, whose clicks then timed out.
    assert not widget_actions._select_combobox_option(  # noqa: SLF001
        page, "#relocate", "Yes", key="willing_to_relocate",
    )
    assert page.locator("#relocate").get_attribute("aria-expanded") == "false"
    assert page.locator("#relocate").input_value() == ""
    for selector in ("#employee", "#employed"):
        assert widget_actions._select_combobox_option(  # noqa: SLF001
            page, selector, "No", key="previous_worker",
        )
        assert widget_actions._selected_combobox_text(page.locator(selector)) == "No"  # noqa: SLF001


@pytest.mark.parametrize(
    ("selector", "value", "key"),
    [
        ("#relocate", "Yes", "willing_to_relocate"),  # the menu closes on the search
        ("#graduation", "2027-06", "graduation_month"),  # the menu says "No options"
    ],
)
def test_a_search_the_menu_says_matches_nothing_is_not_waited_out(page, selector, value, key):
    started = time.monotonic()
    assert not widget_actions._select_combobox_option(page, selector, value, key=key)  # noqa: SLF001
    # Seeing it ends the wait; eight 250 ms rereads per search term did not.
    assert time.monotonic() - started < 1.8
    assert page.locator(selector).get_attribute("aria-expanded") == "false"
