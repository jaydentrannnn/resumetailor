"""Sync fills and async monitors share the extension relay without real connections."""

from __future__ import annotations

import asyncio
import threading

import pytest

from resume_tailor.apply.driver import browser


@pytest.fixture
def relay_lease(monkeypatch):
    lock = threading.Lock()
    monkeypatch.setattr(browser, "_RELAY_LEASE", lock)
    monkeypatch.setenv("BROWSER_MODE", "extension")
    return lock


@pytest.mark.asyncio
async def test_background_observation_skips_active_sync_foreground(relay_lease, monkeypatch):
    async def unexpected_wait(_delay):
        raise AssertionError("A background observation must not wait for a foreground fill")

    monkeypatch.setattr(browser.asyncio, "sleep", unexpected_wait)
    with browser.relay_slot():
        assert relay_lease.locked()
        with pytest.raises(RuntimeError, match=browser.RELAY_BUSY):
            async with browser.async_relay_slot(background=True):
                pytest.fail("A monitor entered the relay while a fill owned it")
        assert relay_lease.locked()
    assert not relay_lease.locked()


@pytest.mark.asyncio
async def test_async_foreground_waits_until_background_releases(relay_lease):
    attempting = asyncio.Event()
    entered = asyncio.Event()

    async def fill():
        attempting.set()
        async with browser.async_relay_slot():
            entered.set()

    async with browser.async_relay_slot(background=True):
        waiter = asyncio.create_task(fill())
        await asyncio.wait_for(attempting.wait(), timeout=1)
        assert not entered.is_set()
        assert relay_lease.locked()
    await asyncio.wait_for(waiter, timeout=1)
    assert entered.is_set()
    assert not relay_lease.locked()


@pytest.mark.asyncio
async def test_sync_foreground_waits_until_async_background_releases(relay_lease):
    attempting, entered = threading.Event(), threading.Event()
    failures = []

    def fill():
        try:
            attempting.set()
            with browser.relay_slot():
                entered.set()
        except BaseException as exc:
            failures.append(exc)

    async with browser.async_relay_slot(background=True):
        waiter = threading.Thread(target=fill, daemon=True)
        waiter.start()
        assert await asyncio.to_thread(attempting.wait, 1)
        assert not entered.is_set()
    await asyncio.to_thread(waiter.join, 1)
    assert not waiter.is_alive()
    assert not failures
    assert entered.is_set()
    assert not relay_lease.locked()


@pytest.mark.asyncio
async def test_cancelling_background_owner_releases_relay(relay_lease):
    entered = asyncio.Event()

    async def observe():
        async with browser.async_relay_slot(background=True):
            entered.set()
            await asyncio.Future()

    owner = asyncio.create_task(observe())
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert relay_lease.locked()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert not relay_lease.locked()
    with browser.relay_slot():
        assert relay_lease.locked()


@pytest.mark.asyncio
async def test_cancelling_waiter_does_not_release_foreground_owners_lease(relay_lease):
    attempting = asyncio.Event()

    async def fill():
        attempting.set()
        async with browser.async_relay_slot():
            pytest.fail("The waiting fill entered before the owning fill exited")

    with browser.relay_slot():
        waiter = asyncio.create_task(fill())
        await asyncio.wait_for(attempting.wait(), timeout=1)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert relay_lease.locked()
    assert not relay_lease.locked()


def test_sync_foreground_has_a_bounded_wait_and_does_not_release_unowned_lease(monkeypatch):
    class BusyLease:
        def __init__(self):
            self.timeout = None

        def acquire(self, *, timeout):
            self.timeout = timeout
            return False

        def release(self):
            pytest.fail("A failed acquisition must not release somebody else's lease")

    lease = BusyLease()
    monkeypatch.setattr(browser, "_RELAY_LEASE", lease)
    monkeypatch.setenv("BROWSER_MODE", "extension")
    with pytest.raises(RuntimeError, match=browser.RELAY_BUSY), browser.relay_slot():
        pytest.fail("The busy relay unexpectedly became available")
    assert lease.timeout == 25


def test_sync_owner_releases_relay_after_failure(relay_lease):
    with pytest.raises(ValueError, match="observation failed"), browser.relay_slot():
        raise ValueError("observation failed")
    assert not relay_lease.locked()


@pytest.mark.asyncio
async def test_cdp_mode_allows_sync_and_async_users_without_global_lease(relay_lease, monkeypatch):
    monkeypatch.setenv("BROWSER_MODE", "cdp")
    relay_lease.acquire()
    try:
        with browser.relay_slot():
            async with browser.async_relay_slot(background=True), browser.async_relay_slot():
                assert relay_lease.locked()
        assert relay_lease.locked()
    finally:
        relay_lease.release()
