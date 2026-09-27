"""Hermetic tests for company watchlists (`apply/boards.py`, `sources.board_rows`, P4-D)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from resume_tailor.apply import boards, eligibility, identity, sources
from resume_tailor.web.app import app as web_app
from resume_tailor.web.routes import discovery
from resume_tailor.web.schemas import ApplySettings, SourceConfig

NOW = datetime(2026, 9, 25, tzinfo=UTC)


class _Response:
    def __init__(self, status: int, payload=None, *, bad_json: bool = False) -> None:
        self.status_code = status
        self._payload = payload
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


class _FakeGet:
    """Serves canned responses by URL and records every request."""

    def __init__(self, routes: dict[str, _Response]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                return response
        return _Response(404)


GREENHOUSE = {
    "jobs": [
        {
            "id": 101,
            "title": "Investment Banking Summer Analyst",
            "updated_at": "2026-09-20T10:00:00-04:00",
            "location": {"name": "New York, NY"},
            "company_name": "Acme Capital",
        },
        {
            "id": 102,
            "title": "Senior Associate",
            "updated_at": "2026-09-24T00:00:00Z",
            "location": {"name": "New York, NY"},
        },
        {
            "id": 103,
            "title": "Finance Intern",
            "updated_at": "2026-09-24T00:00:00Z",
            "location": {"name": "Boston, MA"},
        },
        {"id": 104, "title": "Finance Intern", "updated_at": "", "location": {"name": "Remote"}},
    ]
}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/acme", ("greenhouse", "acme")),
        ("job-boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
        ("https://boards.greenhouse.io/embed/job_board?for=acme&b=x", ("greenhouse", "acme")),
        ("https://jobs.lever.co/acme/0f8f6c1e-0000-0000-0000-000000000000", ("lever", "acme")),
        ("https://jobs.ashbyhq.com/acme", ("ashby", "acme")),
        ("https://careers.smartrecruiters.com/AcmeCorp", ("smartrecruiters", "AcmeCorp")),
        ("https://acme.wd5.myworkdayjobs.com/en-US/External", ("workday", "acme.wd5/acme/External")),
        ("https://acme.wd5.myworkdayjobs.com/External/job/Boston/Analyst_R12345", ("workday", "acme.wd5/acme/External")),
        ("https://www.acme.com/careers", None),
        ("https://jobs.lever.co/", None),
        ("", None),
    ],
)
def test_parse_board_url(url, expected):
    assert boards.parse_board_url(url) == expected


def test_greenhouse_listing_uses_the_ats_job_url():
    get = _FakeGet(
        {"https://boards-api.greenhouse.io/v1/boards/acme/jobs": _Response(200, GREENHOUSE)}
    )
    jobs = boards.list_board("greenhouse", "acme", get=get)
    assert [j.id for j in jobs] == ["101", "102", "103", "104"]
    assert jobs[0].url == "https://boards.greenhouse.io/acme/jobs/101"
    assert identity.canonical_key(jobs[0].url) == "greenhouse:acme:101"
    assert jobs[0].company == "Acme Capital"


def test_lever_ashby_and_smartrecruiters_listings():
    get = _FakeGet(
        {
            "https://api.lever.co/v0/postings/acme": _Response(
                200,
                [
                    {
                        "id": "abc",
                        "text": "Strategy Intern",
                        "hostedUrl": "https://jobs.lever.co/acme/abc",
                        "createdAt": 1789000000000,
                        "categories": {"location": "Chicago"},
                    },
                ],
            ),
            "https://api.ashbyhq.com/posting-api/job-board/acme": _Response(
                200,
                {
                    "jobs": [
                        {
                            "id": "a1",
                            "title": "Ops Analyst",
                            "location": "Remote",
                            "publishedAt": "2026-09-01",
                        },
                        {"id": "a2", "title": "Hidden", "isListed": False},
                    ]
                },
            ),
            "https://api.smartrecruiters.com/v1/companies/Acme/postings?limit=100&offset=0": _Response(
                200,
                {
                    "totalFound": 101,
                    "content": [
                        {
                            "id": "1",
                            "name": "Marketing Intern",
                            "releasedDate": "2026-09-10T00:00:00Z",
                            "location": {"city": "Austin", "region": "TX", "remote": False},
                            "company": {"name": "Acme Corp"},
                        },
                    ],
                },
            ),
            "https://api.smartrecruiters.com/v1/companies/Acme/postings?limit=100&offset=100": _Response(
                200,
                {
                    "totalFound": 101,
                    "content": [
                        {"id": "2", "name": "Finance Intern", "location": {"remote": True}},
                    ],
                },
            ),
        }
    )
    (lever,) = boards.list_board("lever", "acme", get=get)
    assert (lever.title, lever.location) == ("Strategy Intern", "Chicago")
    assert lever.updated_at.startswith("2026-")
    ashby = boards.list_board("ashby", "acme", get=get)
    assert [j.id for j in ashby] == ["a1"]
    assert ashby[0].url == "https://jobs.ashbyhq.com/acme/a1"
    smart = boards.list_board("smartrecruiters", "Acme", get=get)
    assert [j.id for j in smart] == ["1", "2"]
    assert smart[0].location == "Austin, TX" and smart[0].company == "Acme Corp"
    assert smart[1].location == "(Remote)"


def test_workday_listing_pages_with_post_and_round_trips():
    endpoint = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/jobs"
    calls = []

    def post(url, **kwargs):
        assert url == endpoint
        calls.append(kwargs["json"])
        offset = kwargs["json"]["offset"]
        postings = [
            {"title": "Finance Intern", "locationsText": "Boston, MA", "postedOn": "Posted 3 Days Ago",
             "externalPath": "/job/Boston/Finance-Intern_R12345"},
        ] if offset == 0 else [
            {"title": "Strategy Analyst", "locationsText": "Remote", "postedOn": "Posted Today",
             "externalPath": "/job/Remote/Strategy-Analyst_R12346"},
        ]
        return _Response(200, {"total": 21, "jobPostings": postings})

    slug = "acme.wd5/acme/External"
    assert boards.board_url("workday", slug) == "https://acme.wd5.myworkdayjobs.com/External"
    assert boards.parse_board_url(boards.board_url("workday", slug)) == ("workday", slug)
    jobs = boards.list_board("workday", slug, post=post)
    assert [job.id for job in jobs] == ["Finance-Intern_R12345", "Strategy-Analyst_R12346"]
    assert jobs[0].url == "https://acme.wd5.myworkdayjobs.com/External/job/Boston/Finance-Intern_R12345"
    assert identity.canonical_key(jobs[0].url) == "workday:acme:R12345"
    assert (datetime.now(UTC).date() - datetime.fromisoformat(jobs[0].updated_at).date()).days == 3
    assert [call["offset"] for call in calls] == [0, 20]
    assert all(call["limit"] == 20 and call["searchText"] == "" and call["appliedFacets"] == {} for call in calls)
    with pytest.raises(ValueError):
        boards.list_board("workday", "acme.wd5/other/External", post=post)


def test_wrong_board_name_and_outage_are_told_apart():
    with pytest.raises(boards.BoardNotFound):
        boards.list_board("greenhouse", "nope", get=_FakeGet({}))
    down = _FakeGet({"https://boards-api": _Response(503)})
    with pytest.raises(boards.BoardUnavailable):
        boards.list_board("greenhouse", "acme", get=down)
    garbled = _FakeGet({"https://boards-api": _Response(200, bad_json=True)})
    with pytest.raises(boards.BoardUnavailable):
        boards.list_board("greenhouse", "acme", get=garbled)

    def offline(url, **kwargs):
        raise httpx.ConnectError("no route")

    with pytest.raises(boards.BoardUnavailable):
        boards.list_board("greenhouse", "acme", get=offline)
    with pytest.raises(ValueError):
        boards.list_board("workday", "acme", post=offline)
    with pytest.raises(ValueError):
        boards.list_board("greenhouse", "../etc", get=offline)


def _source(**fields) -> SourceConfig:
    data = {
        "id": "watch",
        "kind": "ats_board",
        "boards": [{"ats": "greenhouse", "slug": "acme", "company": "Acme"}],
    }
    data.update(fields)
    return SourceConfig.model_validate(data)


def test_board_rows_filters_keywords_and_locations(monkeypatch):
    monkeypatch.setattr(boards, "_sleep", lambda _s: None)
    get = _FakeGet(
        {"https://boards-api.greenhouse.io/v1/boards/acme/jobs": _Response(200, GREENHOUSE)}
    )
    source = _source(include=["analyst", "intern"], exclude=["senior"], locations=["NY", "Remote"])
    rows, errors = sources.board_rows(
        source, list_board=lambda ats, slug: boards.list_board(ats, slug, get=get), now=NOW
    )
    assert errors == []
    assert [(r.role, r.location) for r in rows] == [
        ("Investment Banking Summer Analyst", "New York, NY"),
        ("Finance Intern", "Remote"),
    ]
    first, undated = rows
    assert first.company == "Acme"
    assert first.job_id == "greenhouse:acme:101"
    assert first.age_days == 4 and first.age == "4d"
    assert undated.age_days == 0 and undated.flags == ["age_unknown"]


def test_board_rows_reports_a_bad_board_and_keeps_the_rest(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(boards, "_sleep", slept.append)
    source = _source(
        boards=[
            {"ats": "greenhouse", "slug": "gone", "company": "Gone Inc"},
            {"ats": "lever", "slug": "flaky"},
            {"ats": "greenhouse", "slug": "acme"},
        ]
    )

    def fake_list(ats, slug):
        if slug == "gone":
            raise boards.BoardNotFound(slug)
        if slug == "flaky":
            raise boards.BoardUnavailable("api.lever.co answered 429")
        return [
            boards.BoardJob("1", "Analyst", "NY", "https://boards.greenhouse.io/acme/jobs/1", "")
        ]

    rows, errors = sources.board_rows(source, list_board=fake_list, now=NOW)
    assert [r.company for r in rows] == ["acme"]
    assert errors == [
        "Gone Inc: no greenhouse board named 'gone'",
        "flaky: api.lever.co answered 429",
    ]
    assert slept == [boards.BOARD_DELAY_SECONDS] * 2


def test_watchlist_source_defaults_and_validation():
    assert _source().max_age_days == 7
    assert _source(max_age_days=30).max_age_days == 30
    with pytest.raises(ValueError):
        SourceConfig(id="x", kind="simplify_html")  # a README source needs its url
    with pytest.raises(ValueError):
        _source(boards=[{"ats": "greenhouse", "slug": "../x"}])
    assert _source(boards=[{"ats": "workday", "slug": "acme.wd5/acme/External"}]).boards[0].ats == "workday"
    with pytest.raises(ValueError):
        _source(boards=[{"ats": "workday", "slug": "acme.wd5/other/External"}])
    # Existing settings files still load unchanged.
    assert ApplySettings().sources[0].max_age_days is None


def test_filter_rows_uses_the_source_age_limit():
    row = sources.SourceRow(
        company="A",
        role="Analyst",
        location="",
        age="5d",
        age_days=5,
        job_id="greenhouse:a:1",
        source_id="watch",
    )
    kept = sources.filter_rows(
        [row],
        max_age_days=7,
        exclude_advanced_degree=True,
        exclude_citizenship=True,
        exclude_no_sponsorship=False,
        known_ids=set(),
    )
    assert len(kept.new_rows) == 1


def test_shipped_watchlists_are_well_formed():
    lists = boards.watchlists()
    assert set(lists) == {"finance", "tech"}
    for entries in lists.values():
        assert entries
        assert len({(b["ats"], b["slug"].lower()) for b in entries}) == len(entries)
        for board in entries:
            assert board["ats"] in boards.BOARD_ATS
            assert boards.valid_slug(board["slug"])
            assert board["company"]


# --- D3 business titles -------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Summer Analyst",
        "2027 Investment Banking Summer Analyst",
        "Rotational Program – Finance",
        "Finance Leadership Development Program",
        "Early Career Analyst Program",
    ],
)
def test_business_entry_titles_are_early_career(title):
    assert eligibility.is_early_career_title(title)
    assert eligibility.check_title(title).passed


@pytest.mark.parametrize(
    "title",
    ["Senior Associate", "Associate Director", "VP, Investment Banking", "Summer Analyst II"],
)
def test_senior_business_titles_are_not_early_career(title):
    assert not eligibility.is_early_career_title(title)


@pytest.mark.parametrize(
    "title", ["Senior Associate", "Associate Director", "VP, Investment Banking"]
)
def test_senior_business_titles_are_rejected(title):
    assert not eligibility.check_title(title).passed


@pytest.mark.parametrize(
    ("title", "passed"),
    [
        ("Product Manager Intern", True),
        ("Associate Product Manager", True),
        ("Assistant Project Manager", True),
        ("Senior Product Manager Intern", False),
        ("Product Manager", False),
        ("Engineering Manager", False),
        ("Analyst", True),
        ("Associate", True),
    ],
)
def test_manager_words_in_entry_titles(title, passed):
    assert eligibility.check_title(title).passed is passed


# --- routes -------------------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(web_app) as test_client:
        yield test_client


def test_resolve_board_route(client, monkeypatch):
    def fake_list(ats, slug):
        if slug == "gone":
            raise boards.BoardNotFound(slug)
        if slug == "down":
            raise boards.BoardUnavailable("boards-api.greenhouse.io answered 503")
        return [boards.BoardJob("1", "Analyst", "NY", "u", "", company="Acme Capital")] * 3

    monkeypatch.setattr(boards, "list_board", fake_list)
    monkeypatch.setattr(discovery, "_fetch_career_page", lambda url: "<html></html>")
    body = client.post(
        "/api/apply/boards/resolve", json={"url": "boards.greenhouse.io/acme"}
    ).json()
    assert body == {
        "ats": "greenhouse",
        "slug": "acme",
        "company": "Acme Capital",
        "jobs": 3,
        "url": "https://boards.greenhouse.io/acme",
    }
    named = client.post(
        "/api/apply/boards/resolve", json={"ats": "lever", "slug": "acme", "company": "Acme"}
    ).json()
    assert named["company"] == "Acme"
    assert (
        client.post("/api/apply/boards/resolve", json={"url": "https://acme.com/jobs"}).status_code
        == 404
    )
    assert (
        client.post("/api/apply/boards/resolve", json={"url": "jobs.lever.co/gone"}).status_code
        == 404
    )
    assert (
        client.post("/api/apply/boards/resolve", json={"url": "jobs.lever.co/down"}).status_code
        == 502
    )


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>', ("greenhouse", "acme")),
        ('<a href="https://jobs.lever.co/acme">Jobs</a>', ("lever", "acme")),
        ('<a href="https://jobs.ashbyhq.com/acme">Jobs</a>', ("ashby", "acme")),
        ('<a href="https://careers.smartrecruiters.com/Acme">Jobs</a>', ("smartrecruiters", "Acme")),
        ('<iframe src="https://acme.wd5.myworkdayjobs.com/en-US/External"></iframe>', ("workday", "acme.wd5/acme/External")),
    ],
)
def test_embedded_board_detection(client, monkeypatch, html, expected):
    fetched = []
    listed = []
    monkeypatch.setattr(discovery, "_fetch_career_page", lambda url: (fetched.append(url), html)[1])
    monkeypatch.setattr(boards, "list_board", lambda ats, slug: (listed.append((ats, slug)), [])[1])
    response = client.post("/api/apply/boards/resolve", json={"url": "https://acme.example/careers"})
    assert response.status_code == 200
    assert (response.json()["ats"], response.json()["slug"]) == expected
    assert fetched == ["https://acme.example/careers"]
    assert listed == [expected]


def test_embedded_board_prefers_most_frequent_and_reports_ties(client, monkeypatch):
    monkeypatch.setattr(boards, "list_board", lambda ats, slug: [])
    html = '<a href="https://jobs.lever.co/acme">A</a><a href="https://jobs.lever.co/acme/x">B</a><a href="https://jobs.ashbyhq.com/other">C</a>'
    monkeypatch.setattr(discovery, "_fetch_career_page", lambda url: html)
    preferred = client.post("/api/apply/boards/resolve", json={"url": "https://acme.example/careers"})
    assert preferred.status_code == 200 and preferred.json()["ats"] == "lever"
    monkeypatch.setattr(discovery, "_fetch_career_page", lambda url: '<a href="https://jobs.lever.co/acme">A</a><a href="https://jobs.ashbyhq.com/other">B</a>')
    tied = client.post("/api/apply/boards/resolve", json={"url": "https://acme.example/careers"})
    assert tied.status_code == 409
    assert "https://jobs.lever.co/acme" in tied.json()["detail"]
    assert "https://jobs.ashbyhq.com/other" in tied.json()["detail"]
    monkeypatch.setattr(discovery, "_fetch_career_page", lambda url: "<p>No jobs</p>")
    none = client.post("/api/apply/boards/resolve", json={"url": "https://acme.example/careers"})
    assert none.status_code == 404
    assert none.json()["detail"] == discovery._NO_BOARD


def test_career_page_fetch_has_a_size_cap(monkeypatch):
    class _Page:
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"x" * (discovery._PAGE_LIMIT + 1)

    calls = []

    def fake_stream(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Page()

    monkeypatch.setattr(discovery.httpx, "stream", fake_stream)
    with pytest.raises(ValueError, match="too large"):
        discovery._fetch_career_page("https://acme.example/careers")
    assert len(calls) == 1
    assert calls[0][2]["timeout"] <= 10
    assert "ResumeTailor" in calls[0][2]["headers"]["User-Agent"]


def test_watchlists_and_sections_routes(client, monkeypatch):
    body = client.get("/api/apply/watchlists").json()
    assert set(body["fields"]) == {"finance", "tech"}
    readme = "# Title\n## Software Engineering Internship Roles\n## Quantitative Finance Internship Roles\n## Software Engineering Internship Roles\n"
    monkeypatch.setattr(sources, "fetch_readme", lambda url: readme)
    sections = client.get(
        "/api/apply/sources/sections", params={"url": "https://x.test/README.md"}
    ).json()
    assert sections["sections"] == [
        "Software Engineering Internship Roles",
        "Quantitative Finance Internship Roles",
    ]
    assert (
        client.get("/api/apply/sources/sections", params={"url": "file:///etc/passwd"}).status_code
        == 400
    )

    def boom(url):
        raise RuntimeError("offline")

    monkeypatch.setattr(sources, "fetch_readme", boom)
    assert (
        client.get(
            "/api/apply/sources/sections", params={"url": "https://x.test/README.md"}
        ).status_code
        == 502
    )
