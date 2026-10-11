"""App-wide AI settings: shared by every profile, split out of each `settings.json`."""

from __future__ import annotations

import json

from resume_tailor import app_settings, workspace
from resume_tailor.workspace import bootstrap
from tests.test_workspace import isolated_roots  # noqa: F401 - fixture


def _profile_file() -> dict:
    return json.loads(workspace.settings_path().read_text(encoding="utf-8"))["defaults"]


def test_save_splits_app_keys_out_of_the_profile_file(isolated_roots):  # noqa: F811
    bootstrap()
    workspace.save_settings(
        {"pages": 2, "model": "gemini", "effort": "high",
         "apply": {"model_provider": "anthropic", "model_name": "x", "enabled": True}}
    )
    own = _profile_file()
    assert own == {"pages": 2, "apply": {"enabled": True}}
    assert app_settings.load() == {
        "model": "gemini", "effort": "high",
        "apply": {"model_provider": "anthropic", "model_name": "x"},
    }
    merged = workspace.load_settings()["defaults"]
    assert merged["model"] == "gemini"
    assert merged["apply"] == {"enabled": True, "model_provider": "anthropic", "model_name": "x"}


def test_model_is_shared_across_profiles(isolated_roots):  # noqa: F811
    bootstrap()
    workspace.save_settings({"pages": 3, "model": "gemini"})
    second = workspace.create("Second")
    workspace.save_settings({"pages": 1, "model": "lmstudio"}, second.id)
    assert workspace.load_settings()["defaults"]["model"] == "lmstudio"
    assert workspace.load_settings()["defaults"]["pages"] == 3
    assert workspace.load_settings(second.id)["empty"] is False


def test_without_an_app_file_profile_values_are_used(isolated_roots):  # noqa: F811
    path = workspace.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"defaults": {"model": "gemini"}}), encoding="utf-8")
    assert workspace.load_settings()["defaults"]["model"] == "gemini"


def test_bootstrap_seeds_from_the_active_profile_once(isolated_roots):  # noqa: F811
    bootstrap()
    path = workspace.settings_path()
    path.write_text(
        json.dumps({"defaults": {"model": "gemini", "pages": 2,
                                 "apply": {"model_name": "m", "enabled": True}}}),
        encoding="utf-8",
    )
    app_settings.path().unlink(missing_ok=True)
    bootstrap()
    saved = app_settings.load()
    assert saved["model"] == "gemini"
    assert saved["apply"] == {"model_name": "m"}
    assert saved["ai_models"]["light"]["provider"] == "gemini"
    assert saved["ai_models"]["heavy"]["model_name"] == "m"
    path.write_text(json.dumps({"defaults": {"model": "lmstudio"}}), encoding="utf-8")
    bootstrap()  # the file exists now: no re-seed
    assert app_settings.load()["model"] == "gemini"
    assert workspace.load_settings()["defaults"]["model"] == "gemini"


def test_retired_run_options_are_ignored_on_load(isolated_roots):  # noqa: F811
    bootstrap()
    path = workspace.settings_path()
    path.write_text(
        json.dumps({"defaults": {"no_skills": True, "no_facets": True, "no_cache": True,
                                 "initial_bullet_share": 0.5, "pages": 2}}),
        encoding="utf-8",
    )
    assert workspace.load_settings()["defaults"] == {"pages": 2}


def test_legacy_save_clears_stale_canonical_apply_selection(isolated_roots):  # noqa: F811
    bootstrap()
    app_settings.save({
        "ai_models": {"light": {"provider": "ollama"}, "heavy": {"provider": "gemini"}},
        "apply": {"model_selection": {"provider": "gemini", "model_name": "previous"}},
    })
    workspace.save_settings({"apply": {"model_provider": "lmstudio", "model_name": "new"}})
    saved = app_settings.load()
    assert "ai_models" not in saved
    assert saved["apply"] == {"model_provider": "lmstudio", "model_name": "new"}


def test_legacy_custom_key_is_migrated_without_saving_its_value(monkeypatch):
    from resume_tailor import config
    from resume_tailor.model_selection import AiModels

    monkeypatch.setenv("LLM_API_KEY", "legacy-test-key")
    assert app_settings.seed({"model": "openai:writer@https://proxy.example/v1"})
    saved = app_settings.load()
    models = AiModels.model_validate(saved["ai_models"])
    with config.pinned(models.light.spec("light")):
        assert config.api_key_for("rewrite") == "legacy-test-key"
    assert "legacy-test-key" not in json.dumps(saved)
