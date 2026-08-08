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
        assert config._ACTIVE == resolved

    assert config._ACTIVE == resolved


def test_pinned_invalid_profile_raises_and_leaves_no_residue():
    config.resolve("claude")

    with pytest.raises(ValueError):
        with config.pinned("not-a-real-profile"):
            pass

    assert config._PINNED.get() is None
    assert config.backend_for("extract").provider == "anthropic"
