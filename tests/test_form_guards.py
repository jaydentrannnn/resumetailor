"""Hermetic tests for the fill edge-case checks (`apply/form_guards.py`, plan P4-E)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.forms import form_guards


@pytest.fixture(autouse=True)
def _fresh_hosts():
    form_guards.reset_hosts()
    yield
    form_guards.reset_hosts()


@pytest.mark.parametrize(
    "text",
    [
        "Sorry, this job is no longer available.",
        "We are no longer accepting applications for this role.",
        "The position has been filled. Browse other openings.",
        "This posting has expired",
        "The job you are looking for is no longer open.",
        "Applications are now closed.",
    ],
)
def test_closing_banners(text):
    assert form_guards.closed_posting(text).startswith("Posting closed")


def test_open_postings_are_not_closed():
    jd = "About the role\n" + "We build things. " * 200
    assert form_guards.closed_posting(jd) is None
    # A late mention in a long JD is not a closing banner.
    late = jd + " Applications are closed on public holidays."
    assert form_guards.closed_posting(late) is None


def test_gone_status_and_redirect_home():
    assert "410" in form_guards.closed_posting("", status=410)
    assert form_guards.closed_posting("", status=200) is None
    assert (
        form_guards.closed_posting(
            "Careers at Acme",
            requested_url="https://careers.acme.com/jobs/123-analyst",
            final_url="https://careers.acme.com/careers",
        )
        == "Posting closed (redirected to the careers home page)"
    )
    # A different host (an ATS redirect) is not "home".
    assert (
        form_guards.closed_posting(
            "Careers",
            requested_url="https://acme.com/jobs/123",
            final_url="https://boards.greenhouse.io/",
        )
        is None
    )


@pytest.mark.parametrize(
    ("lang", "english"),
    [
        ("", True),
        ("en", True),
        ("en-US", True),
        ("EN_gb", True),
        ("und", True),
        ("fr", False),
        ("de-DE", False),
        ("zh-Hans", False),
    ],
)
def test_form_language(lang, english):
    assert (form_guards.form_language(lang) is None) is english


def test_bot_block():
    assert "429" in form_guards.bot_block(status=429)
    assert "Access Denied" in form_guards.bot_block(title="Access Denied")
    assert form_guards.bot_block(body="Our systems have detected unusual traffic from you")
    assert form_guards.bot_block(status=200, title="Analyst Intern - Acme") is None


def test_host_rests_for_an_hour():
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    form_guards.block_host("https://boards.greenhouse.io/acme/jobs/1", now=now)
    left = form_guards.host_blocked("boards.greenhouse.io", now=now + timedelta(minutes=10))
    assert left == timedelta(minutes=50)
    assert form_guards.host_blocked("https://jobs.lever.co/x", now=now) is None
    assert (
        form_guards.host_blocked("https://boards.greenhouse.io/b", now=now + timedelta(hours=2))
        is None
    )
    # Expired entries are forgotten.
    assert form_guards.host_blocked("boards.greenhouse.io", now=now) is None


@pytest.mark.parametrize(
    ("text", "limit", "expected", "shortened"),
    [
        ("Short answer.", 100, "Short answer.", False),
        ("First point. Second point. Third point.", 30, "First point. Second point.", True),
        ("I love finance! Also markets.", 20, "I love finance!", True),
        ("One very long sentence without any stop at all", 20, "One very long", True),
        ("One very long sentence", 13, "One very long", True),
        ("Supercalifragilistic", 5, "", True),
        ("Anything", 0, "Anything", False),
    ],
)
def test_fit_to_limit(text, limit, expected, shortened):
    fitted, cut = form_guards.fit_to_limit(text, limit)
    assert (fitted, cut) == (expected, shortened)
    assert not cut or len(fitted) <= limit


class _Resp:
    def __init__(self, status: int, text: str = "", url: str = "https://careers.acme.com/jobs/1"):
        self.status_code = status
        self.text = text
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_jd_reports_a_closed_posting(monkeypatch):
    monkeypatch.setattr(fetch_jd.httpx, "get", lambda *a, **k: _Resp(404))
    result = fetch_jd.fetch_jd("https://careers.acme.com/jobs/1", allow_browser=False)
    assert result.closed == "Posting closed (the page answered 404)"
    assert result.method == "failed"

    page = "<html><body><h1>Analyst</h1><p>This job is no longer available.</p></body></html>"
    monkeypatch.setattr(fetch_jd.httpx, "get", lambda *a, **k: _Resp(200, page))
    result = fetch_jd.fetch_jd("https://careers.acme.com/jobs/1", allow_browser=False)
    assert result.closed.startswith("Posting closed")


def test_fetch_jd_open_posting_is_not_closed(monkeypatch):
    body = (
        "<html><body><h1>Analyst Intern</h1>"
        + "<p>Help us build models.</p>" * 80
        + "</body></html>"
    )
    monkeypatch.setattr(fetch_jd.httpx, "get", lambda *a, **k: _Resp(200, body))
    result = fetch_jd.fetch_jd("https://careers.acme.com/jobs/1", allow_browser=False)
    assert result.closed == ""
    assert result.method == "http"
