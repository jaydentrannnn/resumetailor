"""Tests for the provider boundary.

The point of these is the *non-frontier* path. Anthropic's SDK guarantees a schema-valid
object; an arbitrary OpenAI-compatible endpoint guarantees nothing, and the behaviours that
matter were measured against a real one (`nemotron-3-super:cloud`): it accepts
`response_format` and ignores it, answering HTTP 200 with markdown prose. So the cases below
are mostly about recovering from a *successful* response that is not what was asked for.

No network: `httpx.post` is replaced with a recorder that returns queued responses.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from resume_tailor import config, llm


class Sample(BaseModel):
    """Small stand-in for JobRequirements. `note` has a default, which is what makes it
    useful: `_strictify` has to promote defaulted fields into `required`."""

    title: str
    note: str = "unset"


VALID = {"title": "Engineer", "note": "ok"}


class _Recorder:
    """Stands in for `httpx.post`, returning queued responses and recording payloads."""

    def __init__(self, *responses: httpx.Response):
        self._queue = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, url, *, headers=None, json=None, timeout=None):
        self.payloads.append(json)
        self.url = url
        self.headers = headers
        return self._queue.pop(0) if self._queue else _completion(VALID)

    @property
    def calls(self) -> int:
        return len(self.payloads)


def _completion(content, *, finish="stop", status=200) -> httpx.Response:
    body = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        status,
        json={"choices": [{"message": {"content": body}, "finish_reason": finish}]},
    )


@pytest.fixture
def client(monkeypatch):
    # `_LEARNED_CEILING` is module-global (see llm.py) so a value recorded by one test
    # would otherwise leak into the next and turn a call-count assertion flaky for reasons
    # that have nothing to do with what that test is checking.
    llm._LEARNED_CEILING.clear()

    def _make(*responses, structured_mode="prompt", max_token_cap=0):
        recorder = _Recorder(*responses)
        monkeypatch.setattr(llm.httpx, "post", recorder)
        c = llm._OpenAICompatClient(
            base_url="http://localhost:11434/v1",
            api_key="",
            timeout=5,
            structured_mode=structured_mode,
            max_token_cap=max_token_cap,
        )
        c.recorder = recorder
        return c

    return _make


def _request(c):
    return c.request(
        model="nemotron-3-super:cloud",
        max_tokens=1000,
        system="You extract things.",
        user="<job_description>x</job_description>",
        output_format=Sample,
    )


# --------------------------------------------------------------------------------------
# Spec parsing — the first-colon rule
# --------------------------------------------------------------------------------------


def test_provider_spec_splits_on_the_first_colon_only():
    """Ollama tags embed colons, and the default model is one of them.

    `ollama:nemotron-3-super:cloud` splitting anywhere else yields model 'cloud', which
    404s. This is the primary use case, not an edge case.
    """
    assert config.parse_spec("ollama:nemotron-3-super:cloud") == (
        "ollama",
        "nemotron-3-super:cloud",
        None,
    )


def test_bare_model_name_keeps_its_colons_and_infers_a_provider():
    """A name whose first segment is not a known provider is entirely a model name."""
    assert config.parse_spec("nemotron-3-super:cloud") == (
        "ollama",
        "nemotron-3-super:cloud",
        None,
    )
    assert config.parse_spec("claude-sonnet-5") == ("anthropic", "claude-sonnet-5", None)


def test_spec_parses_a_base_url_suffix():
    assert config.parse_spec("openai:glm-4@https://host/v1") == (
        "openai",
        "glm-4",
        "https://host/v1",
    )


def test_lmstudio_spec_parses_and_remaps_to_openai_compat():
    """`lmstudio` is an alias for the OpenAI-compatible client at LMSTUDIO_BASE_URL."""
    assert config.parse_spec("lmstudio:foo-bar") == ("lmstudio", "foo-bar", None)
    backends = config.resolve("lmstudio")
    try:
        for purpose in config.PURPOSES:
            b = backends[purpose]
            assert b.provider == "openai"
            assert b.model == config.LMSTUDIO_MODEL
            assert b.base_url == config.LMSTUDIO_BASE_URL
    finally:
        config.resolve("claude")


def test_bare_override_under_lmstudio_stays_on_lmstudio():
    """UI model ids like google/gemma-4-12b must not silently route to Ollama :11434."""
    backends = config.resolve(
        "lmstudio",
        overrides={
            "rewrite": "google/gemma-4-12b",
            "expand": "google/gemma-4-12b",
        },
    )
    try:
        for purpose in ("rewrite", "expand"):
            b = backends[purpose]
            assert b.provider == "openai"
            assert b.model == "google/gemma-4-12b"
            assert b.base_url == config.LMSTUDIO_BASE_URL
        # Un-overridden stages still use the profile default model.
        assert backends["extract"].model == config.LMSTUDIO_MODEL
        assert backends["extract"].base_url == config.LMSTUDIO_BASE_URL
    finally:
        config.resolve("claude")


def test_gemini_spec_parses_and_remaps_to_openai_compat():
    """`gemini` is a third alias for the OpenAI-compatible client, at GEMINI_BASE_URL."""
    assert config.parse_spec("gemini:foo-bar") == ("gemini", "foo-bar", None)
    backends = config.resolve("gemini")
    try:
        for purpose in config.PURPOSES:
            b = backends[purpose]
            assert b.provider == "openai"
            assert b.origin == "gemini"
            assert b.model == config.GEMINI_MODEL
            assert b.base_url == config.GEMINI_BASE_URL
    finally:
        config.resolve("claude")


def test_bare_override_under_gemini_stays_on_gemini():
    """Without this, a bare id typed into the UI's Rewrite field under `gemini` would
    fall through `parse_spec`'s bare-name inference and 404 against Ollama's :11434."""
    backends = config.resolve("gemini", overrides={"rewrite": "gemini-3.5-pro"})
    try:
        b = backends["rewrite"]
        assert b.provider == "openai"
        assert b.origin == "gemini"
        assert b.model == "gemini-3.5-pro"
        assert b.base_url == config.GEMINI_BASE_URL
    finally:
        config.resolve("claude")


def test_backend_origin_defaults_empty_for_hand_built_backends():
    """The NamedTuple append (`origin`) must not break existing kwarg-only construction."""
    b = config.Backend(provider="openai", model="x", base_url=None, effort="low")
    assert b.origin == ""


def test_gemini_and_ollama_fingerprints_differ_for_the_same_model():
    """After the openai remap both share provider=='openai'; origin is what still tells
    a Gemini cache entry apart from an Ollama one for the same model string."""
    try:
        config.resolve("gemini", overrides={"extract": "gemini:shared-name"})
        gemini_fp = config.fingerprint("extract")
        config.resolve("ollama", overrides={"extract": "ollama:shared-name"})
        ollama_fp = config.fingerprint("extract")
        assert gemini_fp != ollama_fp
    finally:
        config.resolve("claude")


def test_structured_mode_defaults_to_schema_for_gemini_only():
    try:
        config.resolve("gemini")
        assert config.structured_mode_for("extract") == "schema"
        config.resolve("ollama")
        assert config.structured_mode_for("extract") == "prompt"
    finally:
        config.resolve("claude")


def test_explicit_structured_mode_env_wins_over_the_provider_default(monkeypatch):
    monkeypatch.setattr(config, "_STRUCTURED_MODE_ENV", "prompt")
    try:
        config.resolve("gemini")
        assert config.structured_mode_for("extract") == "prompt"
    finally:
        config.resolve("claude")


def test_api_key_for_prefers_gemini_key_then_google_then_llm(monkeypatch):
    assert config.api_key_env_for("gemini") == (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "LLM_API_KEY",
    )
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY", "OLLAMA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    try:
        config.resolve("gemini")
        assert config.api_key_for("extract") == ""

        monkeypatch.setenv("LLM_API_KEY", "llm-key")
        assert config.api_key_for("extract") == "llm-key"

        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
        assert config.api_key_for("extract") == "google-key"

        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        assert config.api_key_for("extract") == "gemini-key"
    finally:
        config.resolve("claude")


def test_provider_stages_generalises_and_ollama_stages_still_wraps_it():
    assert config.provider_stages("gemini", "gemini") == config.PURPOSES
    assert config.provider_stages("ollama", "gemini") == ()
    # ollama_stages is a thin wrapper — existing callers (web/jobs.py, web/app.py) keep
    # working unchanged.
    assert config.ollama_stages("hybrid") == config.provider_stages("hybrid", "ollama")


def test_credential_gaps_does_not_touch_active_routing(monkeypatch):
    """Pure: a web-layer preflight call must never resolve, since `_ACTIVE` is
    process-global and a job could be mid-run on another thread."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config.resolve("claude")
    gaps = config.credential_gaps("gemini")
    assert "GEMINI_API_KEY" in gaps[0]
    assert config.provider_for("extract") == "anthropic"  # unchanged by the call above


