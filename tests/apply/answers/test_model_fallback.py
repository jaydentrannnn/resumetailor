"""Fill falls back from the Heavy to the Light task model when Heavy is at its limit."""

from __future__ import annotations

import httpx
import pytest

from resume_tailor import config
from resume_tailor.apply.answers import model_fallback
from resume_tailor.infra import llm, model_queue

HEAVY = "gemini:gemini-3.5-flash"
LIGHT = "gemini:gemini-3.5-flash-lite"


def _route(messages: list[str]) -> model_fallback.Fallback:
    return model_fallback.Fallback(heavy=HEAVY, light=LIGHT, progress=messages.append)


def test_a_429_retries_once_under_light_and_stays_there():
    messages: list[str] = []
    route = _route(messages)
    seen: list[str] = []

    def ask() -> str:
        model = config.model_for("answer")
        seen.append(model)
        if model == "gemini-3.5-flash":
            raise llm.LLMError("HTTP 429", status=429)
        return model

    with model_fallback.pin(route):
        assert model_fallback.call(ask) == "gemini-3.5-flash-lite"
    assert seen == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
    assert messages == [
        "Heavy model is at its limit (HTTP 429); answering with Light (gemini-3.5-flash-lite)"
    ]
    # The rest of the fill pins Light straight away.
    with model_fallback.pin(route):
        assert config.model_for("answer") == "gemini-3.5-flash-lite"


def test_other_errors_and_no_light_model_are_raised():
    route = model_fallback.Fallback(heavy=HEAVY, light=None)
    with model_fallback.pin(route), pytest.raises(llm.LLMError):
        model_fallback.call(lambda: (_ for _ in ()).throw(llm.LLMError("x", status=429)))
    route = _route([])
    with model_fallback.pin(route), pytest.raises(ValueError):
        model_fallback.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
    assert not route.heavy_down


def test_a_used_up_heavy_quota_pins_light_before_any_call():
    url = model_fallback.endpoint(HEAVY)
    with model_queue.queue.slot(url, "gemini"):
        for _ in range(3):
            model_queue.queue.rate_limited(url, httpx.Response(429, headers={"Retry-After": "0"}))
    messages: list[str] = []
    with model_fallback.pin(_route(messages)):
        assert config.model_for("answer") == "gemini-3.5-flash-lite"
    assert messages == [
        "Heavy model is at its quota limit; answering with Light (gemini-3.5-flash-lite)"
    ]
