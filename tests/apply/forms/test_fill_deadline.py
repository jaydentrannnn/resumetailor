"""A fill's time budget grows with forward progress, up to a hard cap."""

from __future__ import annotations

from resume_tailor.apply.forms import fill_outcomes


def test_forward_progress_lines_are_recognised():
    assert fill_outcomes.is_forward_progress("Workday: added skill Python -> Python (exact)")
    assert fill_outcomes.is_forward_progress("Workday: filled Language: English")
    assert fill_outcomes.is_forward_progress("scanning form step 3")
    assert fill_outcomes.is_forward_progress("uploading resume: resume.pdf")
    assert not fill_outcomes.is_forward_progress("Workday: Language: English needs review (Speaking)")
    assert not fill_outcomes.is_forward_progress("connecting to browser")


def test_progress_extends_the_deadline_but_never_past_the_cap():
    started = 1000.0
    deadline = started + fill_outcomes.BASE_BUDGET_S
    # Early progress leaves a later deadline alone.
    assert fill_outcomes.extended_deadline(deadline, started, started + 10) == deadline
    # Progress near the end buys the grace period.
    near_end = deadline - 5
    assert fill_outcomes.extended_deadline(deadline, started, near_end) == (
        near_end + fill_outcomes.PROGRESS_GRACE_S
    )
    # Never past the hard cap.
    late = started + fill_outcomes.HARD_CAP_S - 10
    assert fill_outcomes.extended_deadline(late, started, late) == (
        started + fill_outcomes.HARD_CAP_S
    )
