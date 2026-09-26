"""Tests for the `answer` LLM purpose and apply path globals."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.web.schemas import ApplySettings


def test_answer_is_a_purpose_on_every_profile():
    """Every MODEL_PROFILES entry must key `answer` or resolve() KeyErrors."""
    assert "answer" in config.PURPOSES
    assert "answer" in config.DEFAULT_EFFORT
    for name, specs in config.MODEL_PROFILES.items():
        assert "answer" in specs, f"{name} missing answer stage"


def test_apply_paths_in_workspace_paths(tmp_path, monkeypatch):
    """APPLICATIONS_* and APPLICANT_PROFILE_PATH are bound in workspace_paths().

    Asserts the dict without calling ``set_active_workspace``, which would leave
    process-wide ``config`` globals pointing at a throwaway tree for later tests.
    """
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(config, "TEMPLATES_ROOT", tmp_path / "templates")
    monkeypatch.setattr(config, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_ROOT", tmp_path / "cache")

    paths = config.workspace_paths("alpha")
    assert paths["APPLICATIONS_PATH"] == paths["DATA_DIR"] / "applications.json"
    assert paths["APPLICANT_PROFILE_PATH"] == paths["DATA_DIR"] / "applicant_profile.json"
    assert paths["APPLICATIONS_OUTPUT_DIR"] == paths["OUTPUT_DIR"] / "applications"
    assert "alpha" in str(paths["APPLICATIONS_PATH"])


def test_apply_settings_default_model_is_ollama_nemotron():
    """Defaults so a fresh workspace's funnel never falls through to the Claude default."""
    settings = ApplySettings()
    assert settings.model_provider == "ollama"
    assert settings.model_name == "nemotron-3-super:cloud"
    assert settings.model_spec == "ollama:nemotron-3-super:cloud"


def test_apply_settings_without_model_fields_still_validates():
    """An old settings.json missing the new keys gets the new defaults, not a validation error."""
    legacy = ApplySettings().model_dump()
    del legacy["model_provider"]
    del legacy["model_name"]
    settings = ApplySettings.model_validate(legacy)
    assert settings.model_provider == "ollama"
    assert settings.model_name == "nemotron-3-super:cloud"


def test_apply_settings_ollama_cloud_spec_pins_the_cloud_address():
    """`ollama-cloud` is not a provider word `parse_spec` knows — it must become an
    Ollama spec carrying the cloud base URL, or Fill would silently run on the daemon."""
    settings = ApplySettings(model_provider="ollama-cloud", model_name="gemma4:cloud")
    assert settings.model_spec == f"ollama:gemma4:cloud@{config.OLLAMA_CLOUD_BASE_URL}"
    origin, model, base_url = config.parse_spec(settings.model_spec)
    assert (origin, model, base_url) == ("ollama", "gemma4:cloud", "https://ollama.com/v1")
