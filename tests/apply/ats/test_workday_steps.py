"""Workday step identity when a narrow window hides the progress bar's step names.

Live 2026-10 (Magnite, Midland, Expedia, P&G at 695px): the active step's label keeps only
``current step N of M``; the step's own heading (the apply flow's first ``h3``) still
names it. At 1280px the same label reads ``current step 1 of 7 Create Account/Sign In``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from resume_tailor.apply.ats import workday_flow, workday_page
from resume_tailor.apply.forms import fill_ats_steps, fill_widgets, fill_wizard

_SCREENS = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "workday" / "screens.json").read_text(encoding="utf-8")
)

#: Captured live (P&G and Midland, 695px emulation): innerText of progressBarActiveStep
#: and the first visible h3 of applyFlowPage.
_MY_EXPERIENCE_NARROW = {
    **_SCREENS["my_information"],
    "active_step": "current step 2 of 6",
    "step_title": "My Experience",
}
_MY_EXPERIENCE_WIDE = {**_MY_EXPERIENCE_NARROW, "active_step": "current step 2 of 6\nMy Experience"}
_REVIEW_NARROW = {**_SCREENS["my_information"], "active_step": "current step 6 of 6", "step_title": ""}


def test_active_step_falls_back_to_the_step_heading_when_the_label_has_no_name():
    assert workday_page.active_step(_MY_EXPERIENCE_NARROW) == "My Experience"
    assert workday_page.active_step(_MY_EXPERIENCE_WIDE) == "My Experience"
    # No progress bar at all (a posting, the auth chooser): no step, whatever the headings.
    assert workday_page.active_step({"active_step": "", "step_title": "Sign In"}) == ""


def test_step_position_and_key_survive_a_narrow_window():
    assert workday_page.step_position(_MY_EXPERIENCE_NARROW) == "2 of 6"
    assert workday_page.step_position(_SCREENS["my_information"]) == "1 of 6"
    assert workday_page.step_position({"active_step": ""}) == ""
    # A resize mid-step changes the label's text but not the step.
    assert workday_page.step_key(_MY_EXPERIENCE_NARROW) == workday_page.step_key(_MY_EXPERIENCE_WIDE)
    assert workday_page.step_key(_SCREENS["my_information"]) != workday_page.step_key(_MY_EXPERIENCE_NARROW)


def test_the_last_step_is_review_even_without_its_name():
    assert workday_page.is_review_step(_REVIEW_NARROW)
    assert workday_page.is_review_step({"active_step": "current step 6 of 6 Review"})
    assert not workday_page.is_review_step(_MY_EXPERIENCE_NARROW)


class _Steps:
    """A page whose progress bar moves from ``screens[0]`` to the next after each wait."""

    def __init__(self, *screens: dict) -> None:
        self.screens = list(screens)

    def evaluate(self, script, *_args):
        if script == workday_flow._SAVING_JS:  # noqa: SLF001
            return False
        return self.screens[0]

    def wait_for_timeout(self, _ms):
        if len(self.screens) > 1:
            self.screens.pop(0)


def test_an_unnamed_step_change_is_seen_and_a_resize_is_not(monkeypatch):
    monkeypatch.setattr(workday_page, "snapshot", lambda p: p.evaluate("snapshot"))
    clock = SimpleNamespace(now=0.0)

    def tick():
        clock.now += 0.25
        return clock.now

    monkeypatch.setattr(workday_flow.time, "monotonic", tick)
    before = workday_page.step_key({"active_step": "current step 1 of 6"})
    moved = _Steps({"active_step": "current step 1 of 6"}, _MY_EXPERIENCE_NARROW)
    assert workday_flow.wait_for_step_change(moved, before, deadline=1e9, timeout_s=5)

    before = workday_page.step_key(_MY_EXPERIENCE_NARROW)
    resized = _Steps(_MY_EXPERIENCE_NARROW, _MY_EXPERIENCE_WIDE)
    assert not workday_flow.wait_for_step_change(resized, before, deadline=1e9, timeout_s=5)


def _rows_run(monkeypatch, snap: dict) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(workday_page, "snapshot", lambda _page: snap)
    monkeypatch.setattr(
        fill_widgets, "_fill_workday_experience_and_education",
        lambda *_a: (calls.append("rows") or [{"label": "Education: UC Irvine", "value": "BS"}], []),
    )
    run = fill_ats_steps._FillAtsSteps.__new__(fill_ats_steps._FillAtsSteps)
    run.page, run.pkt, run.progress = object(), object(), lambda _m: None
    run.merged, run.needs_review = {"filled": []}, []
    run._workday_rows()  # noqa: SLF001
    return calls


def test_rows_fill_on_an_unnamed_my_experience_step(monkeypatch):
    # Tonight's P&G / Expedia / Midland fills: no rows were ever attempted.
    assert _rows_run(monkeypatch, _MY_EXPERIENCE_NARROW) == ["rows"]


def test_rows_never_touch_the_review_step(monkeypatch):
    assert _rows_run(monkeypatch, _REVIEW_NARROW) == []


def test_an_unnamed_step_that_advanced_is_not_unchanged(monkeypatch):
    run = fill_wizard._FillWizard.__new__(fill_wizard._FillWizard)
    run.is_workday, run.page = True, object()
    before = workday_page.step_key({"active_step": "current step 1 of 6"})
    monkeypatch.setattr(workday_page, "snapshot", lambda _page: _MY_EXPERIENCE_NARROW)
    assert not run._step_unchanged(None, before)  # noqa: SLF001
    monkeypatch.setattr(workday_page, "snapshot", lambda _page: {"active_step": "current step 1 of 6"})
    assert run._step_unchanged(None, before)  # noqa: SLF001
