"""Tests for the archived-run reader."""

from __future__ import annotations

import json

from resume_tailor.pipeline import runs
from resume_tailor.pipeline.jd import JobRequirements, Keyword


def _write_run(root, job_id: str, *, jd: str, title: str = "T", bullets: dict | None = None):
    """Write a complete archived run directory under `root`."""
    d = root / job_id
    d.mkdir()
    (d / "jd.txt").write_text(jd, encoding="utf-8")
    reqs = JobRequirements(
        title=title,
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )
    (d / "requirements.json").write_text(reqs.model_dump_json(), encoding="utf-8")
    (d / "bullets.json").write_text(
        json.dumps(bullets or {"a": "Built a Python service."}), encoding="utf-8"
    )
    return d


def test_iter_runs_yields_complete_directories(tmp_path):
    _write_run(tmp_path, "job-a", jd="Need Python.")
    _write_run(tmp_path, "job-b", jd="Need FastAPI.")
    found = {r.job_id: r for r in runs.iter_runs(tmp_path)}
    assert set(found) == {"job-a", "job-b"}
    assert found["job-a"].jd_text == "Need Python."
    assert found["job-a"].requirements.title == "T"
    assert found["job-a"].bullets["a"] == "Built a Python service."


def test_iter_runs_skips_directory_missing_bullets(tmp_path):
    """A partial write must not crash an advisory scan."""
    d = tmp_path / "partial"
    d.mkdir()
    (d / "jd.txt").write_text("Need Python.", encoding="utf-8")
    (d / "requirements.json").write_text(
        JobRequirements(title="T", seniority="entry", keywords=[]).model_dump_json(),
        encoding="utf-8",
    )
    # no bullets.json
    assert list(runs.iter_runs(tmp_path)) == []


def test_iter_runs_empty_root(tmp_path):
    assert list(runs.iter_runs(tmp_path / "missing")) == []


def test_closest_run_picks_highest_jaccard(tmp_path):
    _write_run(tmp_path, "far", jd="sales quota crm territory")
    _write_run(
        tmp_path,
        "near",
        jd="python fastapi rag vector database semantic search",
    )
    current = "python fastapi rag vector database semantic search ranking"
    reqs = JobRequirements(title="T", seniority="entry", keywords=[])
    match = runs.closest_run(current, reqs, root=tmp_path)
    assert match is not None
    prior, recommendation, score = match
    assert prior.job_id == "near"
    assert recommendation == "reuse"
    assert score > 0.7


def test_closest_run_can_exclude_current(tmp_path):
    _write_run(tmp_path, "self", jd="python fastapi rag")
    _write_run(tmp_path, "other", jd="completely different sales role")
    reqs = JobRequirements(title="T", seniority="entry", keywords=[])
    match = runs.closest_run(
        "python fastapi rag", reqs, root=tmp_path, exclude_job_id="self"
    )
    assert match is not None
    assert match[0].job_id == "other"
