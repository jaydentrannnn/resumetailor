"""A posting page that is closed or gone is named as closed before the fill looks for a
form (`fill_page.closed_page`, Batch 3 2026-10-21), never reported as "no controls"."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.forms import fill_page

_FORMS = Path(__file__).parents[2] / "fixtures/forms"


@pytest.fixture(scope="module")
def browser():
    try:
        with sync_playwright() as playwright:
            try:
                launched = playwright.chromium.launch(headless=True, channel="msedge")
            except Exception:
                launched = playwright.chromium.launch(
                    headless=True, executable_path=os.environ.get("PW_CHROMIUM_PATH") or None
                )
            try:
                yield launched
            finally:
                launched.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def _page(browser, html: str):
    page = browser.new_page()
    page.route("**/*", lambda route: route.abort())
    page.set_content(html, wait_until="domcontentloaded")
    return page


def test_ashbys_job_not_found_page_is_closed(browser):
    page = _page(browser, (_FORMS / "ashby_job_not_found.html").read_text(encoding="utf-8"))
    try:
        reason = fill_page.closed_page(page, "https://jobs.ashbyhq.com/acme/35c2d853-b6ab-4ba7")
    finally:
        page.close()
    assert reason and reason.startswith("Posting closed")


def test_an_open_form_is_not_closed(browser):
    page = _page(browser, (_FORMS / "greenhouse.html").read_text(encoding="utf-8"))
    try:
        assert fill_page.closed_page(page, "https://job-boards.greenhouse.io/acme/jobs/123") is None
    finally:
        page.close()


def test_a_gh_jid_link_without_its_greenhouse_job_is_closed(browser):
    home = "<h1>Careers at Acme</h1><a href='/jobs'>See open roles</a>"
    page = _page(browser, home)
    try:
        reason = fill_page.closed_page(page, "https://careers.acme.com/?gh_jid=4421632009")
    finally:
        page.close()
    assert reason and "Greenhouse job" in reason
    page = _page(browser, home + "<div id='grnhse_app'></div>")
    try:
        assert fill_page.closed_page(page, "https://careers.acme.com/?gh_jid=4421632009") is None
    finally:
        page.close()


def test_a_gh_jid_page_with_its_own_form_is_not_closed(browser):
    # Duolingo draws its application form from Greenhouse's API, with no embed frame.
    own_form = ("<h1>Software Engineer</h1><form><label for='fn'>First Name</label>"
                "<input id='fn'><textarea aria-label='Cover letter'></textarea></form>")
    page = _page(browser, own_form)
    try:
        assert fill_page.closed_page(
            page, "https://careers.acme.com/jobs/8888721002?gh_jid=8888721002") is None
    finally:
        page.close()
