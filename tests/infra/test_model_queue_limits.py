"""Adaptive limits after a 429: halve, recover, and mark a used-up quota (no network)."""

import json

import httpx

from resume_tailor.infra import model_queue

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai"


def _gemini_429(quota: str, delay: str = "37s") -> httpx.Response:
    body = [{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": quota}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
    ]}}]
    return httpx.Response(429, text=json.dumps(body))


def _endpoint() -> dict:
    return model_queue.queue.status()["endpoints"][0]


def test_parse_rate_limit_reads_gemini_quota_and_delay():
    limit = model_queue.parse_rate_limit(
        _gemini_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier").text
    )
    assert limit.retry_after == 37.0
    assert limit.per_day
    assert model_queue.parse_rate_limit("not json") == model_queue.RateLimit()


def test_a_429_halves_the_limit_and_successes_restore_it():
    q = model_queue.queue
    with q.slot(ENDPOINT, "gemini"):
        q.rate_limited(ENDPOINT, _gemini_429("GenerateRequestsPerMinutePerProjectPerModel", "0s"))
    assert _endpoint()["limit"] == 3
    assert _endpoint()["limit_effective"] == 1
    assert _endpoint()["rate_limited_today"] == 1
    assert not q.exhausted_for(ENDPOINT)
    for _ in range(2 * model_queue._RECOVER_AFTER):  # noqa: SLF001
        q.rate_limited(ENDPOINT, httpx.Response(200))
    assert _endpoint()["limit_effective"] == 3


def test_a_per_day_quota_marks_the_endpoint_used_up():
    q = model_queue.queue
    with q.slot(ENDPOINT, "gemini"):
        q.rate_limited(
            ENDPOINT, _gemini_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "120s")
        )
    assert 100 < q.exhausted_for(ENDPOINT) <= 120
    assert _endpoint()["quota"] == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


def test_repeated_cooldowns_mark_the_endpoint_used_up():
    q = model_queue.queue
    with q.slot(ENDPOINT, "gemini"):
        for _ in range(model_queue._COOLDOWNS_TO_EXHAUST):  # noqa: SLF001
            q.rate_limited(ENDPOINT, httpx.Response(429, headers={"Retry-After": "0"}))
    assert q.exhausted_for(ENDPOINT) > 500


def test_a_plan_sets_the_default_concurrency_unless_a_server_limit_is_saved():
    q = model_queue.queue
    q.set_plan(ENDPOINT, "free")
    with q.slot(ENDPOINT, "gemini"):
        assert _endpoint()["limit"] == 1
    q.save_settings(model_queue.QueueSettings(endpoint_limits={ENDPOINT: 5}))
    assert _endpoint()["limit"] == 5


def test_unavailable_reads_the_status_attribute_or_the_message():
    from resume_tailor.infra import llm

    assert llm.unavailable(llm.LLMError("quota", status=429)) == 429
    assert llm.unavailable(llm.LLMError("bad request", status=400)) is None
    assert llm.unavailable(RuntimeError("server returned HTTP 503 for 'm'")) == 503
    assert llm.unavailable(ValueError("nope")) is None


def test_the_saved_models_plans_set_their_servers_defaults(tmp_path, monkeypatch):
    from resume_tailor import app_settings

    monkeypatch.setattr(app_settings, "path", lambda: tmp_path / "ai_settings.json")
    app_settings.save({"ai_models": {
        "light": {"provider": "gemini", "model_name": "gemini-3.5-flash-lite"},
        "heavy": {"provider": "custom", "model_name": "m", "base_url": "https://ark.example.com/v3",
                  "plan": "subscription"},
    }})
    q = model_queue.queue
    with q.slot(ENDPOINT, "gemini"):
        assert _endpoint()["limit"] == 1
    with q.slot("https://ark.example.com/v3", "custom"):
        assert q.status()["endpoints"][-1]["limit"] == 2
