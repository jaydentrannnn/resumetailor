"""iCIMS postings: the description lives in the iframe document, fetched directly."""

from __future__ import annotations

import httpx
import pytest

from resume_tailor.apply.discovery import fetch_jd

_BODY = "Responsibilities include building data pipelines and dashboards. " * 12
_IFRAME_HTML = f"<html><body><h1>Data Intern</h1><p>About the Role</p><p>{_BODY}</p></body></html>"
_SHELL_HTML = "<html><body><nav>Home</nav><p>Cookies are used on this site.</p></body></html>"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://careers-x.icims.com/jobs/76992/machine-learning-intern---s/job",
            "https://careers-x.icims.com/jobs/76992/machine-learning-intern---s/job?in_iframe=1",
        ),
        (
            "https://careers-x.icims.com/jobs/20717/login?_sp=abc&mobile=false",
            "https://careers-x.icims.com/jobs/20717/job?in_iframe=1",
        ),
        (
            "https://careers-x.icims.com/jobs/5616/some-title/login",
            "https://careers-x.icims.com/jobs/5616/some-title/job?in_iframe=1",
        ),
    ],
)
def test_icims_content_url_points_at_the_iframe_document(url, expected):
    assert fetch_jd.icims_content_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/jobs/1/job",
        "https://careers-x.icims.com/jobs/search",
        "https://careers-x.icims.com/",
        "https://notimims.com/jobs/1/job",
    ],
)
def test_icims_content_url_ignores_other_pages(url):
    assert fetch_jd.icims_content_url(url) is None


def _fake_get(monkeypatch, responses):
    """Patch `httpx.get`; `responses` maps a URL substring to (status, html). Returns the
    list of (url, headers) calls."""
    calls: list[tuple[str, dict]] = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("headers") or {}))
        for needle, (status, html) in responses.items():
            if needle in url:
                request = httpx.Request("GET", url)
                return httpx.Response(status, text=html, request=request)
        raise AssertionError(f"unexpected fetch {url}")

    monkeypatch.setattr(fetch_jd.httpx, "get", get)
    return calls


def test_fetch_jd_reads_the_iframe_document_for_icims(monkeypatch):
    calls = _fake_get(monkeypatch, {"in_iframe=1": (200, _IFRAME_HTML)})
    url = "https://careers-x.icims.com/jobs/20717/login?_sp=abc"
    result = fetch_jd.fetch_jd(url, allow_browser=False)
    assert result.method == "http"
    assert result.ats == "icims"
    assert result.final_url == url
    assert "building data pipelines" in result.text
    assert len(calls) == 1


def test_icims_fetch_does_not_claim_to_be_chrome(monkeypatch):
    # iCIMS answers a Chrome User-Agent from a non-browser client with 405.
    calls = _fake_get(monkeypatch, {"in_iframe=1": (200, _IFRAME_HTML)})
    fetch_jd.fetch_jd("https://careers-x.icims.com/jobs/20717/job", allow_browser=False)
    assert "User-Agent" not in calls[0][1]


def test_icims_short_or_failed_iframe_falls_back_to_the_generic_path(monkeypatch):
    calls = _fake_get(monkeypatch, {
        "in_iframe=1": (405, "Not Allowed"),
        "/job": (200, _SHELL_HTML),
    })
    result = fetch_jd.fetch_jd("https://careers-x.icims.com/jobs/20717/job", allow_browser=False)
    assert result.method == "failed"
    assert "too short" in result.error
    assert len(calls) == 2
