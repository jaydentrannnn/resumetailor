"""The generic pass leaves the controls `smartrecruiters_flow` fills itself: its records
for them are dropped, and a rescan does not handle them again (2026-10-30: answered
screening questions came back as blank "*" leftovers)."""

from __future__ import annotations

from resume_tailor.apply.ats import smartrecruiters_page, smartrecruiters_screening
from resume_tailor.apply.forms import fill_widgets, fill_wizard


def _run(monkeypatch, *, smartrecruiters: bool = True) -> fill_wizard._FillWizard:
    run = fill_wizard._FillWizard.__new__(fill_wizard._FillWizard)
    run.is_smartrecruiters, run.page = smartrecruiters, object()
    monkeypatch.setattr(smartrecruiters_page, "is_form", lambda _page: True)
    monkeypatch.setattr(
        smartrecruiters_screening, "screening_selectors", lambda _page: {"#question_1"}
    )
    run.merged = {key: [] for key in ("filled", "leftovers", "long_text", "file_inputs")}
    run.merged["required_empty"] = []
    return run


_OWN_CITY = {"label": "City", "value": "Irvine, CA, US", "key": "smartrecruiters_entry"}


def test_the_generic_records_for_the_flows_controls_are_dropped(monkeypatch):
    run = _run(monkeypatch)
    run.merged.update(
        filled=[_OWN_CITY, {"label": "City*", "selector": "#spl-form-element_10"}],
        leftovers=[{"label": "", "selector": "#question_1"}, {"label": "Middle name", "selector": "#m"}],
        long_text=[{"label": "", "selector": "#question_1"}],
        required_empty=["*", "Middle name"],
        file_inputs=[{"selector": "#file-input"}, {"selector": "#transcript"}],
    )
    run._drop_smartrecruiters_owned()  # noqa: SLF001
    assert run.merged["filled"] == [_OWN_CITY]
    assert run.merged["leftovers"] == [{"label": "Middle name", "selector": "#m"}]
    assert run.merged["long_text"] == []
    assert run.merged["required_empty"] == ["Middle name"]
    assert run.merged["file_inputs"] == [{"selector": "#transcript"}]


def test_a_rescan_hands_on_only_what_no_flow_owns(monkeypatch):
    run = _run(monkeypatch)
    run.filler_js = run.fields = run.hints = run.facts = None
    run._sync_frames = lambda: [object()]  # noqa: SLF001
    monkeypatch.setattr(fill_widgets, "_fill_frame", lambda *_args: {
        "long_text": [{"label": "", "selector": "#question_1"}, {"label": "Why us?", "selector": "#why"}],
        "leftovers": [{"label": "City*", "selector": "#spl-form-element_10"}],
    })
    handled: list[dict] = []
    run._handle_revealed = handled.append  # noqa: SLF001
    run._rescan_revealed()  # noqa: SLF001
    assert handled == [{
        "leftovers": [], "long_text": [{"label": "Why us?", "selector": "#why", "frame_index": 0}],
        "file_inputs": [],
    }]


def test_other_sites_keep_every_record(monkeypatch):
    run = _run(monkeypatch, smartrecruiters=False)
    assert run._flow_owned() is None  # noqa: SLF001
