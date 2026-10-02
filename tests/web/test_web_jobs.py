"""Tailoring jobs end to end over the web API, with the pipeline stubbed."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import unquote

from resume_tailor import config
from resume_tailor.content.data import load
from resume_tailor.pipeline.events import ProgressEvent
from resume_tailor.pipeline.fit import FitResult
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.jobs import JobQueue
from resume_tailor.web.schemas import JobSettings
from tests.web.helpers import _drain


def test_job_runs_to_success_with_stubbed_pipeline(client, monkeypatch, tmp_path):
    """A submitted job reaches succeeded and writes a downloadable .docx."""
    c, q = client
    resume = load()

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        from resume_tailor.pipeline.jd import JobRequirements, Keyword

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
        contact_fields=None,
        fill_target=None,
        initial_bullet_share=None,
        experience_bullet_share=None,
        max_bullets_per_entry=None,
        coursework_pool=None,
        on_event=None,
    ):
        """Stub fit and record polish/merge/link knobs from JobSettings."""
        seen_fit.update(
            repair_widows=repair_widows,
            repair_verbs=repair_verbs,
            merge_bullets=merge_bullets,
            include_project_links=include_project_links,
            fill_target=fill_target,
            initial_bullet_share=initial_bullet_share,
            experience_bullet_share=experience_bullet_share,
            max_bullets_per_entry=max_bullets_per_entry,
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
    monkeypatch.setattr(jobs_mod.relevance, "score_table", fake_score)
    monkeypatch.setattr(jobs_mod.fit, "fit", fake_fit)
    monkeypatch.setattr(jobs_mod.jd, "verify_verbatim", lambda *a, **k: [])

    def fake_facets(resume, requirements, **kwargs):
        """Budget-only facets so the job path never reaches the network."""
        from resume_tailor.pipeline import facets as facets_mod

        return facets_mod.budget_only(
            resume,
            requirements,
            include_project_links=kwargs.get("include_project_links", True),
        )

    monkeypatch.setattr(jobs_mod.facets, "select_facets", fake_facets)

    from resume_tailor.pipeline.expand import ExpandedEntry, Expansion

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
    template = tmp_path / "live_template.docx"
    template.write_bytes(b"PK-template")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", template)

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
                "initial_bullet_share": 0.6,
                "experience_bullet_share": 0.7,
                "max_bullets_per_entry": 4,
            },
        },
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    status = _drain(c, job_id)
    assert status["status"] == "succeeded", status
    assert status["report"]["title"] == "Stub Role"
    assert status["report"]["pages"] == 1
    assert status["report"]["verb_collisions_remaining"] == 0
    # The final render's inputs are kept so bullets can be edited and re-rendered later.
    job_dir = config.OUTPUT_DIR / "jobs" / job_id
    snapshot = json.loads((job_dir / "render_snapshot.json").read_text())
    assert snapshot["include_project_links"] is False and snapshot["target_pages"] == 1
    stored = config.OUTPUT_DIR / "run_templates" / f"{snapshot['template_sha']}.docx"
    assert stored.read_bytes() == b"PK-template"
    assert not (job_dir / "template.docx").exists()  # shared, not copied per run
    assert isinstance(status["report"]["gaps"], list)
    assert status["expansion"] is not None
    assert status["expansion"]["entries"][0]["company"] == resume.experience[0].company
    assert seen_fit == {
        "repair_widows": True,
        "repair_verbs": False,
        "merge_bullets": True,
        "include_project_links": False,
        "fill_target": 0.88,
        "initial_bullet_share": 0.6,
        "experience_bullet_share": 0.7,
        "max_bullets_per_entry": 4,
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


def test_get_resume_outline(client):
    """GET /api/resume-outline reports the shape the include tile needs to render."""
    c, _ = client
    resume = load()

    res = c.get("/api/resume-outline")
    assert res.status_code == 200
    body = res.json()

    assert set(body["available_contact_fields"]) <= {
        "location", "email", "phone", "linkedin", "github",
    }
    assert "email" in body["available_contact_fields"]  # every fixture resume has one
    assert body["default_contact_order"]
    assert body["has_coursework"] is True  # fixture resume has coursework
    assert {e["id"] for e in body["experience"]} == {e.id for e in resume.experience}
    assert {p["id"] for p in body["projects"]} == {p.id for p in resume.projects}
    assert set(body["sections_enabled"]) == {
        "education", "experience", "projects", "skills", "list_section",
    }

    # `sections` covers every section (any kind), not just entry sections — education
    # and skills are orderable from the include tile too, even though they carry no
    # per-entry excludes and so contribute an empty `entries` list.
    section_kinds = {s["kind"] for s in body["sections"]}
    assert {"education", "skills"} <= section_kinds
    entry_ids_via_sections = {e["id"] for s in body["sections"] for e in s["entries"]}
    entry_ids_via_flat = {e["id"] for e in body["experience"]} | {
        p["id"] for p in body["projects"]
    }
    assert entry_ids_via_sections == entry_ids_via_flat
    for s in body["sections"]:
        if s["kind"] not in ("experience", "project"):
            assert s["entries"] == []
    assert all(isinstance(v, bool) for v in body["sections_enabled"].values())
    assert body["section_mode"] in ("fixed", "generic")


def test_create_job_rejects_a_fully_excluded_resume(client):
    """Excluding every experience and project entry must 400 synchronously, before the
    job ever reaches the worker — the same treatment as a missing credential."""
    c, q = client
    resume = load()

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Some job description.",
            "settings": {
                "include": {
                    "exclude_experience": [e.id for e in resume.experience],
                    "exclude_projects": [p.id for p in resume.projects],
                }
            },
        },
    )
    assert res.status_code == 400
    assert "nothing would render" in res.json()["detail"]
    assert q._jobs == {}


def test_job_honours_exclusions_but_expansion_still_sees_the_excluded_job(
    client, monkeypatch
):
    """An excluded experience entry must be absent from what `fit.fit` receives, but the
    application-form expansion tile still gets the unfiltered resume — see `include.py`'s
    module docstring and `web/jobs.py::_execute` for why."""
    c, q = client
    resume = load()
    excluded_id = resume.experience[0].id

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        from resume_tailor.pipeline.jd import JobRequirements, Keyword

        return JobRequirements(
            title="Stub Role",
            seniority="intern",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )

    monkeypatch.setattr(jobs_mod.jd, "extract", fake_extract)
    monkeypatch.setattr(jobs_mod.jd, "verify_verbatim", lambda *a, **k: [])
    monkeypatch.setattr(
        jobs_mod.relevance, "score_table", lambda bullets, *a, **k: {b.id: 5.0 for b in bullets}
    )

    seen_fit_resume = {}
    seen_expand_resume = {}

    def fake_fit(resume_arg, requirements, *, out=None, on_event=None, **kwargs):
        seen_fit_resume["ids"] = {e.id for e in resume_arg.experience}
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK")
        out.with_suffix(".pdf").write_bytes(b"%PDF-1.4 stub")
        bullet = resume_arg.all_bullets()[0]
        return FitResult(
            out_path=out,
            pages=1,
            pages_are_estimated=False,
            iterations=1,
            bullets_selected=1,
            bullets_total=1,
            bullets={bullet.id: bullet.text},
        )

    monkeypatch.setattr(jobs_mod.fit, "fit", fake_fit)

    def fake_facets(resume_arg, requirements, **kwargs):
        from resume_tailor.pipeline import facets as facets_mod

        return facets_mod.budget_only(
            resume_arg, requirements, include_project_links=kwargs.get(
                "include_project_links", True
            ),
        )

    monkeypatch.setattr(jobs_mod.facets, "select_facets", fake_facets)

    def fake_expand(resume_arg, requirements, **kwargs):
        seen_expand_resume["ids"] = {e.id for e in resume_arg.experience}
        from resume_tailor.pipeline.expand import Expansion

        return Expansion(entries=[], model="stub", char_limit=config.EXPAND_CHAR_LIMIT)

    monkeypatch.setattr(jobs_mod.expand, "expand_experience", fake_expand)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Looking for a Python intern.",
            "settings": {"include": {"exclude_experience": [excluded_id]}},
        },
    )
    assert res.status_code == 200
    status = _drain(c, res.json()["job_id"])
    assert status["status"] == "succeeded", status

    assert excluded_id not in seen_fit_resume["ids"]
    assert excluded_id in seen_expand_resume["ids"]


def test_skills_selection_resume_is_post_include_pre_facets(client, monkeypatch, tmp_path):
    """The skills stage must see project tech before facets truncates it to
    `MAX_PROJECT_TECH`, but must NOT see an entry the user excluded — pins both halves
    of the resume-object decision documented at the skills call site in
    `web/jobs.py::_execute` (see `master_resume` there)."""
    c, _q = client
    tech = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
    resume_path = tmp_path / "test_master_resume.json"
    resume_path.write_text(
        json.dumps(
            {
                "contact": {"name": "X", "email": "x@y.z"},
                "experience": [
                    {
                        "id": "job-keep",
                        "company": "Keep Co",
                        "title": "Engineer",
                        "start": "2020",
                        "end": "2021",
                        "bullets": [{"id": "b1", "text": "Did a thing.", "tags": ["python"]}],
                    },
                    {
                        "id": "job-excl",
                        "company": "Excl Co",
                        "title": "Engineer",
                        "start": "2019",
                        "end": "2020",
                        "bullets": [
                            {"id": "b2", "text": "Did another thing.", "tags": ["excludedtag"]}
                        ],
                    },
                ],
                "projects": [
                    {
                        "id": "proj-a",
                        "name": "Proj",
                        "tech": tech,
                        "bullets": [
                            {"id": "b3", "text": "Built a project.", "tags": ["python"]}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        from resume_tailor.pipeline.jd import JobRequirements, Keyword

        return JobRequirements(
            title="Stub Role",
            seniority="intern",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )

    monkeypatch.setattr(jobs_mod.jd, "extract", fake_extract)
    monkeypatch.setattr(jobs_mod.jd, "verify_verbatim", lambda *a, **k: [])
    monkeypatch.setattr(
        jobs_mod.relevance, "score_table", lambda bullets, *a, **k: {b.id: 5.0 for b in bullets}
    )

    def fake_fit(resume_arg, requirements, *, out=None, on_event=None, **kwargs):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK")
        out.with_suffix(".pdf").write_bytes(b"%PDF-1.4 stub")
        bullet = resume_arg.all_bullets()[0]
        return FitResult(
            out_path=out,
            pages=1,
            pages_are_estimated=False,
            iterations=1,
            bullets_selected=1,
            bullets_total=1,
            bullets={bullet.id: bullet.text},
        )

    monkeypatch.setattr(jobs_mod.fit, "fit", fake_fit)

    def fake_facets(resume_arg, requirements, **kwargs):
        from resume_tailor.pipeline import facets as facets_mod

        return facets_mod.budget_only(
            resume_arg,
            requirements,
            include_project_links=kwargs.get("include_project_links", True),
        )

    monkeypatch.setattr(jobs_mod.facets, "select_facets", fake_facets)

    seen_skills_resume: dict = {}

    def fake_select_skills(resume_arg, requirements, **kwargs):
        seen_skills_resume["experience_ids"] = {e.id for e in resume_arg.experience}
        seen_skills_resume["project_tech"] = list(resume_arg.projects[0].tech)
        from resume_tailor.pipeline.skills import SkillsPlan

        return SkillsPlan(skills=[], model="stub", pool_size=0)

    monkeypatch.setattr(jobs_mod.skills, "select_skills", fake_select_skills)

    res = c.post(
        "/api/jobs",
        json={
            "jd_text": "Looking for a Python intern.",
            "settings": {"include": {"exclude_experience": ["job-excl"]}},
        },
    )
    assert res.status_code == 200
    status = _drain(c, res.json()["job_id"])
    assert status["status"] == "succeeded", status

    # Pre-facets: skills sees all six tech labels, not the ≤4 facets.budget_only trims to.
    assert seen_skills_resume["project_tech"] == tech
    # Post-include: the excluded entry never reaches skills selection.
    assert "job-keep" in seen_skills_resume["experience_ids"]
    assert "job-excl" not in seen_skills_resume["experience_ids"]


def test_skills_endpoint_and_status_field(client, monkeypatch):
    """A successful job exposes `status["skills"]` and serves `skills.md`; the download
    404s until the job is produced and 409s while it is still running."""
    c, _q = client
    load()  # confirms the fixture's resume file is loadable before the job reads it

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        from resume_tailor.pipeline.jd import JobRequirements, Keyword

        return JobRequirements(
            title="Stub Role",
            seniority="intern",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )

    monkeypatch.setattr(jobs_mod.jd, "extract", fake_extract)
    monkeypatch.setattr(jobs_mod.jd, "verify_verbatim", lambda *a, **k: [])
    monkeypatch.setattr(
        jobs_mod.relevance, "score_table", lambda bullets, *a, **k: {b.id: 5.0 for b in bullets}
    )

    def fake_fit(resume_arg, requirements, *, out=None, on_event=None, **kwargs):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK")
        out.with_suffix(".pdf").write_bytes(b"%PDF-1.4 stub")
        bullet = resume_arg.all_bullets()[0]
        return FitResult(
            out_path=out,
            pages=1,
            pages_are_estimated=False,
            iterations=1,
            bullets_selected=1,
            bullets_total=1,
            bullets={bullet.id: bullet.text},
        )

    monkeypatch.setattr(jobs_mod.fit, "fit", fake_fit)

    def fake_facets(resume_arg, requirements, **kwargs):
        from resume_tailor.pipeline import facets as facets_mod

        return facets_mod.budget_only(
            resume_arg,
            requirements,
            include_project_links=kwargs.get("include_project_links", True),
        )

    monkeypatch.setattr(jobs_mod.facets, "select_facets", fake_facets)

    from resume_tailor.pipeline.skills import SkillsPlan, SkillSuggestion

    def fake_select_skills(*a, **k):
        return SkillsPlan(
            skills=[
                SkillSuggestion(
                    skill="Python", pool_label="python", tier="required", jd_phrase="Python"
                )
            ],
            model="stub",
            pool_size=1,
        )

    monkeypatch.setattr(jobs_mod.skills, "select_skills", fake_select_skills)

    from resume_tailor.pipeline.expand import Expansion

    # Was missing entirely — expansion is a real pipeline stage that runs after a
    # successful fit (see CLAUDE.md's six-stage list). Without this stub the worker
    # reached the real `expand.expand_experience`, an unstubbed network call left
    # running in the background for the rest of the suite.
    monkeypatch.setattr(
        jobs_mod.expand,
        "expand_experience",
        lambda *a, **k: Expansion(entries=[], model="stub", char_limit=config.EXPAND_CHAR_LIMIT),
    )

    res = c.post("/api/jobs", json={"jd_text": "Looking for a Python intern."})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    status = _drain(c, job_id)
    assert status["status"] == "succeeded", status
    assert status["skills"] is not None
    assert status["skills"]["skills"][0]["tier"] == "required"
    assert status["skills"]["skills"][0]["skill"] == "Python"

    skills_md = c.get(f"/api/jobs/{job_id}/skills.md")
    assert skills_md.status_code == 200
    assert b"Python" in skills_md.content


def test_skills_download_404s_for_unknown_job(client):
    c, _q = client
    res = c.get("/api/jobs/unknown-job/skills.md")
    assert res.status_code == 404


def test_skills_download_409s_while_job_is_running(client, monkeypatch):
    """A still-queued/running job's skills.md is not ready yet."""
    c, q = client
    from resume_tailor.web.jobs import Job

    job = Job(job_id="pending-job", jd_text="x", settings=JobSettings())
    q._jobs["pending-job"] = job
    res = c.get("/api/jobs/pending-job/skills.md")
    assert res.status_code == 409


