"""The freehire.me keyword search (`discovery/freehire.py`), over a recorded reply shape."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx

from resume_tailor.apply.discovery import freehire, job_apis
from resume_tailor.web.schemas import SourceConfig

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _job(slug: str, title: str = "Software Engineer Intern", **extra: Any) -> dict:
    job = {"public_slug": slug, "title": title, "company": "Acme", "location": "Austin, TX",
           "url": f"https://boards.greenhouse.io/acme/jobs/{slug[-3:]}",
           "posted_at": "2026-10-20T00:00:00Z",
           "enrichment": {"salary_min": 40, "salary_max": 45, "salary_currency": "usd"}}
    return {**job, **extra}


class _Reply:
    def __init__(self, body: Any, status_code: int = 200):
        self.body, self.status_code = body, status_code

    def json(self):
        return self.body


def _source(**extra: Any) -> SimpleNamespace:
    fields = dict(id="fh", country="US", max_age_days=7, include=[], exclude=[], locations=[])
    return SimpleNamespace(**{**fields, **extra})


def _search(get, source=None, max_pages=3):
    pauses = []
    rows, errors = freehire.search(source or _source(), query="software intern", get=get,
                                   now=NOW, max_pages=max_pages,
                                   pause=lambda: pauses.append(1))
    return rows, errors, pauses


def test_maps_jobs_to_rows_and_pages_until_the_total(monkeypatch):
    monkeypatch.setattr(freehire, "PAGE_SIZE", 2)
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        page = kwargs["params"]["offset"] // 2
        jobs = [[_job("a-101"), _job("b-102")], [_job("c-103")]][page]
        return _Reply({"data": jobs, "meta": {"total": 3, "limit": 2, "offset": page * 2}})

    rows, errors, pauses = _search(get)
    assert errors == [] and len(pauses) == 1 and len(calls) == 2
    url, kwargs = calls[0]
    assert url == "https://freehire.me/api/v1/jobs/search"
    assert kwargs["params"] == {"q": "software intern", "limit": 2, "offset": 0,
                                "countries": "us", "posted_within_days": 7}
    row = rows[0]
    assert (row.job_id, row.company, row.role, row.age_days, row.posted_at) == (
        "freehire:a-101", "Acme", "Software Engineer Intern", 2, "2026-10-20")
    assert row.application_link.startswith("https://boards.greenhouse.io/acme/")
    assert row.salary == "USD 40 - 45" and row.source_id == "fh"


def test_filters_like_every_keyword_search_and_skips_unusable_hits():
    jobs = [_job("a-101"), _job("b-102", title="Senior Staff Engineer"), {"title": "no slug"}]
    rows, _errors, _p = _search(lambda url, **kw: _Reply({"data": jobs, "meta": {"total": 3}}),
                                _source(exclude=["senior"]))
    assert [r.job_id for r in rows] == ["freehire:a-101"]


def test_errors_name_the_host_and_keep_rows_already_read(monkeypatch):
    monkeypatch.setattr(freehire, "PAGE_SIZE", 1)
    replies = iter([_Reply({"data": [_job("a-101")], "meta": {"total": 5}}),
                    _Reply({"error": "slow down"}, status_code=429)])
    rows, errors, _p = _search(lambda url, **kw: next(replies))
    assert len(rows) == 1 and errors == ["freehire.me answered HTTP 429"]

    def down(url, **kw):
        raise httpx.ConnectError("refused", request=httpx.Request("GET", url))

    assert _search(down)[1][0].startswith("could not reach freehire.me")


def test_base_url_is_overridable(monkeypatch):
    monkeypatch.setenv(freehire.URL_ENV, "http://localhost:9000/")
    seen = []
    _search(lambda url, **kw: seen.append(url) or _Reply({"data": []}))
    assert seen == ["http://localhost:9000/api/v1/jobs/search"]


def test_a_saved_freehire_search_runs_each_phrase_without_keys(monkeypatch):
    monkeypatch.setattr(job_apis, "_sleep", lambda _s: None)
    monkeypatch.setattr(job_apis.config, "credential", lambda key: None)
    source = SourceConfig(id="fh", kind="job_search", provider="freehire",
                          query="ml intern, data intern", country="us", max_age_days=7)
    queries = []

    def get(url, **kwargs):
        queries.append(kwargs["params"]["q"])
        return _Reply({"data": [_job("a-101")], "meta": {"total": 1}})

    rows, errors = job_apis.job_search_rows(source, get=get, now=NOW)
    assert queries == ["ml intern", "data intern"] and errors == []
    assert [r.job_id for r in rows] == ["freehire:a-101"]
