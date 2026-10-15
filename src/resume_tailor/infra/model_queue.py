"""Process-wide FIFO admission for every physical model request.

Threads and async callers share the same endpoint capacity. Limits are app-wide,
not workspace settings; a model name never creates another pool on one server.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
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
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import httpx2
from pydantic import BaseModel, Field, field_validator

from resume_tailor import config
from resume_tailor.pipeline.events import ProgressCallback, emit

log = logging.getLogger(__name__)

#: Successful calls in a row before a halved limit steps back up by one.
_RECOVER_AFTER = 20
#: Cooldowns within this window that mark a pool used up (`_EXHAUSTED_FOR_S`).
_COOLDOWN_WINDOW_S = 120
_COOLDOWNS_TO_EXHAUST = 3
_EXHAUSTED_FOR_S = 600.0
#: Default concurrency for an endpoint by the plan its model is on.
PLAN_CONCURRENCY = {"free": 1, "subscription": 2, "paid": 4, "local": 1}


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


class QueueLimits(BaseModel):
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


class QueueSettings(QueueLimits):
    custom_mode: bool = False
    custom_settings: QueueLimits | None = None


@dataclass
class _Pool:
    local: bool
    active: int = 0
    waiting: deque[object] = field(default_factory=deque)
    cooldown_until: float = 0
    #: Halved after each 429 (never below 1); None = the configured limit.
    limit_cut: int | None = None
    successes: int = 0
    cooldowns: deque[float] = field(default_factory=deque)
    #: Set when the provider's quota looks used up (a per-day quota, or repeated 429s).
    exhausted_until: float = 0
    rate_limited_today: int = 0
    day: str = ""
    quota: str = ""


@dataclass(frozen=True)
class RateLimit:
    """What a 429 body says: the quota id and how long to wait, when it says so."""

    quota: str = ""
    retry_after: float | None = None

    @property
    def per_day(self) -> bool:
        return "perday" in self.quota.casefold().replace("_", "")


def parse_rate_limit(body: str) -> RateLimit:
    """Gemini's ``QuotaFailure`` quota id and ``RetryInfo.retryDelay`` ("37s") from a 429
    body; an empty `RateLimit` for anything else."""
    try:
        data = json.loads(body)
        # Gemini's OpenAI-compatible endpoint wraps the error in a one-item list.
        if isinstance(data, list) and data:
            data = data[0]
        details = data.get("error", {}).get("details", [])
    except (ValueError, AttributeError):
        details = []
    quota, retry = "", None
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        for violation in detail.get("violations") or []:
            if isinstance(violation, dict) and violation.get("quotaId") and not quota:
                quota = str(violation["quotaId"])
        delay = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(detail.get("retryDelay") or ""))
        if delay:
            retry = float(delay.group(1))
    return RateLimit(quota=quota, retry_after=retry)


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


def _file_stamp(path: Path) -> tuple[str, int, int, int]:
    """What tells a re-read settings file apart from the one already loaded.

    The modified time alone misses a second save within the same clock tick (seen on
    Windows CI); an atomic save is a new file, so its inode/file index and size change too.
    """
    if not path.exists():
        return (str(path), 0, 0, 0)
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino)


class RequestQueue:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._pools: dict[str, _Pool] = {}
        self._settings = QueueSettings()
        self._stamp: tuple[str, int, int, int] | None = None
        self._plans: dict[str, int] = {}
        self._file_plans: dict[str, int] = {}
        self._plan_stamp: tuple[str, int, int, int] | None = None
        self._advanced_enabled = True
        self._roles: dict[str, str] = {}

    def settings(self) -> QueueSettings:
        with self._condition:
            path = settings_path()
            stamp = _file_stamp(path)
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

    def set_plan(self, url: str, plan: str | None) -> None:
        """Default concurrency for ``url`` from its model's plan (`PLAN_CONCURRENCY`);
        an explicit per-server limit in the settings still wins."""
        with self._condition:
            key = endpoint_key(url)
            if plan in PLAN_CONCURRENCY:
                self._plans[key] = PLAN_CONCURRENCY[plan]
            else:
                self._plans.pop(key, None)
            self._condition.notify_all()

    def _model_plans(self) -> dict[str, int]:
        """Default limits from the Light/Heavy models' plans (`app_settings`), re-read
        when that file changes; `set_plan` entries win."""
        from resume_tailor import app_settings

        target = app_settings.path()
        stamp = _file_stamp(target)
        if stamp != self._plan_stamp:
            self._plan_stamp = stamp
            saved = app_settings.load()
            self._advanced_enabled = saved.get("ai_advanced_enabled", True)
            ai_models = saved.get("ai_models") or {}
            self._file_plans = _plans_from(ai_models)
            self._roles = _role_endpoints(ai_models)
        return {**self._file_plans, **self._plans}

    def _configured(self, key: str, pool: _Pool) -> int:
        settings = self.settings()
        plans = self._model_plans()
        if not self._advanced_enabled:
            settings = QueueSettings()
        if key in settings.endpoint_limits:
            return settings.endpoint_limits[key]
        if key in plans:
            return plans[key]
        return settings.local_concurrency if pool.local else settings.cloud_concurrency

    def _limit(self, key: str, pool: _Pool) -> int:
        configured = self._configured(key, pool)
        return min(configured, pool.limit_cut) if pool.limit_cut else configured

    def exhausted_for(self, url: str) -> float:
        """Seconds until ``url``'s provider quota should be usable again; 0 when it is."""
        with self._condition:
            pool = self._pools.get(endpoint_key(url))
            return max(0.0, pool.exhausted_until - time.monotonic()) if pool else 0.0

    def status(self) -> dict[str, Any]:
        with self._condition:
            self._model_plans()
            return {
                "settings": self.settings().model_dump(),
                #: The server each saved task model sends its requests to.
                "roles": dict(self._roles),
                "endpoints": [
                    {
                        "endpoint": key,
                        "local": pool.local,
                        "limit": self._configured(key, pool),
                        "limit_effective": self._limit(key, pool),
                        "exhausted_seconds": max(
                            0, round(pool.exhausted_until - time.monotonic(), 1)
                        ),
                        "rate_limited_today": (
                            pool.rate_limited_today if pool.day == _today() else 0
                        ),
                        "quota": pool.quota,
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

    def rate_limited(self, url: str, response: httpx.Response | httpx2.Response) -> None:
        """Every response passes here: a 429 halves the pool's limit and cools it down
        (marking it used up after a per-day quota or repeated 429s); a success counts
        toward stepping a halved limit back up."""
        key = endpoint_key(url)
        if response.status_code != 429:
            if response.status_code < 400:
                self._succeeded(key)
            return
        body = ""
        with suppress(Exception):
            body = response.text
        limit = parse_rate_limit(body)
        delay = limit.retry_after if limit.retry_after is not None else 2.0
        header = response.headers.get("Retry-After", "")
        if header:
            try:
                delay = float(header)
            except ValueError:
                with suppress(TypeError, ValueError, OverflowError):
                    delay = (parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()
        if not 0 <= delay < float("inf"):
            delay = 2.0
        log.warning(
            "HTTP 429 from %s (quota %s, retry in %.0fs): %s",
            key, limit.quota or "unknown", delay, " ".join(body.split())[:300],
        )
        with self._condition:
            pool = self._pools.get(key)
            if not pool:
                return
            now = time.monotonic()
            pool.cooldown_until = max(pool.cooldown_until, now + delay)
            pool.limit_cut = max(1, self._limit(key, pool) // 2)
            pool.successes = 0
            today = _today()
            if pool.day != today:
                pool.day, pool.rate_limited_today = today, 0
            pool.rate_limited_today += 1
            pool.quota = limit.quota or pool.quota
            pool.cooldowns.append(now)
            while pool.cooldowns and now - pool.cooldowns[0] > _COOLDOWN_WINDOW_S:
                pool.cooldowns.popleft()
            if limit.per_day or len(pool.cooldowns) >= _COOLDOWNS_TO_EXHAUST:
                wait = limit.retry_after if limit.retry_after else _EXHAUSTED_FOR_S
                pool.exhausted_until = max(pool.exhausted_until, now + wait)
                log.warning("%s looks used up; pausing it for %.0fs", key, wait)
            self._condition.notify_all()

    def _succeeded(self, key: str) -> None:
        with self._condition:
            pool = self._pools.get(key)
            if not pool or not pool.limit_cut:
                return
            pool.successes += 1
            if pool.successes >= _RECOVER_AFTER:
                pool.successes = 0
                pool.limit_cut += 1
                if pool.limit_cut >= self._configured(key, pool):
                    pool.limit_cut = None
                self._condition.notify_all()


def _saved_models(ai_models: dict[str, Any]) -> Iterator[tuple[str, Any, str]]:
    """``(role, selection, endpoint)`` for each saved task model that has a server."""
    from resume_tailor.model_selection import ModelSelection

    for role in ("light", "heavy"):
        if not isinstance(ai_models.get(role), dict):
            continue
        try:
            selection = ModelSelection.model_validate(ai_models[role])
            backend = config._backends_for(selection.spec(role))["answer"]  # noqa: SLF001
        except Exception:  # noqa: BLE001 - an incomplete draft has no server yet
            continue
        url = backend.base_url or (
            "https://api.anthropic.com" if backend.provider == "anthropic" else ""
        )
        if url:
            yield role, selection, endpoint_key(url)


def _plans_from(ai_models: dict[str, Any]) -> dict[str, int]:
    """``{endpoint: limit}`` for each saved task model whose plan is known."""
    limits: dict[str, int] = {}
    for _role, selection, key in _saved_models(ai_models):
        plan = selection.effective_plan()
        if plan is not None:
            limits[key] = PLAN_CONCURRENCY[plan]
    return limits


def _role_endpoints(ai_models: dict[str, Any]) -> dict[str, str]:
    return {role: key for role, _selection, key in _saved_models(ai_models)}


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


queue = RequestQueue()


class ScheduledTransport(httpx2.HTTPTransport):
    """Covers Anthropic SDK retries at the physical HTTP boundary."""

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
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


class AsyncScheduledTransport(httpx2.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
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
