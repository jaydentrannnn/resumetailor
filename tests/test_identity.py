"""Hermetic tests for ATS identity helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor import config
from resume_tailor.apply import identity


@pytest.fixture
def resolve_cache(tmp_path, monkeypatch):
    """Isolate the permanent URL resolve cache under a temp applications dir."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    return tmp_path / "applications"


def test_canonical_key_greenhouse_boards():
    key = identity.canonical_key(
        "https://boards.greenhouse.io/figma/jobs/6143238004?gh_jid=6143238004"
    )
    assert key == "greenhouse:figma:6143238004"


def test_canonical_key_greenhouse_job_boards():
    key = identity.canonical_key(
        "https://job-boards.greenhouse.io/doordashusa/jobs/8171041"
    )
    assert key == "greenhouse:doordashusa:8171041"


def test_canonical_key_greenhouse_via_gh_jid_on_careerpuck():
    key = identity.canonical_key(
        "https://app.careerpuck.com/job-board/lyft/job/8767726002?gh_jid=8767726002"
    )
    assert key == "greenhouse:lyft:8767726002"


def test_canonical_key_other_fallback():
    key = identity.canonical_key(
        "https://apply.careers.microsoft.com/careers/job/1970393556982258"
    )
    assert key.startswith("other:apply.careers.microsoft.com:")


def test_group_key_collapses_locations():
    a = identity.group_key(
        "Northrop Grumman",
        "2027 Embedded Software Engineer Intern - Baltimore MD",
    )
    b = identity.group_key(
        "Northrop Grumman",
        "2027 Embedded Software Engineer Intern - Camarillo CA",
    )
    assert a == b


def test_group_key_strips_year_season_and_parens():
    a = identity.group_key(
        "ICF", "2027 Summer Intern, Software Developer (Reston, VA)"
    )
    b = identity.group_key("ICF", "Summer Intern, Software Developer")
    assert a == b


def test_resolve_final_url_caches_and_skips_second_http(resolve_cache, monkeypatch):
    """First call hits HTTP and writes the cache; second call is a cache hit."""
    calls: list[str] = []

    class _Resp:
        status_code = 200
        url = "https://boards.greenhouse.io/acme/jobs/99?utm_source=x&gh_jid=99"

    def _head(url, **kwargs):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(identity.httpx, "head", _head)
    wrapper = "https://simplify.jobs/p/abc"
    first = identity.resolve_final_url(wrapper)
    assert first == "https://boards.greenhouse.io/acme/jobs/99?gh_jid=99"
    assert len(calls) == 1
    cache_path = config.APPLICATIONS_OUTPUT_DIR / "url_resolve_cache.json"
    assert cache_path.is_file()
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert raw[wrapper] == first

    second = identity.resolve_final_url(wrapper)
    assert second == first
    assert len(calls) == 1


def test_resolve_final_url_passthrough_for_direct_ats():
    url = "https://boards.greenhouse.io/figma/jobs/1"
    assert identity.resolve_final_url(url) == url
