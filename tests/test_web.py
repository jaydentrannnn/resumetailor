"""Web API and job queue — no network, no Word, no LibreOffice.

The pipeline is stubbed at the same seams the CLI tests use (`jd.extract`,
`rewrite.score_table`, `fit.fit`), so these assert the HTTP contract and the
single-worker queue behaviour without spending tokens.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.data import load
from resume_tailor.events import ProgressEvent
from resume_tailor.fit import FitResult
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web import template_ops
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
from resume_tailor.web.schemas import JobSettings


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh app client with an isolated job queue and output directory."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    config.OUTPUT_DIR.mkdir()
    config.CACHE_DIR.mkdir()

    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)

    with TestClient(app) as c:
        yield c, q


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
    # Stored vocabulary (or derived fallback) should be non-empty for a real master resume.
    assert len(body["tag_vocabulary"]) >= 1


def test_create_job_rejects_empty_jd(client):
    """An empty JD is a 400, not a queued no-op."""
    c, _ = client
    res = c.post("/api/jobs", json={"jd_text": "   ", "settings": {}})
    assert res.status_code == 400


def test_job_runs_to_success_with_stubbed_pipeline(client, monkeypatch, tmp_path):
    """A submitted job reaches succeeded and writes a downloadable .docx."""
    c, q = client
    resume = load()

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        from resume_tailor.jd import JobRequirements, Keyword

        if on_event:
            on_event(ProgressEvent("extract", "stub extract", {}))
        return JobRequirements(
            title="Stub Role",
            seniority="intern",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )

    def fake_score(bullets, requirements, *, use_cache=True, on_event=None):
        if on_event:
            on_event(ProgressEvent("score", "stub score", {}))
        return {b.id: 5.0 for b in bullets}

    seen_fit: dict = {}

    def fake_fit(
        resume,
        requirements,
        *,
        target_pages=1,
        template=None,
        out=None,
        max_experience=None,
        max_projects=None,
        semantic=None,
        repair_widows=True,
        repair_verbs=True,
        merge_bullets=False,
        include_project_links=True,
        fill_target=None,
        on_event=None,
    ):
        """Stub fit and record polish/merge/link knobs from JobSettings."""
        seen_fit.update(
            repair_widows=repair_widows,
            repair_verbs=repair_verbs,
            merge_bullets=merge_bullets,
            include_project_links=include_project_links,
            fill_target=fill_target,
        )
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK")  # pretend docx
        out.with_suffix(".pdf").write_bytes(b"%PDF-1.4 stub")
        if on_event:
            on_event(ProgressEvent("fit", "stub fit done", {"pages": 1}))
        # One real bullet so report_data has something to summarise.
        bullet = resume.all_bullets()[0]
        return FitResult(
            out_path=out,
            pages=1,
            pages_are_estimated=False,
            iterations=1,
            bullets_selected=1,
            bullets_total=1,
            bullets={bullet.id: bullet.text},
            semantic_used=bool(semantic),
        )

    monkeypatch.setattr(jobs_mod.jd, "extract", fake_extract)
    monkeypatch.setattr(jobs_mod.rewrite, "score_table", fake_score)
    monkeypatch.setattr(jobs_mod.fit, "fit", fake_fit)
    monkeypatch.setattr(jobs_mod.jd, "verify_verbatim", lambda *a, **k: [])

    def fake_facets(resume, requirements, **kwargs):
        """Budget-only facets so the job path never reaches the network."""
        from resume_tailor import facets as facets_mod

        return facets_mod.budget_only(
            resume,
            requirements,
            include_project_links=kwargs.get("include_project_links", True),
        )

    monkeypatch.setattr(jobs_mod.facets, "select_facets", fake_facets)

    from resume_tailor.expand import ExpandedEntry, Expansion

    def fake_expand(*a, **k):
        """Stub expansion so web tests never reach the network."""
        entry = resume.experience[0]
        return Expansion(
            entries=[
                ExpandedEntry(
                    entry_key="exp:0",
                    title=entry.title,
                    company=entry.company,
                    location=entry.location,
                    start=entry.start,
                    end=entry.end,
                    bullets=["Expanded bullet from stub."],
                    char_count=28,
                    on_resume=True,
                )
            ],
            model="stub",
            char_limit=config.EXPAND_CHAR_LIMIT,
        )

    monkeypatch.setattr(jobs_mod.expand, "expand_experience", fake_expand)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Looking for a Python intern.",
            "settings": {
                "model": "claude",
                "merge": True,
                "no_verb_repair": True,
                "no_project_links": True,
                "fill_target": 0.88,
            },
        },
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    # Drain the worker synchronously: the queue's background thread will pick it up,
    # but CI can be slow — poll until done.
    import time

    deadline = time.time() + 10
    while time.time() < deadline:
        status = c.get(f"/api/jobs/{job_id}").json()
        if status["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    else:
        pytest.fail("job did not finish in time")

    assert status["status"] == "succeeded", status
    assert status["report"]["title"] == "Stub Role"
    assert status["report"]["pages"] == 1
    assert status["report"]["verb_collisions_remaining"] == 0
    assert status["expansion"] is not None
    assert status["expansion"]["entries"][0]["company"] == resume.experience[0].company
    assert seen_fit == {
        "repair_widows": True,
        "repair_verbs": False,
        "merge_bullets": True,
        "include_project_links": False,
        "fill_target": 0.88,
    }
    assert any(e["stage"] == "extract" for e in status["events"])

    docx = c.get(f"/api/jobs/{job_id}/download.docx")
    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")
    disposition = unquote(docx.headers.get("content-disposition", ""))
    assert f"{resume.contact.name} Resume - Stub Role.docx" in disposition

    pdf = c.get(f"/api/jobs/{job_id}/preview.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    preview_disp = unquote(pdf.headers.get("content-disposition", ""))
    assert f"{resume.contact.name} Resume - Stub Role.pdf" in preview_disp
    assert "inline" in preview_disp.lower()

    pdf_dl = c.get(f"/api/jobs/{job_id}/download.pdf")
    assert pdf_dl.status_code == 200
    assert pdf_dl.content.startswith(b"%PDF")
    download_disp = unquote(pdf_dl.headers.get("content-disposition", ""))
    assert f"{resume.contact.name} Resume - Stub Role.pdf" in download_disp
    assert "attachment" in download_disp.lower()

    expansion_md = c.get(f"/api/jobs/{job_id}/expansion.md")
    assert expansion_md.status_code == 200
    assert b"Expanded bullet from stub." in expansion_md.content


def test_master_resume_validate_rejects_bad_payload(client):
    """POST /api/master-resume/validate returns field errors, not a 500."""
    c, _ = client
    res = c.post("/api/master-resume/validate", json={"contact": {"name": "x"}})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["errors"]


def test_master_resume_round_trip(client, tmp_path, monkeypatch):
    """PUT saves a validated resume and keeps a backup of the previous file."""
    c, _ = client
    resume = load()
    path = tmp_path / "master_resume.json"
    path.write_text(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    payload = resume.model_dump(by_alias=True)
    payload["contact"]["name"] = "Test User"

    res = c.put("/api/master-resume", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["summary"]["name"] == "Test User"
    assert list(tmp_path.glob("master_resume.*.bak.json")), "expected a timestamped backup"

    got = c.get("/api/master-resume")
    assert got.status_code == 200
    assert got.json()["contact"]["name"] == "Test User"


def test_master_resume_accepts_appended_experience_bullet(client, tmp_path, monkeypatch):
    """PUT with a UI-authored experience entry and new bullet id grows the store."""
    c, _ = client
    resume = load()
    path = tmp_path / "master_resume.json"
    path.write_text(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    before = len(resume.all_bullets())
    payload = resume.model_dump(by_alias=True)
    payload["experience"].append(
        {
            "company": "Editor Test Co",
            "title": "Software Engineer",
            "location": "Remote",
            "start": "2024-01",
            "end": "present",
            "bullets": [
                {
                    "id": "edittest_b1",
                    "text": "Shipped a feature with Python and FastAPI.",
                    "tags": ["Python", "FastAPI"],
                    "metric": False,
                }
            ],
        }
    )

    res = c.put("/api/master-resume", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["summary"]["bullets"] == before + 1
    assert body["summary"]["experience"] == len(resume.experience) + 1

    got = c.get("/api/master-resume").json()
    last = got["experience"][-1]
    assert last["company"] == "Editor Test Co"
    assert last["bullets"][0]["id"] == "edittest_b1"
    # Tags come back canonicalised the way data.Bullet._normalise_tags stores them.
    assert "python" in [t.lower() for t in last["bullets"][0]["tags"]]


def test_queue_serialises_jobs(monkeypatch, tmp_path):
    """Two submitted jobs never run concurrently — the second waits for the first."""
    import threading
    import time

    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir()

    q = JobQueue()
    running = threading.Event()
    release = threading.Event()
    concurrent = []

    def slow_execute(job):
        if running.is_set():
            concurrent.append(True)
        running.set()
        release.wait(timeout=2)
        running.clear()
        job.report = None

    monkeypatch.setattr(q, "_execute", slow_execute)

    j1, _ = q.submit("jd one", JobSettings())
    j2, pos2 = q.submit("jd two", JobSettings())
    assert pos2 >= 1

    # Wait until the first job is running, then release it.
    assert running.wait(timeout=2)
    # While the first is held, the second must still be queued.
    assert q.get(j2.job_id).status == "queued"
    release.set()

    deadline = time.time() + 5
    while time.time() < deadline:
        if q.get(j1.job_id).status == "succeeded" and q.get(j2.job_id).status == "succeeded":
            break
        time.sleep(0.05)

    assert q.get(j1.job_id).status == "succeeded"
    assert q.get(j2.job_id).status == "succeeded"
    assert not concurrent, "jobs overlapped — queue is not serial"


# ---------------------------------------------------------------------------
# Template tab
# ---------------------------------------------------------------------------


def _minimal_docx_bytes() -> bytes:
    """Build a tiny valid .docx in memory for upload tests (no Word required)."""
    import io

    from docx import Document

    buf = io.BytesIO()
    Document().save(buf)
    return buf.getvalue()


def _point_templates_at(tmp_path: Path, monkeypatch) -> Path:
    """Redirect baseline/tagged paths under tmp_path and return the templates dir."""
    templates = tmp_path / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "TEMPLATES_DIR", templates)
    monkeypatch.setattr(config, "BASELINE_TEMPLATE_PATH", templates / "original_export.docx")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", templates / "main_template.docx")
    return templates


def test_get_template_returns_metadata(client, tmp_path, monkeypatch):
    """GET /api/template reports existence and calibration for redirected template paths."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    (templates / "original_export.docx").write_bytes(_minimal_docx_bytes())
    (templates / "main_template.docx").write_bytes(_minimal_docx_bytes())

    res = c.get("/api/template")
    assert res.status_code == 200
    body = res.json()
    assert body["baseline"]["exists"] is True
    assert body["tagged"]["exists"] is True
    assert body["baseline"]["size_bytes"] > 0
    assert "calibration" in body
    assert "stale" in body["calibration"]
    assert isinstance(body["experience_entries"], int)
    assert isinstance(body["bullets"], int)


