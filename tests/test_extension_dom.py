"""Synthetic job pages for the injected browser-extension extractor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

_EXT = Path(__file__).parents[1] / "extension"
# The same files, in the same order, that lib/capture.js EXTRACT_FILES injects.
_LIBS = "\n".join(
    (_EXT / name).read_text(encoding="utf-8") for name in ("lib/sites.js", "lib/applyLink.js")
)
_EXTRACT = _LIBS + "\n" + (_EXT / "extract.js").read_text(encoding="utf-8")
_FIXTURES = _EXT / "tests" / "fixtures"


def _open(page, url: str, fixture: str) -> None:
    """Serve a saved page at its real URL, so `location` is what the site would show."""
    html = (_FIXTURES / fixture).read_text(encoding="utf-8")
    page.route(
        "**/*",
        lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html),
    )
    page.goto(url)


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


def test_linkedin_search_pane_and_cards(page):
    url = "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=analyst"
    _open(page, url, "linkedin-search.html")
    result = page.evaluate(_EXTRACT)
    assert (result["role"], result["company"], result["location"]) == (
        "Summer Analyst",
        "Acme Capital",
        "New York, NY",
    )
    assert result["apply_kind"] == "easy_apply"
    assert result["apply_url"] == ""
    assert "Data Analyst Intern" not in result["jd_text"]
    cards = page.evaluate("RTSites.readCards(document, location.href)")
    assert [(c["job_id"], c["role"], c["company"]) for c in cards] == [
        ("4012345678", "Summer Analyst", "Acme Capital"),
        ("4012345679", "Data Analyst Intern", "Globex"),
    ]
    assert page.evaluate("RTSites.jobFromUrl(location.href).key") == "linkedin:jobs:4012345678"


def test_linkedin_external_apply_ignores_the_sidebar(page):
    _open(page, "https://www.linkedin.com/jobs/view/4099/", "linkedin-view-external.html")
    result = page.evaluate(_EXTRACT)
    assert result["apply_url"] == (
        "https://jobs.lever.co/hooli/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab/apply"
    )
    assert result["apply_kind"] == "external"


def test_indeed_search_pane(page):
    url = "https://www.indeed.com/jobs?q=analyst&vjk=a1b2c3d4e5f60718"
    _open(page, url, "indeed-search.html")
    result = page.evaluate(_EXTRACT)
    assert result["ats_guess"] == "indeed"
    assert (result["role"], result["company"]) == ("Financial Analyst", "Initech")
    assert result["apply_kind"] == "external"
    assert "monthly forecasts" in result["jd_text"]
    assert "Operations Intern" not in result["jd_text"]
    cards = page.evaluate("RTSites.readCards(document, location.href)")
    assert [c["url"] for c in cards] == [
        "https://www.indeed.com/viewjob?jk=a1b2c3d4e5f60718",
        "https://www.indeed.com/viewjob?jk=ffee0011aabb2233",
    ]


def test_indeed_viewjob(page):
    _open(page, "https://www.indeed.com/viewjob?jk=0a0b0c0d", "indeed-viewjob.html")
    result = page.evaluate(_EXTRACT)
    assert (result["role"], result["company"], result["location"]) == (
        "Staff Accountant",
        "Umbrella Corp",
        "Denver, CO",
    )
    assert result["apply_kind"] == "easy_apply"
    assert result["jd_text"].startswith("Umbrella Corp needs")


def test_login_wall_is_not_a_description(page):
    page.set_content("<main><h1>Sign in to view this job</h1><p>Create an account.</p></main>")
    result = page.evaluate(_EXTRACT)
    assert len(result["jd_text"]) < 200
