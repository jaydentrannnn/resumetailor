"""Pause/Cancel stop a Prepare mid-way: the tailor job is cancelled and the row restored."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import daily, daily_row_run, store, store_models
from resume_tailor.web.schemas import ApplySettings, JobSettings
from tests.fixtures import synthetic_resume


class _Queue:
    def __init__(self):
        self.cancelled: list[str] = []

    def get(self, _job_id):
        return None  # still running

    def cancel(self, job_id):
        self.cancelled.append(job_id)


def test_wait_for_job_cancels_the_job_when_told_to_stop(monkeypatch):
    queue = _Queue()
    monkeypatch.setattr(daily_row_run, "get_queue", lambda: queue)
    with pytest.raises(daily_row_run.PrepareInterrupted):
        daily_row_run._wait_for_job("job-1", poll_sec=0.01, should_stop=lambda: True)
    assert queue.cancelled == ["job-1"]


def test_interrupted_prepare_puts_the_row_back(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(daily.data, "load", synthetic_resume)
    monkeypatch.setattr(
        daily.workspace, "load_settings", lambda: {"defaults": JobSettings().model_dump()}
    )
    store.upsert(
        store_models.Application(
            source="test",
            source_job_id="one",
            company="Acme",
            role="Engineer",
            status="ready",
            job_id="old-run",
        )
    )

    def interrupted(row, **_kwargs):
        app = store.get(row.job_id)
        store.set_status(app, "tailoring")
        app.job_id = "new-run"
        store.upsert(app)
        raise daily_row_run.PrepareInterrupted()

    monkeypatch.setattr(daily_row_run, "_process_one", interrupted)
    with pytest.raises(daily_row_run.PrepareInterrupted):
        daily.prepare_application(
            "one", settings=ApplySettings(), force_prepare=True, should_stop=lambda: True
        )
    row = store.get("one")
    assert (row.status, row.job_id, row.error) == ("ready", "old-run", None)
