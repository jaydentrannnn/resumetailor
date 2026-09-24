"""Browser-level checks for the Apply DOM decisions."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply import form_routes
from resume_tailor.apply.packet import Packet, PacketEducation
from resume_tailor.apply.workday_repeaters import fill_education_years_async


def _launch_sync(playwright):
    """Local Edge when present (the dev machine), else Playwright's own Chromium."""
    try:
        return playwright.chromium.launch(headless=True, channel="msedge")
    except Exception:  # noqa: BLE001 - fall back to the bundled/configured Chromium
        return playwright.chromium.launch(headless=True)


async def _launch_async(playwright):
    """Async twin of `_launch_sync`; skips the test when no Chromium exists at all."""
    try:
        return await playwright.chromium.launch(headless=True, channel="msedge")
    except Exception:  # noqa: BLE001
        try:
            return await playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Local Chromium unavailable: {exc}")


@pytest.fixture
def page():
    try:
        with sync_playwright() as playwright:
            browser = _launch_sync(playwright)
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def test_preferred_name_context_and_correction(page):
    page.set_content("""
      <fieldset><legend>Legal Name</legend><label for="legal">First Name</label><input id="legal" value="Alex Jordan"></fieldset>
      <fieldset><legend>Preferred Name</legend><label for="preferred">First Name</label><input id="preferred" value="Alex Jordan"></fieldset>
    """)
    js = (Path(__file__).parents[1] / "src/resume_tailor/apply/filler.js").read_text(encoding="utf-8")
    result = page.evaluate(js, {"fields": {"first_name": "Alex Jordan", "preferred_name": "AJ"}, "hints": {}, "synonyms": []})
    assert page.locator("#legal").input_value() == "Alex Jordan"
    assert page.locator("#preferred").input_value() == "AJ"
    assert any(item.get("corrected") for item in result["filled"])


def test_education_year_select_uses_year_from_full_resume_date(page):
    page.set_content("""
      <fieldset><legend>Education</legend><label for="start-year">Start Year</label>
        <select id="start-year"><option value="">Select</option><option value="2023">2023</option></select>
      </fieldset>
    """)
    js = (Path(__file__).parents[1] / "src/resume_tailor/apply/filler.js").read_text(encoding="utf-8")
    page.evaluate(js, {"fields": {"education_start_month": "2023-09"}, "hints": {}, "synonyms": []})
    assert page.locator("#start-year").input_value() == "2023"


def test_email_route_chooses_email_and_stops_after_transition(page):
    page.set_content("""
      <div id="auth"><button>Continue with Google</button><button>Sign in with LinkedIn</button>
      <button onclick="this.parentNode.innerHTML='<input type=email>'">Sign in with email</button></div>
    """)
    assert form_routes.choose_email_sync(page, deadline=time.monotonic() + 5) == "selected"
    assert page.locator("input[type=email]").count() == 1


def test_email_registration_is_selected_when_sign_in_is_unavailable(page):
    page.set_content("""
      <div id="auth"><button>Continue with Google</button>
      <button onclick="this.parentNode.innerHTML='<input type=email>'">Create account with email</button></div>
    """)
    assert form_routes.choose_email_sync(page, deadline=time.monotonic() + 5) == "selected"
    assert page.locator("input[type=email]").count() == 1


def test_ambiguous_email_routes_are_not_clicked(page):
    page.set_content("<div id='auth'><button>Sign in with email</button><button>Sign in with email</button></div>")
    assert form_routes.choose_email_sync(page, deadline=time.monotonic() + 5) == "ambiguous"


def test_social_only_auth_chooser_hands_off(page):
    page.set_content("<div id='auth'><button>Sign in with LinkedIn</button></div>")
    assert form_routes.choose_email_sync(page, deadline=time.monotonic() + 5) == "unavailable"


def test_required_consent_is_checked_without_optional_opt_in(page):
    page.set_content("""
      <div class="form-group"><label><input type="checkbox" required>I certify that this application is accurate</label></div>
      <div class="form-group"><label><input type="checkbox">Join the talent community</label></div>
    """)
    filled, unresolved = form_routes.accept_workday_sync(page)
    assert unresolved == []
    assert len(filled) == 1
    assert page.locator("input[type=checkbox]").nth(0).is_checked()
    assert not page.locator("input[type=checkbox]").nth(1).is_checked()


def test_required_consent_that_cannot_be_checked_is_reported(page):
    page.set_content('<label><input type="checkbox" required disabled>I agree to the privacy notice</label>')
    filled, unresolved = form_routes.accept_workday_sync(page)
    assert filled == []
    assert len(unresolved) == 1


def test_verified_workday_hidden_year_control_uses_matched_education_row():
    import asyncio
    from playwright.async_api import async_playwright

    async def exercise():
        async with async_playwright() as playwright:
            browser = await _launch_async(playwright)
            try:
                page = await browser.new_page()
                await page.set_content("""
                  <input id="education-1--schoolName" value="Test University">
                  <input id="education-1--fieldOfStudy" value="Computer Science">
                  <input id="education-1--firstYearAttended-dateSectionYear-input">
                  <div id="education-1--firstYearAttended-dateSectionYear-display"
                    onclick="document.getElementById('education-1--firstYearAttended-dateSectionYear-input').focus()">YYYY</div>
                """)
                packet = Packet(job_id="test", built_at="2026-01-01T00:00:00Z", education=[
                    PacketEducation(school="Test University", major="Computer Science", start="2023-09"),
                ])
                filled, review = await fill_education_years_async(page, packet)
                assert review == []
                assert filled[0]["value"] == "2023"
                assert await page.locator("[id='education-1--firstYearAttended-dateSectionYear-input']").input_value() == "2023"
            finally:
                await browser.close()

    asyncio.run(exercise())
