"""Browser-level checks for the Apply DOM decisions."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.ats.workday_repeaters import fill_education_years_async
from resume_tailor.apply.forms import form_routes
from resume_tailor.apply.funnel.packet_models import Packet, PacketEducation


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
    js = (Path(__file__).parents[3] / "src/resume_tailor/apply/forms/filler.js").read_text(encoding="utf-8")
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
    js = (Path(__file__).parents[3] / "src/resume_tailor/apply/forms/filler.js").read_text(encoding="utf-8")
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


_ICIMS_LEFTOVER = {
    "label": "I agree", "type": "checkbox", "options": [], "required": True,
    "reason": "Unrecognized field", "selector": "#accept_gdpr",
}


def test_required_consent_leftover_is_recognised_without_optional_boxes():
    assert form_routes.is_required_consent(_ICIMS_LEFTOVER)
    assert not form_routes.is_required_consent({**_ICIMS_LEFTOVER, "required": False})
    assert not form_routes.is_required_consent({**_ICIMS_LEFTOVER, "type": "radio"})
    assert not form_routes.is_required_consent({**_ICIMS_LEFTOVER, "label": "Email me job alerts"})
    assert not form_routes.is_required_consent({**_ICIMS_LEFTOVER, "label": "Sign up (agree to marketing)"})


def test_icims_style_consent_checkbox_is_ticked(page):
    page.set_content("""
      <input type="email" id="email">
      <label for="accept_gdpr">I agree</label><input type="checkbox" id="accept_gdpr" required>
    """)
    assert form_routes.tick_consent(page, _ICIMS_LEFTOVER)
    assert page.locator("#accept_gdpr").is_checked()


def test_consent_checkbox_with_hidden_input_is_ticked_through_its_label(page):
    page.set_content("""
      <input type="checkbox" id="accept_gdpr" style="position:absolute;opacity:0;pointer-events:none">
      <label for="accept_gdpr">I agree</label>
    """)
    assert form_routes.tick_consent(page, _ICIMS_LEFTOVER)
    assert page.locator("#accept_gdpr").is_checked()


def test_consent_checkbox_that_cannot_be_ticked_is_not_reported_ticked(page):
    page.set_content('<input type="checkbox" id="accept_gdpr" disabled><label>I agree</label>')
    assert not form_routes.tick_consent(page, _ICIMS_LEFTOVER)


def test_icims_step_ticks_consent_and_clears_it_from_the_blocking_lists(page):
    from types import SimpleNamespace

    from resume_tailor.apply.forms.fill_answers import _FillAnswers

    page.set_content('<label for="accept_gdpr">I agree</label><input type="checkbox" id="accept_gdpr">')
    leftover = {**_ICIMS_LEFTOVER, "frame_index": 0}
    run = SimpleNamespace(
        ats_name="icims", frames=[page], needs_review=[],
        merged={"filled": [], "leftovers": [leftover], "required_empty": ["accept_gdpr", "Other"]},
    )
    run._accept_consent = lambda item: _FillAnswers._accept_consent(run, item)
    run._resolve_leftover = lambda item: _FillAnswers._resolve_leftover(run, item)
    run._stop_if_out_of_time = lambda _msg: False
    _FillAnswers._resolve_leftovers(run)
    assert page.locator("#accept_gdpr").is_checked()
    assert run.merged["required_empty"] == ["Other"]
    assert run.merged["leftovers"] == []
    assert run.needs_review == []
    assert run.merged["filled"][0]["key"] == "consent"


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
