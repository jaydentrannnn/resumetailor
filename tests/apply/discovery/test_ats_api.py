"""Hermetic tests for ATS JSON API JD fetching."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from resume_tailor.apply.discovery import ats_api, fetch_browser, fetch_jd

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ats"


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
    text = ats_api.fetch_posting("greenhouse:figma:6143238004").text
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
    text = ats_api.fetch_posting("lever:lyft:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").text
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
    text = ats_api.fetch_posting("smartrecruiters:acme:12345").text
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
    first = ats_api.fetch_posting(key).text
    second = ats_api.fetch_posting(key).text
    assert first is not None and "Ashby" in first
    assert second == first
    assert len(calls) == 1


def test_fetch_posting_empty_on_404(monkeypatch):
    class _Resp:
        status_code = 404

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    assert ats_api.fetch_posting("lever:x:1") == ats_api.ApiRead()


def _fake_responses(monkeypatch, responses):
    """Patch `ats_api.httpx.get`; ``responses`` maps a URL substring to (status, body,
    landed URL or None). Returns the requested URLs."""
    calls: list[str] = []

    def get(url, **kwargs):
        calls.append(url)
        for needle, (status, body, landed) in responses.items():
            if needle in url:
                request = httpx.Request("GET", landed or url)
                if isinstance(body, dict):
                    return httpx.Response(status, json=body, request=request)
                return httpx.Response(status, text=body, request=request)
        raise AssertionError(f"unexpected fetch {url}")

    monkeypatch.setattr(ats_api.httpx, "get", get)
    return calls


def test_gh_jid_job_closed_when_greenhouse_embed_answers_404(monkeypatch):
    """A ``gh_jid`` key guesses its board from the careers page path ("careers"), so the
    board lookup misses; Greenhouse's embed page, keyed by id alone, says it closed."""
    calls = _fake_responses(monkeypatch, {
        "boards-api.greenhouse.io": (404, {}, None),
        "embed/job_app": (404, "Not found", None),
    })
    found = ats_api.fetch_posting("greenhouse:careers:4620638005")
    assert found == ats_api.ApiRead(gone="Greenhouse no longer lists it")
    assert calls[-1] == "https://boards.greenhouse.io/embed/job_app?token=4620638005"


def test_gh_jid_job_read_from_the_board_the_embed_redirects_to(monkeypatch):
    body = "<p>" + "Build trading systems in Python. " * 20 + "</p>"
    calls = _fake_responses(monkeypatch, {
        "boards/careers/jobs": (404, {}, None),
        "embed/job_app": (
            200, "<html></html>",
            "https://job-boards.greenhouse.io/embed/job_app?for=boerboel&token=4318882004",
        ),
        "boards/boerboel/jobs/4318882004": (200, {"content": body}, None),
    })
    found = ats_api.fetch_posting("greenhouse:careers:4318882004")
    assert found.text is not None and "trading systems" in found.text
    assert not found.gone
    assert calls[-1].startswith("https://boards-api.greenhouse.io/v1/boards/boerboel/jobs/4318882004")


def test_workday_403_s22_marks_the_posting_gone(monkeypatch):
    _fake_responses(monkeypatch, {
        "/wday/cxs/": (403, {"errorCode": "S22", "httpStatus": 403}, None),
    })
    found = ats_api.workday_posting("https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1")
    assert found == ats_api.ApiRead(gone="Workday no longer lists it")


def test_workday_other_refusals_are_not_gone(monkeypatch):
    _fake_responses(monkeypatch, {"/wday/cxs/": (403, {"errorCode": "S10"}, None)})
    url = "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
    assert ats_api.workday_posting(url) == ats_api.ApiRead()


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


def test_workday_posting_extracts_description(monkeypatch):
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
    text = ats_api.workday_posting(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/"
        "PA-CLIENT-STATE/Data-Analyst-Intern_R8551"
    ).text
    assert text is not None
    assert "Analyze data." in text
    assert requested == [
        "https://cai.wd5.myworkdayjobs.com/wday/cxs/cai/computer_aid/job/"
        "PA-CLIENT-STATE/Data-Analyst-Intern_R8551"
    ]


def test_workday_posting_keeps_all_paragraphs_not_just_largest(monkeypatch):
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
    text = ats_api.workday_posting(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
    ).text
    assert text is not None
    assert "Analyze data pipelines" in text
    assert "not to discriminate" in text


