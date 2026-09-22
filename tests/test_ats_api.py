"""Hermetic tests for ATS JSON API JD fetching."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor.apply import ats_api, fetch_jd

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
