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


def test_slug_varies_with_the_tag_alias_table(monkeypatch):
    """Editing `TAG_ALIASES` must invalidate stored extractions, the same as a prompt edit.

    `extract` re-canonicalises every keyword through the table right before the cache
    write, so a table edit changes what a fresh extraction produces even though nothing
    else about the request changed — without this in the key, a cached extraction from
    before the edit would keep serving the pre-edit mapping forever.
    """
    text = "We need Postgres."
    before = jd._slug(text, ["postgresql"])
    monkeypatch.setitem(config.TAG_ALIASES, "pg", "postgresql")
    assert jd._slug(text, ["postgresql"]) != before


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
# Consensus voting
# --------------------------------------------------------------------------------------


class _FakeConsensusMessages:
    def __init__(self, replies, calls):
        self._replies = replies
        self._calls = calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        if not self._replies:
            raise AssertionError("model called more times than the test supplied replies")
        return _FakeResponse(self._replies.pop(0))


class _FakeConsensusClient:
    """Returns each queued `JobRequirements` in turn, recording every call's kwargs.

    The queue is shared, not copied: `llm.client_for` runs once per `extract()` call, and
    `extract_consensus` makes several — a per-client copy would silently replay the first
    reply to every run, making every "vote" identical and the test meaningless. Same trap
    documented for `rewrite_calls` in `tests/test_rewrite.py`.
    """

    def __init__(self, replies, calls):
        self.messages = _FakeConsensusMessages(replies, calls)


@pytest.fixture
def consensus_calls(monkeypatch, tmp_path):
    """Queue distinct per-run extractions; yields the recorded call kwargs list."""
    calls: list[dict] = []

    def install(*replies):
        queue = list(replies)
        monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(jd.config, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(
            jd.llm, "client_for", lambda purpose: _FakeConsensusClient(queue, calls)
        )
        return calls

    return install


def _reqs(*keywords: Keyword, title="Engineer", seniority="entry") -> JobRequirements:
    return JobRequirements(title=title, seniority=seniority, keywords=list(keywords))


def test_majority_keeps_a_keyword_seen_in_most_runs(consensus_calls):
    """A phrase 2 of 3 runs agree on survives; a one-off does not."""
    consensus_calls(
        _reqs(
            Keyword(phrase="Python", canonical="python", importance="must_have"),
            Keyword(phrase="Rust", canonical="rust", importance="nice_to_have"),
        ),
        _reqs(
            Keyword(phrase="Python", canonical="python", importance="must_have"),
        ),
        _reqs(
            Keyword(phrase="Python", canonical="python", importance="must_have"),
        ),
    )
    reqs = jd.extract_consensus("We need Python, maybe Rust.", runs=3, use_cache=False)
    phrases = {k.phrase for k in reqs.keywords}
    assert phrases == {"Python"}  # "Rust" seen in only 1 of 3 runs is dropped


def test_canonical_prefers_one_that_hits_known_tags(consensus_calls):
    """Among the canonicals runs proposed for the same phrase, a known-tag hit wins
    over a more frequent miss — this is the mechanism that recovered the real
    "multi-machine setups" -> "distributed training" match lost to canonical noise."""
    consensus_calls(
        _reqs(
            Keyword(
                phrase="multi-machine setups",
                canonical="distributed computing",
                importance="must_have",
            )
        ),
        _reqs(
            Keyword(
                phrase="multi-machine setups",
                canonical="distributed training",
                importance="must_have",
            )
        ),
        _reqs(
            Keyword(
                phrase="multi-machine setups",
                canonical="distributed computing",
                importance="must_have",
            )
        ),
    )
    reqs = jd.extract_consensus(
        "Comfortable in multi-machine setups.",
        known_tags=["distributed training"],
        runs=3,
        use_cache=False,
    )
    assert reqs.keywords[0].canonical == "distributed training"


def test_canonical_never_invents_beyond_what_a_run_proposed(consensus_calls):
    """The known-tags preference only ever picks among canonicals a run actually emitted."""
    consensus_calls(
        _reqs(Keyword(phrase="SQL", canonical="sql", importance="must_have")),
        _reqs(Keyword(phrase="SQL", canonical="sql", importance="must_have")),
        _reqs(Keyword(phrase="SQL", canonical="sql", importance="must_have")),
    )
    reqs = jd.extract_consensus(
        "SQL required.", known_tags=["postgresql", "mysql"], runs=3, use_cache=False
    )
    assert reqs.keywords[0].canonical == "sql"


def test_runs_one_delegates_to_extract(calls):
    """`runs=1` must be byte-identical to calling `extract` directly — no vote, no suffix."""
    direct = jd.extract("We need Python.", known_tags=["python"])
    consensus = jd.extract_consensus("We need Python.", known_tags=["python"], runs=1)
    assert consensus == direct
    assert len(calls) == 1  # the second call was served from `extract`'s own cache


def test_consensus_cache_key_varies_with_runs(consensus_calls, tmp_path):
    """`runs=1` and `runs=3` must write to different cache files, never colliding."""
    consensus_calls(_reqs(Keyword(phrase="Python", canonical="python", importance="must_have")))
    jd.extract_consensus("We need Python.", runs=1)
    single_run_files = set(tmp_path.glob("*.requirements.json"))

    consensus_calls(
        _reqs(Keyword(phrase="Python", canonical="python", importance="must_have")),
        _reqs(Keyword(phrase="Python", canonical="python", importance="must_have")),
        _reqs(Keyword(phrase="Python", canonical="python", importance="must_have")),
    )
    jd.extract_consensus("We need Python.", runs=3)
    all_files = set(tmp_path.glob("*.requirements.json"))

    new_files = all_files - single_run_files
    assert len(new_files) == 1
    assert "-consensus3" in new_files.pop().name


def test_consensus_result_is_cached_across_calls(consensus_calls):
    calls = consensus_calls(
        _reqs(Keyword(phrase="Python", canonical="python", importance="must_have")),
        _reqs(Keyword(phrase="Python", canonical="python", importance="must_have")),
        _reqs(Keyword(phrase="Python", canonical="python", importance="must_have")),
    )
    jd.extract_consensus("We need Python.", runs=3)
    assert len(calls) == 3

    jd.extract_consensus("We need Python.", runs=3)
    assert len(calls) == 3  # served from the consensus cache, no re-extraction


def test_verify_verbatim_passes_on_a_consensus_result(consensus_calls):
    """Consensus never rewrites `phrase`, so the verbatim guarantee still holds."""
    consensus_calls(
        _reqs(Keyword(phrase="vector databases", canonical="vector database", importance="must_have")),
        _reqs(Keyword(phrase="vector databases", canonical="vector database", importance="must_have")),
        _reqs(Keyword(phrase="vector databases", canonical="vector database", importance="must_have")),
    )
    reqs = jd.extract_consensus(
        "Experience with vector databases required.", runs=3, use_cache=False
    )
    assert jd.verify_verbatim(reqs, "Experience with vector databases required.") == []


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
