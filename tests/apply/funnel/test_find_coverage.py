"""Find's must-have coverage agrees with the tailor run that follows it."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import daily, store, store_models
from resume_tailor.web.schemas import JobSettings


@pytest.fixture
def apply_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    return tmp_path


def test_find_skill_list_matches_the_tailor_run_without_touching_its_context(
    monkeypatch, tmp_path
):
    """Find's screen extracts with the same `known_tags` a tailor job computes after
    `prepare_run`, so the job reuses the screen's cached JD extraction (one reading,
    one must-have count), and never replaces a running job's installed context."""
    from resume_tailor.content import bullet_tags
    from resume_tailor.pipeline import tag_infer
    from tests.fixtures import synthetic_resume

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tag_infer, "infer", lambda texts, preferred=(): {t: ["Quantum Annealing"] for t in texts}
    )
    resume = synthetic_resume()
    bullet_tags.clear()

    screen_tags = daily._resume_skills(resume, JobSettings())

    assert "quantum annealing" in screen_tags
    assert "quantum annealing" not in bullet_tags.known_terms(resume)  # context untouched
    tag_infer.prepare_run(resume)  # what the tailor job does first
    assert screen_tags == bullet_tags.known_terms(resume)


def test_rows_show_their_tailor_run_coverage(apply_paths):
    from resume_tailor.apply.funnel.screen import ScreenResult

    run_dir = config.OUTPUT_DIR / "jobs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"report": {"coverage_matched": 6, "coverage_total": 9}}), encoding="utf-8"
    )
    app = store_models.Application(
        source="test", source_job_id="one", company="Acme", role="Engineer", job_id="run-1",
        screen=ScreenResult(passed=True, coverage=0.7, coverage_matched=7, coverage_total=10),
    )
    store.upsert(app)

    assert daily.sync_run_coverage() == 1
    screen = store.get(app.source_job_id).screen
    assert (screen.coverage_matched, screen.coverage_total) == (6, 9)
    assert daily.sync_run_coverage() == 0
