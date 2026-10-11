"""Unified model settings, operation snapshots and write-only custom credentials."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from resume_tailor import app_settings, config, workspace
from resume_tailor.apply.funnel import operations
from resume_tailor.model_selection import AiModels, ModelSelection
from resume_tailor.web.routes import system
from resume_tailor.web.schemas import ApplyOperationRequest, JobSettings
from tests.web.helpers import _point_settings_at


def _models():
    return AiModels(
        light=ModelSelection(model_name="writer"),
        heavy=ModelSelection(
            provider="custom",
            model_name="filler",
            api_format="anthropic",
            base_url="https://proxy.example/api",
        ),
    )


def test_settings_round_trip_and_legacy_client_can_replace_roles(client, tmp_path, monkeypatch):
    http, _ = client
    _point_settings_at(tmp_path, monkeypatch)
    models = _models().model_dump()
    response = http.put("/api/settings", json={"settings": {"ai_models": models}})
    assert response.status_code == 200
    saved = http.get("/api/settings").json()["settings"]
    assert saved["ai_models"] == models
    assert saved["apply"]["model_selection"] == models["heavy"]
    assert app_settings.load()["ai_models"] == models

    # An old API client sends only the old fields. Its choices must still take effect.
    legacy = {
        "model": "gemini",
        "model_name": "old-writer",
        "apply": {"model_provider": "lmstudio", "model_name": "old-filler"},
    }
    assert http.put("/api/settings", json={"settings": legacy}).status_code == 200
    migrated = http.get("/api/settings").json()["settings"]["ai_models"]
    assert migrated["light"]["model_name"] == "old-writer"
    assert migrated["heavy"]["model_name"] == "old-filler"


def test_custom_credentials_are_write_only_and_independent(client, tmp_path, monkeypatch):
    http, _ = client
    _point_settings_at(tmp_path, monkeypatch)
    models = _models()
    name = models.heavy.spec("heavy")["credential_ref"]
    other_role = models.heavy.spec("light")["credential_ref"]
    assert (
        http.put("/api/settings", json={"settings": {"ai_models": models.model_dump()}}).status_code
        == 200
    )
    assert http.put(f"/api/secrets/{name}", json={"value": "test-secret-value"}).status_code == 200
    state = http.get(f"/api/secrets/{name}")
    assert state.json() == {"name": name, "set": True, "source": "saved"}
    assert http.get(f"/api/secrets/{other_role}").json()["set"] is False
    listing = http.get("/api/secrets").json()
    assert any(s["name"] == name and s["set"] for s in listing["secrets"])
    assert "test-secret-value" not in json.dumps([state.json(), listing, app_settings.load()])
    assert http.delete(f"/api/secrets/{name}").json()["set"] is False


@pytest.mark.parametrize(
    "target, expected",
    [
        ("light", "writer"),
        ("tailor", "writer"),
        ("heavy", "filler"),
        ("autofill", "filler"),
    ],
)
def test_model_test_roles_and_legacy_aliases(client, monkeypatch, target, expected):
    http, _ = client
    seen = []
    monkeypatch.setattr(
        system.llm,
        "client_for",
        lambda _purpose: SimpleNamespace(
            messages=SimpleNamespace(
                parse=lambda **_kwargs: seen.append(config.model_for("extract"))
            ),
        ),
    )
    response = http.post(
        "/api/models/test",
        json={
            "target": target,
            "settings": {"ai_models": _models().model_dump()},
        },
    )
    assert response.status_code == 200 and response.json()["ok"]
    assert seen == [expected]


def test_incomplete_light_model_test_returns_failure_without_calling_model(client, monkeypatch):
    http, _ = client

    def no_call(_purpose):
        raise AssertionError("Incomplete connections must not make requests")

    monkeypatch.setattr(system.llm, "client_for", no_call)
    response = http.post(
        "/api/models/test",
        json={
            "target": "light",
            "settings": {"ai_models": {"light": {"provider": "custom"}}},
        },
    )
    assert response.status_code == 200
    assert not response.json()["ok"]
    assert "Custom server needs" in response.json()["detail"]


def test_apply_captures_both_roles_before_later_settings_edits(monkeypatch):
    initial = JobSettings(ai_models=_models())
    monkeypatch.setattr(workspace, "load_settings", lambda: {"defaults": initial.model_dump()})
    request = ApplyOperationRequest(
        action="fill",
        application_ids=["a-1"],
        model_provider="custom",
        model_name="filler",
        model_selection=initial.ai_models.heavy,
    )
    captured = operations._captured_settings(request)
    initial.ai_models.light.model_name = "later-writer"
    initial.ai_models.heavy.base_url = "https://other.example/api"
    assert captured._job_defaults.ai_models.light.model_name == "writer"
    assert captured.model_spec["base_url"] == "https://proxy.example/api"
    assert operations._effective_model(request) == "custom:filler"


def test_invalid_legacy_model_remains_editable(client, tmp_path, monkeypatch):
    http, _ = client
    _point_settings_at(tmp_path, monkeypatch)
    workspace.save_settings({"model": "removed-profile"})
    assert http.get("/api/settings").status_code == 200
