"""Remembered AI drafts stay durable without affecting the active request settings."""

import pytest

from resume_tailor import app_settings, config
from resume_tailor.infra import appearance
from resume_tailor.web.schemas import JobSettings


def test_disabled_advanced_uses_defaults_without_losing_custom_values():
    settings = JobSettings.model_validate({
        "ai_advanced_enabled": False, "effort": {"rewrite": "high", "answer": "high"},
        "extract_runs": 5, "max_concurrent_jobs": 8,
    })
    assert settings.effort is None
    assert settings.extract_runs == 0
    assert settings.max_concurrent_jobs == 2
    assert settings.apply.answer_effort is None
    assert settings.advanced_settings.model_dump() == {
        "effort": {"rewrite": "high", "answer": "high"}, "extract_runs": 5, "max_concurrent_jobs": 8,
    }
    assert JobSettings.model_validate(settings.model_dump()).advanced_settings == settings.advanced_settings
    # Existing integrations that do not send the switch keep their previous behavior.
    assert JobSettings(effort="high").apply.answer_effort == "high"


def test_preferences_round_trip_app_wide(client):
    c, _ = client
    draft = {
        "ai_advanced_enabled": False,
        "custom_effort": {"rewrite": "high"},
        "advanced_settings": {"effort": "high", "extract_runs": 5, "max_concurrent_jobs": 7},
        "ai_models": {
            "light": {"provider": "ollama", "model_name": "writer"},
            "heavy": {"provider": "ollama", "model_name": "filler"},
            "provider_selections": {"light": {
                "custom": {"provider": "custom", "model_name": "proxy", "base_url": "https://proxy.example/v1", "api_format": "anthropic", "plan": "subscription"},
                "vertex_ai": {"provider": "vertex_ai", "model_name": "gemini-test", "vertex_project": "test-project", "vertex_location": "global"},
            }},
        },
    }
    response = c.put("/api/settings", json={"settings": draft})
    assert response.status_code == 200
    saved = c.get("/api/settings").json()["settings"]
    assert saved["advanced_settings"] == draft["advanced_settings"]
    assert saved["custom_effort"] == draft["custom_effort"]
    assert saved["ai_models"]["provider_selections"]["light"]["custom"]["base_url"] == "https://proxy.example/v1"
    assert saved["ai_models"]["provider_selections"]["light"]["vertex_ai"]["vertex_project"] == "test-project"
    assert app_settings.load()["ai_advanced_enabled"] is False
    assert saved["effort"] is None


@pytest.mark.parametrize("url", ["https://", "https://[", "unfinished-server"])
def test_inactive_custom_drafts_can_be_saved_but_active_urls_stay_validated(client, url):
    c, _ = client
    draft = {
        "provider": "custom", "model_name": "proxy", "base_url": url,
        "api_format": "anthropic", "plan": "subscription",
    }
    models = {
        "light": {"provider": "ollama", "model_name": "writer"},
        "heavy": {"provider": "ollama", "model_name": "filler"},
        "provider_selections": {"light": {"custom": draft}},
    }
    assert c.put("/api/settings", json={"settings": {"ai_models": models}}).status_code == 200
    saved = c.get("/api/settings").json()["settings"]
    assert saved["ai_models"]["provider_selections"]["light"]["custom"] == {
        **draft, "vertex_project": "", "vertex_location": "",
    }
    assert saved["ai_models"]["light"]["provider"] == "ollama"
    models["light"] = draft
    assert c.put("/api/settings", json={"settings": {"ai_models": models}}).status_code == 422


def test_inactive_drafts_do_not_store_url_credentials(client):
    c, _ = client
    models = {"provider_selections": {"light": {"custom": {
        "provider": "custom", "base_url": "https://user:secret@proxy.example/v1",
    }}}}
    assert c.put("/api/settings", json={"settings": {"ai_models": models}}).status_code == 422


def test_theme_preference_is_validated_and_persisted(client, tmp_path, monkeypatch):
    c, _ = client
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    assert appearance.load_theme() is None
    for preference in ("light", "dark", "system"):
        assert c.put("/api/theme", json={"preference": preference}).status_code == 200
        assert appearance.load_theme() == preference
    assert c.put("/api/theme", json={"preference": "invalid"}).status_code == 422
    assert appearance.load_theme() == "system"


def test_shell_theme_path_wins_over_the_data_directory(client, tmp_path, monkeypatch):
    c, _ = client
    data = tmp_path / "custom-data"
    target = tmp_path / "shell" / "theme.json"
    monkeypatch.setattr(config, "DATA_ROOT", data)
    monkeypatch.setenv("RESUME_TAILOR_THEME_PATH", str(target))
    assert c.put("/api/theme", json={"preference": "dark"}).status_code == 200
    assert appearance.theme_path() == target
    assert appearance.load_theme() == "dark"
    assert target.exists()
    assert not (data / "theme.json").exists()
