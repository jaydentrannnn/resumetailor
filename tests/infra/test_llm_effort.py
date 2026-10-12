"""Reasoning effort: per-step choices, provider defaults, and forwarding to OpenAI/Gemini."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from resume_tailor import config
from resume_tailor.infra import llm
from resume_tailor.web.schemas import JobSettings


class Sample(BaseModel):
    title: str


def _completion() -> httpx.Response:
    body = json.dumps({"title": "Engineer"})
    return httpx.Response(
        200, json={"choices": [{"message": {"content": body}, "finish_reason": "stop"}]}
    )


class _Recorder:
    def __init__(self, *responses: httpx.Response):
        self._queue = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, url, *, headers=None, json=None, timeout=None):
        self.payloads.append(json)
        return self._queue.pop(0) if self._queue else _completion()


@pytest.fixture
def post(monkeypatch):
    llm._NO_REASONING_EFFORT.clear()

    def _make(*responses):
        recorder = _Recorder(*responses)
        monkeypatch.setattr(llm.httpx, "post", recorder)
        return recorder

    yield _make
    llm._NO_REASONING_EFFORT.clear()


def _parse(*, send_effort: bool, base_url: str = "https://api.openai.com/v1"):
    client = llm._OpenAICompatClient(
        base_url=base_url, api_key="k", timeout=5, structured_mode="prompt",
        send_effort=send_effort,
    )
    return client.messages.parse(
        model="gpt-5-mini", max_tokens=100, system="s",
        messages=[{"role": "user", "content": "u"}], output_format=Sample,
        output_config={"effort": "low"},
    )


def test_effort_is_sent_as_reasoning_effort_when_the_provider_takes_it(post):
    recorder = post()
    _parse(send_effort=True)
    assert recorder.payloads[0]["reasoning_effort"] == "low"


def test_effort_is_dropped_for_servers_that_do_not_take_it(post):
    recorder = post()
    _parse(send_effort=False, base_url="http://localhost:11434/v1")
    assert "reasoning_effort" not in recorder.payloads[0]


def test_a_model_that_rejects_effort_is_retried_without_it_and_remembered(post):
    rejected = httpx.Response(
        400, text="Unsupported parameter: 'reasoning_effort' is not supported with this model."
    )
    recorder = post(rejected, _completion())
    assert _parse(send_effort=True).parsed_output.title == "Engineer"
    assert "reasoning_effort" in recorder.payloads[0]
    assert "reasoning_effort" not in recorder.payloads[1]
    # The retry kept the structured-output rung: only the effort was dropped.
    assert recorder.payloads[0].get("response_format") == recorder.payloads[1].get(
        "response_format"
    )

    later = post()
    _parse(send_effort=True)
    assert "reasoning_effort" not in later.payloads[0]


@pytest.mark.parametrize(
    ("spec", "forwards"),
    [
        ("claude-haiku-5-5", True),
        ("gemini:gemini-3-flash", True),
        ("openai:gpt-5-mini@https://api.openai.com/v1", True),
        ("openai:qwen3@http://localhost:8000/v1", False),
        ("ollama:gemma4:cloud", False),
        ("lmstudio:google/gemma-4-12b", False),
    ],
)
def test_forwards_effort_by_provider(spec, forwards):
    with config.pinned(spec) as backends:
        assert config.forwards_effort(backends["rewrite"]) is forwards


def test_expand_is_recommended_low_on_providers_that_take_effort(monkeypatch):
    monkeypatch.setattr(config, "_EFFORT_FROM_ENV", frozenset())
    for spec in ("claude-haiku-5-5", "gemini:gemini-3-flash"):
        with config.pinned(spec) as backends:
            assert backends["expand"].effort == "low"
            assert backends["rewrite"].effort == "medium"
    with config.pinned("ollama:gemma4:cloud") as backends:
        assert backends["expand"].effort == "medium"


def test_an_env_effort_still_wins_over_the_provider_default(monkeypatch):
    monkeypatch.setattr(config, "_EFFORT_FROM_ENV", frozenset({"expand"}))
    monkeypatch.setitem(config.DEFAULT_EFFORT, "expand", "high")
    with config.pinned("claude-haiku-5-5") as backends:
        assert backends["expand"].effort == "high"


def test_custom_effort_sets_each_step_and_leaves_the_rest_recommended(monkeypatch):
    monkeypatch.setattr(config, "_EFFORT_FROM_ENV", frozenset())
    effort = {"rewrite": "high", "analysis": "medium"}
    with config.pinned("claude-haiku-5-5", effort=effort) as backends:
        assert backends["rewrite"].effort == "high"
        assert {backends[p].effort for p in ("extract", "score", "facets", "skills")} == {
            "medium"
        }
        assert backends["expand"].effort == "low"
        assert backends["cover"].effort == "medium"
        assert backends["review"].effort == "low"


def test_one_effort_still_applies_to_every_stage():
    with config.pinned("claude-haiku-5-5", effort="high") as backends:
        assert {b.effort for b in backends.values()} == {"high"}


def test_fingerprint_marks_providers_that_now_receive_effort():
    with config.pinned("gemini:gemini-3-flash"):
        assert config.fingerprint("rewrite", include_guidance=False).endswith("|effort-sent")
    with config.pinned("ollama:gemma4:cloud"):
        assert "effort-sent" not in config.fingerprint("rewrite", include_guidance=False)
    with config.pinned("claude-haiku-5-5"):
        assert "effort-sent" not in config.fingerprint("rewrite", include_guidance=False)


@pytest.mark.parametrize(
    ("effort", "answer"),
    [(None, None), ("low", "low"), ({"answer": "high", "rewrite": "low"}, "high"),
     ({"rewrite": "low"}, None)],
)
def test_fill_gets_the_answer_steps_effort(effort, answer):
    settings = JobSettings.model_validate({"effort": effort})
    assert settings.apply.answer_effort == answer
