"""Measured Find jobs progress is independent of log text and worker ordering."""

from __future__ import annotations

import threading

import pytest

from resume_tailor import config, workspace
from resume_tailor.apply.discovery import source_rows, source_status, sources
from resume_tailor.apply.funnel import (
    daily,
    daily_progress,
    daily_row_run,
    daily_rows,
    operations,
    store,
)
from resume_tailor.content import data
from resume_tailor.web.schemas import ApplySettings, JobSettings, SourceConfig
from tests.fixtures import synthetic_resume


@pytest.fixture
def progress_run(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "load_settings", lambda: {"defaults": JobSettings().model_dump()})
    monkeypatch.setattr(data, "load", synthetic_resume)
    monkeypatch.setattr(store, "all_ids", lambda: set())
    monkeypatch.setattr(store, "build_index", lambda: {})
    monkeypatch.setattr(store, "get", lambda _id: None)
    monkeypatch.setattr(source_status, "record_source_status", lambda *_args: None)
    monkeypatch.setattr(daily_rows, "_log_path", lambda _date: tmp_path / "daily.log")
    monkeypatch.setattr(daily_row_run, "_process_one", lambda *_args, **_kwargs: None)
    return []


def source(id, enabled=True):
    return SourceConfig(id=id, kind="simplify_html", url="https://example.test/jobs", enabled=enabled)


def row(id):
    return source_rows.SourceRow(
        job_id=id, source_id="good", company=id, role="Engineer", location="Remote",
        age="0d", age_days=0,
    )


def test_reports_sources_including_failures_then_concurrent_postings(progress_run, monkeypatch):
    updates = progress_run
    second_finished = threading.Event()

    def fetch(src):
        if src.id == "bad":
            raise RuntimeError("Source unavailable")
        return [row("one"), row("two")], []

    def process(posting, **_kwargs):
        if posting.job_id == "one":
            assert second_finished.wait(5)
        else:
            second_finished.set()
            raise RuntimeError("Posting unavailable")

    monkeypatch.setattr(sources, "fetch_source_rows", fetch)
    monkeypatch.setattr(daily_row_run, "_process_one", process)
    result = daily.run_daily(
        settings=ApplySettings(sources=[source("good"), source("bad"), source("disabled", False)]),
        fetch_only=True, log=lambda _message: None, on_progress=updates.append,
    )
    discovering = [p for p in updates if p.phase == "discovering"]
    assert [(p.processed, p.total) for p in discovering] == [(0, 2), (0, 2), (1, 2), (1, 2), (2, 2)]
    assert discovering[-1].current == "bad"
    processing = [p for p in updates if p.phase == "processing"]
    assert [(p.processed, p.total) for p in processing] == [(0, 2), (1, 2), (2, 2)]
    assert {p.current for p in processing[1:]} == {"one — Engineer", "two — Engineer"}
    assert len(result.errors) == 2


@pytest.mark.parametrize("configured", [[], [source("empty")], [source("disabled", False)]])
def test_empty_stages_report_zero_counts(progress_run, monkeypatch, configured):
    monkeypatch.setattr(sources, "fetch_source_rows", lambda _src: ([], []))
    daily.run_daily(
        settings=ApplySettings(sources=configured), fetch_only=True,
        log=lambda _message: None, on_progress=progress_run.append,
    )
    assert progress_run[-1] == daily_progress.FindProgress(phase="processing", total=0)
    assert progress_run[0].total == sum(s.enabled for s in configured)


def test_operation_progress_is_persisted_and_old_operations_still_load(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    op = operations.ApplyOperation(operation_id="find", action="find", state="running")
    assert op.find_progress is None
    operations._set_find_progress(op, daily_progress.FindProgress(
        phase="processing", processed=3, total=8, current="Acme — Engineer",
    ))
    persisted = operations._load()["find"]
    assert persisted.find_progress == op.find_progress
    assert persisted.model_dump()["find_progress"]["processed"] == 3


@pytest.mark.parametrize("outcome", ["completed", "completed_with_issues", "failed", "cancelled"])
def test_find_worker_relays_progress_and_retains_it_at_finish(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(operations, "_ACTIVE_ID", "find")
    monkeypatch.setattr(operations, "_CANCEL", threading.Event())
    monkeypatch.setattr(operations, "_RUN_LOCK", threading.Lock())
    progress = daily_progress.FindProgress(phase="processing", processed=3, total=8, current="Acme")

    def run(**kwargs):
        assert kwargs["fetch_only"] is True
        kwargs["on_progress"](progress)
        assert operations.get("find").find_progress == progress
        if outcome == "failed":
            raise RuntimeError("Interrupted search")
        if outcome == "cancelled":
            operations._CANCEL.set()
        return daily_progress.DailySummary(
            errors=["One source failed"] if outcome == "completed_with_issues" else [],
        )

    monkeypatch.setattr(daily, "run_daily", run)
    op = operations.ApplyOperation(operation_id="find", action="find")
    request = operations.ApplyOperationRequest(action="find", model_provider="ollama", model_name="test")
    assert operations._RUN_LOCK.acquire(blocking=False)
    operations._worker(
        op, request, settings_snapshot=ApplySettings(),
    )
    persisted = operations._load()["find"]
    assert persisted.state == outcome
    assert persisted.find_progress == progress
    assert persisted.finished_at
