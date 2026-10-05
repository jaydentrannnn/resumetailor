"""Process-wide FIFO admission for every physical model request.

Threads and async callers share the same endpoint capacity. Limits are app-wide,
not workspace settings; a model name never creates another pool on one server.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import wraps
from inspect import iscoroutinefunction
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field, field_validator

from resume_tailor import config
from resume_tailor.pipeline.events import ProgressCallback, emit


def endpoint_key(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "localhost"
    elif ":" in host:
        host = f"[{host}]"
    port = parts.port
    netloc = host + (
        f":{port}" if port and port != {"http": 80, "https": 443}.get(parts.scheme) else ""
    )
    return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), "", ""))


class QueueSettings(BaseModel):
    local_concurrency: int = Field(default=1, ge=1, le=16)
    cloud_concurrency: int = Field(default=3, ge=1, le=16)
    endpoint_limits: dict[str, int] = Field(default_factory=dict)

    @field_validator("endpoint_limits")
    @classmethod
    def validate_limits(cls, values: dict[str, int]) -> dict[str, int]:
        result = {}
        for url, limit in values.items():
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.hostname or not 1 <= limit <= 16:
                raise ValueError("Endpoint limits need an HTTP(S) URL and a limit from 1 to 16")
            result[endpoint_key(url)] = limit
        return result


@dataclass
class _Pool:
    local: bool
    active: int = 0
    waiting: deque[object] = field(default_factory=deque)
    cooldown_until: float = 0


_OBSERVER: ContextVar[tuple[ProgressCallback | None, Callable[[], None] | None]] = ContextVar(
    "model_queue_observer", default=(None, None)
)


def settings_path():
    return config.DATA_ROOT / "model_queue.json"


@contextmanager
def observe(
    on_event: ProgressCallback | None = None, check_cancelled: Callable[[], None] | None = None
) -> Iterator[None]:
    token = _OBSERVER.set((on_event, check_cancelled))
    try:
        yield
    finally:
        _OBSERVER.reset(token)


def observe_progress(fn):
    """Bridge Apply's string progress/cancellation hooks into model admission."""

    def context(kwargs):
        progress = kwargs.get("on_progress")
        cancelled = kwargs.get("should_cancel")

        def check():
            if cancelled and cancelled():
                raise RuntimeError("Application cancelled while waiting for model capacity")

        return observe(lambda event: progress(event.message) if progress else None, check)

    if iscoroutinefunction(fn):

        @wraps(fn)
        async def async_run(*args, **kwargs):
            with context(kwargs):
                return await fn(*args, **kwargs)

        return async_run

    @wraps(fn)
    def run(*args, **kwargs):
        with context(kwargs):
            return fn(*args, **kwargs)

    return run


def _is_local(url: str, origin: str) -> bool:
    host = urlsplit(url).hostname or ""
    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return origin == "lmstudio"


