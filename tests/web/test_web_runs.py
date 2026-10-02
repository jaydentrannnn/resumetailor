"""Run history, downloads, and job-creation validation over the web API."""

from __future__ import annotations

import json
import time

from resume_tailor import config
from resume_tailor.pipeline import jd
from resume_tailor.web import job_types
from resume_tailor.web.routes import jobs as routes_jobs
from resume_tailor.web.schemas import JobSettings
from tests.web.helpers import _disk_only_run, _drain, _stub_no_network_extract


def test_get_config_returns_defaults(client):
    """GET /api/config exposes the knobs the SPA needs before a run."""
    c, _ = client
    res = c.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert body["pages"] == config.DEFAULT_PAGE_TARGET
    assert body["experience"] == config.MAX_EXPERIENCE_ENTRIES
    assert "claude" in body["model_profiles"]
    assert "lmstudio" in body["model_profiles"]
    assert isinstance(body["tag_vocabulary"], list)
    assert body["pdf_backend"] in ("word", "soffice")
    assert "fill_target" in body
    assert 0.8 <= body["fill_target"] <= 0.95
    assert "initial_bullet_share" in body
    assert 0.3 <= body["initial_bullet_share"] <= 1.0
    assert "experience_bullet_share" in body
    assert body["experience_bullet_share"] == config.EXPERIENCE_BULLET_SHARE
    assert "max_bullets_per_entry" in body
    assert body["max_bullets_per_entry"] == config.MAX_BULLETS_PER_ENTRY
    assert "rewrite_style_default" in body
    assert "expand_style_default" in body
    assert "rewrite_core_rules" in body
    assert "expand_core_rules" in body
    assert "cover_style_default" in body
    assert "cover_core_rules" in body
    assert "NEVER introduce a skill" in body["rewrite_core_rules"]
    assert body["bullet_char_max"] > body["bullet_char_soft_min"] > 0
    # Stored vocabulary (or derived fallback) should be non-empty for a real master resume.
    assert len(body["tag_vocabulary"]) >= 1


def test_list_jobs_includes_persisted_run(client, tmp_path, monkeypatch):
    """GET /api/jobs lists a run.json written under the active workspace's jobs dir."""
    c, _ = client
    jobs_dir = config.OUTPUT_DIR / "jobs" / "histtest01"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "run.json").write_text(
        json.dumps(
            {
                "job_id": "histtest01",
                "workspace_id": config.active_workspace_id(),
                "created_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:01:00+00:00",
                "status": "succeeded",
                "title": "History Fixture Role",
                "error": None,
                "report": {
                    "title": "History Fixture Role",
                    "seniority": "intern",
                    "coverage_matched": 1,
                    "coverage_total": 2,
                    "missing_must_haves": [],
                    "unmatched_canonicals": [],
                    "gaps": [],
                    "model": "stub",
                    "semantic_used": False,
                    "bullets_selected": 1,
                    "bullets_total": 1,
                    "experience": [],
                    "projects": [],
                    "dropped": [],
                    "pages": 1,
                    "pages_are_estimated": True,
                    "iterations": 1,
                    "widows_repaired": 0,
                    "widows_remaining": 0,
                    "verbs_diversified": 0,
                    "verb_collisions_remaining": 0,
                    "warnings": [],
                    "out_path": str(jobs_dir / "tailored.docx"),
                    "pdf_backend": "soffice",
                    "calibration_source": "fallback",
                },
            }
        ),
        encoding="utf-8",
    )
    (jobs_dir / "tailored.docx").write_bytes(b"PK\x03\x04stub")
    res = c.get("/api/jobs")
    assert res.status_code == 200
    runs = res.json()["runs"]
    match = next((r for r in runs if r["job_id"] == "histtest01"), None)
    assert match is not None
    assert match["title"] == "History Fixture Role"
    assert match["has_docx"] is True
    assert match["has_pdf"] is False
    assert match["company"] == ""


