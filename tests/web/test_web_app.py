"""Claim verification, answer memory, job events, and SPA static caching."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.web.jobs import JobQueue
from resume_tailor.web.schemas import JobSettings
from tests.web.helpers import _seed_run_for_verify


def test_verify_claim_flags_unsupported_term(client):
    """POST /api/verify-claim returns ok=false when prose invents a technology."""
    c, _ = client
    _seed_run_for_verify()
    res = c.post(
        "/api/verify-claim",
        json={
            "job_id": "verify01",
            "text": "Led a Kubernetes migration for production services.",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert any(t.lower() == "kubernetes" for t in body["unsupported_terms"])


def test_verify_claim_ok_for_supported_prose(client):
    """POST /api/verify-claim returns ok=true when prose stays within source material."""
    c, _ = client
    _seed_run_for_verify()
    res = c.post(
        "/api/verify-claim",
        json={
            "job_id": "verify01",
            "text": "Improved reliability and throughput for production services at Example Corp.",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["unsupported_terms"] == []
    assert body["unsupported_numbers"] == []


def test_verify_claim_404_when_job_missing_artifacts(client):
    """POST /api/verify-claim 404s when the job has no saved bullets."""
    c, _ = client
    res = c.post(
        "/api/verify-claim",
        json={"job_id": "no-such-job", "text": "Anything at all."},
    )
    assert res.status_code == 404


def test_answer_memory_routes_list_edit_and_forget(client, tmp_path, monkeypatch):
    from resume_tailor.apply.answers import answer_memory

    c, _ = client
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "apps" / "applications.json")
    assert c.get("/api/answer-memory").json() == {"answers": []}
    saved = answer_memory.remember("Preferred office?", "Remote", company="Acme", ats="lever")

    listed = c.get("/api/answer-memory").json()["answers"]
    assert [(a["label"], a["answer"], a["company"]) for a in listed] == [
        ("Preferred office?", "Remote", "Acme")
    ]
    res = c.put(f"/api/answer-memory/{saved.id}", json={"answer": "Irvine"})
    assert res.status_code == 200 and res.json()["answer"] == "Irvine"
    assert c.put(f"/api/answer-memory/{saved.id}", json={"answer": ""}).status_code == 422
    assert c.put("/api/answer-memory/999", json={"answer": "x"}).status_code == 404
    assert c.delete(f"/api/answer-memory/{saved.id}").json() == {"answers": []}
    assert c.delete(f"/api/answer-memory/{saved.id}").status_code == 404


def test_job_start_event_is_not_a_fit_stage(tmp_path, monkeypatch):
    """The worker's pick-up event is `start`, not `fit`: the SPA's stepper and bar
    never rewind, so a leading `fit` jumped them straight to "Fitting to the page"."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir()
    q = JobQueue()
    monkeypatch.setattr(q, "_execute", lambda job: None)
    job, _ = q.submit("jd", JobSettings())
    deadline = time.time() + 2
    while time.time() < deadline and q.get(job.job_id).status in ("queued", "running"):
        time.sleep(0.02)
    events = q.get(job.job_id).events
    assert events[0].stage == "start"
    assert all(e.stage != "fit" for e in events)


@pytest.fixture
def spa_client(tmp_path):
    """A fresh `_SPAStaticFiles` over a tiny fake dist, independent of any built frontend."""
    from fastapi import FastAPI

    from resume_tailor.web.app import _SPAStaticFiles

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    spa = FastAPI()
    spa.mount("/", _SPAStaticFiles(directory=str(dist), html=True))
    with TestClient(spa) as test_client:
        yield test_client


def test_spa_index_and_client_routes_are_revalidated(spa_client):
    """A webview must never reuse a stale index.html after an update."""
    for path in ("/", "/index.html", "/applications", "/apply/settings"):
        response = spa_client.get(path)
        assert response.status_code == 200, path
        assert "<html>app</html>" in response.text
        assert response.headers["cache-control"] == "no-cache", path


def test_spa_hashed_assets_are_immutable_and_other_files_revalidated(spa_client):
    asset = spa_client.get("/assets/index-abc123.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert spa_client.get("/favicon.svg").headers["cache-control"] == "no-cache"


def test_spa_missing_asset_falls_back_to_index_without_immutable_caching(spa_client):
    """A bundle name that is not on disk gets index.html; caching that for a year would
    pin the bad response even after the real bundle appears."""
    response = spa_client.get("/assets/index-gone.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_spa_revalidation_answers_304_with_the_same_policy(spa_client):
    first = spa_client.get("/")
    again = spa_client.get("/", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"
