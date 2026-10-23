"""The Apply page's progress banner counts (`store_stats.progress_stats`)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from resume_tailor.apply.funnel import store_models, store_stats
from resume_tailor.web.schemas import ApplySettings


def _app(job_id: str, status: str, history: tuple[tuple[str, str], ...] = (), **extra):
    return store_models.Application(
        source="t",
        source_job_id=job_id,
        company=f"Co {job_id}",
        role="Intern",
        status=status,
        status_history=[store_models.StatusChange(status=s, at=at) for s, at in history],
        **extra,
    )


def test_counts_each_stage_a_posting_ever_reached():
    rows = [
        _app("found", "discovered"),
        _app("screened", "screened_in", (("screened_in", "2026-10-01T00:00:00+00:00"),)),
        _app("ready", "ready", (("screened_in", "t1"), ("ready", "t2"))),
        _app(
            "sent",
            "submitted",
            (("screened_in", "t1"), ("ready", "t2"), ("filling", "t3"), ("submitted", "2026-10-02T09:00:00+00:00")),
        ),
    ]
    stats = store_stats.progress_stats(rows)
    assert (stats.found, stats.screened_in, stats.tailored, stats.autofilled, stats.sent_total) == (4, 3, 2, 1, 1)
    assert [item.at for item in stats.sent] == ["2026-10-02T09:00:00+00:00"]
    assert stats.ready == 1 and stats.unscreened == 1


def test_an_outcome_counts_as_sent_and_archived_rows_only_leave_the_live_counts():
    rows = [
        # Marked straight to Interview: sent, timed by its first sent-like entry.
        _app("interview", "interview", (("interview", "2026-10-05T12:00:00+00:00"),)),
        # Sent with no timeline: falls back to the status time, discovery for such a row.
        _app("bare", "submitted", discovered_at="2026-10-03T08:00:00+00:00"),
        # Archived: still sent, but no longer waiting on anyone.
        _app(
            "archived",
            "awaiting_review",
            archived_at="2026-10-06T00:00:00+00:00",
        ),
        _app("waiting", "fill_failed"),
    ]
    stats = store_stats.progress_stats(rows)
    assert [item.company for item in stats.sent] == ["Co bare", "Co interview"]
    assert stats.sent_total == 2
    assert stats.needs_you == 1


def test_apply_settings_banner_defaults_and_bounds():
    settings = ApplySettings()
    assert (settings.progress_banner, settings.weekly_goal) == ("goal", 10)
    with pytest.raises(ValidationError):
        ApplySettings(weekly_goal=0)
    with pytest.raises(ValidationError):
        ApplySettings(progress_banner="confetti")


def test_each_posting_carries_when_it_was_found_and_reached_each_stage():
    rows = [
        _app(
            "sent",
            "submitted",
            (("screened_in", "s"), ("ready", "r"), ("filling", "f"), ("submitted", "x")),
            discovered_at="d",
        ),
        _app("new", "discovered", discovered_at="d2"),
    ]
    times = store_stats.progress_stats(rows).postings
    assert times[0].model_dump() == {
        "company": "Co sent",
        "found_at": "d",
        "screened_in_at": "s",
        "tailored_at": "r",
        "autofilled_at": "f",
        "sent_at": "x",
    }
    assert (times[1].found_at, times[1].screened_in_at, times[1].sent_at) == ("d2", None, None)


def test_banner_options_default_and_reject_bad_values():
    apply = ApplySettings()
    assert apply.goal_banner.counts == "sent" and apply.goal_banner.week_start == "monday"
    assert apply.activity_banner.range == "13w" and apply.activity_banner.color == "green"
    assert apply.pipeline_banner.stages == ["found", "screened_in", "tailored", "autofilled", "sent"]
    custom = ApplySettings(
        activity_banner={"range": "custom", "start": "2026-09-01", "end": "2026-10-19"}
    )
    assert custom.activity_banner.start == "2026-09-01"
    for bad in (
        {"activity_banner": {"start": "Sep 1"}},
        {"pipeline_banner": {"stages": ["sent"]}},
        {"pipeline_banner": {"style": "pie"}},
        {"goal_banner": {"counts": "found"}},
    ):
        with pytest.raises(ValidationError):
            ApplySettings(**bad)


def test_an_unconfirmed_submit_counts_as_sent_like_the_reply_rates_do():
    rows = [_app("unsure", "submit_unconfirmed", (("submit_unconfirmed", "2026-09-01T09:00:00+00:00"),))]
    stats = store_stats.progress_stats(rows, today=date(2026, 10, 23))
    assert stats.sent_total == 1 and len(stats.sent) == 1
    assert stats.outcomes.sent == 1