def test_credential_gaps_is_empty_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert config.credential_gaps("gemini") == []


def test_credential_gaps_ignores_profiles_with_no_key_requirement():
    assert config.credential_gaps("ollama") == []
    assert config.credential_gaps("claude") == []


def test_credential_gaps_on_an_unparseable_spec_returns_no_gaps():
    """Rejecting a bad spec stays `resolve`'s job (it raises `ValueError`); this one
    just reports no gaps rather than raising."""
    assert config.credential_gaps("") == []


def test_bare_override_under_hybrid_rewrite_still_defaults_to_ollama():
    """Hybrid rewrite is Anthropic; a bare local id keeps the historical Ollama default."""
    backends = config.resolve("hybrid", overrides={"rewrite": "google/gemma-4-12b"})
    try:
        b = backends["rewrite"]
        assert b.provider == "openai"
        assert b.model == "google/gemma-4-12b"
        assert b.base_url == config.OLLAMA_BASE_URL
    finally:
        config.resolve("claude")


def test_profiles_route_stages_independently():
    """`hybrid` exists so the risky stage can differ from the cheap ones."""
    try:
        backends = config.resolve("hybrid")
        assert backends["extract"].provider == "openai"
        assert backends["rewrite"].provider == "anthropic"
        assert config.fingerprint("extract") != config.fingerprint("rewrite")
    finally:
        # `_ACTIVE` is process-wide, so leaving 'hybrid' resolved leaks into later tests.
        config.resolve("claude")


