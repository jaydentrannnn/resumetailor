"""Tests for keyword job-search sources (Adzuna and USAJobs)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from resume_tailor import config
from resume_tailor.apply import daily, job_apis, store
from resume_tailor.apply.job_apis import MissingCredentialsError
from resume_tailor.apply.sources import SourceRow
from resume_tailor.web.schemas import ApplySettings, SourceConfig
from tests.fixtures import synthetic_resume


@pytest.fixture
def apply_paths(tmp_path, monkeypatch):
    """Isolate applications registry, output tree, and cache."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    (tmp_path / "output" / "jobs").mkdir(parents=True)
    return tmp_path


class _FakeResponse:
    def __init__(self, data: Any, status_code: int = 200, text: str = ""):
        self._data = data
        self.status_code = status_code
        self.text = text or json.dumps(data)

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def test_adzuna_paging_and_mapping(monkeypatch):
    """Adzuna queries pages up to the cap or total count, maps fields and formats salary."""
    monkeypatch.setattr(config, "credential", lambda key: "fake-" + key)
    sleeps: list[float] = []
    monkeypatch.setattr(job_apis, "_sleep", sleeps.append)

    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
    now_iso = (now - timedelta(days=3)).isoformat()
    requests: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs):
        requests.append({"url": url, **kwargs})
        params = kwargs.get("params", {})
        page = int(url.split("/")[-1])
        if page == 1:
            return _FakeResponse({
                "count": 75,
                "results": [
                    {
                        "id": f"ad-{i}",
                        "title": f"Engineer {i}",
                        "company": {"display_name": f"AdzunaCorp {i}"},
                        "location": {"display_name": "San Francisco, CA"},
                        "redirect_url": f"https://adzuna.com/land/{i}",
                        "created": now_iso,
                        "salary_min": 100000,
                        "salary_max": 150000,
                    }
                    for i in range(50)
                ],
            })
        if page == 2:
            return _FakeResponse({
                "count": 75,
                "results": [
                    {
                        "id": f"ad-{i}",
                        "title": f"Engineer {i}",
                        "company": {"display_name": f"AdzunaCorp {i}"},
                        "location": {"display_name": "San Francisco, CA"},
                        "redirect_url": f"https://adzuna.com/land/{i}",
                        "created": now_iso,
                        "salary_min": 120000,
                        "salary_max": 120000,
                    }
                    for i in range(50, 75)
                ],
            })
        return _FakeResponse({"count": 75, "results": []})

    source = SourceConfig(
        id="adzuna-test",
        kind="job_search",
        provider="adzuna",
        query="software engineer",
        location="San Francisco",
        country="us",
        max_age_days=14,
    )

    rows, errors = job_apis.job_search_rows(source, get=fake_get, now=now)
    assert not errors
    assert len(rows) == 75
    assert len(requests) == 2
    # Verify delay between pages was called
    assert len(sleeps) == 1
    assert sleeps[0] == job_apis.JOB_SEARCH_DELAY_SECONDS

    # Verify query parameters in first request
    assert "https://api.adzuna.com/v1/api/jobs/us/search/1" in requests[0]["url"]
    assert requests[0]["params"]["app_id"] == "fake-ADZUNA_APP_ID"
    assert requests[0]["params"]["app_key"] == "fake-ADZUNA_APP_KEY"
    assert requests[0]["params"]["what"] == "software engineer"
    assert requests[0]["params"]["where"] == "San Francisco"
    assert requests[0]["params"]["results_per_page"] == 50
    assert requests[0]["params"]["max_days_old"] == 14

    # Verify mapped fields
    first = rows[0]
    assert first.company == "AdzunaCorp 0"
    assert first.role == "Engineer 0"
    assert first.location == "San Francisco, CA"
    assert first.application_link == "https://adzuna.com/land/0"
    assert first.job_id == "adzuna:ad-0"
    assert first.age_days == 3
    assert first.salary == "$100,000 - $150,000"
    assert first.flags == []

    # Second page row with equal min/max salary
    row50 = rows[50]
    assert row50.salary == "$120,000"


