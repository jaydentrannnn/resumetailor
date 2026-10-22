"""Outcome routes: record, correct and void, on archived rows too."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models
from resume_tailor.web.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    row = store_models.Application(source="simplify", source_job_id="a", company="Acme", role="Analyst")
    apply_store.set_status(row, "submitted", note="")
    apply_store.save_all({"a": row})
    with TestClient(app) as test_client:
        yield test_client


def test_record_an_interview_on_a_done_row(client):
    assert client.get("/api/applications/a").json()["application"]["archived_at"]
    res = client.post(
        "/api/applications/a/outcomes",
        json={"type": "interview_invited", "occurred_on": "2026-10-20", "note": "Phone screen"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "submitted"
    assert body["hiring"]["stage"] == "interview" and body["hiring"]["label"] == "Interviewing"
    [event] = body["outcome_events"]
    assert (event["type"], event["source"], event["note"]) == ("interview_invited", "manual", "Phone screen")
    assert [a["method"] for a in body["attempts"]] == ["manual"]
    listed = client.get("/api/applications?archive=archived").json()["applications"][0]
    assert listed["hiring"]["stage"] == "interview"
    assert listed["outcome_events"] == [] and listed["attempts"] == []


def test_correct_then_void_keeps_both_events(client):
    first = client.post("/api/applications/a/outcomes", json={"type": "rejected"}).json()
    event_id = first["outcome_events"][0]["id"]
    fixed = client.patch(
        f"/api/applications/a/outcomes/{event_id}", json={"type": "ghosted"}
    ).json()
    assert [e["type"] for e in fixed["outcome_events"]] == ["rejected", "ghosted"]
    assert fixed["hiring"]["closed"] == "ghosted"
    new_id = fixed["outcome_events"][1]["id"]
    voided = client.patch(f"/api/applications/a/outcomes/{new_id}", json={"void": True}).json()
    assert all(e["voided_at"] for e in voided["outcome_events"])
    assert voided["hiring"]["closed"] is None
    again = client.patch(f"/api/applications/a/outcomes/{new_id}", json={"void": True})
    assert again.status_code == 422


def test_bad_requests_name_the_problem(client):
    assert client.post("/api/applications/nope/outcomes", json={"type": "offer"}).status_code == 404
    assert client.post("/api/applications/a/outcomes", json={"type": "party"}).status_code == 422
    bad_date = client.post("/api/applications/a/outcomes", json={"type": "offer", "occurred_on": "soon"})
    assert bad_date.status_code == 422
    assert client.patch("/api/applications/a/outcomes/zzz", json={"void": True}).status_code == 404


def test_csv_export_has_the_hiring_columns(client):
    client.post("/api/applications/a/outcomes", json={"type": "offer", "occurred_on": "2026-10-21"})
    [row] = csv.DictReader(io.StringIO(client.get("/api/applications/export.csv").text))
    assert (row["hiring_stage"], row["offer_on"], row["interview_on"]) == ("offer", "2026-10-21", "")
    assert row["applied_on"]
