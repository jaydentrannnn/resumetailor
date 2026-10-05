"""Run-local measurements. Only numeric usage and allowlisted metadata reach disk."""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

_CURRENT: contextvars.ContextVar[Collector | None] = contextvars.ContextVar(
    "telemetry", default=None
)
_SCOPE = contextvars.ContextVar("telemetry_scope", default=("", ""))
_CALL = contextvars.ContextVar("telemetry_call", default="")
_MODEL = contextvars.ContextVar("telemetry_model", default="")
_REASON = contextvars.ContextVar("telemetry_reason", default="generation")
_ARTIFACT_LOCK = threading.Lock()
_LOG = logging.getLogger(__name__)
VERSIONS = {"telemetry": 1, "number_retention": 1, "entry_ranking": "best_three"}


def current() -> Collector | None:
    return _CURRENT.get()


class Collector:
    def __init__(self, output: Path, *, run_id: str, archive_id: str, source: str):
        self.output = output
        self.started = time.perf_counter()
        self.lock = threading.Lock()
        self.data: dict[str, Any] = {
            "schema_version": 1,
            "versions": dict(VERSIONS),
            "run_id": run_id,
            "archive_id": archive_id,
            "source": source,
            "started_at": datetime.now(UTC).isoformat(),
            "status": "running",
            "resume_ready_ms": None,
            "spans": [],
            "requests": [],
            "events": [],
        }

    def ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 3)

    def append(self, key: str, value: dict) -> None:
        with self.lock:
            self.data[key].append(value)

    def save(self) -> None:
        try:
            directory = self.output / "telemetry"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{self.data['run_id']}.json"
            partial = path.with_suffix(".partial")
            partial.write_text(json.dumps(self.data, indent=2, allow_nan=False), "utf-8")
            partial.replace(path)
        except (OSError, ValueError, TypeError):
            _LOG.warning("Could not persist run telemetry")


@contextmanager
def recording(
    output: Path, *, run_id: str | None = None, archive_id: str = "", source: str = "cli"
) -> Iterator[Collector]:
    collector = Collector(
        output, run_id=run_id or uuid.uuid4().hex, archive_id=archive_id, source=source
    )
    token = _CURRENT.set(collector)
    try:
        yield collector
        if collector.data["status"] == "running":
            collector.data["status"] = "succeeded"
    except BaseException as exc:
        collector.data["status"] = (
            "cancelled" if type(exc).__name__ in {"JobCancelled", "CancelledError"} else "failed"
        )
        raise
    finally:
        collector.data["finished_at"] = datetime.now(UTC).isoformat()
        collector.data["completion_ms"] = collector.ms()
        collector.save()
        _CURRENT.reset(token)


def ready() -> None:
    if collector := current():
        collector.data["resume_ready_ms"] = collector.ms()


def configure() -> None:
    from .. import config

    if collector := current():
        collector.data["routing"] = {
            p: {
                "origin": config.backend_for(p).origin,
                "model": config.model_for(p),
                "fingerprint": config.fingerprint(p),
            }
            for p in config.PURPOSES
        }


def event(
    stage: str, *, cached: bool | None = None, skipped: bool = False, **counts: int | float | bool
) -> None:
    if collector := current():
        collector.append(
            "events",
            {
                "stage": stage,
                "at_ms": collector.ms(),
                "cached": cached,
                "skipped": skipped,
                **counts,
            },
        )


