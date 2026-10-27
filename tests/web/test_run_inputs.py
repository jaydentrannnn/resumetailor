"""What a run records it was built from: every setting that changes its output counts."""

from __future__ import annotations

import pytest

from resume_tailor.web import job_routing, run_inputs
from resume_tailor.web.schemas import IncludeOptions, JobSettings
from tests.fixtures import synthetic_resume


@pytest.fixture(autouse=True)
def _fixed_routing(monkeypatch):
    monkeypatch.setattr(run_inputs, "_template", lambda: "template")
    monkeypatch.setattr(job_routing, "model_routing", lambda _settings: ("ollama", {}, None))


def _inputs(**changes) -> dict[str, str]:
    return run_inputs.fingerprints(synthetic_resume(), JobSettings(**changes), None)


@pytest.mark.parametrize("changes", [
    {"no_semantic": True}, {"pages": 2}, {"experience": 2}, {"max_bullets_per_entry": 3},
    {"fill_target": 0.9}, {"merge": False}, {"no_widow_repair": True},
    {"include": IncludeOptions(gpa=False)},
], ids=lambda changes: next(iter(changes)))
def test_a_setting_that_changes_the_output_changes_the_inputs(changes):
    assert _inputs(**changes) != _inputs()


@pytest.mark.parametrize("changes", [
    {"max_concurrent_jobs": 5}, {"no_cache": True}, {"start_page": "/applications"},
    {"no_expand": False}, {"cover_letter": True},
], ids=lambda changes: next(iter(changes)))
def test_app_layout_concurrency_and_on_demand_stages_do_not(changes):
    assert _inputs(**changes) == _inputs()
