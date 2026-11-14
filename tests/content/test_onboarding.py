"""First-run onboarding progress (`onboarding.py`, `/api/onboarding`)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.content import onboarding
from resume_tailor.storage import db
from resume_tailor.web.app import app
from tests.fixtures import synthetic_resume

_STARTER = {"contact": {"name": "Your Name", "email": "you@example.com"}, "education": [],
            "experience": [], "projects": [], "skills": [], "tag_vocabulary": []}


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    resume = tmp_path / "master_resume.json"
    resume.write_text(json.dumps(_STARTER))
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume)
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "main_template.docx")
    yield tmp_path
    db.close_all()


def test_fresh_profile_starts_at_the_first_step(profile_dir):
    state = onboarding.load()
    assert (state.step, state.completed, state.skipped) == ("field", False, False)
    # Reading a fresh profile writes nothing, so it stays fresh.
    conn = db.connect(db.db_path(profile_dir))
    assert db.kv_get(conn, onboarding.KEY) is None


def test_progress_is_saved_and_resumed(profile_dir):
    onboarding.save(field="business", step="resume")
    state = onboarding.load()
    assert (state.field, state.step, state.completed) == ("business", "resume", False)


def test_the_app_opens_after_stage_one_and_setup_ends_after_stage_two(profile_dir):
    state = onboarding.save(completed=True, step="personal")
    assert (state.step, state.completed, state.apply_done) == ("personal", True, False)
    assert onboarding.save(apply_done=True).step == "done"
    # Going back to edit a finished step names that step, so it is not forced to "done".
    assert onboarding.save(step="field").step == "field"
    assert onboarding.save(guide_dismissed=True).guide_dismissed is True


def test_existing_install_is_marked_complete(profile_dir):
    (profile_dir / "master_resume.json").write_text(
        json.dumps(synthetic_resume().model_dump(mode="json", by_alias=True))
    )
    state = onboarding.load()
    assert (state.completed, state.apply_done, state.guide_dismissed) == (True, True, True)
    # Recorded, so emptying the resume later does not reopen the wizard.
    (profile_dir / "master_resume.json").write_text(json.dumps(_STARTER))
    assert onboarding.load().completed is True


def test_installed_template_counts_as_existing(profile_dir):
    (profile_dir / "main_template.docx").write_bytes(b"x")
    assert onboarding.load().completed is True


def test_malformed_row_restarts_the_wizard(profile_dir):
    conn = db.connect(db.db_path(profile_dir))
    db.kv_set(conn, onboarding.KEY, {"step": "nonsense"})
    assert onboarding.load().step == "field"
    assert onboarding.save(step="tools").step == "tools"


@pytest.mark.parametrize(
    ("old", "new"), [("model", "tools"), ("review", "content"), ("basics", "application")]
)
def test_old_wizard_steps_resume_at_their_replacement(profile_dir, old, new):
    conn = db.connect(db.db_path(profile_dir))
    db.kv_set(conn, onboarding.KEY, {"step": old, "field": "cs", "completed": False})
    assert (onboarding.load().step, onboarding.load().field) == (new, "cs")
    # A row the new wizard saved keeps "review" as the summary step.
    onboarding.save(step="review")
    assert onboarding.load().step == "review"


@pytest.mark.parametrize(
    ("row", "step", "completed", "apply_done", "dismissed"),
    [
        # Finished in the one-stage wizard: nothing new to do, and no guide.
        ({"step": "done", "completed": True}, "done", True, True, True),
        # Personal info used to come third; the content check is the next stage-one step.
        ({"step": "personal", "skipped_steps": []}, "content", False, False, False),
        # Past every stage-one step: the app opens and stage two resumes where they were.
        ({"step": "application", "skipped_steps": []}, "application", True, False, False),
        ({"step": "review", "skipped_steps": []}, "review", True, False, False),
        # Still inside stage one: unchanged.
        ({"step": "tools", "skipped_steps": []}, "tools", False, False, False),
    ],
)
def test_one_stage_rows_map_onto_the_two_stages(
    profile_dir, row, step, completed, apply_done, dismissed
):
    conn = db.connect(db.db_path(profile_dir))
    db.kv_set(conn, onboarding.KEY, row)
    state = onboarding.load()
    assert (state.step, state.completed, state.apply_done, state.guide_dismissed) == (
        step, completed, apply_done, dismissed,
    )


def test_a_two_stage_row_is_read_as_saved(profile_dir):
    onboarding.save(step="personal", completed=True)
    state = onboarding.load()
    assert (state.step, state.completed, state.apply_done) == ("personal", True, False)


def test_skipped_steps_and_scratch_round_trip(profile_dir):
    onboarding.save(skipped_steps=["tools", "personal"], resume_from_scratch=True)
    state = onboarding.load()
    assert (state.skipped_steps, state.resume_from_scratch) == (["tools", "personal"], True)


def test_api_round_trip_and_validation(profile_dir):
    with TestClient(app) as c:
        assert c.get("/api/onboarding").json()["step"] == "field"
        body = c.put("/api/onboarding", json={"field": "cs", "step": "tools"}).json()
        assert (body["field"], body["step"]) == ("cs", "tools")
        assert c.put("/api/onboarding", json={"step": "bogus"}).status_code == 422
        assert c.put("/api/onboarding", json={"skipped": True}).json()["skipped"] is True
        body = c.put("/api/onboarding", json={"apply_done": True, "guide_dismissed": True}).json()
        assert (body["apply_done"], body["guide_dismissed"]) == (True, True)
        assert c.get("/api/onboarding").json()["field"] == "cs"