def test_workday_posting_none_when_short(monkeypatch):
    payload = {"jobPostingInfo": {"jobDescription": "<p>Too short</p>"}}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.workday_posting(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
    ).text
    assert text is None


def test_workday_posting_none_on_404(monkeypatch):
    class _Resp:
        status_code = 404

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr(ats_api.httpx, "get", lambda *a, **k: _Resp())
    text = ats_api.workday_posting(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
    ).text
    assert text is None


def test_workday_posting_none_for_non_workday_url():
    assert ats_api.workday_posting("https://boards.greenhouse.io/figma/jobs/1") == ats_api.ApiRead()


def test_fetch_jd_uses_workday_api_before_http(monkeypatch):
    """When the Workday feed succeeds, ``fetch_jd`` reports method=api and skips HTTP/CDP."""
    monkeypatch.setattr(
        ats_api, "workday_posting", lambda url: ats_api.ApiRead(text="Analyze data. " * 60)
    )

    def _no_http(*a, **k):
        raise AssertionError("HTTP should not run")

    monkeypatch.setattr(fetch_jd.httpx, "get", _no_http)

    def _no_browser(url):
        raise AssertionError("browser should not run")

    monkeypatch.setattr(fetch_browser, "read", _no_browser)
    result = fetch_jd.fetch_jd(
        "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1",
        allow_browser=True,
    )
    assert result.method == "api"
    assert result.ats == "workday"


def test_fetch_jd_falls_through_when_workday_api_misses(monkeypatch):
    """A Workday URL whose feed returns nothing still tries the HTTP/CDP path."""
    monkeypatch.setattr(ats_api, "workday_posting", lambda url: ats_api.ApiRead())

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
        "fetch_posting",
        lambda key: ats_api.ApiRead(text="A" * 500),
    )
    browser_calls: list[str] = []

    def _no_browser(url):
        browser_calls.append(url)
        raise AssertionError("browser should not run")

    monkeypatch.setattr(fetch_browser, "read", _no_browser)
    result = fetch_jd.fetch_jd(
        "https://boards.greenhouse.io/figma/jobs/1",
        allow_browser=True,
        canonical_key="greenhouse:figma:1",
    )
    assert result.method == "api"
    assert len(result.text) >= 500
    assert browser_calls == []


_WORKDAY_URL = "https://cai.wd5.myworkdayjobs.com/computer_aid/job/x/y_R1"
_JOB_DATA = '<script type="application/ld+json">{"@type": "JobPosting"}</script>'


def _workday_gone_page(monkeypatch, html: str) -> None:
    """The Workday feed answers 403/S22; the posting page itself serves ``html``."""
    monkeypatch.setattr(
        ats_api, "workday_posting", lambda url: ats_api.ApiRead(gone="Workday no longer lists it")
    )
    monkeypatch.setattr(
        fetch_jd.httpx, "get",
        lambda url, **k: httpx.Response(200, text=html, request=httpx.Request("GET", url)),
    )


def test_fetch_jd_closes_a_workday_posting_the_feed_refuses_and_the_page_lacks(monkeypatch):
    _workday_gone_page(monkeypatch, "<html><head></head><body><div id='root'></div></body></html>")
    result = fetch_jd.fetch_jd(_WORKDAY_URL, allow_browser=False)
    assert result.closed == "Posting closed (Workday no longer lists it)"
    assert result.method == "failed"
    assert result.error == result.closed


def test_fetch_jd_keeps_a_workday_posting_whose_page_still_has_job_data(monkeypatch):
    _workday_gone_page(monkeypatch, f"<html><head>{_JOB_DATA}</head><body></body></html>")
    result = fetch_jd.fetch_jd(_WORKDAY_URL, allow_browser=False)
    assert result.closed == ""


def test_fetch_jd_closes_a_posting_the_feed_says_is_gone(monkeypatch):
    monkeypatch.setattr(
        ats_api, "fetch_posting", lambda key: ats_api.ApiRead(gone="Greenhouse no longer lists it")
    )

    def _no_http(*a, **k):
        raise AssertionError("HTTP should not run")

    monkeypatch.setattr(fetch_jd.httpx, "get", _no_http)
    result = fetch_jd.fetch_jd(
        "https://www.spotandtango.com/careers?gh_jid=4620638005",
        canonical_key="greenhouse:careers:4620638005",
    )
    assert result.closed == "Posting closed (Greenhouse no longer lists it)"
