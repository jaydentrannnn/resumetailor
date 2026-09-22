"""Hermetic tests for the applications.json store."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.apply import store


def _sample_app(**overrides) -> store.Application:
    """Build a minimal application record for store tests."""
    data = {
        "source": "simplify",
        "source_job_id": "job-1",
        "company": "Acme",
        "role": "Intern",
    }
    data.update(overrides)
    return store.Application(**data)


@pytest.fixture
def apps_path(tmp_path, monkeypatch):
    """Redirect ``APPLICATIONS_PATH`` into an isolated temp file."""
    path = tmp_path / "applications.json"
    monkeypatch.setattr(config, "APPLICATIONS_PATH", path)
    return path


def test_load_all_missing_file_returns_empty(apps_path):
    assert store.load_all() == {}


def test_save_and_load_round_trip(apps_path):
    app = _sample_app(location="SF")
    store.save_all({"job-1": app})
    loaded = store.load_all()
    assert set(loaded) == {"job-1"}
    assert loaded["job-1"].company == "Acme"
    assert loaded["job-1"].location == "SF"
    raw = json.loads(apps_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    assert "job-1" in raw["applications"]


def test_upsert_and_get(apps_path):
    app = _sample_app(source_job_id="abc")
    store.upsert(app)
    found = store.get("abc")
    assert found is not None
    assert found.role == "Intern"
    app.role = "Updated Intern"
    store.upsert(app)
    assert store.get("abc").role == "Updated Intern"


def test_all_ids(apps_path):
    store.upsert(_sample_app(source="simplify", source_job_id="a"))
    store.upsert(_sample_app(source="simplify", source_job_id="b"))
    assert store.all_ids() == {("simplify", "a"), ("simplify", "b")}


def test_v1_migrates_to_v2(apps_path):
    """A schema-v1 file is rekeyed onto canonical_key and rewritten once."""
    apps_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "applications": {
                    "uuid-1": {
                        "source": "simplify",
                        "source_job_id": "uuid-1",
                        "company": "Figma",
                        "role": "Intern",
                        "posting_url": (
                            "https://boards.greenhouse.io/figma/jobs/6143238004"
                        ),
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = store.load_all()
    assert len(loaded) == 1
    app = next(iter(loaded.values()))
    assert app.canonical_key == "greenhouse:figma:6143238004"
    assert app.source_refs[0].source_job_id == "uuid-1"
    raw = json.loads(apps_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    assert "greenhouse:figma:6143238004" in raw["applications"]
    # get works by legacy source_job_id and by canonical key
    assert store.get("uuid-1") is not None
    assert store.get("greenhouse:figma:6143238004") is not None


def test_build_index_groups_by_group_key(apps_path):
    """Two apps sharing ``group_key`` appear together in ``by_group``."""
    a = _sample_app(
        source_job_id="a",
        canonical_key="greenhouse:x:1",
        group_key="acme|software intern",
        company="Acme",
        role="Software Intern - SF",
    )
    b = _sample_app(
        source_job_id="b",
        canonical_key="greenhouse:x:2",
        group_key="acme|software intern",
        company="Acme",
        role="Software Intern - NYC",
    )
    store.upsert(a)
    store.upsert(b)
    index = store.build_index()
    assert set(index.by_group["acme|software intern"]) == {
        "greenhouse:x:1",
        "greenhouse:x:2",
    }


def test_set_status_appends_history(apps_path):
    app = _sample_app()
    store.set_status(app, "jd_fetched", note="fetched jd")
    assert app.status == "jd_fetched"
    assert len(app.status_history) == 1
    assert app.status_history[0].status == "jd_fetched"
    assert app.status_history[0].note == "fetched jd"
    assert app.status_history[0].at.endswith("+00:00") or "T" in app.status_history[0].at


def test_set_status_blocks_terminal_to_pre_ready():
    app = _sample_app(status="submitted")
    app.status_history = [
        store.StatusChange(status="submitted", at="2026-01-01T00:00:00+00:00")
    ]
    with pytest.raises(ValueError, match="terminal"):
        store.set_status(app, "discovered")
    with pytest.raises(ValueError, match="terminal"):
        store.set_status(app, "tailoring")


def test_set_status_allows_terminal_to_post_ready():
    app = _sample_app(status="submitted")
    store.set_status(app, "interview", note="callback")
    assert app.status == "interview"


def test_atomic_write_uses_tmp_suffix(apps_path, monkeypatch):
    """Persist via ``.json.tmp`` then replace — no partial read of half a file."""
    writes: list[str] = []

    def _tracked_write_text(self, data, encoding="utf-8"):
        writes.append(self.name)
        return Path_write_text(self, data, encoding=encoding)

    Path_write_text = type(apps_path).write_text
    monkeypatch.setattr(type(apps_path), "write_text", _tracked_write_text)
    replaced: list[tuple] = []

    def _tracked_replace(self, target):
        replaced.append((self.name, target.name))
        return Path_replace(self, target)

    Path_replace = type(apps_path).replace
    monkeypatch.setattr(type(apps_path), "replace", _tracked_replace)

    store.save_all({"job-1": _sample_app()})
    assert any(name.endswith(".json.tmp") for name in writes)
    assert replaced
    assert not (apps_path.parent / "applications.json.tmp").exists()
