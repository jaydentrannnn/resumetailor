"""The Tracker board's columns and moves (`apply/funnel/tracker.py`). Pure: no store."""

from __future__ import annotations

from datetime import date

import pytest

from resume_tailor.apply.funnel import outcomes, store_models, tracker

TODAY = date(2026, 10, 23)
ARCHIVED = "2026-09-10T12:00:00+00:00"


def _app(status="submitted", events=(), **extra):
    history = [store_models.StatusChange(status=status, at="2026-09-10T12:00:00+00:00")]
    app = store_models.Application(
        source="t", source_job_id=extra.pop("source_job_id", "job-1"), company="Acme",
        role="Analyst", status=status, status_history=history,
        discovered_at="2026-09-01T00:00:00+00:00",
        archived_at=extra.pop("archived_at", ARCHIVED), **extra,
    )
    for kind, on in events:
        outcomes.add_event(app, kind, occurred_on=on)
    return app


def _live(app):
    return [e.type for e in outcomes.live_events(app)]


@pytest.mark.parametrize(("status", "events", "column"), [
    ("skipped", (), "not_sent"),
    ("screened_out", (), "not_sent"),
    ("submitted", (), "applied"),
    ("submitted", (("assessment", "2026-09-12"),), "assessment"),
    ("submitted", (("interview_scheduled", "2026-09-12"),), "interview"),
    ("submitted", (("offer", "2026-09-12"),), "offer"),
    ("submitted", (("offer", "2026-09-12"), ("hired", "2026-09-20")), "offer"),
    ("submitted", (("offer", "2026-09-12"), ("offer_declined", "2026-09-20")), "closed"),
    ("submitted", (("rejected", "2026-09-12"),), "closed"),
    ("submitted", (("ghosted", "2026-09-12"), ("interview_invited", "2026-09-20")), "interview"),
])
def test_the_column_follows_the_hiring_stage(status, events, column):
    assert tracker.column_of(_app(status, events)) == column


def test_forward_adds_the_column_step_dated_today():
    app = _app()
    receipt = tracker.move(app, "interview", today=TODAY)
    [event] = outcomes.live_events(app)
    assert (event.type, event.occurred_on, event.source) == ("interview_invited", "2026-10-23", "manual")
    assert receipt.added == [event.id] and receipt.voided == []
    assert tracker.column_of(app) == "interview"


def test_back_voids_only_the_steps_above_the_target_and_keeps_them():
    app = _app(events=(("assessment", "2026-09-11"), ("interview_invited", "2026-09-15"),
                       ("interview_completed", "2026-09-20")))
    receipt = tracker.move(app, "assessment", today=TODAY)
    assert _live(app) == ["assessment"]
    assert len(receipt.voided) == 2 and receipt.added == []
    assert len(app.outcome_events) == 3  # nothing deleted


def test_back_past_a_stage_never_reached_records_that_stage():
    app = _app(events=(("interview_invited", "2026-09-15"),))
    tracker.move(app, "assessment", today=TODAY)
    assert _live(app) == ["assessment"]
    assert tracker.column_of(app) == "assessment"


def test_closing_needs_a_reason_and_declining_needs_an_offer():
    app = _app(events=(("interview_invited", "2026-09-15"),))
    with pytest.raises(ValueError, match="why"):
        tracker.move(app, "closed", today=TODAY)
    with pytest.raises(ValueError, match="offer"):
        tracker.move(app, "closed", reason="offer_declined", today=TODAY)
    tracker.move(app, "closed", reason="ghosted", today=TODAY)
    card = tracker.card(app)
    assert (card.column, card.label, card.reached) == ("closed", "No reply", "Interviewing")


def test_changing_the_reason_replaces_the_closing_event():
    app = _app(events=(("rejected", "2026-09-15"),))
    assert tracker.card(app).reached == ""  # never got past applied
    receipt = tracker.move(app, "closed", reason="withdrawn", today=TODAY)
    assert _live(app) == ["withdrawn"] and len(receipt.voided) == 1
    assert tracker.move(app, "closed", reason="withdrawn", today=TODAY) == tracker.Receipt()


def test_reopening_voids_the_closing_event_only():
    app = _app(events=(("rejected", "2026-09-01"), ("interview_invited", "2026-09-15"),
                       ("rejected", "2026-09-20")))
    tracker.move(app, "interview", today=TODAY)
    # The earlier rejection was already overtaken by the interview: it stays.
    assert _live(app) == ["rejected", "interview_invited"]
    assert tracker.column_of(app) == "interview"


def test_reopening_a_declined_offer_keeps_the_offer():
    app = _app(events=(("offer", "2026-09-15"), ("offer_declined", "2026-09-20")))
    tracker.move(app, "offer", today=TODAY)
    assert _live(app) == ["offer"]


def test_the_same_column_changes_nothing():
    app = _app(events=(("assessment", "2026-09-11"),))
    assert tracker.move(app, "assessment", today=TODAY) == tracker.Receipt()
    assert len(app.outcome_events) == 1


def test_not_sent_is_refused_both_ways():
    with pytest.raises(ValueError, match="never sent"):
        tracker.move(_app("skipped"), "applied", today=TODAY)
    with pytest.raises(ValueError, match="never sent"):
        tracker.move(_app(), "not_sent", today=TODAY)


def test_a_legacy_status_cannot_be_moved_back():
    app = _app("interview")
    assert tracker.column_of(app) == "interview"
    with pytest.raises(ValueError, match="older status mark"):
        tracker.move(app, "applied", today=TODAY)


def test_undo_reverses_a_move_with_copies_and_only_once():
    app = _app(events=(("interview_invited", "2026-09-15"),))
    original = app.outcome_events[0]
    receipt = tracker.move(app, "closed", reason="rejected", today=TODAY)
    tracker.undo(app, receipt)
    assert tracker.column_of(app) == "interview"
    back = tracker.move(app, "applied", today=TODAY)
    assert tracker.column_of(app) == "applied"
    tracker.undo(app, back)
    [copy] = [e for e in outcomes.live_events(app) if e.type == "interview_invited"]
    assert (copy.replaces, copy.occurred_on) == (original.id, "2026-09-15")
    assert original.voided_at is not None
    with pytest.raises(ValueError, match="changed since"):
        tracker.undo(app, back)
    with pytest.raises(ValueError, match="changed since"):
        tracker.undo(app, receipt)


def test_cards_cover_done_rows_only_newest_update_first():
    rows = [
        _app(source_job_id="old"),
        _app(source_job_id="new", events=(("assessment", "2026-10-01"),)),
        _app("skipped", source_job_id="skip"),
        _app(source_job_id="active", archived_at=None),
    ]
    cards = tracker.board(rows)
    assert [c.id for c in cards] == ["new", "old", "skip"]
    skipped = cards[-1]
    assert (skipped.column, skipped.label, skipped.sent_on) == ("not_sent", "Skipped", None)
    assert cards[0].last_update == "2026-10-01"
