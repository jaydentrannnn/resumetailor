"""Structured report_data — same content as format_report, as data."""

from __future__ import annotations

from pathlib import Path

from resume_tailor.pipeline.fit_types import FitResult
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from resume_tailor.pipeline.report import format_report, report_data
from tests.fixtures import synthetic_resume


def _requirements() -> JobRequirements:
    return JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def test_report_data_matches_format_report_facts():
    """report_data carries the same numbers the text report prints."""
    resume = synthetic_resume()
    requirements = _requirements()
    bullet = resume.all_bullets()[0]
    result = FitResult(
        out_path=Path("output/tailored.docx"),
        pages=1,
        pages_are_estimated=False,
        iterations=2,
        bullets_selected=1,
        bullets_total=10,
        bullets={bullet.id: bullet.text},
        semantic_used=True,
        widows_repaired=1,
        widows_remaining=0,
        warnings=["example warning"],
    )

    data = report_data(resume, requirements, result)
    text = format_report(resume, requirements, result)

    assert data.title == requirements.title
    assert data.pages == 1
    assert data.iterations == 2
    assert data.semantic_used is True
    assert data.warnings == ["example warning"]
    assert data.pdf_backend  # whatever the host selected
    assert data.extraction_diagnosis is None
    assert f"{data.coverage_matched}/{data.coverage_total}" in text
    assert "example warning" in text
    assert isinstance(data.gaps, list)  # defaults `master` to `resume` unchanged


def test_report_data_carries_inconclusive_diagnosis():
    """Zero must-haves set extraction_diagnosis instead of a fake coverage ratio."""
    resume = synthetic_resume()
    requirements = JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="nice_to_have")],
    )
    bullet = resume.all_bullets()[0]
    result = FitResult(
        out_path=Path("output/tailored.docx"),
        pages=1,
        pages_are_estimated=False,
        iterations=1,
        bullets_selected=1,
        bullets_total=10,
        bullets={bullet.id: bullet.text},
        semantic_used=False,
        widows_repaired=0,
        widows_remaining=0,
        warnings=[],
    )
    data = report_data(resume, requirements, result)
    text = format_report(resume, requirements, result)
    assert data.extraction_diagnosis == "no_must_haves"
    assert "coverage inconclusive" in text
    assert "0/0" not in text
