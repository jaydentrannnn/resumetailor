"""The existing JSON loop through a fake LiteLLM transport, sync and async."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from resume_tailor import config
from resume_tailor.infra import llm, model_queue, telemetry, vertex_auth, vertex_catalog
from resume_tailor.infra.vertex_llm import AsyncVertexClient, VertexClient
from resume_tailor.model_selection import ModelSelection


class Answer(BaseModel):
    ok: bool


@pytest.fixture
def transport(monkeypatch):
    vertex_auth.save(
        {"refresh_token": "secret", "type": "authorized_user"},
        "user@example.test",
        vertex_auth.epoch(),
    )
    seen, replies = [], []
    model = "claude-sonnet-5-5"
    sdk = SimpleNamespace(
        model_cost={
            f"vertex_ai/{model}": {
                "mode": "chat",
                "supported_regions": ["global"],
                "supports_reasoning": True,
            }
        },
        get_supported_openai_params=lambda **_k: [
            "response_format",
            "reasoning_effort",
            "temperature",
        ],
    )

    def complete(**kwargs):
        seen.append(kwargs)
        assert model_queue.queue.status()["endpoints"][0]["active"] == 1
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        content, finish = item
        return SimpleNamespace(
            model_dump=lambda: {
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            }
        )

    async def acomplete(**kwargs):
        return complete(**kwargs)

    sdk.completion, sdk.acompletion = complete, acomplete
    monkeypatch.setattr(vertex_catalog, "sdk", lambda: sdk)
    selection = ModelSelection(
        provider="vertex_ai",
        model_name=f"vertex_ai/{model}",
        vertex_project="test-project",
        vertex_location="global",
    )
    with config.pinned("ollama", overrides=dict.fromkeys(config.PURPOSES, selection.spec("light"))):
        yield SimpleNamespace(
            seen=seen,
            replies=replies,
            sdk=sdk,
            selection=selection,
            backend=config.backend_for("extract"),
        )


def parse(client, **kwargs):
    return client.messages.parse(
        model="claude-sonnet-5-5",
        max_tokens=256,
        system="Answer.",
        messages=[{"role": "user", "content": "Hi"}],
        output_format=Answer,
        **kwargs,
    )


def test_sync_schema_usage_and_plain_strings(transport, tmp_path):
    transport.replies.append(('{"ok":true}', "stop"))
    with telemetry.recording(tmp_path) as metrics:
        result = parse(llm.client_for("extract"), output_config={"effort": "low"})
    assert result.parsed_output.ok
    request = transport.seen[0]
    assert request["model"] == "vertex_ai/claude-sonnet-5-5"
    assert request["vertex_project"] == "test-project"
    assert request["vertex_location"] == "global"
    assert request["num_retries"] == request["max_retries"] == 0
    assert request["response_format"]["type"] == "json_schema"
    assert request["reasoning_effort"] == "low"
    assert '"properties"' in request["messages"][0]["content"]
    assert metrics.data["requests"][0]["input_tokens"] == 12
    assert model_queue.queue.status()["endpoints"][0]["active"] == 0


def test_one_repair_then_failure(transport):
    transport.replies.extend([("wrong", "stop"), ("still wrong", "stop")])
    with pytest.raises(llm.LLMError, match="repair attempt"):
        parse(VertexClient(transport.backend, "extract"))
    assert len(transport.seen) == 2
    assert transport.seen[1]["messages"][-2]["role"] == "assistant"


def test_truncation_escalates_but_empty_blocked_and_removed_connections_do_not(transport):
    transport.replies.extend([('{"ok":', "length"), ('{"ok":true}', "stop")])
    assert parse(VertexClient(transport.backend, "extract")).parsed_output.ok
    assert transport.seen[1]["max_tokens"] == transport.seen[0]["max_tokens"] * 2
    client = VertexClient(transport.backend, "extract")
    for reply, message in [(("", "stop"), "empty"), (("", "content_filter"), "blocked")]:
        transport.replies.append(reply)
        with pytest.raises(llm.LLMError, match=message):
            parse(client)
    vertex_auth.disconnect()
    count = len(transport.seen)
    with pytest.raises(llm.LLMError, match="changed or was removed"):
        parse(client)
    assert len(transport.seen) == count


@pytest.mark.parametrize(
    "status, message", [(401, "expired"), (403, "Access denied"), (404, "Model unavailable")]
)
def test_provider_errors_are_actionable_redacted_and_not_retried(transport, status, message):
    error = RuntimeError("private-refresh-token and resume text")
    error.status_code = status
    transport.replies.append(error)
    with pytest.raises(llm.LLMError, match=message) as failure:
        parse(VertexClient(transport.backend, "extract"))
    assert "private" not in str(failure.value)
    assert len(transport.seen) == 1


def test_bad_location_is_rejected_before_sdk_can_substitute(transport):
    bad = transport.backend._replace(vertex_location="us-central1")
    with pytest.raises(llm.LLMError, match="does not support"):
        VertexClient(bad, "extract")
    assert not transport.seen


def test_unknown_model_and_unsupported_optional_parameters(transport):
    transport.sdk.get_supported_openai_params = lambda **_k: []
    transport.replies.append(('{"ok":true}', "stop"))
    assert parse(VertexClient(transport.backend, "extract")).parsed_output.ok
    assert "response_format" not in transport.seen[0]
    assert "temperature" not in transport.seen[0]
    assert not vertex_catalog.supports_effort("unknown-model")


@pytest.mark.asyncio
async def test_async_interface_and_json_repair(transport):
    transport.replies.extend([("wrong", "stop"), ('{"ok":true}', "stop")])
    async with llm.async_client_for("answer") as client:
        result = await parse(client)
    assert result.parsed_output.ok
    assert len(transport.seen) == 2
    assert model_queue.queue.status()["endpoints"][0]["active"] == 0


@pytest.mark.asyncio
async def test_async_cancellation_releases_request_slot(transport):
    entered = asyncio.Event()

    async def blocked(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    transport.sdk.acompletion = blocked
    async with AsyncVertexClient(transport.backend, "answer") as client:
        task = asyncio.create_task(parse(client))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert model_queue.queue.status()["endpoints"][0]["active"] == 0


def test_cache_identity_ignores_credential_revision_but_tracks_location_project(transport):
    original = config.fingerprint("extract")
    spec = config.spec_for_backend(transport.backend._replace(credential_revision="replacement"))
    with config.pinned("ollama", overrides={"extract": spec}):
        assert config.fingerprint("extract") == original
    for field in ("vertex_project", "vertex_location"):
        spec = config.spec_for_backend(transport.backend._replace(**{field: "other"}))
        with config.pinned("ollama", overrides={"extract": spec}):
            assert config.fingerprint("extract") != original


def test_vertex_connection_never_falls_back_to_a_different_model(transport):
    from resume_tailor.apply.answers.model_fallback import Fallback

    vertex = transport.selection.spec("heavy")
    assert not Fallback(vertex, "ollama:local").use_light("is at its quota limit")
    assert not Fallback("ollama:local", vertex).use_light("is at its quota limit")
    assert not Fallback({"provider": "vertex_ai", "origin": ""}, "ollama:local").use_light("down")


def test_http_retry_is_bounded_and_each_attempt_is_measured(transport, monkeypatch, tmp_path):
    error = RuntimeError("private-error")
    error.status_code = 503
    transport.replies.extend([error, ('{"ok":true}', "stop")])
    monkeypatch.setattr(llm, "_sleep", lambda _delay: None)
    with telemetry.recording(tmp_path) as metrics:
        assert parse(VertexClient(transport.backend, "extract")).parsed_output.ok
    assert len(metrics.data["requests"]) == 2
    assert metrics.data["requests"][1]["retry_index"] == 1
