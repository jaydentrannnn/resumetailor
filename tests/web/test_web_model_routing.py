"""Saved model settings reach `config.resolve` per stage."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.pipeline import jd
from resume_tailor.web import jobs as jobs_mod
from tests.web.helpers import _drain, _stub_no_network_extract


def test_ollama_model_setting_repoints_only_the_ollama_stages(client, monkeypatch):
    """The UI's Ollama tag field must reach `config.resolve` as per-stage overrides.

    Asserted at the resolve boundary rather than on a live call: what the field is for is
    changing the tag without an `.env` edit and a restart, and that is entirely a routing
    question. Under `hybrid` the Claude rewrite stage must come through untouched.
    """
    c, _q = client
    seen: dict[str, object] = {}
    real_resolve = config.resolve

    def recording_resolve(profile=None, *, overrides=None, effort=None):
        seen["profile"] = profile
        seen["overrides"] = dict(overrides or {})
        return real_resolve(profile, overrides=overrides, effort=effort)

    monkeypatch.setattr(jobs_mod.config, "resolve", recording_resolve)
    monkeypatch.setattr(jd, "extract", _stub_no_network_extract)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Some job description.",
            "settings": {"model": "hybrid", "ollama_model": "gemma4"},
        },
    )
    assert res.status_code == 200
    _drain(c, res.json()["job_id"])

    assert seen["profile"] == "hybrid"
    assert seen["overrides"] == {
        "extract": "gemma4",
        "score": "gemma4",
        "expand": "gemma4",
        "facets": "gemma4",
        "skills": "gemma4",
        "cover": "gemma4",
        "review": "gemma4",
        "answer": "gemma4",
    }
    config.resolve("claude")


def test_model_name_setting_repoints_every_stage(client, monkeypatch):
    """The blanket model_name field overrides every stage of the chosen profile."""
    c, _q = client
    seen: dict[str, object] = {}
    real_resolve = config.resolve

    def recording_resolve(profile=None, *, overrides=None, effort=None):
        seen["profile"] = profile
        seen["overrides"] = dict(overrides or {})
        return real_resolve(profile, overrides=overrides, effort=effort)

    monkeypatch.setattr(jobs_mod.config, "resolve", recording_resolve)
    monkeypatch.setattr(jd, "extract", _stub_no_network_extract)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Some job description.",
            "settings": {"model": "ollama", "model_name": "gemma4:cloud"},
        },
    )
    assert res.status_code == 200
    _drain(c, res.json()["job_id"])

    assert seen["profile"] == "ollama"
    assert seen["overrides"] == dict.fromkeys(config.PURPOSES, "gemma4:cloud")
    config.resolve("claude")


def test_blank_ollama_model_leaves_the_env_default_in_place(client, monkeypatch):
    """The field overrides *only* when filled in; blank must resolve to OLLAMA_MODEL.

    The inverse of the override test below, and the one users actually depend on: a saved
    settings blob with no tag in it must not start sending an empty model to the API.
    """
    c, _q = client
    seen: dict[str, object] = {}
    real_resolve = config.resolve

    def recording_resolve(profile=None, *, overrides=None, effort=None):
        seen["overrides"] = dict(overrides or {})
        seen["backends"] = real_resolve(profile, overrides=overrides, effort=effort)
        return seen["backends"]

    monkeypatch.setattr(jobs_mod.config, "resolve", recording_resolve)
    monkeypatch.setattr(jd, "extract", _stub_no_network_extract)

    res = c.post(
        "/api/jobs",
        json={"jd_text": "Some job description.", "settings": {"model": "ollama"}},
    )
    assert res.status_code == 200
    _drain(c, res.json()["job_id"])

    assert seen["overrides"] == {}
    assert seen["backends"]["extract"].model == config.OLLAMA_MODEL == "gemma4:cloud"
    config.resolve("claude")


def test_gemini_model_setting_repoints_only_the_gemini_stages(client, monkeypatch):
    """Mirrors the Ollama tag test above, for the Gemini field added alongside it."""
    c, _q = client
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    seen: dict[str, object] = {}
    real_resolve = config.resolve

    def recording_resolve(profile=None, *, overrides=None, effort=None):
        seen["profile"] = profile
        seen["overrides"] = dict(overrides or {})
        return real_resolve(profile, overrides=overrides, effort=effort)

    monkeypatch.setattr(jobs_mod.config, "resolve", recording_resolve)
    monkeypatch.setattr(jd, "extract", _stub_no_network_extract)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Some job description.",
            "settings": {"model": "gemini", "gemini_model": "gemini-3.5-pro"},
        },
    )
    assert res.status_code == 200
    _drain(c, res.json()["job_id"])

    assert seen["profile"] == "gemini"
    assert seen["overrides"] == dict.fromkeys(config.PURPOSES, "gemini-3.5-pro")
    config.resolve("claude")


def test_explicit_stage_override_beats_the_blanket_ollama_tag(client, monkeypatch):
    """`rewrite_model` is the narrower choice and must not be clobbered by the tag."""
    c, _q = client
    seen: dict[str, object] = {}
    real_resolve = config.resolve

    def recording_resolve(profile=None, *, overrides=None, effort=None):
        seen["overrides"] = dict(overrides or {})
        return real_resolve(profile, overrides=overrides, effort=effort)

    monkeypatch.setattr(jobs_mod.config, "resolve", recording_resolve)
    monkeypatch.setattr(jd, "extract", _stub_no_network_extract)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Some job description.",
            "settings": {
                "model": "ollama",
                "ollama_model": "gemma4",
                "rewrite_model": "claude-sonnet-5",
            },
        },
    )
    assert res.status_code == 200
    _drain(c, res.json()["job_id"])

    assert seen["overrides"]["rewrite"] == "claude-sonnet-5"
    assert seen["overrides"]["extract"] == "gemma4"
    config.resolve("claude")


def test_skills_model_setting_reaches_resolve_as_a_per_stage_override(client, monkeypatch):
    """`skills_model` must reach `config.resolve` as `overrides["skills"]`, same as
    `rewrite_model`/`expand_model`."""
    c, _q = client
    seen: dict[str, object] = {}
    real_resolve = config.resolve

    def recording_resolve(profile=None, *, overrides=None, effort=None):
        seen["overrides"] = dict(overrides or {})
        return real_resolve(profile, overrides=overrides, effort=effort)

    monkeypatch.setattr(jobs_mod.config, "resolve", recording_resolve)
    monkeypatch.setattr(jd, "extract", _stub_no_network_extract)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Some job description.",
            "settings": {"model": "claude", "skills_model": "ollama:gemma4:cloud"},
        },
    )
    assert res.status_code == 200
    _drain(c, res.json()["job_id"])

    assert seen["overrides"]["skills"] == "ollama:gemma4:cloud"
    config.resolve("claude")
