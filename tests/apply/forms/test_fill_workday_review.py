"""Continue fill on a captured read-only Workday Review step still checks readiness."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from resume_tailor.apply.forms import fill_finish

_SNAPSHOT = Path(__file__).parents[2] / "fixtures/forms/workday_review_snapshot.json"


@pytest.mark.parametrize("review_step", [True, False])
@pytest.mark.parametrize("final_step_reached", [True, False])
def test_only_a_confirmed_workday_review_page_can_have_zero_controls(
    monkeypatch, review_step, final_step_reached,
):
    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    if not review_step:
        snapshot.update(active_step="current step 1 of 6 Create Account", step_title="")
    run = object.__new__(fill_finish._FillFinish)  # noqa: SLF001 - isolated finish guard
    run.page = SimpleNamespace(evaluate=lambda _js: snapshot,
                               inner_text=lambda _selector: "", url="https://example.test/apply")
    run.is_workday = True
    run.final_step_reached = final_step_reached
    run.barrier_hit = ""
    run.merged = {}
    run.target_id = "captured-review"
    run.app = SimpleNamespace(fill=None)
    run.progress = lambda _message: None
    monkeypatch.setattr(fill_finish.store, "set_status", lambda *_a, **_kw: None)
    monkeypatch.setattr(fill_finish.store, "upsert", lambda _app: None)

    result = run._readiness_guard(0, None)  # noqa: SLF001
    if review_step and final_step_reached:
        assert result is None
        assert run.app.fill is None
    else:
        assert result.status == "fill_failed"
        assert result.error == "No application form controls detected on page"