def test_run_history_lists_company_from_posting_metadata(client):
    """History search (Tailor page) matches on company, read from the run's metadata."""
    c, _q = client
    jobs_dir = config.OUTPUT_DIR / "jobs" / "histcompany01"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "run.json").write_text(
        json.dumps(
            {
                "job_id": "histcompany01",
                "workspace_id": config.active_workspace_id(),
                "created_at": "2026-01-02T00:00:00+00:00",
                "status": "succeeded",
                "title": "Analyst",
                "metadata": {"company": "Acme Capital", "role": "Analyst"},
            }
        ),
        encoding="utf-8",
    )
    runs = c.get("/api/jobs").json()["runs"]
    match = next(r for r in runs if r["job_id"] == "histcompany01")
    assert match["company"] == "Acme Capital"


def test_delete_run_history_removes_disk_artifacts(client):
    """POST /api/jobs/history/delete removes a finished run's directory."""
    c, _q = client
    job_id = "histdelete01"
    jobs_dir = config.OUTPUT_DIR / "jobs" / job_id
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "run.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "workspace_id": config.active_workspace_id(),
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "succeeded",
                "title": "Delete Me",
            }
        ),
        encoding="utf-8",
    )

    res = c.post("/api/jobs/history/delete", json={"job_ids": [job_id]})
    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] == [job_id]
    assert body["errors"] == {}
    assert not jobs_dir.exists()
    runs = c.get("/api/jobs").json()["runs"]
    assert all(r["job_id"] != job_id for r in runs)


def test_delete_run_history_rejects_active_job(client):
    """Queued and running jobs cannot be deleted from history."""
    c, q = client
    job = job_types.Job(job_id="activehist", jd_text="x", settings=JobSettings(), status="running")
    q._jobs[job.job_id] = job
    out_dir = config.OUTPUT_DIR / "jobs" / job.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.json").write_text("{}", encoding="utf-8")

    res = c.post("/api/jobs/history/delete", json={"job_ids": [job.job_id]})
    assert res.status_code == 200
    assert res.json()["deleted"] == []
    assert res.json()["errors"][job.job_id] == "still active"
    assert out_dir.exists()


def test_download_works_for_disk_only_job(client):
    """A job id absent from memory but present on disk still serves its artifact."""
    c, q = client
    job_id = "diskonly001"
    # Ensure it is not in the live queue.
    assert q.get(job_id) is None
    jobs_dir = _disk_only_run(job_id)
    (jobs_dir / "tailored.docx").write_bytes(b"PK\x03\x04disk-only")
    res = c.get(f"/api/jobs/{job_id}/download.docx")
    assert res.status_code == 200
    assert res.content == b"PK\x03\x04disk-only"
    status = c.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["title"] == "Disk Only"


def test_missing_pdf_is_rebuilt_from_the_docx(client, monkeypatch):
    """A run whose PDF step failed serves a PDF converted on first request."""
    c, _ = client
    jobs_dir = _disk_only_run("nopdf001")
    (jobs_dir / "tailored.docx").write_bytes(b"PK\x03\x04")
    (jobs_dir / "cover.docx").write_bytes(b"PK\x03\x04")
    converted = []

    def fake_convert(docx, pdf, **_):
        converted.append(docx.name)
        pdf.write_bytes(b"%PDF-rebuilt")
        return pdf

    monkeypatch.setattr(routes_jobs.convert, "convert", fake_convert)
    assert c.get("/api/jobs/nopdf001/download.pdf").content == b"%PDF-rebuilt"
    assert c.get("/api/jobs/nopdf001/preview.pdf").status_code == 200
    assert c.get("/api/jobs/nopdf001/cover-letter/preview.pdf").content == b"%PDF-rebuilt"
    assert converted == ["tailored.docx", "cover.docx"]


