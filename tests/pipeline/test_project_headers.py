"""Project headers stay on one line: measured width, PDF check, tag trim — no Word."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor import config
from resume_tailor.content.data import Bullet, Project
from resume_tailor.document import calibrate, render
from resume_tailor.pipeline import facets_budget, fit_lines, fit_shrink
from tests.fixtures import synthetic_resume


def _project(pid: str = "p1", tech: list[str] | None = None, *, link: str = "Github") -> Project:
    return Project(
        id=pid,
        name="ResumeTailor - JD-Tailored Resume Pipeline",
        tech=["Python", "FastAPI", "Docker", "GitHub Actions"] if tech is None else tech,
        date="Jul 2026 - Present",
        link=link,
        bullets=[Bullet(id=f"{pid}_b1", text="Built it.", tags=["x"])],
    )


# -- header text and budget ------------------------------------------------------------


def test_header_text_matches_the_rendered_line():
    proj = _project()
    assert facets_budget.header_text(proj) == (
        "ResumeTailor - JD-Tailored Resume Pipeline | Python, FastAPI, Docker, "
        "GitHub Actions | Github Jul 2026 - Present"
    )
    assert "Github" not in facets_budget.header_text(proj, include_project_links=False)
    assert facets_budget.header_overhead(proj) == 42 + 3 + 9 + 18


def test_header_chars_prefers_the_measured_width(tmp_path, monkeypatch):
    path = tmp_path / "word.json"
    path.write_text(json.dumps({"chars_per_line": 121, "header_chars_per_line": 108}))
    monkeypatch.setattr(config, "CALIBRATION_SOURCE", str(path))
    monkeypatch.setattr(config, "CHARS_PER_LINE", 121)
    assert config.project_header_chars() == 108
    assert facets_budget.project_header_tech_budget(_project()) == 108 - 72


@pytest.mark.parametrize("payload", [{"chars_per_line": 121}, {"header_chars_per_line": 5}])
def test_header_chars_falls_back_to_the_gap(tmp_path, monkeypatch, payload):
    path = tmp_path / "word.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(config, "CALIBRATION_SOURCE", str(path))
    monkeypatch.setattr(config, "CHARS_PER_LINE", 121)
    assert config.project_header_chars() == 121 - config.PROJECT_HEADER_GAP


def test_live_wrap_is_now_out_of_budget(monkeypatch):
    """The 2026-10-05 run: a 111-char header passed the old 121-4 budget and wrapped."""
    monkeypatch.setattr(config, "CALIBRATION_SOURCE", "fallback")
    monkeypatch.setattr(config, "CHARS_PER_LINE", 121)
    budget = facets_budget.project_header_tech_budget(_project())
    assert budget < len("Python, FastAPI, Docker, GitHub Actions")


# -- PDF line matching -----------------------------------------------------------------


def test_line_layout_reads_a_raised_hyperlink_in_x_order():
    """Word set the "Github" hyperlink 2pt above its line; sorted by top it led the line."""
    def word(text, top, x0, x1):
        return {"text": text, "top": top, "x0": x0, "x1": x1}

    boxes = [
        word("Name", 472.0, 43, 80), word("|", 472.0, 85, 88), word("Python", 472.0, 90, 130),
        word("|", 469.8, 458, 461), word("Github", 469.8, 463, 495),
        word("Jul", 472.0, 524, 536), word("2026", 472.0, 539, 560),
        word("-", 472.0, 565, 568), word("Present", 484.7, 43, 80),
    ]
    layout = render._layout_from_words(boxes, {"h": "Name | Python | Github Jul 2026 - Present"})
    assert layout["h"].lines == 2


def test_wrapped_headers_reports_only_multi_line_matches(tmp_path, monkeypatch):
    resume = synthetic_resume()
    next(s for s in resume.sections if s.kind == "project").entries = [
        _project("wraps"), _project("fits"),
    ]
    projects = resume.projects
    (tmp_path / "out.pdf").write_bytes(b"%PDF")
    lines = {"wraps": 2, "fits": 1}
    monkeypatch.setattr(
        render, "line_layout",
        lambda _pdf, texts: {
            pid: render.LineFit(n, 0.5, 100.0) for pid, n in lines.items() if pid in texts
        },
    )
    wrapped = fit_lines._wrapped_headers(
        tmp_path / "out.docx", resume, include_project_links=True
    )
    assert [p.id for p in wrapped] == [projects[0].id]


def test_wrapped_headers_without_a_pdf_measures_nothing(tmp_path):
    assert fit_lines._wrapped_headers(
        tmp_path / "missing.docx", synthetic_resume(), include_project_links=True
    ) == []


# -- the fit loop's header pass --------------------------------------------------------


class _Run(fit_shrink._FitShrink):
    """Just the state `header_pass` reads, with a counting fake render."""

    def __init__(self, projects: list[Project], *, estimated: bool = False) -> None:
        resume = synthetic_resume()
        resume.sections = [s for s in resume.sections if s.kind != "project"]
        from resume_tailor.content.data import ProjectSection

        resume.sections.append(ProjectSection(id="projects", title="Projects", entries=projects))
        self.resume = resume
        self.rewritten = {"b": "text"}
        self.include_project_links = True
        self.warnings: list[str] = []
        self.on_event = None
        self.doc_path = Path("out.docx")
        self.pages, self.measured_lines, self.pages_are_estimated = 1, 50, estimated
        self.draws: list[str] = []

    def draw(self, texts, step="draft", **note):
        self.draws.append(step)
        return self.doc_path, 1, 49, False


def _wraps_over(limit: int):
    return lambda _path, resume, include_project_links: [
        p for p in resume.projects if len(facets_budget.header_text(p)) > limit
    ]


def test_header_pass_trims_weakest_tags_until_the_header_fits(monkeypatch):
    run = _Run([_project()])
    # Full header is 111 chars; dropping "GitHub Actions" leaves 96, then "Docker" 88.
    monkeypatch.setattr(fit_lines, "_wrapped_headers", _wraps_over(90))
    run.header_pass()
    assert run.resume.projects[0].tech == ["Python", "FastAPI"]
    assert run.draws == ["header", "header"]
    assert run.measured_lines == 49
    assert run.warnings == []


def test_header_pass_warns_once_when_no_tech_is_left(monkeypatch):
    run = _Run([_project(tech=["Python"])])
    monkeypatch.setattr(fit_lines, "_wrapped_headers", _wraps_over(10))
    run.header_pass()
    assert run.resume.projects[0].tech == []
    assert len(run.warnings) == 1 and "no tech left" in run.warnings[0]


def test_header_pass_skips_an_estimated_draft(monkeypatch):
    run = _Run([_project()], estimated=True)
    monkeypatch.setattr(fit_lines, "_wrapped_headers", _wraps_over(10))
    run.header_pass()
    assert run.draws == [] and len(run.resume.projects[0].tech) == 4


# -- calibration -----------------------------------------------------------------------


def test_calibrate_header_chars_finds_the_one_line_limit(monkeypatch):
    overhead = 70
    monkeypatch.setattr(
        calibrate, "_header_lines",
        lambda base, n: (overhead + n, 1 if overhead + n <= 108 else 2),
    )
    assert calibrate.calibrate_header_chars(synthetic_resume()) == 108


def test_calibrate_header_chars_rejects_a_search_that_never_wraps(monkeypatch):
    monkeypatch.setattr(calibrate, "_header_lines", lambda base, n: (70 + n, 1))
    with pytest.raises(calibrate.CalibrationError, match="never wrapped"):
        calibrate.calibrate_header_chars(synthetic_resume())


def test_write_calibration_records_header_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    monkeypatch.setattr(config, "PDF_BACKEND", "word")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "main_template.docx")
    path = calibrate.write_calibration(121, 58, header_chars=108)
    assert json.loads(path.read_text(encoding="utf-8"))["header_chars_per_line"] == 108