def test_usajobs_mapping_and_headers_asserted(monkeypatch):
    """USAJobs passes required headers (Host, User-Agent, Authorization-Key) and maps fields."""
    monkeypatch.setattr(
        config,
        "credential",
        lambda key: "user@example.com" if key == "USAJOBS_EMAIL" else "secret-key",
    )
    sleeps: list[float] = []
    monkeypatch.setattr(job_apis, "_sleep", sleeps.append)

    recorded_headers: list[dict[str, str]] = []

    def fake_get(url: str, **kwargs):
        recorded_headers.append(kwargs.get("headers", {}))
        now_date = (datetime.now(UTC) - timedelta(days=4)).strftime("%Y-%m-%d")
        return _FakeResponse({
            "SearchResult": {
                "SearchResultCount": 1,
                "SearchResultCountAll": 1,
                "SearchResultItems": [
                    {
                        "MatchedObjectId": "12345678",
                        "MatchedObjectDescriptor": {
                            "PositionTitle": "IT Specialist (SYSANALYSIS)",
                            "OrganizationName": "Department of Commerce",
                            "PositionLocationDisplay": "Washington, DC",
                            "ApplyURI": ["https://data.usajobs.gov/apply/12345678"],
                            "PositionURI": "https://www.usajobs.gov/job/12345678",
                            "PublicationStartDate": now_date,
                            "PositionRemuneration": [
                                {
                                    "MinimumRange": "90000",
                                    "MaximumRange": "130000",
                                    "RateIntervalCode": "PA",
                                }
                            ],
                        },
                    }
                ],
            }
        })

    source = SourceConfig(
        id="usajobs-test",
        kind="job_search",
        provider="usajobs",
        query="IT Specialist",
        location="Washington, DC",
        max_age_days=30,
    )

    rows, errors = job_apis.job_search_rows(source, get=fake_get)
    assert not errors
    assert len(rows) == 1

    # Assert headers were sent exactly as required
    assert len(recorded_headers) == 1
    headers = recorded_headers[0]
    assert headers["Host"] == "data.usajobs.gov"
    assert headers["User-Agent"] == "user@example.com"
    assert headers["Authorization-Key"] == "secret-key"

    # Assert mapped SourceRow fields
    row = rows[0]
    assert row.job_id == "usajobs:12345678"
    assert row.company == "Department of Commerce"
    assert row.role == "IT Specialist (SYSANALYSIS)"
    assert row.location == "Washington, DC"
    assert row.application_link == "https://data.usajobs.gov/apply/12345678"
    assert row.age_days == 4
    assert row.salary == "$90,000 - $130,000 / PA"


def test_missing_credentials_records_per_source_error_in_run_daily(apply_paths, monkeypatch):
    """When API keys are missing, run_daily records a per-source error without crashing."""
    monkeypatch.setattr(daily.data, "load", synthetic_resume)
    # Ensure credentials return empty strings
    monkeypatch.setattr(config, "credential", lambda _key: "")

    settings = ApplySettings(
        enabled=True,
        max_new_per_day=5,
        sources=[
            SourceConfig(
                id="adzuna-missing",
                kind="job_search",
                provider="adzuna",
                query="developer",
            ),
            SourceConfig(
                id="usajobs-missing",
                kind="job_search",
                provider="usajobs",
                query="analyst",
            ),
        ],
    )

    summary = daily.run_daily(settings=settings, fetch_only=True)
    assert summary.new_rows == 0
    assert len(summary.errors) == 2
    assert "adzuna-missing:" in summary.errors[0]
    assert "ADZUNA_APP_ID" in summary.errors[0]
    assert "usajobs-missing:" in summary.errors[1]
    assert "USAJOBS_API_KEY" in summary.errors[1]


def test_include_exclude_and_location_filters(monkeypatch):
    """Include, exclude, and location keywords filter results before SourceRow collection."""
    monkeypatch.setattr(config, "credential", lambda key: "fake-" + key)

    def fake_get(url: str, **kwargs):
        now_iso = datetime.now(UTC).isoformat()
        return _FakeResponse({
            "results": [
                {
                    "id": "1",
                    "title": "Senior Python Developer",
                    "company": {"display_name": "Co1"},
                    "location": {"display_name": "Austin, TX"},
                    "redirect_url": "https://adzuna.com/1",
                    "created": now_iso,
                },
                {
                    "id": "2",
                    "title": "Junior Python Developer",
                    "company": {"display_name": "Co2"},
                    "location": {"display_name": "Austin, TX"},
                    "redirect_url": "https://adzuna.com/2",
                    "created": now_iso,
                },
                {
                    "id": "3",
                    "title": "Junior Python Developer",
                    "company": {"display_name": "Co3"},
                    "location": {"display_name": "New York, NY"},
                    "redirect_url": "https://adzuna.com/3",
                    "created": now_iso,
                },
                {
                    "id": "4",
                    "title": "Java Developer",
                    "company": {"display_name": "Co4"},
                    "location": {"display_name": "Austin, TX"},
                    "redirect_url": "https://adzuna.com/4",
                    "created": now_iso,
                },
            ]
        })

    source = SourceConfig(
        id="filtered-search",
        kind="job_search",
        provider="adzuna",
        query="developer",
        include=["python"],
        exclude=["senior"],
        locations=["TX"],
    )

    rows, errors = job_apis.job_search_rows(source, get=fake_get)
    assert not errors
    # Job 1 excluded by "senior"
    # Job 3 excluded by location ("New York, NY" != "TX")
    # Job 4 excluded by include ("Java" lacks "python")
    # Only Job 2 survives
    assert len(rows) == 1
    assert rows[0].job_id == "adzuna:2"
    assert rows[0].role == "Junior Python Developer"


