"""The curated source catalog and the Sources-tab endpoints (catalog, inspect, test)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply import source_catalog, sources
from resume_tailor.web.schemas import ApplySettings, SourceConfig

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _Resp:
    def __init__(self, status_code: int = 200, body: object = None, etag: str = ""):
        self.status_code = status_code
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = {"ETag": etag} if etag else {}


def _remote_catalog(version: str = "2099.01.01", schema_version: int = 1) -> dict:
    return {
        "schema_version": schema_version,
        "entries": [
            {
                "id": "remote-only",
                "name": "Remote list",
                "fields": ["finance"],
                "version": version,
                "template": {
                    "id": "remote-only",
                    "kind": "pipe_table",
                    "url": "https://raw.githubusercontent.com/o/r/main/README.md",
                },
            }
        ],
    }


@pytest.fixture
def cache_file(tmp_path, monkeypatch):
    path = tmp_path / "shared" / "source_catalog_cache.json"
    monkeypatch.setattr(source_catalog, "cache_path", lambda: path)
    monkeypatch.delenv("RESUME_TAILOR_CATALOG_URL", raising=False)
    return path


# --- bundled file ----------------------------------------------------------------


def test_bundled_catalog_validates_and_templates_are_sources():
    catalog = source_catalog.bundled()
    assert catalog.schema_version == source_catalog.SCHEMA_VERSION
    assert len(catalog.entries) >= 20
    fields = set()
    for entry in catalog.entries:
        template = SourceConfig.model_validate(entry.template.model_dump())
        assert template.catalog_id == entry.id
        assert template.catalog_version == entry.version
        assert template.name
        fields.update(entry.fields)
    assert fields == {
        "swe", "data", "quant", "finance", "consulting", "product", "business", "hardware",
        "government",
    }
    kinds = {entry.template.kind for entry in catalog.entries}
    assert {"simplify_html", "pipe_table", "company_link_table", "job_search"} <= kinds


def test_defaults_come_from_catalog_ids():
    defaults = ApplySettings().sources
    assert [s.id for s in defaults] == ["simplify-internships", "simplify-newgrad", "speedyapply"]
    assert [s.catalog_id for s in defaults] == [s.id for s in defaults]
    assert defaults[0].categories == [
        "Software Engineering Internship Roles",
        "Data Science, AI & Machine Learning Internship Roles",
    ]
    assert defaults[2].categories == ["2027 USA SWE Internships", "USA Positions"]
    # Each profile gets its own copies.
    defaults[0].categories.append("x")
    assert "x" not in ApplySettings().sources[0].categories


def test_empty_sources_list_stays_empty():
    assert ApplySettings.model_validate({"sources": []}).sources == []
    dumped = ApplySettings.model_validate({"sources": []}).model_dump(mode="json")
    assert ApplySettings.model_validate(dumped).sources == []


def test_duplicate_ids_rejected():
    raw = _remote_catalog()
    raw["entries"].append(raw["entries"][0])
    assert source_catalog._parse(raw) is None


# --- remote / cache / bundled ----------------------------------------------------


def test_remote_fetch_writes_cache(cache_file):
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Resp(200, _remote_catalog(), etag='"v1"')

    result = source_catalog.load_catalog(get=fake_get, now=1000.0)
    assert result.origin == "remote"
    assert [e.id for e in result.entries] == ["remote-only"]
    assert result.entries[0].template.catalog_id == "remote-only"
    assert calls[0]["url"] == source_catalog.DEFAULT_CATALOG_URL
    record = json.loads(cache_file.read_text(encoding="utf-8"))
    assert record["etag"] == '"v1"' and record["fetched_at"] == 1000.0

    # Within 12h the cache answers without the network.
    again = source_catalog.load_catalog(get=lambda *a, **k: pytest.fail("no fetch"), now=2000.0)
    assert again.origin == "cache"


def test_stale_cache_revalidates_with_etag(cache_file):
    source_catalog.load_catalog(get=lambda *a, **k: _Resp(200, _remote_catalog(), '"v1"'), now=0.0)
    sent: list[dict] = []

    def not_modified(url, **kwargs):
        sent.append(kwargs["headers"])
        return _Resp(304)

    later = source_catalog.REFRESH_SECONDS + 1
    result = source_catalog.load_catalog(get=not_modified, now=later)
    assert result.origin == "cache"
    assert sent == [{"If-None-Match": '"v1"'}]
    assert json.loads(cache_file.read_text(encoding="utf-8"))["fetched_at"] == later


def test_network_failure_falls_back_to_cache_then_bundled(cache_file):
    def boom(url, **kwargs):
        raise OSError("offline")

    assert source_catalog.load_catalog(get=boom, now=0.0).origin == "bundled"
    source_catalog.load_catalog(get=lambda *a, **k: _Resp(200, _remote_catalog()), now=0.0)
    stale = source_catalog.load_catalog(get=boom, now=source_catalog.REFRESH_SECONDS * 3)
    assert stale.origin == "cache"
    assert [e.id for e in stale.entries] == ["remote-only"]


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        {"schema_version": 1, "entries": [{"id": "x"}]},
        _remote_catalog(schema_version=source_catalog.SCHEMA_VERSION + 1),
    ],
    ids=["garbage", "invalid-entry", "newer-schema"],
)
def test_invalid_or_newer_remote_is_ignored(cache_file, body):
    result = source_catalog.load_catalog(get=lambda *a, **k: _Resp(200, body), now=0.0)
    assert result.origin == "bundled"
    assert not cache_file.exists()


def test_env_overrides_url_and_cache_is_per_url(cache_file, monkeypatch):
    source_catalog.load_catalog(get=lambda *a, **k: _Resp(200, _remote_catalog()), now=0.0)
    monkeypatch.setenv("RESUME_TAILOR_CATALOG_URL", "https://example.com/catalog.json")
    urls: list[str] = []

    def failing(url, **kwargs):
        urls.append(url)
        raise OSError("down")

    # The cached copy belongs to the default URL, so it is not reused.
    assert source_catalog.load_catalog(get=failing, now=1.0).origin == "bundled"
    assert urls == ["https://example.com/catalog.json"]


# --- endpoints -------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch, cache_file):
    from resume_tailor import workspace
    from resume_tailor.web.app import app

    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    settings = {"defaults": {"apply": {"max_age_days": 30, "sources": []}}}
    monkeypatch.setattr(workspace, "load_settings", lambda: settings)
    with TestClient(app) as test_client:
        yield test_client, settings


def test_catalog_endpoint(client, monkeypatch):
    c, _settings = client
    monkeypatch.setattr(source_catalog.httpx, "get", lambda *a, **k: _Resp(503))
    body = c.get("/api/apply/catalog").json()
    assert body["origin"] == "bundled"
    assert body["schema_version"] == 1
    entry = next(e for e in body["entries"] if e["id"] == "northwesternfintech-quant")
    assert set(entry) == {"id", "name", "description", "fields", "version", "template"}
    assert entry["template"]["kind"] == "company_link_table"
    assert entry["template"]["catalog_id"] == "northwesternfintech-quant"


def test_inspect_endpoint(client, monkeypatch):
    c, _settings = client
    text = (_FIXTURES / "zapplyjobs_readme.md").read_text(encoding="utf-8")
    monkeypatch.setattr(sources, "fetch_readme", lambda url: text)
    body = c.post(
        "/api/apply/sources/inspect",
        json={"url": "https://raw.githubusercontent.com/zapplyjobs/Internships-2027/main/README.md"},
    ).json()
    assert body["kind"] == "pipe_table"
    assert "Software Engineering" in body["sections"]
    assert body["row_count"] == 4

    monkeypatch.setattr(sources, "fetch_readme", lambda url: "# prose only\n")
    empty = c.post("/api/apply/sources/inspect", json={"url": "https://example.com/README.md"})
    assert empty.json() == {"kind": None, "sections": [], "row_count": 0}


@pytest.mark.parametrize("url", ["http://127.0.0.1/README.md", "http://localhost:8000/x.md"])
def test_inspect_rejects_private_hosts(client, monkeypatch, url):
    c, _settings = client
    monkeypatch.setattr(sources, "fetch_readme", lambda u: pytest.fail("must not fetch"))
    assert c.post("/api/apply/sources/inspect", json={"url": url}).status_code == 400


def test_source_test_endpoint_uses_profile_filters(client, monkeypatch):
    c, settings = client
    text = (_FIXTURES / "zapplyjobs_readme.md").read_text(encoding="utf-8")
    monkeypatch.setattr(sources, "fetch_readme", lambda url: text)
    source = {
        "id": "z", "kind": "pipe_table",
        "url": "https://raw.githubusercontent.com/zapplyjobs/Internships-2027/main/README.md",
        "categories": ["Software Engineering"],
    }
    body = c.post("/api/apply/sources/test", json={"source": source}).json()
    # Three rows; "Date unknown" fails the age filter.
    assert body["rows_total"] == 3
    assert body["rows_kept"] == 2
    assert [r["company"] for r in body["sample"]] == ["LabCorp", "Cisco"]
    assert set(body["sample"][0]) == {
        "company", "role", "location", "age", "posted_at", "application_link",
    }
    assert body["errors"] == []

    # The funnel-wide age limit applies: a 1-day window drops the 3-day-old row.
    settings["defaults"]["apply"]["max_age_days"] = 1
    body = c.post("/api/apply/sources/test", json={"source": source}).json()
    assert body["rows_kept"] == 1


def test_source_test_endpoint_reports_failure(client, monkeypatch):
    c, _settings = client

    def offline(url):
        raise OSError("offline")

    monkeypatch.setattr(sources, "fetch_readme", offline)
    source = {"id": "z", "kind": "pipe_table", "url": "https://example.com/README.md"}
    body = c.post("/api/apply/sources/test", json={"source": source}).json()
    assert body == {"rows_total": 0, "rows_kept": 0, "sample": [], "errors": ["offline"]}
