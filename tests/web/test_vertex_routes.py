"""Vertex metadata and write-only connection APIs under the existing request gate."""

import json

import httpx
import pytest

from resume_tailor import config
from resume_tailor.infra import vertex_auth, vertex_catalog, vertex_oauth
from resume_tailor.model_selection import ModelSelection
from resume_tailor.web.routes import vertex


def connected():
    vertex_auth.save(
        {"refresh_token": "private-google-token", "client_id": "id"},
        "user@example.test",
        vertex_auth.epoch(),
    )


def selection():
    return ModelSelection(
        provider="vertex_ai",
        model_name="vertex_ai/claude-sonnet-5-5",
        vertex_project="test-project",
        vertex_location="global",
    )


def test_connection_removal_and_missing_client_configuration(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(vertex_oauth, "client_config", lambda: None)
    connected()
    state = http.get("/api/vertex/connection")
    assert state.json()["email"] == "user@example.test"
    assert state.json()["configured"] is False
    assert "private-google-token" not in state.text
    unavailable = http.post("/api/vertex/auth")
    assert unavailable.status_code == 503
    assert "Desktop OAuth" in unavailable.text
    assert http.delete("/api/vertex/connection").json()["connected"] is False


def test_auth_lifecycle_and_unknown_sessions(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(
        vertex_oauth,
        "start",
        lambda: {
            "flow_id": "opaque",
            "authorization_url": "https://accounts.google.com/auth",
        },
    )
    assert http.post("/api/vertex/auth").json()["flow_id"] == "opaque"
    assert http.get("/api/vertex/auth/missing").status_code == 404
    assert http.delete("/api/vertex/auth/missing").status_code == 404


def test_projects_pagination_and_manual_entry_failure(client, monkeypatch):
    http, _ = client
    connected()
    monkeypatch.setattr(vertex_auth, "access_token", lambda *_a: "private-access-token")
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(
            200,
            json={
                "projects": [{"projectId": "test-project", "displayName": "Test"}],
                "nextPageToken": "next",
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(vertex.httpx, "get", get)
    response = http.get("/api/vertex/projects?page_token=prior")
    assert response.json() == {
        "projects": [{"id": "test-project", "name": "Test"}],
        "next_page_token": "next",
    }
    assert calls[0]["params"]["pageToken"] == "prior"
    assert "private-access-token" not in response.text

    def unavailable(*_a, **_k):
        raise httpx.ConnectError("private-error")

    monkeypatch.setattr(vertex.httpx, "get", unavailable)
    response = http.get("/api/vertex/projects")
    assert response.status_code == 503
    assert "manually" in response.text
    assert "private" not in response.text


def test_model_suggestions_do_not_generate_or_need_credentials(client, monkeypatch):
    http, _ = client
    expected = [{"id": "claude-haiku-5-5", "reasoning": True, "locations": ["global"]}]
    monkeypatch.setattr(vertex_catalog, "suggestions", lambda: expected)
    assert http.get("/api/vertex/models").json() == {"models": expected}


def test_vertex_both_roles_round_trip_and_snapshots_do_not_contain_tokens(client):
    http, _ = client
    connected()
    light = selection()
    heavy = selection().model_copy(
        update={"model_name": "claude-haiku-5-5", "vertex_location": "us-east5"}
    )
    body = {"settings": {"ai_models": {"light": light.model_dump(), "heavy": heavy.model_dump()}}}
    assert http.put("/api/settings", json=body).status_code == 200
    settings = http.get("/api/settings").json()["settings"]
    assert settings["apply"]["model_selection"] == heavy.model_dump()
    with config.pinned("ollama", overrides={"rewrite": light.spec("light")}):
        snapshot = config.backend_specs_snapshot()
    assert snapshot["rewrite"]["model"] == "claude-sonnet-5-5"
    assert snapshot["rewrite"]["vertex_project"] == "test-project"
    assert "private-google-token" not in json.dumps(snapshot)


@pytest.mark.parametrize(
    "field, value", [("vertex_project", "name/escape"), ("vertex_location", "evil.example")]
)
def test_invalid_project_or_location_cannot_build_arbitrary_urls(field, value):
    with pytest.raises(ValueError):
        selection().model_copy(update={field: value}).spec("light")


def test_vertex_endpoints_keep_request_gate(client, monkeypatch):
    http, _ = client
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "session-secret")
    assert http.get("/api/vertex/connection").status_code == 401
    assert (
        http.post(
            "/api/vertex/auth",
            headers={"X-RT-Token": "session-secret", "Origin": "https://foreign.example"},
        ).status_code
        == 403
    )
