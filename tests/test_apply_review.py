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


def _correctable(tmp_path, monkeypatch, label: str):
    """An application whose review tab shows one empty field labelled ``label``,
    with the browser, scanner and control writes faked."""
    from contextlib import asynccontextmanager

    from resume_tailor.apply.field_types import FieldOutcome

    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    url = "https://boards.greenhouse.io/acme/jobs/1"
    field = _field("").model_copy(update={"label": label})
    saved = {**field.model_dump(), "expected_state_hash": review.state_hash(field, url)}
    store.upsert(store.Application(
        source="test", source_job_id="app-1", company="Acme", role="Intern", ats="greenhouse",
        status="awaiting_review",
        fill=store.FillResult(
            browser_target_id="tab-1", review_snapshot_id="snapshot", review_fields=[saved],
        ),
    ))
    page = SimpleNamespace(url=url)

    @asynccontextmanager
    async def fake_browser():
        yield SimpleNamespace(contexts=[object()])

    async def fake_find(_context, _target):
        return page

    async def fake_scan(_page):
        return scanner.ScanSnapshot(snapshot_id="snapshot", fields=[field])

    async def fake_apply(_page, _snapshot, observed, value, **_kwargs):
        return FieldOutcome(
            field_id=observed.field_id, frame_id=observed.frame_id, label=observed.label,
            state="verified_filled", observed_value=value,
        )

    monkeypatch.setattr(review.browser, "async_cdp_browser", fake_browser)
    monkeypatch.setattr(review.browser, "async_find_target", fake_find)
    monkeypatch.setattr(review.scanner, "scan", fake_scan)
    monkeypatch.setattr(review.controls, "apply_value", fake_apply)
    return saved


def _correct(saved, value):
    return asyncio.run(review.correct(
        "app-1", snapshot_id="snapshot", field_id="field-1",
        expected_state_hash=saved["expected_state_hash"], value=value, option_ids=[],
    ))


def test_a_verified_correction_to_a_custom_question_is_remembered(tmp_path, monkeypatch):
    from resume_tailor.apply import answer_memory

    saved = _correctable(tmp_path, monkeypatch, "Which Acme office do you prefer?")
    outcome = _correct(saved, "Irvine")
    assert outcome.answer_source == "explicit_user_correction"
    [remembered] = answer_memory.list_answers()
    assert (remembered.label, remembered.answer, remembered.ats, remembered.company) == (
        "Which Acme office do you prefer?", "Irvine", "greenhouse", "Acme",
    )
    recalled = answer_memory.recall("Which Beta office do you prefer?", company="Beta")
    assert recalled is not None and recalled.answer == "Irvine"


def test_a_correction_to_a_profile_fact_is_not_remembered(tmp_path, monkeypatch):
    from resume_tailor.apply import answer_memory

    saved = _correctable(tmp_path, monkeypatch, "Phone number")
    _correct(saved, "555 010 0000")
    assert answer_memory.list_answers() == []


def test_a_correction_to_a_blank_profile_question_fills_the_profile(tmp_path, monkeypatch):
    # Workday asked "Middle Name" (a profile field the fill had no value for): the
    # correction belongs in the profile, not in remembered answers as a second copy.
    from resume_tailor import config
    from resume_tailor.apply import answer_memory
    from resume_tailor.apply import profile as profile_mod

    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    saved = _correctable(tmp_path, monkeypatch, "Middle Name")
    _correct(saved, "Quinn")
    assert answer_memory.list_answers() == []
    assert profile_mod.load_profile()[0].middle_name == "Quinn"
