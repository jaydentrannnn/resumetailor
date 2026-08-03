"""The provider boundary: where the pipeline gets a client from.

`jd.py`, `rewrite.py`, and `expand.py` remain the only modules that *call* a model. This
one decides which model they call, so that pointing a run at Ollama Cloud instead of
Claude is configuration rather than a code change.

The interface is `client.messages.parse(...)` -> object with `.parsed_output` and
`.stop_reason`. That shape is Anthropic's, and it is kept deliberately: it was already the
project's de-facto internal interface (both call sites use it, and every test fake
implements it), so adopting it as *the* interface meant the call bodies in `jd.py` and
`rewrite.py` did not have to change at all. Anthropic implements it natively; everything
else goes through `_OpenAICompatClient`, which translates.

The architectural invariant is untouched. This module moves plain strings and JSON, and
knows nothing about `.docx`, XML, or layout.

## Why OpenAI-compatible rather than one SDK per provider

Ollama (local and Cloud), LM Studio, vLLM, llama.cpp, OpenRouter, Groq, DeepSeek, Moonshot
and Z.ai all expose `/chat/completions` in OpenAI's shape. One adapter reaches all of them,
and `httpx` (already an Anthropic dependency) is enough — the request body is a dict. A
provider-specific SDK would add a dependency to reach a subset of the same endpoints.

## Why the schema goes in the prompt

Measured against `nemotron-3-super:cloud`, the intended target:

- `response_format: {json_schema, strict: true}` -> **HTTP 200 carrying markdown prose.**
  The parameter is accepted and silently unenforced.
- Ollama's own native `format: <schema>` on `/api/chat` -> **also prose.** Cloud models get
  no constrained decoding through either surface.
- `response_format: {json_object}` alone -> valid JSON, but an invented shape.
- **Schema in the system prompt + `json_object`** -> exact schema match, first attempt.

Two things follow, and they shape everything below. Non-compliance arrives as a **200**, not
a 4xx, so escalation keys on parse failure rather than status code. And a speculative
`json_schema` attempt is a round trip that always fails on this backend, which costs quota
rather than costing nothing — hence `config.LLM_STRUCTURED_MODE` defaults to "prompt".

That default is now per-provider, not global (`config.structured_mode_for`). Gemini's
OpenAI-compat shim is a different story from Ollama's: it genuinely constrains decoding, so
it defaults to "schema" instead. An explicit `LLM_STRUCTURED_MODE` still wins everywhere —
this only fills the gap where nothing was configured.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from . import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """A provider call failed in a way no retry inside this module could repair.

    Subclasses `RuntimeError` so the existing handlers in `tailor.py` catch it without
    needing a new except clause.
    """


_JSON_INSTRUCTION = (
    "Return ONLY a single JSON object conforming to this JSON Schema. "
    "No prose, no explanation, no markdown fences.\n\n{schema}"
)


# --------------------------------------------------------------------------------------
# JSON recovery
# --------------------------------------------------------------------------------------


def _extract_json_object(text: str) -> str:
    """Pull the first complete JSON object out of a model response.

    Models without constrained decoding wrap JSON in ``` fences or introduce it with a
    sentence. Rather than regex the fences off (which breaks the moment a string value
    contains a brace), scan for the first `{` and track depth, skipping string literals
    and their escapes.

    Returns the text unchanged if no balanced object is found, so the caller's Pydantic
    error names the real problem instead of a slicing artefact.
    """
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escaped = False

    for i, ch in enumerate(text[start:], start):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return text


def _strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a Pydantic schema into the subset OpenAI's `strict` mode accepts.

    Strict mode requires every property listed in `required` and every object to set
    `additionalProperties: false`. Pydantic omits fields that have defaults from `required`
    (`Keyword.kind` is one), which strict mode rejects.

    Forcing them required only affects what the *model* must emit. Loading a cached
    `*.requirements.json` still goes through Pydantic, where the default applies as before,
    so extractions written before a field existed keep working.

    Only used when `config.LLM_STRUCTURED_MODE == "schema"`; the default path puts the
    plain schema in the prompt instead.
    """
    if not isinstance(schema, dict):
        return schema

    out: dict[str, Any] = dict(schema)

    for key in ("$defs", "properties"):
        if isinstance(out.get(key), dict):
            out[key] = {k: _strictify(v) for k, v in out[key].items()}
    if isinstance(out.get("items"), dict):
        out["items"] = _strictify(out["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(out.get(key), list):
            out[key] = [_strictify(s) for s in out[key]]

    if out.get("type") == "object" and isinstance(out.get("properties"), dict):
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])

    return out


def _response_format_ladder(
    structured_mode: str, output_format: type[T], schema: dict[str, Any]
) -> list[dict[str, Any] | None]:
    """Ordered `response_format` values to try on a 400/422, most-constrained first.

    A rejection walks down this list instead of jumping straight to no constraint at all.
    That distinction matters once `schema` mode is a real default (Gemini): every output
    model in this project is nested (`$defs` + `$ref`), where OpenAI-compat shims commonly
    have gaps, and dropping straight to nothing on a schema rejection would land *below*
    the "prompt" default it started from. "prompt" mode's ladder is `[json_object, None]`,
    which is exactly the one-step drop this replaces — unchanged behaviour by construction.
    """
    json_object = {"type": "json_object"}
    if structured_mode == "schema":
        json_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": output_format.__name__,
                "strict": True,
                "schema": _strictify(schema),
            },
        }
        return [json_schema, json_object, None]
    return [json_object, None]


#: Working `max_tokens` ceiling discovered by escalation, keyed `(base_url, model)` rather
#: than by pipeline stage — verbosity is a property of the model, and several stages
#: (score, rewrite's several sub-calls, expand) can share one within a single run. A
#: rewrite-heavy run makes up to five calls; without this, a verbose model pays a full
#: truncated generation to rediscover the same working ceiling on every one of them.
#:
#: Module-global and never cleared in production — the project already requires a single
#: process and serial jobs (see `config._ACTIVE`), and this is strictly a *measurement*,
#: not configuration, which is why it lives here rather than growing `config._ACTIVE`.
#: Tests MUST clear this between cases or a call-count assertion becomes flaky for reasons
#: that have nothing to do with the test — see the `client` fixture in tests/test_llm.py.
_LEARNED_CEILING: dict[tuple[str, str], int] = {}


# --------------------------------------------------------------------------------------
# OpenAI-compatible adapter
# --------------------------------------------------------------------------------------


class _Response:
    """Mirrors the fields `jd.py` and `rewrite.py` read off an Anthropic response."""

    def __init__(self, parsed: BaseModel | None, stop_reason: str | None):
        self.parsed_output = parsed
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, client: "_OpenAICompatClient"):
        self._client = client

    def parse(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        output_format: type[T],
        output_config: dict[str, Any] | None = None,
        **_ignored: Any,
    ) -> _Response:
        """Translate an Anthropic-shaped request into `/chat/completions`.

        `output_config` (Anthropic's reasoning-effort control) has no portable equivalent
        and is accepted-and-dropped rather than rejected, so the same call site works
        against both providers. Endpoints that expose reasoning do so under incompatible
        names; forwarding a guess would break more endpoints than it would help.
        """
        return self._client.request(
            model=model,
            max_tokens=max_tokens,
            system=system,
            user="\n\n".join(str(m.get("content", "")) for m in messages),
            output_format=output_format,
        )


class _OpenAICompatClient:
    """Minimal `/chat/completions` client that gets JSON out of unconstrained models."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float,
        structured_mode: str,
        max_token_cap: int = 0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.structured_mode = structured_mode
        #: 0 disables escalation entirely — a truncated response fails exactly as it did
        #: before this feature existed. `client_for` always supplies the real per-stage
        #: cap; direct construction (every existing test) gets that safe default unless it
        #: opts in.
        self.max_token_cap = max_token_cap
        self.messages = _Messages(self)

    # -- transport ---------------------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        # Ollama authenticates through the daemon, and some local servers reject a bearer
        # header outright, so send one only when there is a key.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            return httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except httpx.RequestError as exc:
            # base_url is whatever the profile/override resolved — do not assume Ollama.
            # :11434 → Ollama, :1234 → LM Studio; from Docker both use host.docker.internal.
            raise LLMError(
                f"Could not reach {self.base_url}: {exc}. Check that server is running "
                f"and reachable from this process (local: localhost; Docker: "
                f"host.docker.internal). A :11434 URL is Ollama; :1234 is LM Studio. "
                f"Profile 'lmstudio' uses LM Studio for all stages unless Rewrite/Expand "
                f"model overrides (or profile hybrid/ollama) point elsewhere."
            ) from exc

    def _check_status(self, response: httpx.Response, model: str) -> None:
        if response.status_code < 400:
            return
        detail = response.text[:400]
        if response.status_code == 404:
            # By far the most common first error: the tag is not available to this
            # account, or was never pulled.
            raise LLMError(
                f"{self.base_url} has no model {model!r}. Pull it with "
                f"`ollama pull {model}`, or run `ollama signin` if it is a :cloud tag."
            )
        raise LLMError(
            f"{self.base_url} returned HTTP {response.status_code} for {model!r}: {detail}"
        )

    @staticmethod
    def _read(response: httpx.Response, model: str) -> tuple[str, str | None]:
        try:
            choice = response.json()["choices"][0]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(
                f"Unreadable response from {model!r}: {response.text[:400]}"
            ) from exc
        # Reasoning models put their trace in `message.reasoning`; `content` is the answer.
        return choice["message"].get("content") or "", choice.get("finish_reason")

    # -- request -----------------------------------------------------------------------

    def request(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        user: str,
        output_format: type[T],
    ) -> _Response:
        schema = output_format.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": system
                + "\n\n"
                + _JSON_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False)),
            },
            {"role": "user", "content": user},
        ]
        ladder = _response_format_ladder(self.structured_mode, output_format, schema)

        # `max_token_cap` of 0 (the direct-construction default) means "no escalation":
        # cap collapses to the starting request, so `ceiling` below can never rise past it.
        cap = max(max_tokens, self.max_token_cap) if self.max_token_cap else max_tokens
        learned = _LEARNED_CEILING.get((self.base_url, model), 0)
        ceiling = min(max(max_tokens, learned), cap)
        escalations = 0

        rung = 0
        while True:
            payload: dict[str, Any] = {
                "model": model,
                # `max_tokens` only. Ollama maps it to num_predict; stricter servers reject
                # `max_completion_tokens` alongside it.
                "max_tokens": ceiling,
                "temperature": 0,
                "messages": messages,
            }
            response_format = ladder[rung]
            if response_format is not None:
                payload["response_format"] = response_format

            response = self._post(payload)

            # Some endpoints reject `response_format` in any form. Walk the ladder toward
            # less structure rather than jumping straight to none.
            #
            # Only on a *parameter* rejection. A 404 means the model does not exist and a
            # 401 means the sign-in lapsed; retrying either just spends another round trip
            # against a metered quota to be told the same thing.
            if response.status_code in (400, 422) and rung < len(ladder) - 1:
                rung += 1
                continue

            self._check_status(response, model)
            content, finish = self._read(response, model)

            try:
                parsed = output_format.model_validate_json(_extract_json_object(content))
                if ceiling > max_tokens:
                    _LEARNED_CEILING[(self.base_url, model)] = ceiling
                return _Response(parsed, finish)
            except ValidationError as first_error:
                if finish != "length":
                    return self._repair(payload, content, first_error, model, output_format)

                # Truncated. Escalating only fires on what would otherwise be a hard
                # failure right here, so a run that already succeeds never pays for this —
                # it issues the same requests at the same ceiling it always did.
                if ceiling < cap and escalations < config.MAX_TOKEN_ESCALATIONS:
                    ceiling = min(ceiling * 2, cap)
                    escalations += 1
                    continue

                if escalations:
                    raise LLMError(
                        f"{model!r} hit the {ceiling}-token ceiling after escalating "
                        f"from {max_tokens} (cap {cap}) before finishing its JSON. "
                        f"Reasoning tokens count against this budget — set "
                        f"LLM_MAX_TOKENS to raise the cap, or lower the stage's effort."
                    ) from first_error
                raise LLMError(
                    f"{model!r} hit the {ceiling}-token ceiling (cap {cap}) before "
                    f"finishing its JSON. Reasoning tokens count against this budget — "
                    f"set LLM_MAX_TOKENS to raise the cap, or lower the stage's effort."
                ) from first_error

    def _repair(
        self,
        payload: dict[str, Any],
        content: str,
        error: ValidationError,
        model: str,
        output_format: type[T],
    ) -> _Response:
        """One corrective round trip, showing the model its own output and the error.

        One only. A model that cannot produce the schema twice will not on the third go,
        and against a quota-limited free tier each attempt has a real cost.
        """
        retry = dict(payload)
        retry["messages"] = [
            *payload["messages"],
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "That did not match the required JSON schema:\n"
                    f"{str(error)[:600]}\n\n"
                    "Return ONLY a corrected JSON object. No prose, no markdown fences."
                ),
            },
        ]

        response = self._post(retry)
        self._check_status(response, model)
        repaired, finish = self._read(response, model)

        try:
            parsed = output_format.model_validate_json(_extract_json_object(repaired))
        except ValidationError as exc:
            raise LLMError(
                f"{model!r} did not return JSON matching {output_format.__name__} after a "
                f"repair attempt. This backend may not follow schemas reliably enough for "
                f"this stage — try --model hybrid or --model claude.\n"
                f"Last response: {repaired[:400]}"
            ) from exc

        return _Response(parsed, finish)


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def client_for(purpose: str) -> Any:
    """Return a client for one pipeline stage: extract, score, rewrite, expand, or facets.

    Per-stage routing is the point. Extraction, scoring, and facets are structured-
    judgement tasks that survive a cheaper model; rewriting carries the fabrication risk
    and the length constraints, and is where model quality actually shows. Pointing the
    cheap stages at a free endpoint and leaving rewriting on Claude is what
    `--model hybrid` does. Expansion follows the profile (Ollama under `hybrid`) and is
    advisory paste text.
    """
    backend = config.backend_for(purpose)

    if backend.provider == "anthropic":
        import anthropic

        return anthropic.Anthropic(api_key=config.api_key_for(purpose))

    if backend.provider == "openai":
        if not backend.base_url:
            raise LLMError(
                f"Provider 'openai' for {purpose!r} needs a base URL. Use "
                f"'openai:model@https://host/v1', 'ollama:model' (defaults to "
                f"{config.OLLAMA_BASE_URL}), 'lmstudio:model' (defaults to "
                f"{config.LMSTUDIO_BASE_URL}), or 'gemini:model' (defaults to "
                f"{config.GEMINI_BASE_URL})."
            )
        if backend.origin in config.PROVIDERS_REQUIRING_KEY and not config.api_key_for(
            purpose
        ):
            env_names = " or ".join(config.api_key_env_for(backend.origin))
            raise LLMError(
                f"No API key found for the {backend.origin!r} provider ({purpose!r} "
                f"stage). Set {env_names} in .env."
            )
        return _OpenAICompatClient(
            base_url=backend.base_url,
            api_key=config.api_key_for(purpose),
            timeout=config.LLM_TIMEOUT,
            structured_mode=config.structured_mode_for(purpose),
            max_token_cap=config.max_token_cap_for(purpose),
        )

    raise LLMError(
        f"Unknown provider {backend.provider!r} for {purpose!r}. "
        f"Supported: {', '.join(config.PROVIDERS)}."
    )
