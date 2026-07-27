"""Tests for job-description extraction.

The API call itself is not tested — it costs money and is non-deterministic. What is tested
is everything around it: the prompt the model receives, the cache key that decides whether
it is called at all, and the schema's tolerance of extractions written before a field
existed.

The client is stubbed throughout; nothing here reaches the network or needs an API key.
"""

from __future__ import annotations

import json

import pytest

from resume_tailor import config, jd
from resume_tailor.jd import JobRequirements, Keyword


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, parsed, calls):
        self._parsed = parsed
        self._calls = calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return _FakeResponse(self._parsed)


class _FakeClient:
    def __init__(self, parsed, calls):
        self.messages = _FakeMessages(parsed, calls)


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """Stub the API and redirect the extraction cache into a temp directory."""
    recorded: list[dict] = []
    parsed = JobRequirements(
        title="AI Data Solutions Intern",
        seniority="intern",
        keywords=[
            Keyword(phrase="Python", canonical="python", importance="must_have"),
            # Deliberately an alias, to prove post-extraction canonicalisation still runs.
            Keyword(phrase="LLMs", canonical="llms", importance="nice_to_have"),
        ],
        domain_notes=["Data partnerships team"],
    )
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(jd.config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    # Stubbed at the provider boundary rather than at `anthropic.Anthropic`: every backend
    # goes through `llm.client_for`, so one seam covers all of them and `_FakeClient` keeps
    # working unchanged.
    monkeypatch.setattr(jd.llm, "client_for", lambda purpose: _FakeClient(parsed, recorded))
    return recorded


# --------------------------------------------------------------------------------------
# Closed-vocabulary canonicalisation
# --------------------------------------------------------------------------------------


def test_known_tags_reach_the_prompt(calls):
    """The vocabulary is what stops the model coining canonicals that can never match."""
    jd.extract("We need Python.", known_tags=["python", "data analysis", "communication"])

    content = calls[0]["messages"][0]["content"]
    assert "<known_tags>" in content
    # Sorted, so the prompt (and therefore the cache key) is stable across tag orderings.
    assert "communication, data analysis, python" in content


def test_no_known_tags_means_no_vocabulary_block(calls):
    jd.extract("We need Python.")

    content = calls[0]["messages"][0]["content"]
    assert "<known_tags>" not in content
    assert "<job_description>" in content


def test_system_prompt_explains_how_to_use_the_vocabulary(calls):
    jd.extract("We need Python.", known_tags=["python"])
    assert "known_tags" in calls[0]["system"]


# --------------------------------------------------------------------------------------
# Cache key
# --------------------------------------------------------------------------------------


def test_slug_varies_with_the_job_description():
    assert jd._slug("posting A") != jd._slug("posting B")


def test_slug_varies_with_the_tag_vocabulary():
    """Re-tagging the master resume must not silently reuse an old extraction.

    The vocabulary steers `canonical`, so an extraction made against a different tag set is
    scored against a vocabulary that no longer exists — wrong in a way nothing would show.
    """
    text = "We need Python."
    assert jd._slug(text, ["python"]) != jd._slug(text, ["python", "sql"])
    assert jd._slug(text, None) != jd._slug(text, ["python"])


def test_slug_is_stable_across_tag_ordering():
    text = "We need Python."
    assert jd._slug(text, ["sql", "python"]) == jd._slug(text, ["python", "sql"])


def test_slug_varies_with_prompt_version(monkeypatch):
    """A prompt edit must invalidate stored extractions without anyone remembering to."""
    text = "We need Python."
    before = jd._slug(text, ["python"])
    monkeypatch.setattr(jd, "_PROMPT_VERSION", jd._PROMPT_VERSION + 1)
    assert jd._slug(text, ["python"]) != before


def test_slug_keeps_a_readable_prefix():
    assert jd._slug("Senior Python Engineer wanted").startswith("senior-python-engineer")


def test_slug_varies_with_the_backend():
    """Two models given the same posting extract differently.

    Without the backend in the key, switching models and re-running replays the previous
    model's output under the new model's name — wrong with no symptom, and it would make
    comparing backends impossible since the second run would never call anything.
    """
    text = "Senior Python Engineer"
    config.resolve("claude")
    on_claude = jd._slug(text, ["python"])
    config.resolve("ollama")
    on_ollama = jd._slug(text, ["python"])
    config.resolve("claude")

    assert on_claude != on_ollama
    assert jd._slug(text, ["python"]) == on_claude  # and stable when nothing changed


def test_cache_is_reused_and_bypassed(calls, tmp_path):
    jd.extract("We need Python.", known_tags=["python"])
    assert len(calls) == 1

    jd.extract("We need Python.", known_tags=["python"])
    assert len(calls) == 1  # served from cache

    jd.extract("We need Python.", known_tags=["python"], use_cache=False)
    assert len(calls) == 2

    # A different vocabulary is a different key, so it must re-extract.
    jd.extract("We need Python.", known_tags=["python", "sql"])
    assert len(calls) == 3


# --------------------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------------------


def test_kind_defaults_to_technical_when_absent():
    """Extractions cached before `kind` existed must still load, at full must-have weight."""
    raw = json.dumps(
        {
            "title": "ML Engineer",
            "seniority": "entry",
            "keywords": [
                {"phrase": "Python", "canonical": "python", "importance": "must_have"}
            ],
            "domain_notes": [],
        }
    )
    reqs = JobRequirements.model_validate_json(raw)
    assert reqs.keywords[0].kind == "technical"


def test_kind_round_trips():
    reqs = JobRequirements(
        title="T",
        seniority="intern",
        keywords=[
            Keyword(
                phrase="communication",
                canonical="communication",
                importance="must_have",
                kind="soft",
            )
        ],
    )
    assert JobRequirements.model_validate_json(reqs.model_dump_json()).keywords[0].kind == "soft"


def test_canonical_still_passes_through_tag_aliases(calls):
    """The alias table stays in the path — it catches what the model spells differently."""
    reqs = jd.extract("We need LLMs.", known_tags=["llm"])
    assert [k.canonical for k in reqs.keywords] == ["python", "llm"]


# --------------------------------------------------------------------------------------
# Verbatim guarantee
# --------------------------------------------------------------------------------------


def test_verify_verbatim_accepts_a_real_quote():
    reqs = JobRequirements(
        title="T",
        seniority="entry",
        keywords=[Keyword(phrase="vector databases", canonical="vector database",
                          importance="must_have")],
    )
    assert jd.verify_verbatim(reqs, "Experience with vector databases required.") == []


def test_verify_verbatim_catches_a_paraphrase():
    reqs = JobRequirements(
        title="T",
        seniority="entry",
        keywords=[Keyword(phrase="vector stores", canonical="vector database",
                          importance="must_have")],
    )
    assert jd.verify_verbatim(reqs, "Experience with vector databases required.") == [
        "vector stores"
    ]


def test_empty_job_description_is_rejected():
    with pytest.raises(ValueError):
        jd.extract("   ")
