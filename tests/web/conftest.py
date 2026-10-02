"""Web API fixtures: an isolated app client with a fresh job queue and stubbed pipeline
stages, so tests assert the HTTP contract without network, Word or LibreOffice.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.pipeline import coverletter, coverletter_models, jd, skills
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
from tests.fixtures import synthetic_resume
from tests.web.helpers import _stub_extract_consensus


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh app client with an isolated job queue, output directory, and master resume.

    `config.MASTER_RESUME_PATH` is seeded with `synthetic_resume()` rather than left
    pointing at whatever `data/master_resume.json` happens to hold on the machine
    running the suite — that file is gitignored (personal data) and may not exist at
    all on a clean checkout or in CI. Most tests in this file exercise API behavior
    that merely needs *a* valid resume, not any particular content; the ones that do
    care about specific content already build their own via `_write_test_resume` or an
    explicit `monkeypatch.setattr(config, "MASTER_RESUME_PATH", ...)`, both of which
    still win, since they run later. A handful of tests read
    `config.MASTER_RESUME_PATH.read_text()` to copy "the current resume" into a second
    temp location before redirecting further — seeding it here is what makes that
    pattern copy synthetic content instead of a developer's own.
    """
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    config.OUTPUT_DIR.mkdir()
    config.CACHE_DIR.mkdir()
    monkeypatch.setattr(jd, "extract_consensus", _stub_extract_consensus)
    # Default stub for every job test, set here (not per-test) so an unstubbed job never
    # silently attempts a real network call — the same gap `expand.expand_experience`
    # still has (it relies on each test's own `except Exception` swallow). A test that
    # cares about the skills stage overrides this with its own `monkeypatch.setattr`,
    # which still wins since it runs after fixture setup.
    monkeypatch.setattr(
        skills,
        "select_skills",
        lambda *a, **k: skills.SkillsPlan(skills=[], model="stub", pool_size=0),
    )
    monkeypatch.setattr(
        coverletter,
        "draft_letter",
        lambda *a, **k: coverletter_models.CoverLetter(model="stub"),
    )
    monkeypatch.setattr(
        coverletter,
        "render_cover_letter",
        lambda _resume, letter, **k: letter,
    )
    # Review is CLI-only today, but stub the module so a future jobs-path wire-up
    # cannot reach the network from an unstubbed test (same pattern as skills/cover).
    from resume_tailor.pipeline import review as review_mod
    from resume_tailor.pipeline.review import ReviewResult

    monkeypatch.setattr(
        review_mod,
        "review_bullets",
        lambda *a, **k: ReviewResult(model="stub"),
    )

    resume_path = tmp_path / "master_resume.json"
    resume_path.write_text(
        json.dumps(synthetic_resume().model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)

    with TestClient(app) as c:
        yield c, q