def test_stable_job_id_dedupe_across_runs(apply_paths, monkeypatch):
    """Job IDs (e.g. adzuna:<id> and usajobs:<id>) deduplicate correctly across runs."""
    monkeypatch.setattr(daily.data, "load", synthetic_resume)
    monkeypatch.setattr(config, "credential", lambda key: "fake-" + key)

    now_iso = datetime.now(UTC).isoformat()

    def fake_get(url: str, **kwargs):
        return _FakeResponse({
            "results": [
                {
                    "id": "job-abc",
                    "title": "Software Engineer",
                    "company": {"display_name": "Tech Corp"},
                    "location": {"display_name": "Remote"},
                    "redirect_url": "https://adzuna.com/job-abc",
                    "created": now_iso,
                }
            ]
        })

    source = SourceConfig(
        id="job-search-src",
        kind="job_search",
        provider="adzuna",
        query="software engineer",
    )
    settings = ApplySettings(
        enabled=True,
        max_new_per_day=5,
        sources=[source],
    )

    monkeypatch.setattr(job_apis, "httpx", type("HttpxStub", (), {"get": staticmethod(fake_get)}))

    # First run discovers the posting
    summary1 = daily.run_daily(settings=settings, fetch_only=True)
    assert summary1.new_rows == 1
    assert summary1.already_known == 0

    # Applications store now contains this application
    all_apps = store.load_all()
    assert len(all_apps) == 1
    (app,) = all_apps.values()
    assert app.source_job_id == "adzuna:job-abc"

    # Second run with same results recognizes it as already known
    summary2 = daily.run_daily(settings=settings, fetch_only=True)
    assert summary2.new_rows == 0
    assert summary2.already_known == 1


def test_old_settings_json_shapes_still_validate():
    """Existing settings.json shapes validate without error, keeping backwards compatibility."""
    # Legacy single-source shape with readme_url
    legacy = {
        "enabled": False,
        "schedule_time": "02:00",
        "readme_url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
        "categories": ["Software Engineering Internship Roles"],
        "max_age_days": 1,
        "sources": [],
    }
    loaded_legacy = ApplySettings.model_validate(legacy)
    assert len(loaded_legacy.sources) == 1
    assert loaded_legacy.sources[0].kind == "simplify_html"
    assert loaded_legacy.sources[0].url == legacy["readme_url"]

    # Modern multi-source shape with ats_board, pipe_table, simplify_html
    multi = {
        "enabled": True,
        "sources": [
            {
                "id": "simplify-internships",
                "kind": "simplify_html",
                "url": "https://raw.githubusercontent.com/.../README.md",
                "categories": ["SWE Roles"],
            },
            {
                "id": "speedyapply",
                "kind": "pipe_table",
                "url": "https://raw.githubusercontent.com/.../speedy.md",
                "categories": ["2027 USA SWE"],
            },
            {
                "id": "watchlist",
                "kind": "ats_board",
                "boards": [{"ats": "greenhouse", "slug": "acme", "company": "Acme"}],
            },
        ],
    }
    loaded_multi = ApplySettings.model_validate(multi)
    assert len(loaded_multi.sources) == 3
    assert loaded_multi.sources[2].max_age_days == 7  # ats_board default

    # New job_search source defaults max_age_days to 14
    search_cfg = SourceConfig.model_validate({
        "id": "adzuna-jobs",
        "kind": "job_search",
        "provider": "adzuna",
        "query": "backend engineer",
    })
    assert search_cfg.max_age_days == 14
    assert search_cfg.country == "us"
    assert search_cfg.url == ""

    # Invalid job_search (missing provider or query) raises ValueError
    with pytest.raises(ValueError, match="needs a provider"):
        SourceConfig.model_validate({
            "id": "bad-search-1",
            "kind": "job_search",
            "query": "backend engineer",
        })

    with pytest.raises(ValueError, match="needs a query"):
        SourceConfig.model_validate({
            "id": "bad-search-2",
            "kind": "job_search",
            "provider": "adzuna",
            "query": "   ",
        })
