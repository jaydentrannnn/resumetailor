"""Routes that settle or edit one application wait only for Apply work on that row, and
settling it by hand takes it from the batch holding it (audit #2, #7, #20)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.funnel import operations as operations_mod
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
from tests.fixtures import synthetic_resume


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    resume_path = tmp_path / "master_resume.json"
    resume_path.write_text(json.dumps(synthetic_resume().model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)
    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)
    monkeypatch.setattr(operations_mod, "_ACTIVE", {})
    monkeypatch.setattr(operations_mod, "_CONTROLS", {})
    with TestClient(app) as test_client:
        yield test_client


def _row(key: str, status: str, **fields) -> None:
    apply_store.upsert(store_models.Application(
        source="simplify", source_job_id=key, canonical_key=f"gh:{key}", company="Acme",
        role="Engineer", status=status, **fields,
    ))


def _holding(*ids: str) -> operations_mod.ApplyOperation:
    operation = operations_mod.ApplyOperation(
        operation_id="busy", action="fill", state="running", held_ids=list(ids)
    )
    operations_mod._ACTIVE["busy"] = operation
    operations_mod._CONTROLS["busy"] = operations_mod._Controls()
    return operation


@pytest.mark.parametrize("status", ["fill_failed", "awaiting_review", "awaiting_otp", "ready"])
def test_mark_submitted_from_any_working_status(client, status):
    _row("a", status)
    result = client.post("/api/applications/a/status", json={"status": "submitted"})
    assert result.status_code == 200
    assert apply_store.get("a").status == "submitted"


def test_marking_a_held_row_revokes_it_from_its_batch(client):
    _row("a", "filling")
    _holding("a")
    result = client.post("/api/applications/gh:a/status", json={"status": "skipped"})
    assert result.status_code == 200
    assert apply_store.get("a").status == "skipped"
    assert "a" in operations_mod._CONTROLS["busy"].revoked
    events = operations_mod._ACTIVE["busy"].events
    assert any(event["stage"] == "revoked" for event in events)


def test_a_working_status_change_waits_for_the_batch(client):
    _row("a", "awaiting_review")
    _holding("a")
    result = client.post("/api/applications/a/status", json={"status": "ready"})
    assert result.status_code == 409
    assert apply_store.get("a").status == "awaiting_review"


def test_the_applicants_correction_reopens_a_closed_row(client):
    _row("a", "rejected")
    result = client.post("/api/applications/a/status", json={"status": "awaiting_review"})
    assert result.status_code == 200
    assert apply_store.get("a").status == "awaiting_review"


def test_archive_waits_only_for_held_rows(client):
    _row("a", "ready")
    _row("b", "ready")
    _holding("a")
    held = client.post("/api/applications/archive", json={"application_ids": ["a"], "archived": True})
    assert held.status_code == 409
    free = client.post("/api/applications/archive", json={"application_ids": ["b"], "archived": True})
    assert free.status_code == 200 and free.json()["updated"] == ["b"]


def test_archive_runs_beside_a_tailoring_run(client, monkeypatch):
    _row("b", "ready")
    monkeypatch.setattr(jobs_mod.queue_singleton, "busy", lambda: True)
    result = client.post("/api/applications/archive", json={"application_ids": ["b"], "archived": True})
    assert result.status_code == 200


def test_open_tabs_lists_closing_tabs_and_keep_open_stops_one(client, monkeypatch):
    from resume_tailor.apply.funnel import tab_close

    monkeypatch.setattr(tab_close, "_PENDING", {})
    monkeypatch.setattr(tab_close, "KEPT", set())
    monkeypatch.setattr(operations_mod.browser, "open_target_ids", lambda: {"T1"})
    _row("a", "submitted", fill={"browser_target_id": "T1"})
    tab_close._PENDING["a"] = tab_close.Pending(
        due=1e12, url="https://x.example/jobs/1", company="Acme", target="T1", armed_page_ms=0.0,
    )
    body = client.get("/api/applications/open-tabs").json()
    assert body["target_ids"] == ["T1"]
    assert [item["id"] for item in body["closing"]] == ["a"]
    kept = client.post("/api/applications/gh:a/keep-tab").json()
    assert kept == {"kept": True, "was_closing": True}
    assert client.get("/api/applications/open-tabs").json()["closing"] == []
    assert "a" in tab_close.KEPT
