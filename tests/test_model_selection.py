"""Shared app routing, connection snapshots and independent custom credentials."""

from __future__ import annotations

import asyncio
import json

import anthropic
import httpx
import httpx2
import pytest
from pydantic import BaseModel, ValidationError

from resume_tailor import config
from resume_tailor.infra import llm, model_queue, secret_store
from resume_tailor.model_selection import AiModels, ModelSelection, migrated_models
from resume_tailor.web.job_routing import model_routing, pinned_role
from resume_tailor.web.schemas import JobSettings


def _custom(url="http://localhost:9876/v1", api_format="openai"):
    return ModelSelection(
        provider="custom", model_name="test-model", base_url=url, api_format=api_format
    )


def test_migration_retains_light_heavy_and_only_different_stage_routes():
    models = migrated_models(
        {
            "model": "ollama",
            "model_name": "writer",
            "skills_model": "selector",
            "apply": {"model_provider": "gemini", "model_name": "filler"},
        }
    )
    assert models.light.model_name == "writer"
    assert models.heavy == ModelSelection(provider="gemini", model_name="filler")
    assert set(models.legacy_light_overrides) == {"skills"}
    assert config.parse_spec(models.legacy_light_overrides["skills"]) == (
        "ollama",
        "selector",
        config.OLLAMA_BASE_URL,
    )


def test_simple_migration_has_no_spurious_effort_overrides():
    assert migrated_models({"model": "ollama"}).legacy_light_overrides == {}


def test_legacy_remote_openai_server_becomes_custom():
    models = migrated_models({"model": "openai:writer@https://proxy.example/v1"})
    assert models.light.provider == "custom"
    assert models.light.base_url == "https://proxy.example/v1"
    assert models.light.api_format == "openai"


def test_migration_preserves_nested_custom_heavy_selection():
    heavy = _custom(api_format="anthropic")
    models = migrated_models({"model": "ollama", "apply": {"model_selection": heavy.model_dump()}})
    assert models.heavy == heavy


def test_tailoring_and_heavy_answer_routing_are_independent():
    settings = JobSettings(
        ai_models=AiModels(
            light=ModelSelection(model_name="writer"),
            heavy=ModelSelection(provider="gemini", model_name="filler"),
        )
    )
    profile, overrides, effort = model_routing(settings)
    with config.pinned(profile, overrides=overrides, effort=effort):
        assert all(config.model_for(p) == "writer" for p in config.PURPOSES)
    with pinned_role("heavy", settings):
        assert config.model_for("answer") == "filler"
        assert config.backend_for("answer").origin == "gemini"
    assert settings.apply.model_selection == settings.ai_models.heavy


def test_incomplete_heavy_draft_does_not_block_light():
    settings = JobSettings(
        ai_models=AiModels(
            light=ModelSelection(model_name="writer"), heavy=ModelSelection(provider="custom")
        )
    )
    with pinned_role("light", settings):
        assert config.model_for("rewrite") == "writer"
    with pytest.raises(ValueError, match="Custom server needs"), pinned_role("heavy", settings):
        pass


def test_custom_credentials_are_bound_to_endpoint_format_and_role(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "unrelated-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "another-unrelated-key")
    first = _custom()
    spec = first.spec("light")
    secret_store.set(f"api_key:{spec['credential_ref']}", "first-key")
    with config.pinned(spec):
        assert config.api_key_for("rewrite") == "first-key"
    for selection, role in [
        (_custom("http://localhost:9877/v1"), "light"),
        (first, "heavy"),
        (_custom(api_format="anthropic"), "light"),
    ]:
        with config.pinned(selection.spec(role)):
            assert config.api_key_for("rewrite") == ""


def test_snapshot_restores_url_format_effort_and_secret_reference():
    selection = _custom(api_format="anthropic")
    with config.pinned(selection.spec("heavy"), effort="high"):
        before = config.backend_for("answer")
        snapshot = config.backend_specs_snapshot()
    assert "credential_ref" in json.dumps(snapshot)
    with config.pinned_specs(json.loads(json.dumps(snapshot))):
        assert config.backend_for("answer") == before


def test_old_string_snapshots_remain_supported():
    with config.pinned_specs(dict.fromkeys(config.PURPOSES, "ollama:old-model")):
        assert config.model_for("expand") == "old-model"


def test_cache_identity_changes_with_endpoint_and_api_format():
    identities = []
    for selection in [
        _custom(),
        _custom("http://localhost:9877/v1"),
        _custom(api_format="anthropic"),
    ]:
        with config.pinned(selection.spec("light")):
            identities.append(config.fingerprint("rewrite"))
    assert len(set(identities)) == 3


def test_built_in_cache_identity_is_unchanged_so_upgrades_keep_caches():
    with config.pinned("ollama:gemma4:cloud@https://ollama.com/v1", effort="low"):
        assert config.fingerprint("score") == "ollama|gemma4:cloud|low"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://server",
        "https://user:pass@server",
        "https://server?key=secret",
        "https://server#secret",
    ],
)
def test_server_url_cannot_embed_credentials(url):
    with pytest.raises(ValidationError):
        _custom(url)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_anthropic_custom_client_uses_own_url_and_key(monkeypatch, asynchronous):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(anthropic, "AsyncAnthropic" if asynchronous else "Anthropic", fake_client)
    selection = _custom("https://proxy.example/api", "anthropic")
    spec = selection.spec("heavy")
    secret_store.set(f"api_key:{spec['credential_ref']}", "proxy-key")
    with config.pinned(spec):
        (llm.async_client_for if asynchronous else llm.client_for)("answer")
    assert captured["base_url"] == "https://proxy.example/api"
    assert captured["api_key"] == "proxy-key"
    assert captured["auth_token"] is None
    if asynchronous:
        asyncio.run(captured["http_client"].aclose())
    else:
        captured["http_client"].close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("with_key", [False, True])
