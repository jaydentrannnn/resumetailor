"""LiteLLM transport under the existing JSON parsing, repair and escalation loop."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from resume_tailor import config

from . import llm, model_queue, telemetry, vertex_auth, vertex_catalog


def check_status(response: httpx.Response, model: str) -> None:
    details = {
        400: "Request rejected. Check this model's capabilities and settings.",
        401: "Google sign-in expired or was revoked. Reconnect Google Cloud.",
        403: (
            "Access denied. Check Vertex permissions, API activation, billing "
            "and model access in your project."
        ),
        404: "Model unavailable in this project/location. Check the model ID and chosen location.",
        429: (
            "Google Cloud quota or capacity is exhausted. Wait and retry, or check project quotas."
        ),
    }
    detail = details.get(
        response.status_code, "Google Cloud is temporarily unavailable. Retry later."
    )
    if response.status_code == 429:
        quota = model_queue.parse_rate_limit(response.text).quota
        if quota:
            detail = (
                f"Google Cloud quota exceeded: {quota}. "
                "Check this project's Quotas & System Limits and request an increase. "
                "Available billing credit does not increase request quotas."
            )
    raise llm.LLMError(f"Vertex AI {model!r}: {detail}", status=response.status_code)


def _response(result: Any, endpoint: str) -> httpx.Response:
    body = result.model_dump()
    choice = (body.get("choices") or [{}])[0]
    if choice.get("finish_reason") in {"content_filter", "safety"}:
        raise llm.LLMError("Google blocked this response. Review the request and retry.")
    if not (choice.get("message") or {}).get("content") and choice.get("finish_reason") != "length":
        raise llm.LLMError("Vertex AI returned an empty response. Retry or choose another model.")
    return httpx.Response(200, json=body, request=httpx.Request("POST", endpoint))


def _failure(exc: Exception, endpoint: str) -> httpx.Response:
    # SDK exception strings can contain request bodies or credentials. Never display them.
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or status < 400:
        raise llm.LLMError(
            "Vertex AI could not answer. Check your connection or reconnect Google Cloud."
        ) from None
    hint = (
        "reasoning_effort" if type(exc).__name__ == "UnsupportedParamsError" else "provider_error"
    )
    upstream = getattr(exc, "response", None)
    retry_after = getattr(upstream, "headers", {}).get("retry-after")
    body: dict = {"error": hint}
    if status == 429:
        # The pinned SDK wraps Google's JSON in its message instead of retaining
        # a JSON response. Return only a recognized constant, never provider text.
        message = str(getattr(exc, "message", ""))
        for location in ("global", "us_multi_region", "eu_multi_region"):
            for unit in ("requests", "input_tokens_per_minute", "output_tokens_per_minute"):
                metric = (
                    f"aiplatform.googleapis.com/{location}_online_prediction_{unit}_per_base_model"
                )
                if f"Quota exceeded for {metric}" in message:
                    body = {"error": {"details": [{"violations": [{"quotaId": metric}]}]}}
    return httpx.Response(
        status,
        json=body,
        request=httpx.Request("POST", endpoint),
        headers={"retry-after": retry_after} if retry_after else None,
    )


class _Connection:
    def _init_connection(self, backend: config.Backend, purpose: str) -> None:
        self.backend = backend
        self.deadline = float("inf")
        self.base_url = vertex_catalog.endpoint(backend.vertex_project, backend.vertex_location)
        try:
            vertex_auth.credentials(backend.credential_revision, backend.vertex_project)
            vertex_catalog.validate_location(backend.model, backend.vertex_location)
        except (ValueError, vertex_auth.ConnectionError) as exc:
            raise llm.LLMError(str(exc)) from None
        self.timeout = config.LLM_TIMEOUT
        self.max_token_cap = config.max_token_cap_for(purpose)
        self.send_effort = vertex_catalog.supports_effort(backend.model)
        self.structured_mode = config.structured_mode_for(purpose)
        self.origin = "vertex_ai"

    def _parameters(self, payload: dict, remaining: float) -> dict:
        try:
            creds = vertex_auth.credentials(
                self.backend.credential_revision, self.backend.vertex_project
            )
        except vertex_auth.ConnectionError as exc:
            raise llm.LLMError(str(exc)) from None
        params = (
            vertex_catalog.sdk().get_supported_openai_params(model=f"vertex_ai/{payload['model']}")
            or []
        )
        request = dict(payload)
        # The prompt always contains the schema; unknown models can use this path too.
        for optional in ("response_format", "reasoning_effort", "temperature"):
            if optional not in params:
                request.pop(optional, None)
        if payload["model"].startswith("claude-") or vertex_catalog.ignores_sampling(
            payload["model"]
        ):
            # New Claude models reject temperature=0, and adaptive thinking uses
            # the model's own sampling defaults. Gemini Flash 3.6+ ignores it.
            request.pop("temperature", None)
        return {
            **request,
            "model": f"vertex_ai/{payload['model']}",
            "vertex_project": self.backend.vertex_project,
            "vertex_location": self.backend.vertex_location,
            "vertex_credentials": creds,
            "timeout": remaining,
            "num_retries": 0,
            "max_retries": 0,
            "caching": False,
        }


class VertexClient(_Connection, llm._OpenAICompatClient):
    def __init__(self, backend: config.Backend, purpose: str):
        self._init_connection(backend, purpose)
        self.messages = llm._Messages(self)

    def request(self, **kwargs):
        self.deadline = time.monotonic() + self.timeout
        return super().request(**kwargs)

    def _post(self, payload: dict) -> httpx.Response:
        for retry in range(len(llm._RETRY_BACKOFF) + 1):
            with (
                telemetry.request(self.origin, payload["model"], retry) as measured,
                model_queue.queue.slot(self.base_url, self.origin, deadline=self.deadline),
            ):
                if model_queue.queue.exhausted_for(self.base_url):
                    raise llm._exhausted_error(self.base_url)
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Vertex AI request exceeded its deadline")
                params = self._parameters(payload, remaining)
                measured.admitted()
                try:
                    response = _response(vertex_catalog.sdk().completion(**params), self.base_url)
                except llm.LLMError:
                    raise
                except Exception as exc:
                    response = _failure(exc, self.base_url)
                measured.response(response)
                model_queue.queue.rate_limited(self.base_url, response)
            if model_queue.parse_rate_limit(response.text).quota:
                return response  # Google asks for a quota increase, not an immediate retry.
            if response.status_code not in llm._RETRYABLE_STATUSES or retry == len(
                llm._RETRY_BACKOFF
            ):
                return response
            delay = llm._retry_delay(response, retry)
            if delay + 1 >= self.deadline - time.monotonic():
                return response
            llm._sleep(delay)
        return response


class AsyncVertexClient(_Connection, llm._AsyncOpenAICompatClient):
    def __init__(self, backend: config.Backend, purpose: str):
        self._init_connection(backend, purpose)
        self.timeout = min(self.timeout, 60)
        self.messages = llm._AsyncMessages(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def request(self, *, deadline: float | None = None, **kwargs):
        deadline = min(deadline or float("inf"), time.monotonic() + self.timeout)
        return await super().request(deadline=deadline, **kwargs)

    async def _post(self, payload: dict, deadline: float) -> httpx.Response:
        deadline = min(deadline, time.monotonic() + self.timeout)
        for retry in range(len(llm._RETRY_BACKOFF) + 1):
            with telemetry.request(self.origin, payload["model"], retry) as measured:
                async with model_queue.queue.async_slot(
                    self.base_url, self.origin, deadline=deadline
                ):
                    if model_queue.queue.exhausted_for(self.base_url):
                        raise llm._exhausted_error(self.base_url)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Vertex AI request exceeded its deadline")
                    params = self._parameters(payload, remaining)
                    measured.admitted()
                    try:
                        async with asyncio.timeout(remaining):
                            result = await vertex_catalog.sdk().acompletion(**params)
                        response = _response(result, self.base_url)
                    except (llm.LLMError, TimeoutError):
                        raise
                    except Exception as exc:
                        response = _failure(exc, self.base_url)
                    measured.response(response)
                    model_queue.queue.rate_limited(self.base_url, response)
            if model_queue.parse_rate_limit(response.text).quota:
                return response
            if response.status_code not in llm._RETRYABLE_STATUSES or retry == len(
                llm._RETRY_BACKOFF
            ):
                return response
            delay = llm._retry_delay(response, retry)
            if delay + 1 >= deadline - time.monotonic():
                return response
            await llm._async_sleep(delay)
        return response
