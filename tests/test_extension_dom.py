"""Synthetic job pages for the injected browser-extension extractor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

_EXTRACT = (Path(__file__).parents[1] / "extension/extract.js").read_text(encoding="utf-8")


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
                yield browser.new_page()
            finally:
                browser.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def test_linkedin_redirect_and_details(page):
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=""))
    page.goto("https://www.linkedin.com/jobs/view/3812345678")
    page.set_content("""
      <h1 class="job-details-jobs-unified-top-card__job-title">Analyst</h1>
      <div class="job-details-jobs-unified-top-card__company-name">Acme</div>
      <div class="job-details-jobs-unified-top-card__tertiary-description-container">New York</div>
      <div class="jobs-description">Build models and present results to clients.</div>
      <a href="/redir/redirect?url=https%3A%2F%2Fboards.greenhouse.io%2Facme%2Fjobs%2F5">Apply</a>
    """)
    result = page.evaluate(_EXTRACT)
    assert result["ats_guess"] == "linkedin"
    assert (result["company"], result["role"], result["location"]) == (
        "Acme",
        "Analyst",
        "New York",
    )
    assert "Build models" in result["jd_text"]
    assert result["apply_url"] == "https://boards.greenhouse.io/acme/jobs/5"


def test_greenhouse(page):
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=""))
    page.goto("https://boards.greenhouse.io/acme/jobs/5")
    page.set_content("""
      <h1>Analyst</h1><div class="company-name">Acme</div><div class="location">Remote</div>
      <div id="content">Prepare financial reports and study the business.</div>
    """)
    result = page.evaluate(_EXTRACT)
    assert result["ats_guess"] == "greenhouse"
    assert result["role"] == "Analyst"
    assert result["company"] == "Acme"
    assert result["location"] == "Remote"
    assert result["jd_text"].startswith("Prepare financial reports")


def test_generic_page_ignores_navigation_and_hidden_text(page):
    page.set_content(
        """
      <nav>"""
        + "Navigation " * 90
        + """</nav>
      <main><h1>Research Associate</h1><article>"""
        + "Analyze markets and write reports. " * 20
        + """</article></main>
      <section hidden>"""
        + "Hidden unrelated text " * 70
        + """</section>
    """
    )
    result = page.evaluate(_EXTRACT)
    assert "Analyze markets" in result["jd_text"]
    assert "Navigation" not in result["jd_text"]
    assert "Hidden" not in result["jd_text"]


def test_login_wall_is_not_a_description(page):
    page.set_content("<main><h1>Sign in to view this job</h1><p>Create an account.</p></main>")
    result = page.evaluate(_EXTRACT)
    assert len(result["jd_text"]) < 200
