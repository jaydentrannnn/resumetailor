"""Hermetic browser regressions for reduced DoorDash and P&G widget shapes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import (
    hybrid_resolver,
    page_blockers,
    questions,
    resolver_types,
    widget_actions,
)
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.ats import ats_hints
from resume_tailor.apply.forms import field_matcher, fill_page
from resume_tailor.apply.funnel.packet_models import Packet

_ROOT = Path(__file__).parents[3]
_FIXTURE = _ROOT / "tests/fixtures/forms/doordash_pg_controls.html"
_FILLER = fill_page._load_filler_js()  # noqa: SLF001
_SOURCE_QUESTION = (
    "What source(s) of information influenced your decision to apply for a P&G position?"
)
_FIELDS = {
    "city": "Fountain Valley",
    "state": "California",
    "country": "United States",
    "phone_country_code": "+1",
    "phone_country_region": "United States",
    "how_heard": "LinkedIn",
}


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


def _fill(page, *, scan=False, plan=None):
    return page.evaluate(
        _FILLER,
        {
            "fields": _FIELDS,
            "hints": {},
            "synonyms": [list(p) for p in ats_hints.SYNONYMS],
            "eeo": field_matcher.eeo_patterns(_FIELDS),
            "scan": scan,
            "plan": plan,
        },
    )


def test_phone_prefix_is_verified_even_when_plus_one_is_already_displayed(page):
    blockers = page_blockers.extract_page_blockers(page)
    phone = next(item for item in blockers["unresolved"] if item["selector"] == "#country")
    assert phone["current"] == "+1"
    assert phone["phone_code_menu"] is True
    assert page.locator("#country-ca").get_attribute("aria-selected") == "true"
    original_phone = page.locator("#phone-number").input_value()

    assert widget_actions._select_combobox_option(  # noqa: SLF001
        page,
        "#country",
        "+1",
        key="phone_country_code",
        phone_region="United States",
    )

    assert page.locator("#country-us").get_attribute("aria-selected") == "true"
    assert page.locator("#country-ca").get_attribute("aria-selected") == "false"
    assert page.locator("#phone-country-value .iti__us").count() == 1
    assert page.locator("#phone-country-value").inner_text() == "+1"
    assert page.locator("#phone-number").input_value() == original_phone


def test_location_uses_profile_city_and_commits_the_matching_state_and_country(page):
    blockers = page_blockers.extract_page_blockers(page)
    location = next(
        item for item in blockers["unresolved"] if item["selector"] == "#candidate-location"
    )
    resolver = hybrid_resolver._StepResolver(  # noqa: SLF001
        page,
        Packet.model_construct(fields=_FIELDS),
        ApplicantProfile(),
        max_retries=1,
        on_progress=None,
        deadline=None,
        ledger=resolver_types.StepLedger(),
        only_invalid=False,
    )

    assert resolver._resolve_known([location]) == []  # noqa: SLF001
    assert "#candidate-location" in resolver.ledger.done
    assert page.evaluate("window.locationSearches") == ["Fountain Valley"]
    assert page.locator("#location-value").inner_text() == "Fountain Valley, CA, USA"
    assert page.locator("#candidate-location").get_attribute("data-committed") == (
        "Fountain Valley, CA, USA"
    )
    assert page.locator("#candidate-location").input_value() == ""


def test_optional_cover_letter_keeps_its_upload_header_and_requiredness(page):
    result = _fill(page)
    cover = next(item for item in result["file_inputs"] if item["selector"] == "#cover_letter")
    assert cover["label"] == "Cover Letter"
    assert cover["section"] == "Cover Letter"
    assert cover["required"] is False
    assert page.locator("#cover_letter").input_value() == ""


def test_pg_source_group_uses_full_question_and_saved_source_only(page):
    scanned = _fill(page, scan=True)["questions"]
    source = next(item for item in scanned if item["label"] == _SOURCE_QUESTION)
    assert source["kind"] == "multi"
    assert source["options"] == ["LinkedIn", "P&G Career Site", "Job Board"]
    assert source["required"] is True
    assert len([item for item in scanned if item["label"] == _SOURCE_QUESTION]) == 1
    plan = questions.plan_for(scanned, questions.Facts(fields=_FIELDS))
    assert plan[source["qid"]] == {"key": "how_heard", "value": "LinkedIn"}

    result = _fill(page, plan=plan)

    assert page.locator("#source-linkedin").is_checked()
    assert not page.locator("#source-career").is_checked()
    assert not page.locator("#source-jobboard").is_checked()
    assert any(
        item["key"] == "how_heard" and item["value"] == "LinkedIn" for item in result["filled"]
    )
