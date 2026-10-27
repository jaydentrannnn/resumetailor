"""What was sent can be opened, and a run an application uses is never deleted from
history (audit #9, #34)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.forms import submit_guard
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)
    with TestClient(app) as test_client:
        yield test_client


def _run(job_id: str) -> None:
    folder = config.OUTPUT_DIR / "jobs" / job_id
    folder.mkdir(parents=True)
    (folder / "tailored.pdf").write_bytes(b"%PDF resume")
    (folder / "run.json").write_text(json.dumps({
        "job_id": job_id, "workspace_id": config.active_workspace_id(),
        "created_at": "2026-10-01T00:00:00+00:00", "status": "succeeded", "title": job_id,
    }), encoding="utf-8")


def _sent(job_id: str = "run1") -> store_models.Application:
    app_row = store_models.Application(
        source="t", source_job_id="sent-1", company="Acme", role="Analyst", status="ready",
        job_id=job_id,
    )
    apply_store.set_status(app_row, "submitted", note=submit_guard.AUTO_NOTE)
    apply_store.upsert(app_row)
    return app_row


def test_an_attempts_files_open_read_only_and_nothing_outside_it(client):
    _run("run1")
    _sent()
    base = "/api/applications/sent-1/attempts/1/files"
    res = client.get(f"{base}/tailored.pdf")
    assert res.status_code == 200 and res.content == b"%PDF resume"
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].startswith("inline")
    saved = client.get(f"{base}/tailored.pdf?download=1")
    assert saved.headers["content-disposition"].startswith("attachment")
    for name in ("run.json", "../../../applications.json", "missing.pdf"):
        assert client.get(f"{base}/{name}").status_code == 404
    assert client.get("/api/applications/sent-1/attempts/9/files/tailored.pdf").status_code == 404


def test_a_run_an_application_uses_is_hidden_never_deleted(client):
    _run("run1")
    _run("run2")
    _sent("run1")
    res = client.post("/api/jobs/history/delete", json={"job_ids": ["run1", "run2"]})
    body = res.json()
    assert body["deleted"] == ["run2"] and body["hidden"] == ["run1"] and body["errors"] == {}
    assert (config.OUTPUT_DIR / "jobs" / "run1" / "tailored.pdf").is_file()
    assert [run["job_id"] for run in client.get("/api/jobs").json()["runs"]] == []