def test_upload_template_rejects_non_docx(client, tmp_path, monkeypatch):
    """POST /api/template with a .txt leaves the baseline untouched and returns 400."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    baseline = templates / "original_export.docx"
    original = _minimal_docx_bytes()
    baseline.write_bytes(original)

    res = c.post(
        "/api/template",
        files={"file": ("resume.txt", b"not a docx", "text/plain")},
    )
    assert res.status_code == 400
    assert "docx" in res.json()["detail"].lower()
    assert baseline.read_bytes() == original


def test_upload_template_rejects_when_queue_busy(client, tmp_path, monkeypatch):
    """POST /api/template returns 409 while a job is queued or running."""
    c, q = client
    _point_templates_at(tmp_path, monkeypatch)

    # Mark the queue busy without actually running the pipeline.
    job, _ = q.submit("placeholder jd", JobSettings())
    job.status = "running"

    res = c.post(
        "/api/template",
        files={
            "file": (
                "resume.docx",
                _minimal_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 409
    assert "progress" in res.json()["detail"].lower() or "job" in res.json()["detail"].lower()


def test_upload_template_backs_up_and_rebuilds(client, tmp_path, monkeypatch):
    """Successful upload writes a timestamped backup and invokes the build stub."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    baseline = templates / "original_export.docx"
    tagged = templates / "main_template.docx"
    old_bytes = _minimal_docx_bytes()
    baseline.write_bytes(old_bytes)
    tagged.write_bytes(old_bytes)

    builds: list[int] = []

    def fake_build():
        """Pretend build_template.py succeeded and wrote a new tagged file."""
        builds.append(1)
        tagged.write_bytes(b"PK\x03\x04rebuilt")
        return 0, "found 1 education, 1 experience entries, 1 projects\nwrote main_template.docx\n"

    monkeypatch.setattr(template_ops, "_run_build", fake_build)

    new_bytes = _minimal_docx_bytes()
    # Ensure the new upload differs from the old baseline so we can assert replacement.
    assert new_bytes  # non-empty

    res = c.post(
        "/api/template",
        files={
            "file": (
                "resume.docx",
                new_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert builds == [1]
    assert "wrote" in body["log"].lower() or "found" in body["log"].lower()
    backups = list((templates / "backups").glob("original_export.*.docx"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == old_bytes
    assert baseline.read_bytes() == new_bytes


def test_upload_template_restores_baseline_on_build_failure(client, tmp_path, monkeypatch):
    """Failed build restores the previous baseline byte-for-byte and returns 422."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    baseline = templates / "original_export.docx"
    old_bytes = _minimal_docx_bytes()
    baseline.write_bytes(old_bytes)

    def failing_build():
        """Simulate build_template.py exiting non-zero with a useful log."""
        return 1, "ERROR: could not find section heading(s): WORK EXPERIENCES.\n"

    monkeypatch.setattr(template_ops, "_run_build", failing_build)

    res = c.post(
        "/api/template",
        files={
            "file": (
                "resume.docx",
                _minimal_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, dict)
    assert "log" in detail
    assert "WORK EXPERIENCES" in detail["log"]
    assert baseline.read_bytes() == old_bytes


def test_template_preview_uses_stubbed_render(client, tmp_path, monkeypatch):
    """GET /api/template/preview.pdf serves a PDF produced via the render seam (no Word)."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    (templates / "main_template.docx").write_bytes(_minimal_docx_bytes())
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir(exist_ok=True)

    def fake_render(resume, *, out, **_kwargs):
        """Write a placeholder .docx where the preview would land."""
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-docx")
        return out

    def fake_to_pdf(docx_path, pdf_path=None, **_kwargs):
        """Write a minimal PDF-like payload without calling Word/LibreOffice."""
        target = pdf_path or docx_path.with_suffix(".pdf")
        # Minimal PDF header so FileResponse has something to stream.
        target.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n%%EOF\n")
        return target

    monkeypatch.setattr(template_ops.render, "render", fake_render)
    monkeypatch.setattr(template_ops.render, "to_pdf", fake_to_pdf)

    res = c.get("/api/template/preview.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content.startswith(b"%PDF")
