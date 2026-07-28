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
    assert isinstance(body["tag_vocabulary"], list)
    assert body["pdf_backend"] in ("word", "soffice")


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
        on_event=None,
    ):
        """Stub fit and record polish/merge knobs from JobSettings."""
        seen_fit.update(
            repair_widows=repair_widows,
            repair_verbs=repair_verbs,
            merge_bullets=merge_bullets,
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
    assert f"{resume.contact.name} Resume - Stub Role.pdf" in unquote(
        pdf.headers.get("content-disposition", "")
    )

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
