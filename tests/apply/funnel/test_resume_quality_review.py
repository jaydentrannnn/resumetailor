import json

import pytest

from resume_tailor import config
from resume_tailor.apply.forms import submit_guard
from resume_tailor.apply.funnel import preparation, resume_review, store, store_models
from resume_tailor.pipeline import resume_quality
from resume_tailor.web.schemas import ApplySettings
from tests.fixtures import synthetic_resume


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    out = config.OUTPUT_DIR / "jobs" / "run1"
    out.mkdir(parents=True)
    (out / "tailored.docx").write_bytes(b"resume1")
    (out / "run.json").write_text(json.dumps({"status": "succeeded"}), "utf-8")
    (out / "expansion.json").write_text(
        json.dumps({"entries": [], "source_experience_count": 0}), "utf-8"
    )
    app = store.upsert(
        store_models.Application(
            source="test",
            source_job_id="one",
            company="Acme",
            role="Engineer",
            status="ready",
            job_id="run1",
        )
    )
    return app, out


def test_entire_selected_section_only_and_underfill():
    resume = synthetic_resume()
    bullets = {b.id: b.text for b in resume.experience[0].bullets}
    quality = resume_quality.assess(resume, bullets, {}, fill_ratio=0.81, fill_target=0.93)
    assert "81%" in quality.warnings[0]
    assert [s.title for s in quality.missing_sections] == [resume.sections[2].title]
    resume.sections = [s for s in resume.sections if s.kind != "project"]
    assert not resume_quality.assess(
        resume, bullets, {}, fill_ratio=0.93, fill_target=0.93
    ).warnings


def test_unsupported_section_warning_uses_section_identity():
    resume = synthetic_resume()
    quality = resume_quality.assess(
        resume,
        {b.id: b.text for b in resume.all_bullets()},
        {"enabled": {"skills": False}},
        fill_ratio=0.95,
        fill_target=0.93,
    )
    assert quality.missing_sections[0].id == resume.sections[-1].id
    assert "template" in quality.missing_sections[0].reason


def test_acknowledgement_required_and_invalidated_by_artifact_or_quality_changes(prepared):
    app, out = prepared
    resume_quality.save(out, resume_quality.ResumeQuality(fill_ratio=0.8, fill_target=0.93))
    assert "resume_quality_ack_required" in preparation.check(app, require_cover=False).reasons
    state = resume_review.state(app)
    app = resume_review.acknowledge("one", state.revision)
    assert preparation.check(app, require_cover=False).eligible
    assert resume_review.state(store.get("one")).acknowledged
    (out / "tailored.docx").write_bytes(b"edited resume")
    assert resume_review.state(app).required
    with pytest.raises(ValueError, match="changed"):
        resume_review.acknowledge("one", state.revision)
    app = resume_review.acknowledge("one", resume_review.state(app).revision)
    resume_quality.save(out, resume_quality.ResumeQuality(fill_ratio=0.75, fill_target=0.93))
    assert resume_review.state(app).required


def test_clean_resume_needs_no_ack_and_unknown_legacy_run_needs_prepare(prepared):
    app, out = prepared
    assert "resume_quality_unverified" in preparation.check(app, require_cover=False).reasons
    with pytest.raises(ValueError, match="verified"):
        resume_review.acknowledge("one", resume_review.state(app).revision)
    resume_quality.save(out, resume_quality.ResumeQuality(fill_ratio=0.94, fill_target=0.93))
    assert preparation.check(app, require_cover=False).eligible
    assert not resume_review.state(app).required


def test_automatic_submit_checks_live_acknowledgement(prepared):
    app, out = prepared
    resume_quality.save(out, resume_quality.ResumeQuality(fill_ratio=0.8, fill_target=0.93))
    assert submit_guard.check(app, ApplySettings()).code == "resume_quality"
    resume_review.acknowledge("one", resume_review.state(app).revision)
    assert submit_guard.check(app, ApplySettings()) is None
