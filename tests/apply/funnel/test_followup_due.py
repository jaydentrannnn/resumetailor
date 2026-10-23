"""When follow-ups, thank-yous and "no reply" marks are due (`followup_due`), and what
was sent read back for them (`sent_copy`)."""

from __future__ import annotations

import json
from datetime import date

from resume_tailor import config
from resume_tailor.apply.funnel import followup_due, outcomes, sent_copy, store, store_models

TODAY = date(2026, 10, 22)


def _app(sent: str | None = "2026-10-01", status: str = "submitted", **extra):
    history = [store_models.StatusChange(status="submitted", at=f"{sent}T12:00:00+00:00")]
    return store_models.Application(
        source="t", source_job_id=extra.pop("source_job_id", "job-1"), company="Acme",
        role="Analyst", status=status, discovered_at="2026-09-01T00:00:00+00:00",
        status_history=history if sent else [], **extra,
    )


def _with(app, *events):
    for kind, day in events:
        outcomes.add_event(app, kind, occurred_on=day)
    return app


def test_a_follow_up_is_due_ten_days_after_sending_with_no_reply():
    assert followup_due.state(_app("2026-10-15"), TODAY).reason.startswith("Sent 7 day(s)")
    found = followup_due.state(_app("2026-10-01"), TODAY)
    assert (found.due, found.days_since_sent, found.stale) == ("follow_up", 21, False)
    assert followup_due.state(_app(None, status="ready"), TODAY).due is None


def test_replies_closes_and_sent_follow_ups_stop_it():
    replied = followup_due.state(_with(_app(), ("assessment", "2026-10-05")), TODAY)
    assert (replied.due, replied.reason) == (None, "The employer has replied.")
    closed = followup_due.state(_with(_app(), ("withdrawn", "2026-10-05")), TODAY)
    assert closed.reason == "Closed: withdrawn."
    legacy = followup_due.state(_app(status="rejected"), TODAY)
    assert legacy.due is None
    recent = _with(_app(), ("followup_sent", "2026-10-18"))
    assert followup_due.state(recent, TODAY).reason.startswith("Followed up less than")
    again = _with(_app(), ("followup_sent", "2026-10-11"))
    assert followup_due.state(again, TODAY).due == "follow_up"
    twice = _with(_app(), ("followup_sent", "2026-10-11"), ("followup_sent", "2026-10-12"))
    assert followup_due.state(twice, TODAY).follow_ups_sent == 2
    assert followup_due.state(twice, TODAY).due is None


def test_an_employer_timeline_waits_until_its_date_passes():
    waiting = _with(_app(), ("employer_timeline", "2026-10-30"))
    assert followup_due.state(waiting, TODAY).reason.endswith("by 2026-10-30.")
    passed = _with(_app(), ("employer_timeline", "2026-10-20"))
    assert followup_due.state(passed, TODAY).due == "follow_up"


def test_a_thank_you_follows_an_interview_until_a_note_is_sent():
    interviewed = _with(_app(), ("interview_completed", "2026-10-20"))
    assert followup_due.state(interviewed, TODAY).due == "thank_you"
    _with(interviewed, ("followup_sent", "2026-10-20"))
    assert followup_due.state(interviewed, TODAY).due is None


def test_silence_for_sixty_days_is_stale_and_listed_oldest_first():
    rows = [
        _app("2026-08-01", source_job_id="old"),
        _app("2026-07-01", source_job_id="older"),
        _app("2026-10-01", source_job_id="due"),
        _app("2026-10-20", source_job_id="fresh"),
        _with(_app("2026-07-15", source_job_id="ghost"), ("ghosted", "2026-10-01")),
    ]
    listed = followup_due.due_list(rows, TODAY)
    assert [r.application_id for r in listed.stale] == ["older", "old"]
    assert [r.application_id for r in listed.due] == ["older", "old", "due"]
    assert listed.stale[0].days_since_sent == 113


def test_the_sent_copy_reads_the_attempt_then_falls_back_to_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    run = config.OUTPUT_DIR / "jobs" / "run1"
    run.mkdir(parents=True)
    (run / "bullets.json").write_text('{"b1": "Built the dashboard"}', "utf-8")
    (run / "cover.json").write_text('{"paragraphs": ["Hello.", "Thanks."]}', "utf-8")
    (run / "requirements.json").write_text(json.dumps({
        "title": "Old title", "seniority": "entry",
        "keywords": [{"phrase": "Tableau", "canonical": "tableau", "importance": "must_have"}],
    }), "utf-8")
    (run / "coverage.json").write_text(json.dumps({
        "total": 1, "in_resume": 0, "on_page": 0,
        "keywords": [{"canonical": "tableau", "phrase": "Tableau", "resume": None, "page": None}],
    }), "utf-8")
    app_dir = config.APPLICATIONS_OUTPUT_DIR / "job-1"
    app_dir.mkdir(parents=True)
    (app_dir / "jd.txt").write_text("Analyst role", "utf-8")
    app = _app(status="ready", job_id="run1")
    assert sent_copy.load(_app(status="ready")) is None

    before = sent_copy.load(app)
    assert (before.attempt, before.based_on) == (
        None, "Latest prepared files (no submitted copy was recorded)")
    store.set_status(app, "submitted")
    (run / "bullets.json").write_text('{"b1": "Rewritten later"}', "utf-8")
    copy = sent_copy.load(app)
    assert (copy.attempt, copy.bullets, copy.cover_letter) == (
        1, {"b1": "Built the dashboard"}, "Hello.\n\nThanks.")
    assert (copy.requirements.title, copy.jd_text, copy.gaps) == (
        "Analyst", "Analyst role", ["Tableau"])
    reused = sent_copy.load(app.model_copy(update={"reused_from_job_id": "other"}))
    assert (reused.requirements, reused.gaps) == (None, [])
