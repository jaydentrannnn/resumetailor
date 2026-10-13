"""Apply deadline bounding accepts numeric and SDK HTTP timeout objects."""

from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import httpx2
import pytest

from resume_tailor.infra import llm, llm_telemetry


@pytest.mark.parametrize(
    ("original", "budget", "expected"),
    [
        (120, 15, 15),
        (5, 15, 5),
        (4.5, 4, 4),
        (60, 0, 0.001),
    ],
)
def test_numeric_timeout_bounds_and_disables_sdk_retries(original, budget, expected):
    client = SimpleNamespace(timeout=original, max_retries=2)
    result = llm.bound_client_timeout(client, budget)
    assert result is client
    assert client.timeout == expected and client.max_retries == 0


@pytest.mark.parametrize("timeout_type", [httpx.Timeout, httpx2.Timeout])
def test_sdk_timeout_object_caps_each_phase_without_float_cast(timeout_type):
    client = SimpleNamespace(
        timeout=timeout_type(connect=2, read=120, write=5, pool=None), max_retries=2
    )
    result = llm.bound_client_timeout(client, 15)
    assert result is client and isinstance(client.timeout, timeout_type)
    assert client.timeout.connect == 2
    assert client.timeout.read == 15
    assert client.timeout.write == 5
    assert client.timeout.pool == 15
    assert client.max_retries == 0


@pytest.mark.parametrize("timeout_type", [httpx.Timeout, httpx2.Timeout])
def test_repeated_sdk_timeout_bounding_never_increases_phase_limits(timeout_type):
    client = SimpleNamespace(timeout=timeout_type(3), max_retries=3)
    llm.bound_client_timeout(client, 10)
    assert client.timeout.read == 3
    llm.bound_client_timeout(client, 1)
    assert all(
        getattr(client.timeout, phase) == 1 for phase in ("connect", "read", "write", "pool")
    )


def test_telemetry_wrapper_forwards_timeout_and_retries_and_keeps_parse_instrumentation(
    monkeypatch,
):
    calls, parsed = [], []

    @contextmanager
    def _call(*args):
        calls.append(args)
        yield

    def _parse(**kwargs):
        parsed.append(kwargs)
        return "same provider response"

    monkeypatch.setattr(llm_telemetry.telemetry, "call", _call)
    raw = SimpleNamespace(
        timeout=httpx.Timeout(120), max_retries=2, messages=SimpleNamespace(parse=_parse)
    )
    wrapped = llm_telemetry.Client(raw, "apply_answer", "claude")
    result = llm.bound_client_timeout(wrapped, 15)
    assert result is wrapped and wrapped.raw is raw
    assert raw.timeout.read == 15 and raw.max_retries == 0
    assert "timeout" not in wrapped.__dict__ and "max_retries" not in wrapped.__dict__
    assert wrapped.messages.parse(model="synthetic-model", messages=[]) == "same provider response"
    assert calls == [("apply_answer", "synthetic-model", "claude")]
    assert parsed == [{"model": "synthetic-model", "messages": []}]
