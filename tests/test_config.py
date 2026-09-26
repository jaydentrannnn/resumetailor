"""Tests for `config.canonical_tag` and `config.tag_alias_fingerprint`.

Neither had a unit test before this file — `test_rewrite.py::test_score_uses_canonical_tags`
and `test_jd.py::test_canonical_still_passes_through_tag_aliases` only assert it end to end
through a bigger pipeline. These pin the function's own contract: what it does and, just as
importantly, what it deliberately does not do (no stemming, no plurals beyond the table, no
transitive alias resolution).
"""

from __future__ import annotations

import pytest

from resume_tailor import config


def test_strips_and_lowercases():
    assert config.canonical_tag("  Python  ") == "python"
    assert config.canonical_tag("PYTHON") == "python"


def test_alias_hit():
    assert config.canonical_tag("py") == "python"
    assert config.canonical_tag("ml") == "machine learning"
    assert config.canonical_tag("vector databases") == "vector database"


def test_unknown_term_passes_through_unchanged():
    assert config.canonical_tag("kubernetes") == "kubernetes"
    assert config.canonical_tag("some made-up skill") == "some made-up skill"


def test_no_stemming_or_generic_plural_handling():
    """Only the exact plurals hand-entered in TAG_ALIASES collapse; nothing else does."""
    assert config.canonical_tag("apis") == "apis"  # not stemmed to "api"
    assert config.canonical_tag("llms") == "llm"  # in the table
    assert config.canonical_tag("dockers") == "dockers"  # not in the table, stays as-is


def test_no_transitive_alias_resolution():
    """An alias's *value* is never itself looked up again."""
    for value in config.TAG_ALIASES.values():
        cleaned = value.strip().lower()
        # If a value were also a key mapping somewhere else, canonical_tag(value) would
        # differ from value itself — assert every alias target is already a fixed point.
        assert config.canonical_tag(cleaned) == cleaned


def test_tag_alias_fingerprint_stable_under_key_reordering(monkeypatch):
    forward = dict(config.TAG_ALIASES)
    reversed_order = dict(reversed(list(config.TAG_ALIASES.items())))

    monkeypatch.setattr(config, "TAG_ALIASES", forward)
    a = config.tag_alias_fingerprint()
    monkeypatch.setattr(config, "TAG_ALIASES", reversed_order)
    b = config.tag_alias_fingerprint()

    assert a == b


def test_tag_alias_fingerprint_changes_when_a_value_changes(monkeypatch):
    before = config.tag_alias_fingerprint()
    monkeypatch.setitem(config.TAG_ALIASES, "py", "not-python")
    after = config.tag_alias_fingerprint()

    assert before != after


def test_tag_alias_fingerprint_changes_when_a_key_is_added(monkeypatch):
    before = config.tag_alias_fingerprint()
    monkeypatch.setitem(config.TAG_ALIASES, "brand-new-alias-key", "some-target")
    after = config.tag_alias_fingerprint()

    assert before != after


# --------------------------------------------------------------------------------------
# config.pinned() — the ContextVar overlay `backend_for` consults ahead of `_ACTIVE`.
# --------------------------------------------------------------------------------------


def test_pinned_overrides_active_for_every_purpose(monkeypatch):
    """A `pinned()` block wins over whatever `resolve()` last set, for every stage."""
    config.resolve("claude")
    assert config.backend_for("extract").provider == "anthropic"

    with config.pinned("ollama"):
        for purpose in config.PURPOSES:
            backend = config.backend_for(purpose)
            assert backend.origin == "ollama"
            assert backend.model == config.OLLAMA_MODEL
            assert backend.provider == "openai"

    # Restored exactly, once the block exits.
    assert config.backend_for("extract").provider == "anthropic"


def test_pinned_covers_every_purpose_keyed_accessor():
    """Every `*_for(purpose)` helper funnels through `backend_for`, so the pin must be
    visible from all of them, not just `backend_for` itself."""
    config.resolve("claude")

    with config.pinned("ollama"):
        assert config.model_for("extract") == config.OLLAMA_MODEL
        assert config.provider_for("extract") == "openai"
        assert config.base_url_for("extract") == config.OLLAMA_BASE_URL
        assert config.structured_mode_for("extract") == "prompt"


def test_pinned_never_mutates_active():
    """`pinned()` must leave `_ACTIVE` byte-identical — a job resolved separately must
    never be repointed by an unrelated one-off web action."""
    resolved = config.resolve("claude")

    with config.pinned("ollama"):
        assert resolved == config._ACTIVE

    assert resolved == config._ACTIVE


def test_pinned_invalid_profile_raises_and_leaves_no_residue():
    config.resolve("claude")

    with pytest.raises(ValueError), config.pinned("not-a-real-profile"):
        pass

    assert config._PINNED.get() is None
    assert config.backend_for("extract").provider == "anthropic"


def test_pinned_applies_stage_overrides_then_resets():
    """`pinned(..., overrides=)` routes the named stage elsewhere for the block only."""
    config.resolve("claude")

    with config.pinned("ollama", overrides={"rewrite": "other-model"}):
        assert config.backend_for("rewrite").model == "other-model"
        assert config.backend_for("rewrite").origin == "ollama"
        assert config.backend_for("extract").model == config.OLLAMA_MODEL

    assert config._PINNED.get() is None
    assert config.backend_for("rewrite").provider == "anthropic"