def test_real_anthropic_sdk_custom_connection_and_auth(monkeypatch, asynchronous, with_key):
    """Exercise the installed SDK's request, parsing and scheduled transport, without network."""

    class Result(BaseModel):
        ok: bool

    seen = []

    def send(_transport, request):
        seen.append(request)
        return httpx2.Response(
            200,
            request=request,
            json={
                "id": "message-test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [{"type": "text", "text": '{"ok":true}'}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    async def async_send(transport, request):
        return send(transport, request)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "unrelated-provider-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "unrelated-provider-token")
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", send)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", async_send)
    selection = _custom("https://proxy.example/api", "anthropic")
    spec = selection.spec("heavy")
    if with_key:
        secret_store.set(f"api_key:{spec['credential_ref']}", "proxy-test-key")
    kwargs = dict(
        model="test-model",
        max_tokens=128,
        system="Return JSON",
        messages=[{"role": "user", "content": "Test"}],
        output_format=Result,
    )
    with config.pinned(spec):
        if asynchronous:

            async def run():
                async with llm.async_client_for("answer") as client:
                    return await client.messages.parse(**kwargs)

            response = asyncio.run(run())
        else:
            with llm.client_for("answer") as client:
                response = client.messages.parse(**kwargs)
    assert response.parsed_output.ok
    assert str(seen[0].url) == "https://proxy.example/api/v1/messages"
    assert seen[0].headers.get("x-api-key") == ("proxy-test-key" if with_key else None)
    assert "authorization" not in seen[0].headers
    assert model_queue.queue.status()["endpoints"][0]["active"] == 0


@pytest.mark.parametrize("asynchronous", [False, True])
def test_openai_client_requires_its_key_and_uses_official_endpoint(monkeypatch, asynchronous):
    selection = ModelSelection(provider="openai", model_name="test-model")
    with config.pinned(selection.spec("light")):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(llm.LLMError, match="OpenAI needs an API key"):
            (llm.async_client_for if asynchronous else llm.client_for)("rewrite")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        client = (llm.async_client_for if asynchronous else llm.client_for)("rewrite")
        assert client.base_url == "https://api.openai.com/v1"
        assert client.api_key == "test-key"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("official", [False, True])
def test_openai_payload_and_token_escalation_preserve_compatible_servers(
    monkeypatch, asynchronous, official
):
    class Result(BaseModel):
        ok: bool

    captured = []

    def post(payload, *_args):
        captured.append(payload)
        content, finish = ('{"ok":', "length") if len(captured) == 1 else ('{"ok":true}', "stop")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": content}, "finish_reason": finish},
                ]
            },
        )

    async def async_post(payload, *_args):
        return post(payload)

    selection = ModelSelection(provider="openai", model_name="reasoner") if official else _custom()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm._LEARNED_CEILING.clear()
    with config.pinned(selection.spec("light")):
        client = (llm.async_client_for if asynchronous else llm.client_for)("rewrite")
        client.max_token_cap = 200
        monkeypatch.setattr(client, "_post", async_post if asynchronous else post)
        kwargs = dict(
            model="reasoner",
            max_tokens=100,
            system="Return JSON",
            user="Test",
            output_format=Result,
        )
        response = (
            asyncio.run(client.request(**kwargs)) if asynchronous else client.request(**kwargs)
        )
    assert response.parsed_output.ok
    token_field = "max_completion_tokens" if official else "max_tokens"
    assert [payload[token_field] for payload in captured] == [100, 200]
    assert all(("temperature" not in payload) == official for payload in captured)
    assert all(("max_tokens" not in payload) == official for payload in captured)
