"""A value the form rejects at the end of a fill is validated again, then handed over."""

from __future__ import annotations

from types import SimpleNamespace

from resume_tailor.apply.forms import fill_finish


def _run(*scans: dict) -> fill_finish._FillFinish:
    run = fill_finish._FillFinish.__new__(fill_finish._FillFinish)
    replies = iter(scans)
    run.calls = []

    def evaluate(script, args=None):
        run.calls.append(args)
        return {"required_empty": [], "invalid": []} if args else next(replies)

    run.page = SimpleNamespace(frames=[SimpleNamespace(evaluate=evaluate)],
                               wait_for_timeout=lambda _ms: None)
    run.readiness_js = "ready"
    run.merged = {"leftovers": []}
    run.needs_review = []
    run.lines = []
    run.on_progress = run.lines.append
    return run


def test_a_rejected_value_becomes_a_review_line_and_blocks_submit():
    run = _run({"required_empty": [], "invalid": ["Email"]},
               {"required_empty": ["City"], "invalid": ["Email"]})
    assert run._final_required_empty() == ["City"]  # noqa: SLF001
    assert run.calls == [None, {"revalidate": True}, None]
    assert run.needs_review == [f"Email: {fill_finish.REJECTED_NOTE}"]


def test_a_stale_rejection_that_clears_leaves_no_review_line():
    run = _run({"required_empty": [], "invalid": ["Phone"]},
               {"required_empty": [], "invalid": []})
    assert run._final_required_empty() == []  # noqa: SLF001
    assert run.needs_review == []


def test_no_rejection_skips_the_second_pass():
    run = _run({"required_empty": [], "invalid": []})
    run._final_required_empty()  # noqa: SLF001
    assert run.calls == [None]
