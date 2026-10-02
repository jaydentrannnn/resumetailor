"""Shared physical-request limits across threads and event loops, without network."""

import asyncio
import threading
import time

import httpx
import pytest

from resume_tailor.infra import model_queue


def test_endpoint_aliases_and_cloud_ollama_classification():
    q = model_queue.queue
    with q.slot("http://localhost:11434/v1/", "ollama"):
        assert q.status()["endpoints"][0]["limit"] == 1
        with (
            pytest.raises(TimeoutError),
            q.slot(
                "http://127.0.0.1:11434/v1",
                "ollama",
                deadline=time.monotonic() + 0.01,
            ),
        ):
            pytest.fail("A second model on the same daemon bypassed capacity")
    with q.slot("https://ollama.com/v1", "ollama"):
        assert q.status()["endpoints"][-1]["limit"] == 3


def test_cloud_three_in_flight_and_next_starts_when_one_finishes():
    q = model_queue.queue
    endpoint = "https://api.example.com/v1"
    entered = [threading.Event() for _ in range(4)]
    release = [threading.Event() for _ in range(4)]

    def request(index):
        with q.slot(endpoint):
            entered[index].set()
            assert release[index].wait(2)

    threads = [threading.Thread(target=request, args=(i,)) for i in range(4)]
    try:
        for i in range(3):
            threads[i].start()
            assert entered[i].wait(1)
        threads[3].start()
        assert not entered[3].wait(0.02)
        release[0].set()
        assert entered[3].wait(1)  # Other two still running: no fixed batch pause.
        assert q.status()["endpoints"][0]["active"] == 3
    finally:
        for event in release:
            event.set()
        for thread in threads:
            if thread.ident:
                thread.join(2)
    assert q.status()["endpoints"][0]["active"] == 0


def test_async_and_sync_share_capacity_and_cancellation_cleans_up():
    q = model_queue.queue
    endpoint = "http://localhost:11434/v1"
    entered = threading.Event()
    release = threading.Event()

    def sync_request():
        with q.slot(endpoint):
            entered.set()
            release.wait(2)

    thread = threading.Thread(target=sync_request)
    thread.start()
    assert entered.wait(1)

    async def scenario():
        async def request():
            async with q.async_slot(endpoint):
                pytest.fail("Async request bypassed the sync request")

        task = asyncio.create_task(request())
        await asyncio.sleep(0.01)
        assert q.status()["endpoints"][0]["waiting"] == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert q.status()["endpoints"][0]["waiting"] == 0
        # The event loop remains free while queued, and an independent cloud is free.
        async with q.async_slot("https://api.example.com/v1"):
            pass

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        thread.join(2)


def test_provider_cooldown_and_error_release():
    q = model_queue.queue
    endpoint = "https://api.example.com/v1"
    with pytest.raises(ValueError), q.slot(endpoint):
        raise ValueError("request failed")
    assert q.status()["endpoints"][0]["active"] == 0
    with q.slot(endpoint):
        q.rate_limited(endpoint, httpx.Response(429, headers={"Retry-After": "30"}))
    assert q.status()["endpoints"][0]["cooldown_seconds"] > 29
    with (
        pytest.raises(TimeoutError, match="capacity"),
        q.slot(
            endpoint,
            deadline=time.monotonic() + 0.01,
        ),
    ):
        pytest.fail("Provider cooldown was bypassed")
    assert q.status()["endpoints"][0]["waiting"] == 0


def test_limits_persist_and_live_changes_do_not_interrupt_active_requests():
    q = model_queue.queue
    endpoint = "https://api.example.com/v1"
    q.save_settings(model_queue.QueueSettings(endpoint_limits={endpoint: 1}))
    fresh = model_queue.RequestQueue()
    assert fresh.settings().endpoint_limits[endpoint] == 1
    with q.slot(endpoint):
        q.save_settings(model_queue.QueueSettings(endpoint_limits={endpoint: 2}))
        with q.slot(endpoint):
            assert q.status()["endpoints"][0]["active"] == 2


def test_waiting_progress_and_cancel_callback_do_not_leak_tickets():
    q = model_queue.queue
    seen = []
    endpoint = "http://localhost:11434/v1"
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise RuntimeError("cancelled")

    with (
        q.slot(endpoint),
        model_queue.observe(seen.append, cancelled),
        pytest.raises(RuntimeError, match="cancelled"),
        q.slot(endpoint),
    ):
        pass
    assert seen[0].stage == "model_wait"
    assert q.status()["endpoints"][0]["waiting"] == 0


def test_anthropic_transport_holds_slot_through_response_body_and_cooldown(monkeypatch):
    q = model_queue.queue
    observed = []

    def send(transport, request):
        observed.append(q.status()["endpoints"][0]["active"])
        return httpx.Response(429, headers={"Retry-After": "30"}, content=b"rate limited")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", send)
    with model_queue.ScheduledTransport() as transport:
        response = transport.handle_request(
            httpx.Request("POST", "https://api.example.com/v1/messages")
        )
    assert response.content == b"rate limited"
    assert observed == [1]
    endpoint = q.status()["endpoints"][0]
    assert endpoint["active"] == 0
    assert endpoint["cooldown_seconds"] > 29


def test_anthropic_async_transport_admits_physical_attempt(monkeypatch):
    q = model_queue.queue

    async def send(transport, request):
        assert q.status()["endpoints"][0]["active"] == 1
        return httpx.Response(200, content=b"reply")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)

    async def scenario():
        async with model_queue.AsyncScheduledTransport() as transport:
            response = await transport.handle_async_request(
                httpx.Request("POST", "https://api.example.com/v1/messages")
            )
        assert response.content == b"reply"

    asyncio.run(scenario())
    assert q.status()["endpoints"][0]["active"] == 0