def test_missing_pdf_rebuild_failure_is_a_404(client, monkeypatch):
    c, _ = client
    jobs_dir = _disk_only_run("nopdf002")
    (jobs_dir / "tailored.docx").write_bytes(b"PK\x03\x04")

    def boom(docx, pdf, **_):
        raise RuntimeError("word could not convert tailored.docx")

    monkeypatch.setattr(routes_jobs.convert, "convert", boom)
    res = c.get("/api/jobs/nopdf002/download.pdf")
    assert res.status_code == 404
    assert "word could not convert" in res.json()["detail"]


def test_failed_run_writes_run_json(client, monkeypatch):
    """A failed execute still persists run.json so history can show the error."""
    c, q = client

    def boom(job):
        job.out_dir = config.OUTPUT_DIR / "jobs" / job.job_id
        job.out_dir.mkdir(parents=True, exist_ok=True)
        raise RuntimeError("forced failure for history test")

    monkeypatch.setattr(q, "_execute", boom)
    res = c.post("/api/jobs", json={"jd_text": "Looking for a Python intern.", "settings": {}})
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    # Wait briefly for the worker to mark it failed and persist.
    for _ in range(50):
        job = q.get(job_id)
        if job and job.status == "failed":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("job never reached failed")
    run_path = config.OUTPUT_DIR / "jobs" / job_id / "run.json"
    assert run_path.exists()
    record = json.loads(run_path.read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert "forced failure" in (record.get("error") or "")


def test_create_job_rejects_empty_jd(client):
    """An empty JD is a 400, not a queued no-op."""
    c, _ = client
    res = c.post("/api/jobs", json={"jd_text": "   ", "settings": {}})
    assert res.status_code == 400


def test_get_config_exposes_gemini_fields(client):
    """The settings panel needs the Gemini env defaults and which profiles use them,
    mirroring the Ollama fields it already gets."""
    c, _ = client
    body = c.get("/api/config").json()
    assert "gemini" in body["model_profiles"]
    assert body["gemini_model"] == config.GEMINI_MODEL
    assert body["gemini_base_url"] == config.GEMINI_BASE_URL
    assert "gemini" in body["gemini_profiles"]
    assert "ollama" not in body["gemini_profiles"]
    assert "gemini" in body["provider_keys"]
    # Booleans only — never the key value itself.
    assert isinstance(body["provider_keys"]["gemini"], bool)


def test_create_job_rejects_a_profile_with_no_key(client, monkeypatch):
    """A missing Gemini key must fail the POST synchronously, not surface later as an
    async `job.status == 'failed'` once the worker gets to it."""
    c, q = client
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    res = c.post(
        "/api/jobs",
        json={"jd_text": "Some job description.", "settings": {"model": "gemini"}},
    )
    assert res.status_code == 400
    assert "GEMINI_API_KEY" in res.json()["detail"]
    # The queue never saw it — rejected before `submit()`, not queued and then failed.
    assert q._jobs == {}


def test_create_job_rejects_ollama_cloud_with_no_key(client, monkeypatch):
    """Ollama Cloud's direct API needs `OLLAMA_API_KEY`; refused at the door like Gemini."""
    c, q = client
    monkeypatch.setattr(config, "credential", lambda name: "")

    res = c.post(
        "/api/jobs",
        json={"jd_text": "Some job description.", "settings": {"model": "ollama-cloud"}},
    )
    assert res.status_code == 400
    assert "OLLAMA_API_KEY" in res.json()["detail"]
    assert q._jobs == {}


def test_create_job_with_a_gemini_key_present_is_accepted(client, monkeypatch):
    """The inverse: a key present, even a fake one, must not be blocked at the door."""
    c, q = client
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(jd, "extract", _stub_no_network_extract)

    res = c.post(
        "/api/jobs",
        json={"jd_text": "Some job description.", "settings": {"model": "gemini"}},
    )
    assert res.status_code == 200
    _drain(c, res.json()["job_id"])
    config.resolve("claude")
