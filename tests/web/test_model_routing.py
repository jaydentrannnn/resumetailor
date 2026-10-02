"""Tailor-tab model routing shared by the job runner and the Apply funnel."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.apply.funnel import operations
from resume_tailor.web.job_routing import model_label, model_routing
from resume_tailor.web.schemas import ApplyOperationRequest, JobSettings


def test_model_routing_defaults_to_profile_without_overrides():
    assert model_routing(JobSettings(model="ollama")) == ("ollama", None, None)


def test_model_routing_precedence_blanket_then_provider_then_stage():
    """A blanket model name repoints every stage, a provider tag overwrites its stages,
    and a per-stage field wins over both."""
    profile, overrides, effort = model_routing(
        JobSettings(
            model="ollama",
            model_name="blanket",
            ollama_model="ollama-tag",
            rewrite_model="rewrite-only",
            effort="high",
        )
    )
    assert profile == "ollama"
    assert effort == "high"
    assert overrides is not None
    assert overrides["rewrite"] == "rewrite-only"
    assert overrides["extract"] == "ollama-tag"
    assert set(overrides) == set(config.PURPOSES)


def test_model_label_names_the_rewrite_backend():
    assert model_label(JobSettings(model="ollama", model_name="gemma4:cloud")) == (
        "ollama:gemma4:cloud"
    )


def test_model_label_flags_stage_overrides():
    label = model_label(
        JobSettings(model="ollama", model_name="gemma4:cloud", skills_model="other")
    )
    assert label == "ollama:gemma4:cloud + stage overrides"


def test_model_label_ignores_answer_override():
    """The answer stage isn't part of tailoring, so it doesn't make the label noisy."""
    label = model_label(
        JobSettings(model="ollama", model_name="gemma4:cloud", answer_model="other")
    )
    assert label == "ollama:gemma4:cloud"


def test_model_label_falls_back_to_raw_profile_on_bad_spec():
    assert model_label(JobSettings(model="not-a-real-profile")) == "not-a-real-profile"


def _request(action: str) -> ApplyOperationRequest:
    return ApplyOperationRequest(
        action=action,
        application_ids=["a-1"],
        model_provider="lmstudio",
        model_name="autofill-model",
    )


def test_effective_model_prepare_shows_tailor_routing(monkeypatch):
    tailor = JobSettings(model="ollama", model_name="gemma4:cloud")
    monkeypatch.setattr(
        operations.workspace, "load_settings", lambda: {"defaults": tailor.model_dump()}
    )
    assert operations._effective_model(_request("prepare")) == "ollama:gemma4:cloud"
    assert operations._effective_model(_request("find")) == "ollama:gemma4:cloud"


def test_effective_model_fill_shows_autofill_model(monkeypatch):
    def _no_settings():
        raise AssertionError("fill must not consult Tailor settings")

    monkeypatch.setattr(operations.workspace, "load_settings", _no_settings)
    assert operations._effective_model(_request("fill")) == "lmstudio:autofill-model"


def test_ollama_model_setting_repoints_the_cloud_profile_and_keeps_its_address():
    """`ollama-cloud` is an Ollama-routed profile, so the shared Ollama tag applies — the
    same `:cloud` tag works on the daemon and on the direct API."""
    profile, overrides, _effort = model_routing(
        JobSettings(model="ollama-cloud", ollama_model="x:cloud")
    )
    assert profile == "ollama-cloud"
    assert overrides == dict.fromkeys(config.PURPOSES, "x:cloud")
    try:
        backends = config.resolve(profile, overrides=overrides)
        assert {b.base_url for b in backends.values()} == {config.OLLAMA_CLOUD_BASE_URL}
        assert {b.model for b in backends.values()} == {"x:cloud"}
    finally:
        config.resolve("claude")


def test_apply_request_accepts_ollama_cloud():
    request = ApplyOperationRequest(
        action="fill", model_provider="ollama-cloud", model_name="gemma4:cloud"
    )
    assert request.model_provider == "ollama-cloud"
