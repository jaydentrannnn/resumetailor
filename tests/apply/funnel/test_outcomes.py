"""Outcomes after sending (`outcomes`), what was sent (`attempts`), and their stats."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import stat
from datetime import date

import pytest

from resume_tailor import config
from resume_tailor.apply.forms import submit_guard
from resume_tailor.apply.funnel import (
    attempts,
    outcomes,
    store,
    store_models,
    store_stats,
    store_views,
)


def _app(status: str = "ready", history: tuple[tuple[str, str], ...] = (), **extra):
    return store_models.Application(
        source="t", source_job_id=extra.pop("source_job_id", "job-1"), company="Acme",
        role="Analyst", status=status, discovered_at="2026-09-01T00:00:00+00:00",
        status_history=[store_models.StatusChange(status=s, at=at) for s, at in history],
        **extra,
    )


SENT = (("submitted", "2026-09-10T12:00:00+00:00"),)


def test_unsent_rows_have_no_stage():
    assert outcomes.hiring_progress(_app()).stage is None
    assert outcomes.hiring_progress(_app()).label == ""


def test_legacy_statuses_derive_a_stage_without_rewriting_the_row():
    interview = _app("interview", SENT + (("interview", "2026-09-20T09:00:00+00:00"),))
    progress = outcomes.hiring_progress(interview)
    assert (progress.stage, progress.closed, progress.label) == ("interview", None, "Interviewing")
    assert progress.stage_dates == {"applied": "2026-09-10", "interview": "2026-09-20"}
    assert progress.responded
    assert interview.outcome_events == []
    ghosted = outcomes.hiring_progress(_app("ghosted", SENT + (("ghosted", "2026-10-20T00:00:00"),)))
    assert (ghosted.stage, ghosted.closed, ghosted.responded) == ("applied", "ghosted", False)
    # A legacy row whose status was set with no timeline entry.
    assert outcomes.hiring_progress(_app("rejected")).closed == "rejected"


def test_events_track_the_furthest_stage_and_the_latest_close():
    app = _app("submitted", SENT)
    outcomes.add_event(app, "ghosted", occurred_on="2026-09-25")
    outcomes.add_event(app, "interview_invited", occurred_on="2026-09-28", note="Phone screen")
    outcomes.add_event(app, "rejected", occurred_on="2026-10-05")
    progress = outcomes.hiring_progress(app)
    assert (progress.stage, progress.closed, progress.label) == ("interview", "rejected", "Rejected")
    assert progress.stage_dates["interview"] == "2026-09-28"
    outcomes.add_event(app, "offer", occurred_on="2026-10-09")
    assert outcomes.hiring_progress(app).label == "Offer"
    assert app.status == "submitted"


def test_correct_and_void_keep_history():
    app = _app("submitted", SENT)
    first = outcomes.add_event(app, "interview_invited", occurred_on="2026-09-20")
    fixed = outcomes.correct_event(app, first.id, type="interview_scheduled", note="Onsite")
    assert fixed.replaces == first.id and first.voided_at == fixed.recorded_at
    assert (fixed.type, fixed.occurred_on, fixed.note) == ("interview_scheduled", "2026-09-20", "Onsite")
    outcomes.void_event(app, fixed.id)
    assert len(app.outcome_events) == 2 and outcomes.live_events(app) == []
    assert outcomes.hiring_progress(app).stage == "applied"
    with pytest.raises(ValueError, match="already"):
        outcomes.void_event(app, first.id)
    with pytest.raises(KeyError):
        outcomes.void_event(app, "missing")
    with pytest.raises(ValueError):
        outcomes.add_event(app, "offer", occurred_on="next week")


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    run = config.OUTPUT_DIR / "jobs" / "run1"
    run.mkdir(parents=True)
    for name, body in {
        "tailored.pdf": b"%PDF resume", "tailored.docx": b"docx", "packet.json": b"{}",
        "bullets.json": b'{"b1": "Built it"}', "cover.json": b'{"paragraphs": []}',
    }.items():
        (run / name).write_bytes(body)
    app_dir = config.APPLICATIONS_OUTPUT_DIR / "job-1"
    app_dir.mkdir(parents=True)
    (app_dir / "jd.txt").write_text("Analyst role", "utf-8")
    (app_dir / "fill.json").write_text("{}", "utf-8")
    return _app("ready", job_id="run1", jd_text_path=str(app_dir / "jd.txt")), run


def test_submitting_snapshots_read_only_files_with_matching_hashes(prepared):
    app, run = prepared
    store.set_status(app, "submitted", note=submit_guard.AUTO_NOTE)
    [attempt] = app.attempts
    assert (attempt.number, attempt.method, attempt.confirmed, attempt.error) == (1, "auto", True, "")
    folder = config.APPLICATIONS_OUTPUT_DIR / "job-1" / "attempts" / "1"
    assert attempt.snapshot_dir == str(folder)
    assert set(attempt.files) == {
        "tailored.pdf", "tailored.docx", "packet.json", "bullets.json", "cover.json",
        "jd.txt", "fill.json",
    }
    for name, digest in attempt.files.items():
        copied = folder / name
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == digest
        assert not os.stat(copied).st_mode & stat.S_IWRITE
    assert attempt.packet_digest == attempt.files["packet.json"]
    assert attempt.jd_sha256 == attempt.files["jd.txt"]
    # A later Prepare rewrites the run folder; the attempt keeps what was sent.
    (run / "tailored.pdf").write_bytes(b"%PDF newer")
    assert (folder / "tailored.pdf").read_bytes() == b"%PDF resume"


def test_manual_mark_is_unconfirmed_and_a_late_confirmation_reuses_the_attempt(prepared):
    app, _ = prepared
    store.set_status(app, "submitted", note="")
    assert [(a.method, a.confirmed) for a in app.attempts] == [("manual", False)]
    auto = _app("ready", source_job_id="job-2")
    store.set_status(auto, "submit_unconfirmed", note=submit_guard.AUTO_NOTE)
    store.set_status(auto, "submitted", note=attempts.MONITOR_NOTE)
    assert [(a.method, a.confirmed) for a in auto.attempts] == [("auto", True)]
    store.set_status(auto, "interview")
    assert len(auto.attempts) == 1


def test_undo_voids_the_attempt_and_a_resubmit_adds_another(prepared):
    app, _ = prepared
    store.set_status(app, "submitted", note="")
    assert store.undo_terminal(app, "undone")
    assert app.attempts[0].voided_at and attempts.latest(app) is None
    store.set_status(app, "submitted", note="")
    assert [a.number for a in app.attempts] == [1, 2]
    assert attempts.latest(app).number == 2


def test_a_copy_failure_still_records_the_status(prepared, monkeypatch):
    app, _ = prepared

    def refuse(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(attempts.shutil, "copyfile", refuse)
    store.set_status(app, "submitted", note="")
    assert app.status == "submitted"
    assert app.attempts[0].error.startswith("Could not copy every file")


def test_cohort_counts_only_applications_old_enough_to_have_heard_back():
    old = _app("submitted", SENT, source_job_id="old")
    outcomes.add_event(old, "interview_invited")
    rejected = _app("rejected", SENT + (("rejected", "2026-09-15T00:00:00"),), source_job_id="rej")
    silent = _app("submitted", SENT, source_job_id="silent")
    recent = _app("submitted", (("submitted", "2026-10-15T00:00:00"),), source_job_id="new")
    cohort = store_stats.progress_stats(
        [old, rejected, silent, recent, _app(source_job_id="unsent")], today=date(2026, 10, 22)
    ).outcomes
    assert cohort.model_dump() == {
        "window_days": 21, "sent": 3, "responded": 2, "interviewed": 1, "offers": 0,
        "rejected": 1, "no_reply": 1,
    }


def test_csv_export_carries_stage_and_dates(monkeypatch):
    app = _app("submitted", SENT)
    outcomes.add_event(app, "interview_invited", occurred_on="2026-09-20")
    monkeypatch.setattr(store_views, "list_applications", lambda: [app])
    [row] = list(csv.DictReader(io.StringIO(store_views.export_csv())))
    assert (row["hiring_stage"], row["hiring_closed"]) == ("interview", "")
    assert (row["applied_on"], row["interview_on"], row["offer_on"]) == ("2026-09-10", "2026-09-20", "")
