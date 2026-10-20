"""The Apply page's progress banner counts (`store_stats.progress_stats`)."""

from __future__ import annotations

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
