"""The offline application report (`report_html`): counts, denominators and escaping."""

from __future__ import annotations

from datetime import date

from resume_tailor.apply.funnel import report_html, store_models

TODAY = date(2026, 10, 23)


def _event(kind: str, on: str) -> store_models.OutcomeEvent:
    return store_models.OutcomeEvent(
        id=f"{kind}-{on}", type=kind, occurred_on=on, recorded_at=f"{on}T12:00:00+00:00"
    )


def _app(key: str, status: str = "submitted", sent: str | None = "2026-09-01", **extra):
    history = [store_models.StatusChange(status=status, at=f"{sent}T09:00:00+00:00")] if sent else []
    return store_models.Application(
        source=extra.pop("source", "simplify"), source_job_id=key,
        company=extra.pop("company", f"Co {key}"),
        role="Analyst Intern", status=status, status_history=history, **extra,
    )


def test_a_rejection_after_an_interview_still_counts_as_interviewed():
    rows = [
        _app("a", outcome_events=[_event("interview_invited", "2026-09-10"),
                                  _event("rejected", "2026-09-20")]),
        _app("b"),
    ]
    data = report_html.summarize(rows, today=TODAY)
    assert data.reached["interview"] == 1 and data.reached["applied"] == 2
    assert data.rejected == 1
    assert data.cohort.sent == 2 and data.cohort.interviewed == 1


def test_silence_is_kept_apart_from_rejection():
    rows = [
        _app("quiet"),
        _app("marked", outcome_events=[_event("ghosted", "2026-10-01")]),
        _app("no", outcome_events=[_event("rejected", "2026-09-15")]),
    ]
    data = report_html.summarize(rows, today=TODAY)
    assert (data.rejected, data.marked_no_reply, data.no_reply_yet) == (1, 1, 1)


def test_recent_sends_wait_outside_the_cohort_and_prepared_rows_are_counted_apart():
    rows = [
        _app("old"),
        _app("new", sent="2026-10-20"),
        _app("ready", status="ready", sent=None),
        _app("done-ready", status="ready", sent=None, archived_at="2026-10-01T00:00:00+00:00"),
    ]
    data = report_html.summarize(rows, today=TODAY)
    assert len(data.sent) == 2 and data.cohort.sent == 1
    assert data.prepared == 1
    assert data.weekly[-1] == ("2026-10-19", 1)


def test_how_each_application_was_sent():
    attempt = store_models.SubmissionAttempt(
        id="x", number=1, submitted_at="2026-09-01T09:00:00+00:00", method="auto", confirmed=True
    )
    rows = [
        _app("app", attempts=[attempt]),
        _app("hand"),
        _app("unsure", status="submit_unconfirmed"),
    ]
    data = report_html.summarize(rows, today=TODAY)
    assert {row.company: row.how for row in data.sent} == {
        "Co app": "app", "Co hand": "hand", "Co unsure": "unconfirmed"
    }


def test_every_value_is_escaped_and_the_page_needs_nothing_from_the_network():
    rows = [_app("x", source="<b>src</b>", company="<script>alert(1)</script>")]
    html = report_html.build(rows, today=TODAY, profile="Me & co")
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "Me &amp; co" in html
    assert "http://" not in html and "https://" not in html and "<script" not in html


def test_rates_show_their_denominator_and_an_empty_registry_renders():
    html = report_html.build([_app("a"), _app("b", outcome_events=[_event("offer", "2026-09-30")])],
                             today=TODAY)
    assert "1 of 2 (50%)" in html
    empty = report_html.build([], today=TODAY)
    assert "Nothing has been sent yet." in empty and "0 of 0" in empty
