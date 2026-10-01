"""SmartRecruiters: the "I'm interested" entry, its DataDome wall, and assist-only submit.

The posting markup is trimmed from jobs.smartrecruiters.com/Resultant/744000151474767
(2026-09): the same entry link repeats in the header, sidebar and footer, and hidden
"apply with Smartr" twins point at another site.
"""

from __future__ import annotations

import asyncio

import pytest

from resume_tailor.apply.ats import adapters, ats_hints
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import fill
from resume_tailor.web.schemas import ApplySettings

_FORM = "https://jobs.smartrecruiters.com/oneclick-ui/company/Acme/publication/abc"
_POSTING = f"""
  <h1>Data Analyst Intern</h1>
  <a href="{_FORM}" class="button button--primary js-oneclick job-button">I'm interested</a>
  <a href="https://www.smartr.me/oneclick-ui/company/Acme/publication/abc"
     class="apply-with-smartr-button js-smartr-oneclick h" style="display:none">I'm interested</a>
  <a href="{_FORM}" id="st-apply" class="button js-oneclick button--block">I'm interested</a>
  <button type="submit">Submit</button>
"""


@pytest.mark.parametrize("label", [
    "Apply", "Apply now", "Apply for this job", "Apply for this position", "Apply manually",
    "I'm interested", "I’m interested", "I am interested", "Start application",
])
def test_every_entry_label_opens_an_application(label):
    assert ats_hints.APPLY_ENTRY_PATTERN.search(label)
    assert not clicks.reads_as_submit(label)


@pytest.mark.parametrize("label", ["Submit", "Submit application", "Not interested", "Interests"])
def test_other_buttons_are_not_entries(label):
    assert not ats_hints.APPLY_ENTRY_PATTERN.search(label)


def test_smartrecruiters_urls_get_their_adapter():
    assert isinstance(adapters.for_url("https://jobs.smartrecruiters.com/Acme/7440001"), adapters.SmartRecruitersAdapter)
    assert adapters.for_url("https://careers.smartrecruiters.com/Acme").platform == "smartrecruiters"
    assert adapters.for_url("https://example.com/jobs/1").platform == "generic"


def test_smartrecruiters_never_submits_automatically():
    settings = ApplySettings(auto_submit_enabled=True, auto_submit_ats=["smartrecruiters"])
    assert "smartrecruiters" in fill.ASSIST_ONLY_ATS
    assert fill.decide_submit_action(ats="smartrecruiters", settings=settings, ready_to_submit=True) == "awaiting_review"


def _page(playwright):
    try:
        browser = playwright.chromium.launch(headless=True, channel="msedge")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Local Chromium unavailable: {exc}")
    return browser


@pytest.mark.browser
def test_the_legacy_entry_follows_the_postings_own_link_once():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = _page(playwright)
        try:
            page = browser.new_page()
            followed: list[str] = []
            page.route("**/oneclick-ui/**", lambda route: (followed.append(route.request.url),
                                                          route.fulfill(body="<h1>Form</h1>")))
            page.route("**/smartr.me/**", lambda route: (followed.append(route.request.url), route.abort()))
            page.set_content(_POSTING)
            landed = fill.find_and_click_apply(page, "smartrecruiters")
            landed.wait_for_load_state()
            assert followed == [_FORM]
            assert landed.locator("h1").inner_text() == "Form"
        finally:
            browser.close()


@pytest.mark.browser
def test_the_verified_adapter_enters_the_form():
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.launch(headless=True, channel="msedge")
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"Local Chromium unavailable: {exc}")
            try:
                page = await browser.new_page()
                await page.route("**/oneclick-ui/**", lambda route: route.fulfill(body="<h1>Form</h1>"))
                await page.set_content(_POSTING)
                page = await adapters.SmartRecruitersAdapter().enter_application(page, timeout_ms=5000)
                assert page.url == _FORM
                # On the form already: nothing more is clicked.
                assert await adapters.SmartRecruitersAdapter().enter_application(page, timeout_ms=5000) is page
            finally:
                await browser.close()

    asyncio.run(run())


@pytest.mark.browser
def test_the_datadome_wall_is_a_barrier_for_the_applicant():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = _page(playwright)
        try:
            page = browser.new_page()
            page.route("**/captcha-delivery.com/**", lambda route: route.fulfill(body="Verification Required"))
            page.set_content('<p>Please try again later.</p><iframe title="Verification system" '
                             'src="https://geo.captcha-delivery.com/captcha/?initialCid=x" width="400" height="300"></iframe>')
            assert fill._detect_barriers(page) == "CAPTCHA detected"  # noqa: SLF001
        finally:
            browser.close()
