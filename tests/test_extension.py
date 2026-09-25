"""Browser-extension pairing, its lane through the request gate, and page capture (P4-X)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply import daily, store
from resume_tailor.apply import operations as apply_operations
from resume_tailor.web import extension
from resume_tailor.web.app import app as web_app

_ORIGIN = {"origin": "chrome-extension://abcdefghijklmnop"}
_JD = (
    "About the role. You will build financial models, analyze company performance and "
    "present findings to the team. Requirements: Excel, PowerPoint and strong written "
    "communication. Experience with valuation is a plus. We offer mentorship and a "
    "summer program for students graduating in 2027. "
) * 2


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    with TestClient(web_app) as test_client:
        yield test_client


def _pair(client: TestClient) -> dict[str, str]:
    code = client.post("/api/extension-pairings/code").json()["code"]
    response = client.post(
        "/api/extension/pair/complete", json={"code": code, "label": "Chrome"}, headers=_ORIGIN
    )
    assert response.status_code == 200, response.text
    return {**_ORIGIN, extension.HEADER_NAME: response.json()["token"]}


# --- pairing store ------------------------------------------------------------------


def test_code_is_single_use_and_token_is_stored_hashed():
    code = extension.start_pairing()["code"]
    assert len(code) == 6 and code.isdigit()
    pairing_id, token = extension.complete_pairing(code, "Edge")
    assert extension.verify_token(token) == pairing_id
    assert token not in extension.store_path().read_text(encoding="utf-8")
    with pytest.raises(extension.PairingError, match="No pairing code"):
        extension.complete_pairing(code)
    assert extension.list_pairings()[0]["label"] == "Edge"
    assert "token_sha256" not in extension.list_pairings()[0]


def test_code_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(extension, "_clock", lambda: now[0])
    code = extension.start_pairing()["code"]
    now[0] += extension.CODE_TTL + 1
    with pytest.raises(extension.PairingError, match="expired"):
        extension.complete_pairing(code)


def test_wrong_guesses_void_the_code():
    code = extension.start_pairing()["code"]
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    for _ in range(extension.MAX_ATTEMPTS - 1):
        with pytest.raises(extension.PairingError, match="not right"):
            extension.complete_pairing(wrong)
    with pytest.raises(extension.PairingError, match="Too many"):
        extension.complete_pairing(wrong)
    with pytest.raises(extension.PairingError, match="No pairing code"):
        extension.complete_pairing(code)


def test_a_new_code_replaces_the_old_one():
    first = extension.start_pairing()["code"]
    second = extension.start_pairing()["code"]
    if first != second:
        with pytest.raises(extension.PairingError):
            extension.complete_pairing(first)
    extension.complete_pairing(second)


def test_revoke_and_unreadable_store(tmp_path):
    _id, token = extension.complete_pairing(extension.start_pairing()["code"])
    assert extension.revoke(_id)
    assert not extension.revoke(_id)
    assert extension.verify_token(token) is None
    extension.store_path().write_text("{not json", encoding="utf-8")
    assert extension.list_pairings() == []
    assert extension.verify_token("anything") is None


# --- request gate -------------------------------------------------------------------


def test_extension_routes_need_a_paired_token(client):
    assert client.get("/api/extension/status", headers=_ORIGIN).status_code == 401
    bad = {**_ORIGIN, extension.HEADER_NAME: "nope"}
    assert client.get("/api/extension/status", headers=bad).json()["error"] == "extension_auth"
    headers = _pair(client)
    status = client.get("/api/extension/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["app"] == "resumetailor"


def test_extension_origin_writes_pass_only_on_the_extension_lane(client):
    headers = _pair(client)
    # The same origin is still refused on the app's own routes.
    refused = client.put("/api/automation", json={"paused": True}, headers=headers)
    assert refused.status_code == 403
    response = client.post(
        "/api/extension/capture",
        json={"url": "https://boards.greenhouse.io/acme/jobs/123", "jd_text": _JD},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_web_pages_cannot_use_the_extension_lane(client):
    headers = _pair(client)
    evil = {**headers, "origin": "https://evil.example"}
    assert client.get("/api/extension/status", headers=evil).status_code == 403
    code = client.post("/api/extension-pairings/code").json()["code"]
    response = client.post(
        "/api/extension/pair/complete", json={"code": code}, headers={"origin": "null"}
    )
    assert response.status_code == 403


def test_extension_lane_works_with_the_session_token_on(client, monkeypatch):
    headers = _pair(client)
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "s3cret")
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/extension/status", headers=headers).status_code == 200
    # Pairing management stays behind the app's own session.
    assert client.get("/api/extension-pairings").status_code == 401
    assert (
        client.get("/api/extension-pairings", headers={"x-rt-token": "s3cret"}).status_code == 200
    )


def test_pairing_routes(client):
    headers = _pair(client)
    rows = client.get("/api/extension-pairings").json()
    assert [r["label"] for r in rows] == ["Chrome"]
    assert client.delete(f"/api/extension-pairings/{rows[0]['id']}").status_code == 204
    assert client.get("/api/extension/status", headers=headers).status_code == 401
    assert client.delete(f"/api/extension-pairings/{rows[0]['id']}").status_code == 404
    wrong = client.post("/api/extension/pair/complete", json={"code": "000000"}, headers=_ORIGIN)
    assert wrong.status_code == 400


# --- capture ------------------------------------------------------------------------


def test_capture_creates_a_tracked_row_and_dedupes(client):
    headers = _pair(client)
    body = {
        "url": "https://www.linkedin.com/jobs/view/analyst-at-acme-3812345678",
        "company": "Acme",
        "role": "Summer Analyst",
        "location": "New York, NY",
        "jd_text": _JD,
    }
    first = client.post("/api/extension/capture", json=body, headers=headers).json()
    assert first["result"] == "created"
    row = first["application"]
    assert row["id"] == "linkedin:jobs:3812345678"
    assert row["ats"] == "linkedin"
    assert row["status"] == "jd_fetched"
    stored = store.get(row["id"])
    assert stored is not None and stored.source == "extension"
    assert Path(stored.jd_text_path).read_text(encoding="utf-8").startswith("About the role")

    again = client.post("/api/extension/capture", json=body, headers=headers).json()
    assert again["result"] == "exists"
    assert len(store.load_all()) == 1

    lookup = client.get(
        "/api/extension/lookup", params={"url": body["url"]}, headers=headers
    ).json()
    assert lookup["assist_only"] is True
    assert lookup["application"]["id"] == row["id"]


def test_capture_keys_on_the_external_apply_url(client):
    headers = _pair(client)
    body = {
        "url": "https://www.linkedin.com/jobs/view/3812345678",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/4455",
        "company": "Acme",
        "role": "Analyst",
        "jd_text": _JD,
    }
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]
    assert row["id"] == "greenhouse:acme:4455"
    assert row["ats"] == "greenhouse"
    # The same job seen later on its own board is the same row.
    later = client.post(
        "/api/extension/capture",
        json={"url": "https://boards.greenhouse.io/acme/jobs/4455", "jd_text": _JD},
        headers=headers,
    ).json()
    assert later["result"] == "exists"


def test_capture_rejects_a_login_wall(client):
    headers = _pair(client)
    response = client.post(
        "/api/extension/capture",
        json={"url": "https://www.linkedin.com/jobs/view/1", "jd_text": "Sign in to view"},
        headers=headers,
    )
    assert response.status_code == 422
    assert "Send selection" in response.json()["detail"]
    assert store.load_all() == {}


def test_capture_runs_the_no_llm_prefilter(client):
    headers = _pair(client)
    body = {
        "url": "https://jobs.lever.co/acme/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab",
        "company": "Acme",
        "role": "Analyst",
        "jd_text": _JD + " An active security clearance is required.",
    }
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]
    assert row["status"] == "screened_out"
    assert row["screen_reasons"]


def test_prepare_reuses_the_captured_text():
    app = store.Application(
        source="extension",
        source_job_id="ext-1",
        company="Acme",
        role="Analyst",
        posting_url="https://www.linkedin.com/jobs/view/1",
        final_url="https://www.linkedin.com/jobs/view/1",
        ats="linkedin",
    )
    app.jd_text_path = daily._save_jd("ext-1", _JD)
    captured = daily._captured_jd(app)
    assert captured is not None
    assert captured.method == "captured"
    assert captured.ats == "linkedin"
    assert captured.text == _JD

    other = app.model_copy(update={"source": "simplify"})
    assert daily._captured_jd(other) is None


def test_prepare_and_fill_build_the_request_from_settings(client, monkeypatch):
    settings = {"defaults": {"apply": {"model_provider": "gemini", "model_name": "flash"}}}
    config.SETTINGS_PATH.write_text(json.dumps(settings), encoding="utf-8")
    headers = _pair(client)
    body = {"url": "https://boards.greenhouse.io/acme/jobs/9", "jd_text": _JD}
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]

    seen = []

    def _start(request):
        seen.append(request)
        return apply_operations.ApplyOperation(
            operation_id="op1", action=request.action, application_ids=request.application_ids
        )

    monkeypatch.setattr(apply_operations, "start", _start)
    response = client.post(f"/api/extension/applications/{row['id']}/prepare", headers=headers)
    assert response.status_code == 202, response.text
    response = client.post(f"/api/extension/applications/{row['id']}/fill", headers=headers)
    assert response.status_code == 202
    assert [r.action for r in seen] == ["prepare", "fill"]
    assert all(r.model_provider == "gemini" and r.model_name == "flash" for r in seen)
    assert all(r.auto_submit is False for r in seen)
    assert seen[0].application_ids == [row["id"]]

    missing = client.post("/api/extension/applications/nope/prepare", headers=headers)
    assert missing.status_code == 404

    def _busy(_request):
        raise RuntimeError("Apply operation x is already active")

    monkeypatch.setattr(apply_operations, "start", _busy)
    busy = client.post(f"/api/extension/applications/{row['id']}/fill", headers=headers)
    assert busy.status_code == 409


def test_status_counts_rows_that_need_you(client):
    headers = _pair(client)
    for n, status in enumerate(["awaiting_otp", "ready", "fill_failed"]):
        row = store.Application(
            source="t", source_job_id=f"r{n}", company="A", role="B", canonical_key=f"k{n}"
        )
        store.set_status(row, status)
        store.upsert(row)
    body = client.get("/api/extension/status", headers=headers).json()
    assert body["needs_you"] == 2
    assert body["paused"] is False
