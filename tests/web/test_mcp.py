"""MCP tool layer — hermetic via httpx.ASGITransport against the FastAPI app.

No network, no Word, no MCP SDK: tools.py is exercised through the real routes with
the same pipeline stubs as ``tests/web/conftest.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from resume_tailor import config
from resume_tailor.mcp_server import tools
from resume_tailor.mcp_server.client import BackendClient, BackendError
from resume_tailor.pipeline import (
    coverletter,
    coverletter_models,
    expand,
    facets,
    fit,
    jd,
    relevance,
    skills,
)
from resume_tailor.pipeline.events import ProgressEvent
from resume_tailor.pipeline.expand import ExpandedEntry, Expansion
from resume_tailor.pipeline.fit_types import FitResult
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from resume_tailor.pipeline.skills import SkillsPlan, SkillSuggestion
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
from tests.fixtures import synthetic_resume


def _stub_extract_consensus(text, *, known_tags=None, runs=1, use_cache=True, on_event=None):
    """Route extract_consensus to jd.extract so tests control the reply once."""
    return jd.extract(text, known_tags=known_tags, use_cache=use_cache, on_event=on_event)


@pytest.fixture
async def mcp_client(tmp_path, monkeypatch):
    """BackendClient over ASGITransport with a fully stubbed pipeline."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    config.OUTPUT_DIR.mkdir()
    config.CACHE_DIR.mkdir()
    monkeypatch.setattr(jd, "extract_consensus", _stub_extract_consensus)

    resume_path = tmp_path / "master_resume.json"
    resume = synthetic_resume()
    resume_path.write_text(
        json.dumps(resume.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        """Stub JD extraction for MCP tool tests."""
        if on_event:
            on_event(ProgressEvent("extract", "stub extract", {}))
        return JobRequirements(
            title="Stub Role",
            seniority="intern",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )

    def fake_score(bullets, requirements, *, use_cache=True, on_event=None):
        """Stub semantic scoring."""
        if on_event:
            on_event(ProgressEvent("score", "stub score", {}))
        return {b.id: 5.0 for b in bullets}

    def fake_fit(resume_arg, requirements, *, out=None, on_event=None, **kwargs):
        """Stub fit: write fake docx/pdf and return one selected bullet."""
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK")
        out.with_suffix(".pdf").write_bytes(b"%PDF-1.4 stub")
        if on_event:
            on_event(ProgressEvent("fit", "stub fit done", {"pages": 1}))
        bullet = resume_arg.all_bullets()[0]
        return FitResult(
            out_path=out,
            pages=1,
            pages_are_estimated=False,
            iterations=1,
            bullets_selected=1,
            bullets_total=1,
            bullets={bullet.id: bullet.text},
            semantic_used=False,
        )

    def fake_facets(resume_arg, requirements, **kwargs):
        """Budget-only facets so the job never reaches the network."""
        from resume_tailor.pipeline import facets as facets_mod

        return facets_mod.budget_only(
            resume_arg,
            requirements,
            include_project_links=kwargs.get("include_project_links", True),
        )

    def fake_expand(*a, **k):
        """Stub application-form expansion."""
        entry = resume.experience[0]
        return Expansion(
            entries=[
                ExpandedEntry(
                    entry_key="exp:example-corp",
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

    def fake_skills(*a, **k):
        """Stub skills selection."""
        return SkillsPlan(
            skills=[
                SkillSuggestion(
                    skill="Python",
                    pool_label="Tools",
                    tier="required",
                    jd_phrase="Python",
                    sources=["exp_b1"],
                    reason="must-have",
                )
            ],
            model="stub",
            pool_size=1,
        )

    def fake_draft(*a, **k):
        """Stub cover-letter drafting."""
        return coverletter_models.CoverLetter(
            company="Stub Co",
            paragraphs=["I improved reliability for production services."],
            salutation="Dear Hiring Manager,",
            signature="Jordan Rivera",
            model="stub",
            word_count=7,
        )

    monkeypatch.setattr(jd, "extract", fake_extract)
    monkeypatch.setattr(jd, "verify_verbatim", lambda *a, **k: [])
    monkeypatch.setattr(relevance, "score_table", fake_score)
    monkeypatch.setattr(fit, "fit", fake_fit)
    monkeypatch.setattr(facets, "select_facets", fake_facets)
    monkeypatch.setattr(expand, "expand_experience", fake_expand)
    monkeypatch.setattr(skills, "select_skills", fake_skills)
    monkeypatch.setattr(coverletter, "draft_letter", fake_draft)
    monkeypatch.setattr(
        coverletter,
        "render_cover_letter",
        lambda _resume, letter, **k: letter,
    )

    async def _instant_sleep(_seconds):
        """Skip the real 2s poll interval in tests."""
        return None

    monkeypatch.setattr(tools.asyncio, "sleep", _instant_sleep)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as http:
        # Lifespan (workspace bootstrap) runs on first ASGI request.
        await http.get("/api/config")
        yield BackendClient(http)


@pytest.mark.asyncio
async def test_tailor_application_returns_report_and_cover(mcp_client):
    """tailor_application runs the stubbed pipeline end-to-end and returns artifacts."""
    result = await tools.tailor_application(
        mcp_client,
        "Looking for a Python engineer.",
        cover_letter=True,
        wait_seconds=30,
    )
    assert result["status"] == "succeeded", result
    assert result["report"] is not None
    assert result["report"]["title"] == "Stub Role"
    assert result["cover_letter"] is not None
    assert result["cover_letter"]["company"] == "Stub Co"
    assert result["expansion"] is not None
    assert result["skills"] is not None


@pytest.mark.asyncio
async def test_get_application_answers_returns_paste_bundle(mcp_client):
    """get_application_answers surfaces expansion, skills, and contact after a run."""
    run = await tools.tailor_application(
        mcp_client,
        "Looking for a Python engineer.",
        cover_letter=True,
        wait_seconds=30,
    )
    job_id = run["job_id"]
    answers = await tools.get_application_answers(mcp_client, job_id)
    assert answers["contact"]["name"] == "Jordan Rivera"
    assert answers["expansion"]["entries"][0]["company"] == "Example Corp"
    assert answers["skills"]["skills"][0]["skill"] == "Python"
    assert answers["cover_letter"]["company"] == "Stub Co"


@pytest.mark.asyncio
async def test_verify_claim_flags_fabricated_term(mcp_client):
    """verify_claim returns ok=false when prose invents a technology."""
    run = await tools.tailor_application(
        mcp_client,
        "Looking for a Python engineer.",
        cover_letter=False,
        wait_seconds=30,
    )
    job_id = run["job_id"]
    result = await tools.verify_claim(
        mcp_client,
        "Led a Kubernetes migration for production services.",
        job_id=job_id,
    )
    assert result["ok"] is False
    assert any(t.lower() == "kubernetes" for t in result["unsupported_terms"])


@pytest.mark.asyncio
async def test_get_run_unknown_job_id_raises_clean_error(mcp_client):
    """An unknown job_id yields BackendError, not a traceback."""
    with pytest.raises(BackendError) as exc_info:
        await tools.get_run(mcp_client, "no-such-job-zzzz")
    assert exc_info.value.status_code == 404
    assert "Unknown" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_resume_facts_projects_headers(mcp_client):
    """get_resume_facts returns contact and entry headers, not full bullet text."""
    facts = await tools.get_resume_facts(mcp_client)
    assert facts["contact"]["email"] == "jordan@example.com"
    assert facts["experience"][0]["company"] == "Example Corp"
    assert "bullets" not in facts["experience"][0]


@pytest.mark.asyncio
async def test_read_artifact_docx_returns_paths_not_base64(mcp_client):
    """Binary artifacts return pointers only, regardless of how small they are."""
    run = await tools.tailor_application(
        mcp_client,
        "Looking for a Python engineer.",
        cover_letter=False,
        wait_seconds=30,
    )
    job_id = run["job_id"]
    docx_path = config.OUTPUT_DIR / "jobs" / job_id / "tailored.docx"
    docx_path.write_bytes(b"PK" + b"x" * 64)  # tiny: would have been inlined before

    result = await tools.read_artifact(mcp_client, job_id, "resume_docx")
    assert "base64" not in result
    assert result["inline"] is False
    assert "download.docx" in result["download_url"]
    assert result.get("disk_path")  # MCP process shares OUTPUT_DIR with the app


@pytest.mark.asyncio
async def test_read_artifact_markdown_returns_text(mcp_client):
    """Markdown artifacts return inline text, not base64."""
    run = await tools.tailor_application(
        mcp_client,
        "Looking for a Python engineer.",
        cover_letter=False,
        wait_seconds=30,
    )
    job_id = run["job_id"]
    result = await tools.read_artifact(mcp_client, job_id, "expansion_md")
    assert "text" in result
    assert "base64" not in result
    assert "Expanded bullet" in result["text"]


@pytest.mark.asyncio
async def test_list_applications_empty(mcp_client, tmp_path, monkeypatch):
    """list_applications returns an empty tracker on a fresh workspace."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    result = await tools.list_applications(mcp_client, limit=10)
    assert result["applications"] == []
    assert result["counts"] == {}


@pytest.mark.asyncio
async def test_get_application_packet_after_run(mcp_client):
    """get_application_packet returns JSON for a finished run (rebuild if needed)."""
    run = await tools.tailor_application(
        mcp_client,
        "Looking for a Python engineer.",
        cover_letter=False,
        wait_seconds=30,
    )
    job_id = run["job_id"]
    packet_path = config.OUTPUT_DIR / "jobs" / job_id / "packet.json"
    if not packet_path.is_file():
        await mcp_client._request("POST", f"/api/jobs/{job_id}/packet/rebuild")
    packet = await tools.get_application_packet(mcp_client, job_id)
    assert packet["job_id"] == job_id
    assert "fields" in packet
