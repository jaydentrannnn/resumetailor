"""Deadline and structured-output parity for the Apply async transport."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from pydantic import BaseModel

from resume_tailor import llm


class _Answer(BaseModel):
    value: str


def _reply(content: str, *, finish: str = "stop", status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"content": content}, "finish_reason": finish}]})


def test_async_client_retries_schema_rejection_and_repairs_parse():
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(400, text="unsupported response_format")
        if len(calls) == 2:
            return _reply("not json")
        return _reply('{"value":"grounded"}')

    async def run() -> str:
        client = llm._AsyncOpenAICompatClient(  # noqa: SLF001
            base_url="https://example.test/v1", api_key="", structured_mode="schema",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client._http = http  # noqa: SLF001
            response = await client.messages.parse(
                model="test", max_tokens=128, system="Answer", messages=[{"content": "Question"}],
                output_format=_Answer,
            )
        return response.parsed_output.value

    assert asyncio.run(run()) == "grounded"
    assert len(calls) == 3
    assert calls[1]["response_format"] == {"type": "json_object"}


def test_async_client_checks_absolute_deadline_before_request():
    async def run() -> None:
        client = llm._AsyncOpenAICompatClient(  # noqa: SLF001
            base_url="https://example.test/v1", api_key="", structured_mode="prompt",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: _reply('{"value":"x"}'))) as http:
            client._http = http  # noqa: SLF001
            with pytest.raises(TimeoutError, match="deadline"):
                await client.messages.parse(
                    model="test", max_tokens=128, system="Answer", messages=[{"content": "Question"}],
                    output_format=_Answer, deadline=time.monotonic() - 1,
                )

    asyncio.run(run())


def test_async_client_retries_transient_503(monkeypatch):
    calls: list[dict] = []
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) < 3:
            return httpx.Response(503)
        return _reply('{"value":"grounded"}')

    monkeypatch.setattr(llm, "_async_sleep", fake_sleep)

    async def run() -> str:
        client = llm._AsyncOpenAICompatClient(  # noqa: SLF001
            base_url="https://example.test/v1", api_key="", structured_mode="prompt",
            timeout=30,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client._http = http  # noqa: SLF001
            response = await client.messages.parse(
                model="test", max_tokens=128, system="Answer", messages=[{"content": "Question"}],
                output_format=_Answer,
            )
        return response.parsed_output.value

    assert asyncio.run(run()) == "grounded"
    assert len(calls) == 3
    assert sleeps == [2.0, 5.0]