def test_ollama_stages_excludes_hybrids_anthropic_rewrite():
    """The UI tag field must repoint Ollama stages only — never hybrid's Claude rewrite."""
    assert config.ollama_stages("ollama") == config.PURPOSES
    assert set(config.ollama_stages("hybrid")) == {"extract", "score", "expand", "facets"}
    assert config.ollama_stages("claude") == ()
    assert config.ollama_stages("lmstudio") == ()


def test_ollama_stages_handles_raw_specs_and_junk():
    """`model` is free text, so a spec (or a typo) must not raise on the job path."""
    assert config.ollama_stages("ollama:gemma4:cloud") == config.PURPOSES
    assert config.ollama_stages("claude-sonnet-5") == ()
    assert config.ollama_stages("") == ()


def test_ollama_tag_override_repoints_every_ollama_stage_under_hybrid():
    """What the web UI's Ollama-model field expands into, end to end through resolve."""
    overrides = dict.fromkeys(config.ollama_stages("hybrid"), "gemma4")
    backends = config.resolve("hybrid", overrides=overrides)
    try:
        for purpose in ("extract", "score", "expand", "facets"):
            assert backends[purpose].model == "gemma4"
            assert backends[purpose].base_url == config.OLLAMA_BASE_URL
        # The stage the tag must not touch.
        assert backends["rewrite"].provider == "anthropic"
        assert backends["rewrite"].model == config.MODEL
    finally:
        config.resolve("claude")


