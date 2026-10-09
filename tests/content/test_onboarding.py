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
    assert onboarding.save(completed=True).step == "done"


def test_existing_install_is_marked_complete(profile_dir):
    (profile_dir / "master_resume.json").write_text(
        json.dumps(synthetic_resume().model_dump(mode="json", by_alias=True))
    )
    assert onboarding.load().completed is True
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
        assert c.get("/api/onboarding").json()["field"] == "cs"
