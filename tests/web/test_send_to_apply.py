"""A finished Tailor run becomes a tracked application ready to Fill (audit #29)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.discovery import identity
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models
from resume_tailor.content import data
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web import run_inputs
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
from tests.fixtures import synthetic_resume

URL = "https://job-boards.greenhouse.io/acme/jobs/4242"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    resume_path = tmp_path / "master_resume.json"
    resume_path.write_text(json.dumps(synthetic_resume().model_dump(mode="json")), "utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)
    with TestClient(app) as test_client:
        yield test_client


def _run(job_id: str = "run1", *, resume: str | None = None, status: str = "succeeded") -> None:
    folder = config.OUTPUT_DIR / "jobs" / job_id
    folder.mkdir(parents=True)
    (folder / "jd.txt").write_text("Data analyst. SQL and Python.", encoding="utf-8")
    current = run_inputs._hash(data.load().model_dump(mode="json"))
    (folder / "run.json").write_text(json.dumps({
        "job_id": job_id, "workspace_id": config.active_workspace_id(),
        "created_at": "2026-10-01T00:00:00+00:00", "status": status, "title": "Data Analyst",
        "inputs": {"resume": resume or current},
    }), encoding="utf-8")


def test_a_run_becomes_a_ready_application(client):
    _run()
    res = client.post("/api/jobs/run1/send-to-apply", json={"posting_url": URL, "company": "Acme"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] is True
    row = apply_store.get(body["application"]["source_job_id"])
    assert row is not None and row.status == "ready" and row.job_id == "run1"
    assert row.company == "Acme" and row.role == "Data Analyst" and row.posting_url == URL
    assert row.jd_text_path


def test_a_tracked_posting_takes_the_run(client):
    _run()
    apply_store.upsert(store_models.Application(
        source="t", source_job_id="known", company="Acme", role="Analyst", status="tailor_failed",
        posting_url=URL, final_url=URL, canonical_key=identity.canonical_key(URL),
    ))
    body = client.post("/api/jobs/run1/send-to-apply", json={"posting_url": URL}).json()
    assert body["created"] is False
    row = apply_store.get("known")
    assert row.status == "ready" and row.job_id == "run1"


def test_a_run_from_an_older_resume_is_refused(client):
    _run(resume="0123456789abcdef")
    res = client.post("/api/jobs/run1/send-to-apply", json={"posting_url": URL, "company": "Acme"})
    assert res.status_code == 409 and "resume" in res.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "status"),
    [({"posting_url": "acme.com/jobs"}, 422), ({"posting_url": URL}, 422)],
)
def test_it_asks_for_a_link_and_a_company(client, payload, status):
    _run()
    assert client.post("/api/jobs/run1/send-to-apply", json=payload).status_code == status


def test_an_unfinished_run_is_refused(client):
    _run(status="failed")
    res = client.post("/api/jobs/run1/send-to-apply", json={"posting_url": URL, "company": "Acme"})
    assert res.status_code == 409