def test_extract_runs_follows_the_extract_backend(monkeypatch):
    monkeypatch.setattr(config, "_EXTRACT_RUNS_PINNED", False)
    with config.pinned("anthropic:claude-x"):
        assert config.extract_runs(None) == 1
        assert config.extract_runs(0) == 1
        assert config.extract_runs(5) == 5
    with config.pinned("ollama:llama3"):
        assert config.extract_runs(None) == config.EXTRACT_CONSENSUS_RUNS
    monkeypatch.setattr(config, "_EXTRACT_RUNS_PINNED", True)
    monkeypatch.setattr(config, "EXTRACT_CONSENSUS_RUNS", 2)
    with config.pinned("anthropic:claude-x"):
        assert config.extract_runs(None) == 2


# --------------------------------------------------------------------------------------
# Ollama Cloud: which backends need a key
# --------------------------------------------------------------------------------------


def _keys(monkeypatch, **present: str) -> None:
    """Make `config.credential` see exactly these keys and nothing else."""
    monkeypatch.setattr(config, "credential", lambda name: present.get(name, ""))


@pytest.mark.parametrize(
    ("url", "cloud"),
    [
        ("https://ollama.com/v1", True),
        ("https://OLLAMA.com/v1/", True),
        ("http://localhost:11434/v1", False),
        ("http://gpu-box:11434/v1", False),
        ("http://host.docker.internal:11434/v1", False),
        ("https://generativelanguage.googleapis.com/v1beta/openai", False),
        (None, False),
        ("", False),
    ],
)
def test_is_ollama_cloud_matches_the_cloud_host_only(url, cloud):
    assert config.is_ollama_cloud(url) is cloud


def test_requires_key_for_gemini_and_ollama_cloud_but_not_local_ollama():
    assert config.requires_key("gemini", config.GEMINI_BASE_URL)
    assert config.requires_key("ollama", "https://ollama.com/v1")
    assert not config.requires_key("ollama", "http://localhost:11434/v1")
    # A self-hosted server on a LAN hostname is remote by `is_local_url`, yet keyless.
    assert not config.requires_key("ollama", "http://gpu-box:11434/v1")
    assert not config.requires_key("lmstudio", "https://ollama.com/v1")


def test_ollama_cloud_prefers_its_own_key_over_llm_api_key():
    """`LLM_API_KEY` may belong to another custom server; it must not reach ollama.com."""
    assert config.api_key_env_for("ollama", "https://ollama.com/v1") == (
        "OLLAMA_API_KEY",
        "LLM_API_KEY",
    )
    assert config.api_key_env_for("ollama", "http://localhost:11434/v1") == (
        "LLM_API_KEY",
        "OLLAMA_API_KEY",
    )
    assert config.api_key_env_for("ollama") == ("LLM_API_KEY", "OLLAMA_API_KEY")


def test_ollama_cloud_profile_without_a_key_is_one_gap_naming_it(monkeypatch):
    _keys(monkeypatch)
    gaps = config.credential_gaps("ollama-cloud")
    assert len(gaps) == 1
    assert "OLLAMA_API_KEY" in gaps[0] and "Ollama Cloud" in gaps[0]


def test_ollama_cloud_profile_with_a_key_has_no_gap(monkeypatch):
    _keys(monkeypatch, OLLAMA_API_KEY="sk-test")
    assert config.credential_gaps("ollama-cloud") == []
    _keys(monkeypatch, LLM_API_KEY="sk-test")
    assert config.credential_gaps("ollama-cloud") == []


def test_local_ollama_needs_no_key(monkeypatch):
    _keys(monkeypatch)
    assert config.credential_gaps("ollama") == []
    assert config.credential_gaps("hybrid") == []


def test_ollama_profile_pointed_at_the_cloud_by_env_needs_the_key(monkeypatch):
    """The older `.env` route (`OLLAMA_BASE_URL=https://ollama.com/v1`) is caught too."""
    _keys(monkeypatch)
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "https://ollama.com/v1")
    gaps = config.credential_gaps("ollama")
    assert len(gaps) == 1 and "Ollama Cloud" in gaps[0]


def test_ollama_cloud_profile_routes_every_stage_to_the_cloud():
    try:
        backends = config.resolve("ollama-cloud")
        for purpose in config.PURPOSES:
            backend = backends[purpose]
            assert backend.origin == "ollama"
            assert backend.provider == "openai"
            assert backend.base_url == config.OLLAMA_CLOUD_BASE_URL
            assert backend.model == config.OLLAMA_MODEL
    finally:
        config.resolve("claude")


def test_a_bare_tag_override_keeps_the_cloud_address():
    try:
        backends = config.resolve("ollama-cloud", overrides={"rewrite": "other:cloud"})
        assert backends["rewrite"].model == "other:cloud"
        assert backends["rewrite"].base_url == config.OLLAMA_CLOUD_BASE_URL
    finally:
        config.resolve("claude")