def test_unknown_profile_names_the_valid_ones():
    with pytest.raises(ValueError, match="claude"):
        config.resolve("gpt5-turbo-ultra")


def test_anthropic_stages_are_clamped_below_the_nonstreaming_ceiling():
    """A MAX_TOKENS above Anthropic's cap must not reach an Anthropic call.

    The SDK refuses `max_tokens > 21_333` on a non-streaming request client-side, so an
    unclamped value fails every Claude run on its first call rather than degrading.
    """
    try:
        config.resolve("hybrid")
        assert (
            config.max_tokens_for("rewrite") <= config.ANTHROPIC_NONSTREAMING_MAX_TOKENS
        )
        # Same run, different ceilings: only the Anthropic half is capped.
        assert config.max_tokens_for("extract") == config.MAX_TOKENS
    finally:
        # `_ACTIVE` is process-wide, so leaving 'hybrid' resolved leaks into later tests.
        config.resolve("claude")


# --------------------------------------------------------------------------------------
# JSON recovery
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"title": "Engineer"}',
        '```json\n{"title": "Engineer"}\n```',
        'Here is the JSON:\n\n{"title": "Engineer"}\n\nLet me know!',
    ],
)
def test_extract_json_object_recovers_from_fences_and_preamble(raw):
    assert json.loads(llm._extract_json_object(raw))["title"] == "Engineer"


def test_extract_json_object_is_not_confused_by_braces_inside_strings():
    """Depth tracking has to skip string literals, or the object closes early."""
    raw = '{"title": "a } brace", "note": "ok"}'
    assert json.loads(llm._extract_json_object(raw))["title"] == "a } brace"


def test_extract_json_object_returns_input_when_there_is_no_object():
    """So the caller's Pydantic error names the real problem, not a slicing artefact."""
    assert llm._extract_json_object("I cannot help with that.") == "I cannot help with that."


def test_strictify_promotes_defaulted_fields_to_required():
    """Pydantic omits defaulted fields from `required`; OpenAI strict mode rejects that."""
    strict = llm._strictify(Sample.model_json_schema())
    assert set(strict["required"]) == {"title", "note"}
    assert strict["additionalProperties"] is False


# --------------------------------------------------------------------------------------
# The request path
# --------------------------------------------------------------------------------------


def test_schema_goes_in_the_system_prompt_on_the_default_path(client):
    """The measured-working configuration: schema in the prompt, json_object as a hint."""
    c = client(_completion(VALID))
    _request(c)

    payload = c.recorder.payloads[0]
    assert payload["response_format"] == {"type": "json_object"}
    assert "json_schema" not in json.dumps(payload["response_format"])
    system = payload["messages"][0]["content"]
    assert '"title"' in system and "JSON Schema" in system


