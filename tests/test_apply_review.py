"""Review snapshots and explicit corrections reject stale browser state."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from resume_tailor import config
from resume_tailor.apply import review, scanner, store
from resume_tailor.apply.field_types import FieldObservation


def _field(value: str = "") -> FieldObservation:
    return FieldObservation(
        snapshot_id="snapshot", field_id="field-1", frame_id="0:123",
        document_generation="generation-1", label="Desired salary",
        control_kind="text", current_value=value,
    )


def test_state_hash_changes_when_answer_changes():
    assert review.state_hash(_field(""), "https://example.com") != review.state_hash(
        _field("$50,000"), "https://example.com",
    )


def test_refresh_records_current_observed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    app = store.Application(
        source="test", source_job_id="app-1", company="Acme", role="Intern",
        status="awaiting_review", fill=store.FillResult(browser_target_id="tab-1"),
    )
    store.upsert(app)

    async def fake_scan(_page):
        return scanner.ScanSnapshot(snapshot_id="snapshot", fields=[_field("$50,000")])

    monkeypatch.setattr(review.scanner, "scan", fake_scan)
    result = asyncio.run(review._record(app, SimpleNamespace(url="https://example.com")))  # noqa: SLF001
    assert result.review_snapshot_id == "snapshot"
    assert result.review_fields[0]["expected_state_hash"]
    assert result.field_outcomes[0]["state"] == "preserved"
    assert store.FillResult.model_validate(store.get("app-1").fill).browser_target_id == "tab-1"


def test_refresh_keeps_completed_step_evidence_but_replaces_current_step(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    previous = store.FillResult(
        browser_target_id="tab-1", current_step_id="current-step",
        field_outcomes=[
            {"field_id": "old-school", "step_id": "completed-step", "label": "School", "state": "verified_filled"},
            {"field_id": "old-salary", "step_id": "current-step", "label": "Desired salary", "state": "unanswered"},
        ],
    )
    app = store.Application(
        source="test", source_job_id="app-1", company="Acme", role="Intern",
        status="awaiting_review", fill=previous,
    )
    store.upsert(app)

    async def fake_scan(_page):
        return scanner.ScanSnapshot(snapshot_id="new-snapshot", fields=[_field("$50,000")])

    monkeypatch.setattr(review.scanner, "scan", fake_scan)
    result = asyncio.run(review._record(app, SimpleNamespace(url="https://example.com")))  # noqa: SLF001
    assert [item["label"] for item in result.field_outcomes] == ["School", "Desired salary"]
    assert result.field_outcomes[0]["state"] == "verified_filled"
    assert result.field_outcomes[1]["state"] == "preserved"


def test_correction_rejects_old_snapshot_before_browser_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    store.upsert(store.Application(
        source="test", source_job_id="app-1", company="Acme", role="Intern",
        status="awaiting_review",
        fill=store.FillResult(browser_target_id="tab-1", review_snapshot_id="new-snapshot"),
    ))
    with pytest.raises(ValueError, match="stale_snapshot"):
        asyncio.run(review.correct(
            "app-1", snapshot_id="old-snapshot", field_id="field-1",
            expected_state_hash="hash", value="text", option_ids=[],
        ))
