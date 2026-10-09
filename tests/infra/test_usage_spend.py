"""`usage_spend`: measured tokens priced at list price, never estimated."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.infra import usage_spend
from resume_tailor.web.app import app


def _run(run_id: str, *requests: dict, started: str = "2026-10-01T00:00:00+00:00") -> dict:
    return {"schema_version": 1, "run_id": run_id, "started_at": started, "status": "succeeded",
            "requests": list(requests), "spans": [], "events": []}


def _req(origin: str, model: str, tin: int | None, tout: int | None) -> dict:
    return {"origin": origin, "model": model, "input_tokens": tin, "output_tokens": tout}


def test_prices_known_models_and_marks_local_as_no_per_token():
    summary = usage_spend.summarize([
        _run("a", _req("anthropic", "claude-sonnet-4-5", 1_000_000, 100_000)),
        _run("b", _req("ollama", "llama3", 500, 50)),
    ])
    rows = {r["origin"]: r for r in summary["models"]}
    assert rows["anthropic"]["usd"] == 4.5  # 1M × $3 + 0.1M × $15
    assert rows["ollama"]["usd"] is None and rows["ollama"]["billing"] == "no_per_token"
    assert summary["usd"] == 4.5 and summary["runs"] == 2 and summary["complete"] is True


def test_unreported_usage_and_unknown_models_are_never_estimated():
    summary = usage_spend.summarize([
        _run("a", _req("anthropic", "claude-unknown", 10, 10), _req("gemini", "gemini-2.5-pro",
                                                                   None, None)),
    ])
    rows = {r["origin"]: r for r in summary["models"]}
    assert rows["anthropic"]["usd"] is None
    assert rows["gemini"]["unreported"] == 1 and rows["gemini"]["input_tokens"] == 0
    assert summary["complete"] is False


def test_collect_filters_by_start_date(tmp_path):
    folder = tmp_path / "telemetry"
    folder.mkdir()
    for run in (_run("old", started="2026-01-01T00:00:00+00:00"), _run("new")):
        (folder / f"{run['run_id']}.json").write_text(json.dumps(run), "utf-8")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    assert usage_spend.collect([tmp_path], days=30, now=now)["runs"] == 1


def test_usage_route_reads_the_active_output(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(usage_spend, "read_runs", lambda output, since: [
        _run("a", _req("anthropic", "claude-haiku-4-5", 1_000_000, 0))
    ] if output == tmp_path else [])
    monkeypatch.setattr("resume_tailor.workspace.list_workspaces", lambda: [])
    with TestClient(app) as c:
        body = c.get("/api/usage?days=7").json()
    assert body["days"] == 7 and body["usd"] == 1.0