def test_cancel_job_404s_for_unknown_job(client):
    c, _q = client
    res = c.delete("/api/jobs/unknown-job")
    assert res.status_code == 404


def test_cancel_job_cancels_a_queued_job(client):
    """DELETE on a job the worker hasn't touched yet cancels it immediately."""
    c, q = client
    job = jobs_mod.Job(job_id="queued-job", jd_text="x", settings=JobSettings(), status="queued")
    q._jobs[job.job_id] = job

    res = c.delete("/api/jobs/queued-job")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "cancelled"
    assert any(e["stage"] == "cancel" for e in body["events"])
    assert q.get("queued-job").status == "cancelled"


def test_cancel_job_flags_a_running_job_without_finishing_it_immediately(client):
    """A running job's cancellation is cooperative: DELETE only sets the flag —
    `_execute` (with no worker thread running here) never gets a chance to notice it,
    so the job legitimately still reads "running" right after the call."""
    c, q = client
    job = jobs_mod.Job(job_id="running-job", jd_text="x", settings=JobSettings(), status="running")
    q._jobs[job.job_id] = job

    res = c.delete("/api/jobs/running-job")
    assert res.status_code == 200
    assert res.json()["status"] == "running"
    assert job.cancel_requested.is_set()


def test_cancel_job_409s_when_already_terminal(client):
    c, q = client
    job = jobs_mod.Job(job_id="done-job", jd_text="x", settings=JobSettings(), status="succeeded")
    q._jobs[job.job_id] = job

    res = c.delete("/api/jobs/done-job")
    assert res.status_code == 409


