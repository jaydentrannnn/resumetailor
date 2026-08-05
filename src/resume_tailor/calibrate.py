"""Derive `config.CHARS_PER_LINE` and `config.LINES_PER_PAGE` from the real template.

Phase 5b of the build plan (see docs/PLAN.md). Both constants are placeholders until this
module measures them against actual Word/LibreOffice-rendered PDFs — no formula, just
render, convert, and read where wrapping and page breaks really happen.

The CLI `scripts/calibrate.py` is a thin wrapper around `run()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from resume_tailor import config, data, render
from resume_tailor.data import Bullet, Experience, ExperienceSection, MasterResume

_WORDS = (
    "Delivered scalable systems by partnering across engineering and product teams to "
    "ship measurable improvements in latency accuracy and reliability for production "
    "workloads under real world constraints and deadlines "
)

_CURRENT_RESUME_BULLET_IDS = {
    "aol_b1",
    "aol_b2",
    "aol_b3",
    "vnpt_b1",
    "vnpt_b2",
    "uci_b1",
    "uci_b2",
    "aeth_b1",
    "aeth_b2",
    "aeth_b3",
    "t2s_b1",
    "t2s_b2",
    "t2s_b3",
}


@dataclass
class CalibrationResult:
    """Outcome of a calibration run."""

    chars_per_line: int
    lines_per_page: int
    path: Path
    log: str = ""
    warnings: list[str] | None = None


def _text_of_length(n: int) -> str:
    """A realistic, word-wrappable string of exactly `n` characters."""
    repeated = (_WORDS * (n // len(_WORDS) + 2))[:n]
    return repeated


def _nonblank_lines(pdf_path: Path, page_index: int) -> list[str]:
    """Layout-mode non-blank lines on one PDF page."""
    from pypdf import PdfReader

    page = PdfReader(str(pdf_path)).pages[page_index]
    text = page.extract_text(extraction_mode="layout")
    return [line for line in text.split("\n") if line.strip()]


def _experience_only_sections(base: MasterResume, entry: Experience) -> list:
    """Every section from `base` except experience/project kinds, plus one experience
    section holding `entry` — used by the calibration resumes below, which need a
    controlled single job and no projects."""
    sections = [s for s in base.sections if s.kind not in ("experience", "project")]
    sections.append(ExperienceSection(id="experience", title="Experience", entries=[entry]))
    return sections


def _single_bullet_resume(base: MasterResume, text: str) -> MasterResume:
    """A minimal resume: one experience entry, one bullet, no projects or skills."""
    resume = base.model_copy(deep=True)
    entry = Experience(
        company="Calibration Co",
        title="Calibration Role",
        location="",
        start="2025-01",
        end="2025-02",
        bullets=[Bullet(id="calib_1", text=text, tags=["calibration"])],
    )
    resume.sections = [
        s for s in _experience_only_sections(resume, entry) if s.kind != "skills"
    ]
    return resume


def _n_bullet_resume(base: MasterResume, n: int, bullet_text: str) -> MasterResume:
    """One experience entry with `n` short one-line bullets, no projects."""
    resume = base.model_copy(deep=True)
    entry = Experience(
        company="Calibration Co",
        title="Calibration Role",
        location="",
        start="2025-01",
        end="2025-02",
        bullets=[
            Bullet(id=f"calib_{i}", text=bullet_text, tags=["calibration"])
            for i in range(n)
        ],
    )
    resume.sections = _experience_only_sections(resume, entry)
    return resume


def _render_pages(resume: MasterResume, stub: str) -> tuple[Path, int]:
    """Render `resume` to DOCX+PDF under output/ and return `(pdf_path, page_count)`."""
    out = config.OUTPUT_DIR / f"_calib_{stub}.docx"
    render.render(resume, out=out)
    pdf = render.to_pdf(out)
    return pdf, render.page_count(pdf)


def calibrate_chars_per_line(base: MasterResume) -> int:
    """Binary search the longest single-bullet text that still fits one physical line."""
    low, high = 20, 220
    while low < high:
        mid = (low + high + 1) // 2
        resume = _single_bullet_resume(base, _text_of_length(mid))
        pdf, _ = _render_pages(resume, "chars")
        lines = _nonblank_lines(pdf, 0)
        role_idx = next(i for i, line in enumerate(lines) if "Calibration Role" in line)
        wrapped_lines = [
            line for line in lines[role_idx + 1 :] if line.strip() not in ("PROJECTS", "SKILLS")
        ]
        if len(wrapped_lines) == 1:
            low = mid
        else:
            high = mid - 1
    return low


def calibrate_lines_per_page(base: MasterResume, chars_per_line: int) -> int:
    """Binary search the largest bullet count that still fits on page 1."""
    one_line_text = _text_of_length(max(10, chars_per_line - 15))

    low, high = 5, 90
    while low < high:
        mid = (low + high + 1) // 2
        resume = _n_bullet_resume(base, mid, one_line_text)
        _, pages = _render_pages(resume, "lines")
        if pages == 1:
            low = mid
        else:
            high = mid - 1

    resume = _n_bullet_resume(base, low, one_line_text)
    pdf, pages = _render_pages(resume, "lines_final")
    assert pages == 1
    return len(_nonblank_lines(pdf, 0))


def verify_known_anchors() -> None:
    """Owner-specific sanity checks for the current master resume + template."""
    resume = data.load()

    _, full_pages = _render_pages(resume, "anchor_full")
    if full_pages != 3:
        raise AssertionError(
            f"full master resume (39 bullets) rendered to {full_pages} page(s), expected 3"
        )

    subset_bullets = {
        b.id: b.text for b in resume.all_bullets() if b.id in _CURRENT_RESUME_BULLET_IDS
    }
    out = config.OUTPUT_DIR / "_calib_anchor_subset.docx"
    render.render(resume, bullets=subset_bullets, out=out)
    subset_pages = render.page_count(render.to_pdf(out))
    if subset_pages != 1:
        raise AssertionError(
            f"13-bullet current-resume subset rendered to {subset_pages} page(s), expected 1"
        )


def write_calibration(chars_per_line: int, lines_per_page: int) -> Path:
    """Record the measurements as data, keyed by the PDF backend that produced them."""
    config.CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    path = config.CALIBRATION_DIR / f"{config.PDF_BACKEND}.json"
    payload = {
        "backend": config.PDF_BACKEND,
        "chars_per_line": chars_per_line,
        "lines_per_page": lines_per_page,
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "template": config.DEFAULT_TEMPLATE_PATH.name,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run(*, verify_anchors: bool = True) -> CalibrationResult:
    """Measure fit constants against the active tagged template and write them to disk.

    When `verify_anchors` is True, owner-specific page-count checks run; failures become
    warnings (constants are still written) so a web install is not rolled back.
    """
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Tagged template not found: {config.DEFAULT_TEMPLATE_PATH}. "
            "Build it before calibrating."
        )

    base = data.load()
    lines: list[str] = [f"PDF backend: {config.PDF_BACKEND}"]

    lines.append("Calibrating CHARS_PER_LINE…")
    chars_per_line = calibrate_chars_per_line(base)
    lines.append(f"  CHARS_PER_LINE = {chars_per_line}")

    lines.append("Calibrating LINES_PER_PAGE…")
    lines_per_page = calibrate_lines_per_page(base, chars_per_line)
    lines.append(f"  LINES_PER_PAGE = {lines_per_page}")

    warnings: list[str] = []
    if verify_anchors:
        lines.append("Verifying known-good anchors…")
        try:
            verify_known_anchors()
            lines.append("  anchor checks OK")
        except AssertionError as exc:
            warnings.append(str(exc))
            lines.append(f"  warning: anchor check failed ({exc})")

    path = write_calibration(chars_per_line, lines_per_page)
    lines.append(
        f"Wrote CHARS_PER_LINE={chars_per_line}, LINES_PER_PAGE={lines_per_page} "
        f"for '{config.PDF_BACKEND}' to {path}"
    )
    return CalibrationResult(
        chars_per_line=chars_per_line,
        lines_per_page=lines_per_page,
        path=path,
        log="\n".join(lines),
        warnings=warnings or None,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry used by `scripts/calibrate.py`."""
    import argparse

    from resume_tailor import workspace

    parser = argparse.ArgumentParser(description="Measure fit constants for the active template.")
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="ID",
        help="Calibrate this profile instead of the active one (this invocation only).",
    )
    args = parser.parse_args(argv)
    try:
        workspace.bootstrap(workspace_id=args.workspace)
    except workspace.WorkspaceError as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        result = run(verify_anchors=True)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(result.log)
    return 0