@contextmanager
def span(stage: str, operation: str = "", *, kind: str = "stage") -> Iterator[dict]:
    collector = current()
    scope = _SCOPE.set((stage, operation or stage))
    item: dict[str, Any] = {"stage": stage, "operation": operation or stage, "kind": kind}
    started = time.perf_counter()
    if collector:
        item["start_ms"] = collector.ms()
    try:
        yield item
        item["status"] = "succeeded"
    except BaseException:
        item["status"] = "failed"
        raise
    finally:
        item["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if collector:
            collector.append("spans", item)
        _SCOPE.reset(scope)


def stage(name: str, operation: str = ""):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if current() is None or _SCOPE.get() == (name, operation or name):
                return fn(*args, **kwargs)
            with span(name, operation):
                return fn(*args, **kwargs)

        return wrapped

    return decorate


@contextmanager
def call(purpose: str, model: str, origin: str) -> Iterator[None]:
    operation = _SCOPE.get()[1] or purpose
    token = _CALL.set(uuid.uuid4().hex)
    model_token = _MODEL.set(model)
    reason = _REASON.set("generation")
    try:
        with span(purpose, operation, kind="llm_call") as item:
            item.update(call_id=_CALL.get(), model=model, origin=origin)
            yield
    finally:
        _REASON.reset(reason)
        _CALL.reset(token)
        _MODEL.reset(model_token)


def retry_reason(reason: str) -> None:
    _REASON.set(reason)


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage(body: dict, origin: str) -> dict[str, int | None]:
    raw = body.get("usage") or {}
    if not isinstance(raw, dict):
        raw = {}
    cached = write = reasoning = None
    if origin == "anthropic":
        inp, out = _number(raw.get("input_tokens")), _number(raw.get("output_tokens"))
        cached = _number(raw.get("cache_read_input_tokens"))
        write = _number(raw.get("cache_creation_input_tokens"))
        # Anthropic's input_tokens excludes cache reads/writes; missing cache fields
        # mean no cache use in its wire format, not missing total usage.
        total = None if inp is None else inp + (cached or 0) + (write or 0)
    else:
        total = _number(raw.get("prompt_tokens"))
        out = _number(raw.get("completion_tokens"))
        details = raw.get("prompt_tokens_details") or {}
        completion = raw.get("completion_tokens_details") or {}
        if isinstance(details, dict):
            cached = _number(details.get("cached_tokens"))
        if isinstance(completion, dict):
            reasoning = _number(completion.get("reasoning_tokens"))
    return {
        "input_tokens": total,
        "output_tokens": out,
        "cached_input_tokens": cached,
        "cache_creation_tokens": write,
        "reasoning_tokens": reasoning,
    }


class Request:
    def __init__(self, origin: str, model: str, retry: int):
        self.collector = current()
        self.start = time.perf_counter()
        self.sent: float | None = None
        self.item: dict[str, Any] = {
            "call_id": _CALL.get(),
            "stage": _SCOPE.get()[0],
            "operation": _SCOPE.get()[1],
            "origin": origin,
            "model": model or _MODEL.get(),
            "reason": "http_retry" if retry else _REASON.get(),
            "retry_index": retry,
            "status_code": None,
            "finish_reason": None,
            **usage({}, origin),
        }
        if self.collector:
            self.item["start_ms"] = self.collector.ms()

    def admitted(self) -> None:
        self.sent = time.perf_counter()

    def response(self, response) -> None:
        if not self.collector:
            return
        self.item["status_code"] = response.status_code
        try:
            body = response.json()
            if not isinstance(body, dict):
                return
            self.item.update(usage(body, self.item["origin"]))
            choices = body.get("choices") or []
            finish = choices[0].get("finish_reason") if choices else body.get("stop_reason")
            if finish in {
                "stop",
                "length",
                "end_turn",
                "max_tokens",
                "tool_use",
                "stop_sequence",
                "content_filter",
            }:
                self.item["finish_reason"] = finish
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            pass  # Measurement must never interfere with the actual response parser.

    def finish(self) -> None:
        if self.collector:
            now = time.perf_counter()
            self.item["queue_ms"] = round(((self.sent or now) - self.start) * 1000, 3)
            self.item["request_ms"] = round((now - self.sent) * 1000, 3) if self.sent else 0
            self.collector.append("requests", self.item)


@contextmanager
def request(origin: str, model: str = "", retry: int = 0) -> Iterator[Request]:
    item = Request(origin, model, retry)
    try:
        yield item
    finally:
        item.finish()


def artifact_use(output: Path, archive_id: str, action: str) -> None:
    """Append consumption after a run finishes; no artifact contents are recorded."""
    if action not in {"copy", "download", "autofill"}:
        return
    try:
        directory = output / "telemetry"
        directory.mkdir(parents=True, exist_ok=True)
        row = {
            "archive_id": archive_id,
            "artifact": "skills",
            "action": action,
            "at": datetime.now(UTC).isoformat(),
        }
        with _ARTIFACT_LOCK, (directory / "artifact_usage.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        _LOG.warning("Could not persist artifact consumption")
