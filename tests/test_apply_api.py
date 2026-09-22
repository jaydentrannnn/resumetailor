"""Hermetic tests for apply API routes (profile, applications list, browser status)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply import profile as profile_mod
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
from resume_tailor.web import jobs as jobs_mod
from tests.fixtures import synthetic_resume


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Minimal TestClient with isolated apply paths and stubbed job queue."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    resume_path = tmp_path / "master_resume.json"
    resume_path.write_text(
        json.dumps(synthetic_resume().model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)

    with TestClient(app) as test_client:
        test_client.get("/api/config")
        yield test_client, q


def test_applicant_profile_round_trip(client, tmp_path, monkeypatch):
    """GET seeds an empty profile; PUT persists and GET returns it."""
    c, _q = client
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    monkeypatch.setattr(profile_mod.config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")

    res = c.get("/api/applicant-profile")
    assert res.status_code == 200
    body = res.json()
    assert body["seeded"] is True
    assert body["profile"]["email"] == ""

    body["profile"]["email"] = "test@example.com"
    body["profile"]["first_name"] = "Ada"
    put = c.put("/api/applicant-profile", json={"profile": body["profile"]})
    assert put.status_code == 200
    assert put.json()["profile"]["email"] == "test@example.com"
    assert put.json()["seeded"] is False

    again = c.get("/api/applicant-profile")
    assert again.json()["profile"]["first_name"] == "Ada"


def test_applications_list_empty(client):
    """Empty registry returns zero counts."""
    c, _q = client
    res = c.get("/api/applications")
    assert res.status_code == 200
    body = res.json()
    assert body["applications"] == []
    assert isinstance(body["counts"], dict)


def test_browser_status_shape(client):
    """Browser status always returns the probe schema (usually unreachable in CI)."""
    c, _q = client
    res = c.get("/api/browser/status")
    assert res.status_code == 200
    body = res.json()
    assert "reachable" in body
    assert "cdp_url" in body


def test_packet_missing_404(client):
    """Unknown job id has no packet."""
    c, _q = client
    res = c.get("/api/jobs/doesnotexist/packet.json")
    assert res.status_code == 404


def test_verify_claim_without_job_id(client, tmp_path, monkeypatch):
    """POST /api/verify-claim accepts omitted job_id and checks master bullets."""
    c, _q = client
    resume_path = tmp_path / "master_resume.json"
    resume = synthetic_resume()
    resume_path.write_text(json.dumps(resume.model_dump(mode="json"), indent=2), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    res = c.post(
        "/api/verify-claim",
        json={"text": "Led a Kubernetes migration for production services."},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is False
