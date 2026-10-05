"""Measured retries, isolation and privacy without a model endpoint or document engine."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from resume_tailor import config
from resume_tailor.infra import llm, llm_telemetry, model_queue, telemetry, usage_report


class Sample(BaseModel):
    title: str


def completion(value, *, usage=None, finish="stop", status=200):
    return httpx.Response(
        status,
        json={
            "choices": [{"message": {"content": json.dumps(value)}, "finish_reason": finish}],
            **({"usage": usage} if usage is not None else {}),
        },
    )


def test_all_attempts_count_and_private_bodies_never_persist(tmp_path, monkeypatch):
    replies = [
        completion({}, status=429),
        completion(
            {"wrong": "private retry output"}, usage={"prompt_tokens": 20, "completion_tokens": 10}
        ),
        completion(
            {"title": "private resume output"},
            usage={
                "prompt_tokens": 30,
                "completion_tokens": 15,
                "prompt_tokens_details": {"cached_tokens": 5},
                "completion_tokens_details": {"reasoning_tokens": 6},
            },
        ),
    ]
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    raw = llm._OpenAICompatClient(
        base_url="http://local/v1",
        api_key="private-key",
        timeout=60,
        structured_mode="prompt",
        origin="ollama",
    )
    with telemetry.recording(tmp_path, run_id="run") as measured:
        client = llm_telemetry.wrap(raw, "rewrite", "ollama")
        with telemetry.span("rewrite", "initial"):
            result = client.messages.parse(
                model="test",
                max_tokens=100,
                system="private prompt",
                messages=[{"content": "private resume text"}],
                output_format=Sample,
            )
        assert result.parsed_output.title == "private resume output"
        telemetry.event("rewrite", number_omissions=2, number_repairs=1, number_fallbacks=1)
        telemetry.ready()
    data = json.loads((tmp_path / "telemetry/run.json").read_text())
    assert len(data["requests"]) == 3
    assert [r["reason"] for r in data["requests"]] == ["generation", "http_retry", "json_repair"]
    assert data["requests"][0]["input_tokens"] is None
    assert data["requests"][2]["cached_input_tokens"] == 5
    assert data["requests"][2]["reasoning_tokens"] == 6
    assert len({r["call_id"] for r in data["requests"]}) == 1
    assert data["resume_ready_ms"] <= data["completion_ms"]
    assert "private" not in json.dumps(data)
    summary = usage_report.summarize([data], [])
    group = summary["groups"][0]
    assert group["known_tokens"]["input_tokens"] == 50
    assert group["known_tokens"]["output_tokens"] == 25  # reasoning is a subset
    assert group["unknown_usage_requests"] == 1
    assert group["logical_calls"] == 1
    assert group["request_reasons"] == {"generation": 1, "http_retry": 1, "json_repair": 1}
    assert group["rewrite_numbers"] == {
        "number_omissions": 2,
        "number_repairs": 1,
        "number_fallbacks": 1,
    }
    assert group["operations"]["rewrite/initial"]["count"] == 1
    assert telemetry.current() is None
    assert measured.data["status"] == "succeeded"


def test_anthropic_retries_are_observed_at_transport(tmp_path, monkeypatch):
    responses = [429, 200]

    def send(self, request):
        status = responses.pop(0)
        return httpx.Response(
            status,
            request=request,
            json={
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 8,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 5,
                }
            },
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", send)
    with (
        telemetry.recording(tmp_path, run_id="sdk") as measured,
        telemetry.call("extract", "test-anthropic", "anthropic"),
    ):
        transport = model_queue.ScheduledTransport()
        for retry in range(2):
            transport.handle_request(
                httpx.Request(
                    "POST",
                    "https://api.example/v1/messages",
                    headers={"x-stainless-retry-count": str(retry)},
                )
            )
        transport.close()
    assert [r["status_code"] for r in measured.data["requests"]] == [429, 200]
    assert measured.data["requests"][1]["model"] == "test-anthropic"
    assert measured.data["requests"][1]["input_tokens"] == 35
    assert measured.data["requests"][1]["reason"] == "http_retry"


def test_contexts_isolate_runs_and_propagate_to_workers(tmp_path):
    def worker():
        telemetry.event("skills", available=True)
        return telemetry.current().data["run_id"]

    with telemetry.recording(tmp_path, run_id="outer") as outer:
        with ThreadPoolExecutor(2) as executor:
            first = config.submit_in_context(executor, worker)
            with telemetry.recording(tmp_path, run_id="inner") as inner:
                second = config.submit_in_context(executor, worker)
                assert second.result() == "inner"
            assert first.result() == "outer"
        assert telemetry.current() is outer
    assert len(outer.data["events"]) == len(inner.data["events"]) == 1


def test_failed_and_cancelled_runs_keep_partial_data(tmp_path):
    class JobCancelled(Exception):
        pass

    for error, expected in [(ValueError, "failed"), (JobCancelled, "cancelled")]:
        with pytest.raises(error), telemetry.recording(tmp_path, run_id=expected):
            telemetry.event("extract", cached=False)
            raise error("private error body")
        data = json.loads((tmp_path / f"telemetry/{expected}.json").read_text())
        assert data["status"] == expected and data["events"]
        assert "private error" not in json.dumps(data)


def test_persistence_failure_does_not_fail_run(tmp_path, monkeypatch):
    monkeypatch.setattr(
        type(tmp_path), "write_text", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    with telemetry.recording(tmp_path):
        telemetry.ready()
    assert telemetry.current() is None


def test_async_request_records_usage_and_restores_context(tmp_path, monkeypatch):
    import asyncio

    async def post(*args, **kwargs):
        return completion({"title": "ok"}, usage={"prompt_tokens": 12, "completion_tokens": 3})

    async def exercise():
        raw = llm._AsyncOpenAICompatClient(
            base_url="http://local/v1", api_key="", origin="ollama", structured_mode="prompt"
        )
        with telemetry.recording(tmp_path, run_id="async") as measured:
            async with llm_telemetry.wrap(raw, "answer", "ollama", asynchronous=True) as client:
                monkeypatch.setattr(raw._http, "post", post)
                result = await client.messages.parse(
                    model="test", max_tokens=100, system="x", messages=[], output_format=Sample
                )
                assert result.parsed_output.title == "ok"
            assert measured.data["requests"][0]["input_tokens"] == 12

    asyncio.run(exercise())


def test_wrapper_delegates_and_is_free_without_collector():
    raw = SimpleNamespace(extra="ok")
    assert llm_telemetry.wrap(raw, "rewrite", "ollama") is raw
    assert llm_telemetry.Client(raw, "rewrite", "ollama").extra == "ok"


def test_usage_report_keeps_versions_cache_states_and_usage_unknown(tmp_path):
    now = datetime.now(UTC)
    runs = []
    for i in range(30):
        with telemetry.recording(tmp_path, run_id=str(i), archive_id=str(i), source="web") as c:
            telemetry.event("extract", cached=i >= 10)
            telemetry.event("skills", available=True)
            c.data["routing"] = {"extract": {"origin": "ollama", "model": "test"}}
            telemetry.ready()
        c.data["finished_at"] = (now - timedelta(days=8)).isoformat()
        runs.append(c.data)
    report = usage_report.summarize(runs, [], now=now)
    assert len(report["groups"]) == 2
    assert report["decisions"][0]["jd_voting_decision"] == "paired_quality_comparison_required"
    assert report["decisions"][0]["skills"]["decision"] == "collect_more_data"
    # Only count consumption inside the observation window, once per run.
    events = [
        {"archive_id": "0", "at": (now - timedelta(days=7)).isoformat(), "action": action}
        for action in ("copy", "download")
    ]
    summary = usage_report.summarize(runs, events, now=now)["decisions"][0]
    assert summary["skills"]["consuming_runs"] == 1
    assert summary["skills"]["events"] == 2
    runs[0]["versions"] = {"entry_ranking": "different"}
    assert len(usage_report.summarize(runs, events, now=now)["decisions"]) == 2


def test_report_skills_overlap_does_not_sum_parallel_latency():
    run = {
        "resume_ready_ms": 100,
        "spans": [
            {"stage": "skills", "kind": "stage", "start_ms": 100, "duration_ms": 70},
            {"stage": "expand", "kind": "stage", "start_ms": 100, "duration_ms": 90},
        ],
    }
    assert usage_report._skills_delay(run) == 0
    run["spans"][0]["duration_ms"] = 120
    assert usage_report._skills_delay(run) == 30


def test_on_demand_review_requires_mature_runs_known_cost_and_low_observed_use(tmp_path):
    now = datetime.now(UTC)
    runs = []
    for i in range(30):
        with telemetry.recording(tmp_path, archive_id=str(i), source="web") as measured:
            telemetry.event("skills", available=True)
            with telemetry.span("skills"), telemetry.request("ollama", "test") as request:
                request.admitted()
                request.response(
                    completion({}, usage={"prompt_tokens": 10, "completion_tokens": 5})
                )
        measured.data["finished_at"] = (now - timedelta(days=8)).isoformat()
        runs.append(measured.data)
    assert usage_report.summarize(runs, [], now=now)["decisions"][0]["skills"]["decision"] == (
        "evaluate_on_demand"
    )
    used = [{"archive_id": str(i), "at": (now - timedelta(days=7)).isoformat()} for i in range(7)]
    assert usage_report.summarize(runs, used, now=now)["decisions"][0]["skills"]["decision"] == (
        "retain_automatic_generation"
    )
    runs[0]["requests"][0]["input_tokens"] = None
    assert usage_report.summarize(runs, [], now=now)["decisions"][0]["skills"]["decision"] == (
        "collect_more_data"
    )
