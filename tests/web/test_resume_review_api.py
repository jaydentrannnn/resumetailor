import json

from resume_tailor import config
from resume_tailor.apply.funnel import store, store_models
from resume_tailor.pipeline import resume_quality


def test_fill_api_requires_current_resume_acknowledgement(client, tmp_path, monkeypatch):
    c, _ = client
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    out = config.OUTPUT_DIR / "jobs" / "resume1"
    out.mkdir(parents=True)
    (out / "run.json").write_text(json.dumps({"status": "succeeded"}), "utf-8")
    (out / "tailored.docx").write_bytes(b"resume")
    (out / "cover.docx").write_bytes(b"cover")
    (out / "expansion.json").write_text(
        json.dumps({"entries": [], "source_experience_count": 0}), "utf-8"
    )
    resume_quality.save(out, resume_quality.ResumeQuality(fill_ratio=0.81, fill_target=0.93))
    store.upsert(
        store_models.Application(
            source="test",
            source_job_id="one",
            company="Acme",
            role="Engineer",
            status="ready",
            job_id="resume1",
        )
    )
    row = c.get("/api/applications/one").json()["application"]
    assert row["preparation_reasons"] == ["resume_quality_ack_required"]
    blocked = c.post(
        "/api/applications/operations",
        json={
            "action": "fill",
            "application_ids": ["one"],
            "model_provider": "ollama",
            "model_name": "test",
        },
    )
    assert blocked.status_code == 422
    assert "resume_quality_ack_required" in blocked.json()["detail"]
    revision = row["resume_review"]["revision"]
    ack = c.post("/api/applications/one/resume-acknowledgement", json={"revision": revision})
    assert ack.status_code == 200
    assert ack.json()["preparation_eligible"]
    (out / "tailored.docx").write_bytes(b"new resume")
    assert (
        c.post(
            "/api/applications/one/resume-acknowledgement", json={"revision": revision}
        ).status_code
        == 409
    )
    assert not c.get("/api/applications/one").json()["application"]["preparation_eligible"]