def test_skills_download_404s_when_no_skills_produced(client, monkeypatch):
    """`no_skills` leaves no `skills.md` on disk; the download 404s with a clear reason."""
    c, _q = client

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        from resume_tailor.pipeline.jd import JobRequirements, Keyword

        return JobRequirements(
            title="Stub Role",
            seniority="intern",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )

    monkeypatch.setattr(jobs_mod.jd, "extract", fake_extract)
    monkeypatch.setattr(jobs_mod.jd, "verify_verbatim", lambda *a, **k: [])
    monkeypatch.setattr(
        jobs_mod.relevance, "score_table", lambda bullets, *a, **k: {b.id: 5.0 for b in bullets}
    )

    def fake_fit(resume_arg, requirements, *, out=None, on_event=None, **kwargs):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK")
        out.with_suffix(".pdf").write_bytes(b"%PDF-1.4 stub")
        bullet = resume_arg.all_bullets()[0]
        return FitResult(
            out_path=out,
            pages=1,
            pages_are_estimated=False,
            iterations=1,
            bullets_selected=1,
            bullets_total=1,
            bullets={bullet.id: bullet.text},
        )

    monkeypatch.setattr(jobs_mod.fit, "fit", fake_fit)

    def fake_facets(resume_arg, requirements, **kwargs):
        from resume_tailor.pipeline import facets as facets_mod

        return facets_mod.budget_only(
            resume_arg,
            requirements,
            include_project_links=kwargs.get("include_project_links", True),
        )

    monkeypatch.setattr(jobs_mod.facets, "select_facets", fake_facets)

    called = []
    monkeypatch.setattr(
        jobs_mod.skills, "select_skills", lambda *a, **k: called.append(1)
    )

    res = c.post(
        "/api/jobs",
        json={"jd_text": "Looking for a Python intern.", "settings": {"no_skills": True}},
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    status = _drain(c, job_id)
    assert status["status"] == "succeeded", status
    assert called == []
    assert status["skills"] is None

    res = c.get(f"/api/jobs/{job_id}/skills.md")
    assert res.status_code == 404
    assert "not produced" in res.json()["detail"]


def test_queue_respects_one_job_limit(monkeypatch, tmp_path):
    """An explicit one-job limit keeps the second run waiting."""
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

    j1, _ = q.submit("jd one", JobSettings(max_concurrent_jobs=1))
    j2, pos2 = q.submit("jd two", JobSettings(max_concurrent_jobs=1))
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


def test_cancel_removes_a_queued_job_before_the_worker_ever_executes_it(monkeypatch, tmp_path):
    """Cancelling a job still waiting behind another one skips it outright — the
    worker must never call `_execute` for it, not even once it's dequeued."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir()

    q = JobQueue()
    running = threading.Event()
    release = threading.Event()
    executed = []

    def slow_execute(job):
        executed.append(job.job_id)
        running.set()
        release.wait(timeout=2)

    monkeypatch.setattr(q, "_execute", slow_execute)

    j1, _ = q.submit("jd one", JobSettings(max_concurrent_jobs=1))
    j2, _ = q.submit("jd two", JobSettings(max_concurrent_jobs=1))

    assert running.wait(timeout=2)
    assert q.get(j2.job_id).status == "queued"

    assert q.cancel(j2.job_id) is not None
    assert q.get(j2.job_id).status == "cancelled"

    release.set()
    deadline = time.time() + 5
    while time.time() < deadline and q.get(j1.job_id).status == "running":
        time.sleep(0.02)
    assert q.get(j1.job_id).status == "succeeded"

    # Give the worker a beat to dequeue j2's id off `_pending` and confirm it is
    # skipped rather than executed now that it's already terminal.
    deadline = time.time() + 2
    while time.time() < deadline and not q._pending.empty():
        time.sleep(0.02)
    assert j2.job_id not in executed
    assert q.get(j2.job_id).status == "cancelled"


def test_cancel_stops_a_running_job_at_the_next_checkpoint(monkeypatch, tmp_path):
    """A running job's `check_cancelled()` checkpoints actually stop it: the worker
    catches `JobCancelled` and marks the job terminal without reaching later code."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir()

    q = JobQueue()
    reached_first_checkpoint = threading.Event()
    reached_second_checkpoint = threading.Event()

    def fake_execute(job):
        reached_first_checkpoint.set()
        job.check_cancelled()  # not yet cancelled — must not raise
        deadline = time.time() + 2
        while time.time() < deadline and not job.cancel_requested.is_set():
            time.sleep(0.01)
        job.check_cancelled()  # cancelled by now — must raise and unwind here
        reached_second_checkpoint.set()  # must never run

    monkeypatch.setattr(q, "_execute", fake_execute)

    job, _ = q.submit("jd", JobSettings())
    assert reached_first_checkpoint.wait(timeout=2)
    assert q.cancel(job.job_id) is not None

    deadline = time.time() + 2
    while time.time() < deadline and q.get(job.job_id).status == "running":
        time.sleep(0.02)

    assert q.get(job.job_id).status == "cancelled"
    assert not reached_second_checkpoint.is_set()
    assert any(e.stage == "cancel" for e in q.get(job.job_id).events)


def test_cancel_is_a_noop_for_an_unknown_or_already_terminal_job(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir()

    q = JobQueue()
    assert q.cancel("no-such-job") is None

    job = jobs_mod.Job(job_id="done", jd_text="x", settings=JobSettings(), status="succeeded")
    q._jobs[job.job_id] = job
    assert q.cancel("done") is None
    assert q.get("done").status == "succeeded"  # unchanged
