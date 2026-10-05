"""Relevance scoring and facet selection run at the same time, before the fit loop."""

from __future__ import annotations

import argparse
import threading
from types import SimpleNamespace

import pytest

from resume_tailor.cli import run as cli_run
from resume_tailor.infra.llm import LLMError
from resume_tailor.pipeline import facets, jd, relevance
from resume_tailor.pipeline.include import IncludeOptions
from resume_tailor.web import job_tailor_run
from resume_tailor.web.schemas import JobSettings
from tests.fixtures import synthetic_resume


def _web_run(events: list) -> job_tailor_run._TailorJobRun:
    job = SimpleNamespace(settings=JobSettings(), emit=events.append)
    runner = job_tailor_run._TailorJobRun(job)
    runner.full_resume = synthetic_resume()
    runner.resume = runner.full_resume
    runner.requirements = jd.JobRequirements(title="Engineer", seniority="intern")
    return runner


def _stub_stages(monkeypatch, score) -> dict:
    seen: dict = {}

    def select_facets(resume, requirements, **kwargs):
        seen["facets_resume"] = resume
        return SimpleNamespace(warnings=[])

    monkeypatch.setattr(relevance, "score_table", score)
    monkeypatch.setattr(facets, "select_facets", select_facets)
    monkeypatch.setattr(facets, "apply", lambda resume, result: resume)
    return seen


def test_scoring_and_facets_overlap(monkeypatch):
    # Both must be inside their stage at once; run one after another, the barrier
    # times out and scoring records "sequential" instead.
    barrier = threading.Barrier(2, timeout=5)
    seen: dict = {}

    def score(bullets, requirements, **kwargs):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            seen["score"] = "sequential"
        return {b.id: 5.0 for b in bullets}

    seen.update(_stub_stages(monkeypatch, score))
    original = facets.select_facets

    def facets_waiting(resume, requirements, **kwargs):
        barrier.wait()
        return original(resume, requirements, **kwargs)

    monkeypatch.setattr(facets, "select_facets", facets_waiting)
    runner = _web_run([])

    runner._score_with_facets()

    assert "score" not in seen
    assert set(runner.semantic) == {b.id for b in runner.full_resume.all_bullets()}
    assert runner.facet_result.warnings == []


def test_a_scoring_failure_still_applies_facets(monkeypatch):
    def score(bullets, requirements, **kwargs):
        raise ValueError("model answered nonsense")

    _stub_stages(monkeypatch, score)
    events: list = []
    runner = _web_run(events)

    runner._score_with_facets()

    assert runner.semantic is None
    assert any("keywords only" in e.message for e in events)
    assert runner.facet_result is not None


def test_a_broken_backend_fails_the_run_after_facets_finish(monkeypatch):
    finished: list[str] = []

    def score(bullets, requirements, **kwargs):
        raise LLMError("daemon unreachable")

    def select_facets(resume, requirements, **kwargs):
        finished.append("facets")
        return SimpleNamespace(warnings=[])

    _stub_stages(monkeypatch, score)
    monkeypatch.setattr(facets, "select_facets", select_facets)

    with pytest.raises(RuntimeError, match="daemon unreachable"):
        _web_run([])._score_with_facets()
    assert finished == ["facets"]


def test_cli_scores_the_unfiltered_resume_and_facets_the_filtered_one(monkeypatch):
    scored: list[set[str]] = []
    seen = _stub_stages(
        monkeypatch,
        lambda bullets, requirements, **k: scored.append({b.id for b in bullets}) or {},
    )
    resume = synthetic_resume()
    excluded = resume.experience[0]
    runner = cli_run._CliRun(argparse.Namespace(
        no_semantic=False, no_cache=False, no_facets=False, no_project_links=False,
    ))
    runner.resume = resume
    runner.requirements = jd.JobRequirements(title="Engineer", seniority="intern")
    runner.include_options = IncludeOptions(exclude_entries=[excluded.id])

    assert runner._score_with_facets() is None

    assert {b.id for b in excluded.bullets} <= scored[0]
    assert excluded.id not in {e.id for e in seen["facets_resume"].experience}
    assert runner.full_resume is resume
