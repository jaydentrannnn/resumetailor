"""Master resume version history (S4): recording, hand edits, pruning, restore route."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.content import resume_versions
from resume_tailor.web.app import app
from tests.fixtures import synthetic_resume


@pytest.fixture
def resume_path(tmp_path, monkeypatch):
    path = tmp_path / "master_resume.json"
    path.write_text(
        json.dumps(synthetic_resume().model_dump(mode="json", by_alias=True), indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    return path


def test_record_skips_unchanged_text_and_prunes(resume_path, monkeypatch):
    monkeypatch.setattr(resume_versions, "KEEP", 3)
    assert resume_versions.record("a") == 1
    assert resume_versions.record("a") is None
    for text in ("b", "c", "d"):
        resume_versions.record(text)
    versions = [v["version"] for v in resume_versions.list_versions()]
    # The file on disk differs from "d", so it is recorded first as a hand edit.
    assert versions[0] == 5 and len(versions) == 3
    assert resume_versions.list_versions()[0]["note"] == "edited outside the app"


def test_first_listing_records_the_file(resume_path):
    versions = resume_versions.list_versions()
    assert len(versions) == 1 and versions[0]["current"]
    assert versions[0]["note"] == "first recorded version"
    assert versions[0]["bullets"] > 0 and versions[0]["name"]


def test_save_restore_round_trip_keeps_hand_edits(resume_path):
    with TestClient(app) as c:
        original = c.get("/api/master-resume").json()
        edited = json.loads(json.dumps(original))
        edited["contact"]["name"] = "Edited Name"
        assert c.put("/api/master-resume", json=edited).status_code == 200

        # A hand edit while "the app was closed" is kept as its own version.
        on_disk = json.loads(resume_path.read_text(encoding="utf-8"))
        on_disk["contact"]["name"] = "Hand Edit"
        resume_path.write_text(json.dumps(on_disk, indent=2), encoding="utf-8")

        versions = c.get("/api/master-resume/versions").json()["versions"]
        notes = [v["note"] for v in versions]
        assert notes[:2] == ["edited outside the app", "saved in the editor"]
        first = versions[-1]["version"]

        res = c.post(f"/api/master-resume/restore/{first}")
        assert res.status_code == 200
        assert res.json()["resume"]["contact"]["name"] == original["contact"]["name"]
        assert c.get("/api/master-resume").json()["contact"]["name"] == original["contact"]["name"]
        latest = c.get("/api/master-resume/versions").json()["versions"][0]
        assert latest["note"] == f"restored version {first}"
        assert any(v["name"] == "Hand Edit" for v in c.get("/api/master-resume/versions").json()["versions"])

        assert c.post("/api/master-resume/restore/999").status_code == 404


def test_history_failure_never_blocks_a_save(resume_path, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(resume_versions, "record", _boom)
    monkeypatch.setattr(resume_versions, "sync_external", _boom)
    with TestClient(app) as c:
        body = c.get("/api/master-resume").json()
        body["contact"]["name"] = "Still Saved"
        assert c.put("/api/master-resume", json=body).status_code == 200
    assert json.loads(resume_path.read_text(encoding="utf-8"))["contact"]["name"] == "Still Saved"