class RequestQueue:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._pools: dict[str, _Pool] = {}
        self._settings = QueueSettings()
        self._stamp: tuple[str, int] | None = None

    def settings(self) -> QueueSettings:
        with self._condition:
            path = settings_path()
            stamp = (str(path), path.stat().st_mtime_ns if path.exists() else 0)
            if stamp != self._stamp:
                self._settings = (
                    QueueSettings.model_validate_json(path.read_text("utf-8"))
                    if path.exists()
                    else QueueSettings()
                )
                self._stamp = stamp
            return self._settings.model_copy(deep=True)

    def save_settings(self, settings: QueueSettings) -> None:
        with self._condition:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix(".partial")
            partial.write_text(settings.model_dump_json(indent=2), "utf-8")
            os.replace(partial, path)
            self._stamp = None
            self.settings()
            self._condition.notify_all()

    def _limit(self, key: str, pool: _Pool) -> int:
        settings = self.settings()
        return settings.endpoint_limits.get(
            key, settings.local_concurrency if pool.local else settings.cloud_concurrency
        )

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "settings": self.settings().model_dump(),
                "endpoints": [
                    {
                        "endpoint": key,
                        "local": pool.local,
                        "limit": self._limit(key, pool),
                        "active": pool.active,
                        "waiting": len(pool.waiting),
                        "cooldown_seconds": max(
                            0, round(pool.cooldown_until - time.monotonic(), 1)
                        ),
                    }
                    for key, pool in self._pools.items()
                ],
            }

    def _enqueue(self, url: str, origin: str) -> tuple[str, _Pool, object]:
        key = endpoint_key(url)
        with self._condition:
            pool = self._pools.setdefault(key, _Pool(local=_is_local(key, origin)))
            if len(pool.waiting) >= 100:
                raise RuntimeError(
                    "Model request queue is full; try again after pending work finishes"
                )
            ticket = object()
            pool.waiting.append(ticket)
            return key, pool, ticket

    def _admit(self, key: str, pool: _Pool, ticket: object, deadline: float) -> bool:
        _, cancelled = _OBSERVER.get()
        if cancelled:
            cancelled()
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for model capacity")
        if (
            pool.waiting[0] is ticket
            and pool.active < self._limit(key, pool)
            and time.monotonic() >= pool.cooldown_until
        ):
            pool.waiting.popleft()
            pool.active += 1
            self._condition.notify_all()
            return True
        return False

    def _cleanup(self, pool: _Pool, ticket: object, admitted: bool) -> None:
        with self._condition:
            if admitted:
                pool.active -= 1
            elif ticket in pool.waiting:
                pool.waiting.remove(ticket)
            self._condition.notify_all()

    def _waiting(self, key: str) -> None:
        callback, _ = _OBSERVER.get()
        emit(callback, "model_wait", "Waiting for model capacity", endpoint=key)

    @contextmanager
    def slot(self, url: str, origin: str = "", *, deadline: float | None = None) -> Iterator[None]:
        deadline = deadline if deadline is not None else time.monotonic() + config.LLM_TIMEOUT
        key, pool, ticket = self._enqueue(url, origin)
        admitted = False
        announced = False
        try:
            with self._condition:
                while not (admitted := self._admit(key, pool, ticket, deadline)):
                    if not announced:
                        self._waiting(key)
                        announced = True
                    self._condition.wait(min(0.1, max(0, deadline - time.monotonic())))
            yield
        finally:
            self._cleanup(pool, ticket, admitted)

    @asynccontextmanager
    async def async_slot(self, url: str, origin: str = "", *, deadline: float | None = None):
        deadline = deadline if deadline is not None else time.monotonic() + config.LLM_TIMEOUT
        key, pool, ticket = self._enqueue(url, origin)
        admitted = False
        announced = False
        try:
            while True:
                with self._condition:
                    admitted = self._admit(key, pool, ticket, deadline)
                if admitted:
                    break
                if not announced:
                    self._waiting(key)
                    announced = True
                await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
            yield
        finally:
            self._cleanup(pool, ticket, admitted)

    def rate_limited(self, url: str, response: httpx.Response) -> None:
        if response.status_code != 429:
            return
        delay = 2.0
        header = response.headers.get("Retry-After", "")
        try:
            delay = float(header)
        except ValueError:
            with suppress(TypeError, ValueError, OverflowError):
                delay = (parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()
        if not 0 <= delay < float("inf"):
            delay = 2.0
        with self._condition:
            pool = self._pools.get(endpoint_key(url))
            if pool:
                pool.cooldown_until = max(pool.cooldown_until, time.monotonic() + delay)
                self._condition.notify_all()


queue = RequestQueue()


class ScheduledTransport(httpx.HTTPTransport):
    """Covers Anthropic SDK retries at the physical HTTP boundary."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        endpoint = str(request.url.copy_with(path="", query=None))
        from . import telemetry

        retry = int(request.headers.get("x-stainless-retry-count", "0"))
        with telemetry.request("anthropic", retry=retry) as measured, \
                queue.slot(endpoint, "anthropic"):
            measured.admitted()
            response = super().handle_request(request)
            response.read()
            measured.response(response)
            queue.rate_limited(endpoint, response)
            return response


class AsyncScheduledTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        from . import telemetry

        endpoint = str(request.url.copy_with(path="", query=None))
        with_deadline = time.monotonic() + min(config.LLM_TIMEOUT, 60)
        with telemetry.request("anthropic") as measured:
            async with queue.async_slot(endpoint, "anthropic", deadline=with_deadline):
                measured.admitted()
                response = await super().handle_async_request(request)
                await response.aread()
                measured.response(response)
                queue.rate_limited(endpoint, response)
                return response