def test_schema_mode_sends_json_schema_instead(client):
    """Opt-in for endpoints that genuinely constrain decoding."""
    c = client(_completion(VALID), structured_mode="schema")
    _request(c)

    fmt = c.recorder.payloads[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True


def test_max_completion_tokens_is_not_sent(client):
    """Ollama ignores unknown fields; stricter servers reject them."""
    c = client(_completion(VALID))
    _request(c)
    assert "max_completion_tokens" not in c.recorder.payloads[0]


def test_prose_in_a_200_triggers_the_repair_retry(client):
    """The measured failure mode.

    Ollama Cloud accepts `response_format` and ignores it, so non-compliance arrives as a
    successful response carrying markdown. A design that escalated on status code alone
    would sail past every fallback into a hard failure.
    """
    c = client(
        _completion("### Requirements\n\n- **Title**: Engineer"),
        _completion(VALID),
    )
    result = _request(c)

    assert result.parsed_output.title == "Engineer"
    assert c.recorder.calls == 2
    assert "did not match" in c.recorder.payloads[1]["messages"][-1]["content"]


def test_a_400_on_response_format_retries_without_it(client):
    """Some endpoints reject the field outright; the schema is already in the prompt.

    Default `prompt` mode's ladder is `[json_object, None]` — the same one-step drop this
    behaviour always had, so this passes unchanged by the graded-ladder rewrite.
    """
    c = client(httpx.Response(400, text="unknown parameter response_format"), _completion(VALID))
    result = _request(c)

    assert result.parsed_output.title == "Engineer"
    assert "response_format" not in c.recorder.payloads[1]


def test_schema_mode_downgrades_to_json_object_before_dropping_the_format(client):
    """`schema` mode's ladder has a middle rung `prompt` mode doesn't: a rejection of a
    strict json_schema should try plain json_object before giving up on structure
    entirely — dropping straight to nothing would be strictly worse than the `prompt`
    default it started from."""
    c = client(
        httpx.Response(400, text="bad schema"),
        httpx.Response(400, text="still bad"),
        _completion(VALID),
        structured_mode="schema",
    )
    result = _request(c)

    assert result.parsed_output.title == "Engineer"
    assert c.recorder.payloads[0]["response_format"]["type"] == "json_schema"
    assert c.recorder.payloads[1]["response_format"] == {"type": "json_object"}
    assert "response_format" not in c.recorder.payloads[2]


def test_the_format_ladder_does_not_retry_past_its_last_rung(client):
    """Bounded: once the ladder is exhausted, a further 400 is a real failure, not
    something to keep retrying against a metered quota."""
    c = client(
        httpx.Response(400, text="bad"),
        httpx.Response(400, text="bad"),
        httpx.Response(400, text="bad"),
        httpx.Response(400, text="bad"),
        structured_mode="schema",
    )
    with pytest.raises(llm.LLMError, match="400"):
        _request(c)
    assert c.recorder.calls == 3  # 3 rungs: json_schema, json_object, none


def test_repair_is_attempted_exactly_once_then_raises(client):
    """A model that cannot produce the schema twice will not on the third go, and each
    attempt costs quota against a free tier."""
    c = client(_completion("nope"), _completion("still nope"))
    with pytest.raises(llm.LLMError, match="repair attempt"):
        _request(c)
    assert c.recorder.calls == 2


def test_truncation_is_reported_rather_than_retried_when_already_at_the_cap(client):
    """No `max_token_cap` (the direct-construction default of 0) means no headroom to
    escalate into — cap collapses to the starting request, so this still hard-fails
    exactly as it always did. Reasoning tokens come out of max_tokens, so this is a real
    failure for a verbose model with nowhere left to grow."""
    c = client(_completion('{"title": "Engi', finish="length"))
    with pytest.raises(llm.LLMError, match="ceiling"):
        _request(c)
    assert c.recorder.calls == 1


def test_truncation_escalates_the_ceiling_and_succeeds(client):
    """The headline behaviour: given headroom, a truncated response is not a dead end —
    the ceiling doubles and the same request is retried at the higher value."""
    c = client(
        _completion('{"title": "Engi', finish="length"),
        _completion(VALID),
        max_token_cap=64_000,
    )
    result = _request(c)

    assert result.parsed_output.title == "Engineer"
    assert c.recorder.payloads[0]["max_tokens"] == 1000
    assert c.recorder.payloads[1]["max_tokens"] == 2000


def test_escalation_stops_at_the_provider_cap_and_reports_it(client):
    """Escalation is bounded by the cap, not just by MAX_TOKEN_ESCALATIONS — a model
    verbose enough to blow through the cap itself still gets a clean failure."""
    c = client(
        _completion('{"title": "Engi', finish="length"),
        _completion('{"title": "Engi', finish="length"),
        max_token_cap=1500,
    )
    with pytest.raises(llm.LLMError, match="ceiling"):
        _request(c)
    assert c.recorder.payloads[0]["max_tokens"] == 1000
    assert c.recorder.payloads[1]["max_tokens"] == 1500  # 1000*2 clamped to the 1500 cap
    assert c.recorder.calls == 2


def test_a_truncated_response_that_parses_is_not_escalated(client):
    """A `finish == 'length'` response that nonetheless satisfies the schema is not
    escalated — escalating a call that already succeeded would double the cost of a
    *working* run, the exact thing that makes this feature safe to turn on by default."""
    c = client(_completion(VALID, finish="length"), max_token_cap=64_000)
    result = _request(c)

    assert result.parsed_output.title == "Engineer"
    assert result.stop_reason == "length"
    assert c.recorder.calls == 1


def test_the_learned_ceiling_is_reused_by_a_later_call(client, monkeypatch):
    """A rewrite-heavy run makes several calls to the same model; the second one should
    not have to rediscover a ceiling the first one already found the hard way."""
    c1 = client(
        _completion('{"title": "Engi', finish="length"),
        _completion(VALID),
        max_token_cap=64_000,
    )
    _request(c1)
    assert llm._LEARNED_CEILING[("http://localhost:11434/v1", "nemotron-3-super:cloud")] == 2000

    # A second, independent client against the same (base_url, model) starts already
    # escalated — it does not need `_LEARNED_CEILING.clear()` to have skipped happening.
    recorder2 = _Recorder(_completion(VALID))
    monkeypatch.setattr(llm.httpx, "post", recorder2)
    c2 = llm._OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        api_key="",
        timeout=5,
        structured_mode="prompt",
        max_token_cap=64_000,
    )
    _request(c2)
    assert recorder2.payloads[0]["max_tokens"] == 2000


