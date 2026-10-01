"""Hermetic tests for ATS JSON API JD fetching."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor.apply.discovery import ats_api, fetch_jd

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ats"


@pytest.fixture(autouse=True)
def _clear_ashby():
    """Reset the process-lifetime Ashby board cache between tests."""
    ats_api.clear_ashby_cache()
    yield
    ats_api.clear_ashby_cache()


def _load(name: str):
    """Load a recorded ATS JSON fixture."""
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_greenhouse_extracts_content(monkeypatch):
    payload = _load("greenhouse.json")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.fetch_posting_text("greenhouse:figma:6143238004")
    assert text is not None
    assert "Python" in text
    assert len(text) >= 400


def test_lever_joins_sections(monkeypatch):
    payload = _load("lever.json")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.fetch_posting_text(
        "lever:lyft:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    assert text is not None
    assert "Requirements" in text
    assert "Python" in text


def test_smartrecruiters_strips_tags(monkeypatch):
    payload = _load("smartrecruiters.json")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.fetch_posting_text("smartrecruiters:acme:12345")
    assert text is not None
    assert "Bachelor" in text
    assert "<p>" not in text


def test_ashby_uses_board_cache(monkeypatch):
    payload = _load("ashby_board.json")
    calls: list[str] = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    def _get(url, **kwargs):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(ats_api.httpx, "get", _get)
    key = "ashby:acme:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    first = ats_api.fetch_posting_text(key)
    second = ats_api.fetch_posting_text(key)
    assert first is not None and "Ashby" in first
    assert second == first
    assert len(calls) == 1


def test_fetch_posting_text_none_on_404(monkeypatch):
    class _Resp:
        status_code = 404

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    assert ats_api.fetch_posting_text("greenhouse:x:1") is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://cai.wd5.myworkdayjobs.com/computer_aid/job/"
            "PA-CLIENT-STATE/Data-Analyst-Intern_R8551",
            "https://cai.wd5.myworkdayjobs.com/wday/cxs/cai/computer_aid/job/"
            "PA-CLIENT-STATE/Data-Analyst-Intern_R8551",
        ),
        (
            "https://mfs.wd1.myworkdayjobs.com/en-US/MFS-Careers/job/Boston/"
            "Co-op_MFS-231931",
            "https://mfs.wd1.myworkdayjobs.com/wday/cxs/mfs/MFS-Careers/job/"
            "Boston/Co-op_MFS-231931",
        ),
        ("https://boards.greenhouse.io/figma/jobs/1", None),
    ],
)
def test_workday_api_url(url, expected):
    assert ats_api._workday_api_url(url) == expected


def test_workday_posting_text_extracts_description(monkeypatch):
    payload = {
        "jobPostingInfo": {
            "title": "Data Analyst Intern",
            "jobDescription": "<p>" + "Analyze data. " * 60 + "</p>",
        }
    }

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    requested: list[str] = []

    def _get(url, **kwargs):
        requested.append(url)
        return _Resp()

    monkeypatch.setattr(ats_api.httpx, "get", _get)
    text = ats_api.workday_posting_text(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/"
        "PA-CLIENT-STATE/Data-Analyst-Intern_R8551"
    )
    assert text is not None
    assert "Analyze data." in text
    assert requested == [
        "https://cai.wd5.myworkdayjobs.com/wday/cxs/cai/computer_aid/job/"
        "PA-CLIENT-STATE/Data-Analyst-Intern_R8551"
    ]


def test_workday_posting_text_keeps_all_paragraphs_not_just_largest(monkeypatch):
    """A real posting's ``jobDescription`` is several ``<p>`` blocks — an EEO/
    boilerplate paragraph can easily be the single largest one. Regression for a
    bug where `extract_text`'s "largest block only" page-scraping heuristic was
    reused on this JD-only fragment and silently dropped everything else (e.g. a
    957-char EEO paragraph kept, an ~8k-char responsibilities/requirements body
    thrown away)."""
    responsibilities = "<p>" + "Analyze data pipelines and dashboards. " * 20 + "</p>"
    eeo = "<p>" + "It is the policy of Acme not to discriminate. " * 25 + "</p>"
    assert len(eeo) > len(responsibilities)  # the boilerplate block is the larger one
    payload = {"jobPostingInfo": {"jobDescription": responsibilities + eeo}}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.workday_posting_text(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
    )
    assert text is not None
    assert "Analyze data pipelines" in text
    assert "not to discriminate" in text


def test_workday_posting_text_none_when_short(monkeypatch):
    payload = {"jobPostingInfo": {"jobDescription": "<p>Too short</p>"}}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.workday_posting_text(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
    )
    assert text is None


def test_workday_posting_text_none_on_404(monkeypatch):
    class _Resp:
        status_code = 404

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.workday_posting_text(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
    )
    assert text is None


def test_workday_posting_text_none_for_non_workday_url():
    assert ats_api.workday_posting_text("https://boards.greenhouse.io/figma/jobs/1") is None


def test_fetch_jd_uses_workday_api_before_http(monkeypatch):
    """When the Workday feed succeeds, ``fetch_jd`` reports method=api and skips HTTP/CDP."""
    monkeypatch.setattr(
        ats_api, "workday_posting_text", lambda url: "Analyze data. " * 60
    )

    def _no_http(*a, **k):
        raise AssertionError("HTTP should not run")

    monkeypatch.setattr(fetch_jd.httpx, "get", _no_http)

    def _no_browser(url):
        raise AssertionError("browser should not run")

    monkeypatch.setattr(fetch_jd, "_fetch_via_browser", _no_browser)
    result = fetch_jd.fetch_jd(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1",
        allow_browser=True,
    )
    assert result.method == "api"
    assert result.ats == "workday"


def test_fetch_jd_falls_through_when_workday_api_misses(monkeypatch):
    """A Workday URL whose feed returns nothing still tries the HTTP/CDP path."""
    monkeypatch.setattr(ats_api, "workday_posting_text", lambda url: None)

    class _Resp:
        status_code = 200
        url = "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
        text = "<html><body>" + "x" * 500 + "</body></html>"

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr(fetch_jd.httpx, "get", lambda *a, **k: _Resp())
    result = fetch_jd.fetch_jd(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1",
        allow_browser=False,
    )
    assert result.method == "http"


def test_fetch_jd_uses_api_before_browser(monkeypatch):
    """When the ATS API succeeds, ``fetch_jd`` reports method=api and skips CDP."""
    monkeypatch.setattr(
        ats_api,
        "fetch_posting_text",
        lambda key: "A" * 500,
    )
    browser_calls: list[str] = []

    def _no_browser(url):
        browser_calls.append(url)
        raise AssertionError("browser should not run")

    monkeypatch.setattr(fetch_jd, "_fetch_via_browser", _no_browser)
    result = fetch_jd.fetch_jd(
        "https://boards.greenhouse.io/figma/jobs/1",
        allow_browser=True,
        canonical_key="greenhouse:figma:1",
    )
    assert result.method == "api"
    assert len(result.text) >= 500
    assert browser_calls == []