def test_worst_case_round_trips_are_bounded(client):
    """Ladder retries + escalation retries + one repair, all firing in the same call,
    must still terminate rather than retry forever against a metered quota."""
    c = client(
        httpx.Response(400, text="bad"),  # rung 0 -> 1 (schema -> json_object)
        httpx.Response(400, text="bad"),  # rung 1 -> 2 (json_object -> none)
        _completion('{"title": "Engi', finish="length"),  # truncated, escalate
        _completion('{"title": "Engi', finish="length"),  # truncated again, escalate
        _completion("nope"),  # parses status-wise but fails validation -> repair
        _completion("still nope"),  # repair also fails -> raise
        structured_mode="schema",
        max_token_cap=10_000,
    )
    with pytest.raises(llm.LLMError, match="repair attempt"):
        _request(c)
    assert c.recorder.calls <= 6


def test_a_404_explains_that_the_model_is_not_available(client):
    """The most likely first error on this setup."""
    c = client(httpx.Response(404, text='{"error":{"message":"model not found"}}'))
    with pytest.raises(llm.LLMError, match="ollama pull"):
        _request(c)


def test_an_unreachable_daemon_says_so(client, monkeypatch):
    c = client()

    def boom(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(llm.httpx, "post", boom)
    with pytest.raises(llm.LLMError, match="Could not reach.*11434"):
        _request(c)


def test_no_authorization_header_when_there_is_no_key(client):
    """Ollama authenticates through the daemon, and some servers reject a bearer header."""
    c = client(_completion(VALID))
    _request(c)
    assert "Authorization" not in c.recorder.headers


# --------------------------------------------------------------------------------------
# client_for
# --------------------------------------------------------------------------------------


def test_client_for_rejects_an_openai_provider_with_no_base_url(monkeypatch):
    monkeypatch.setitem(
        config._ACTIVE,
        "extract",
        config.Backend(provider="openai", model="x", base_url=None, effort="low"),
    )
    with pytest.raises(llm.LLMError, match="base URL"):
        llm.client_for("extract")


def test_client_for_rejects_an_unknown_provider(monkeypatch):
    monkeypatch.setitem(
        config._ACTIVE,
        "extract",
        config.Backend(provider="cohere", model="x", base_url=None, effort="low"),
    )
    with pytest.raises(llm.LLMError, match="Unknown provider"):
        llm.client_for("extract")


def test_llm_error_is_catchable_as_runtime_error():
    """`tailor.py`'s existing handlers catch RuntimeError; this keeps them working."""
    assert issubclass(llm.LLMError, RuntimeError)
