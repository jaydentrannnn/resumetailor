"""Derive `config.CHARS_PER_LINE` and `config.LINES_PER_PAGE` from the real template.

Phase 5b of the build plan (see docs/PLAN.md). Both constants are placeholders until this
script measures them against actual Word-rendered PDFs — no formula, just render, convert,
and read where wrapping and page breaks really happen.

Method:
  1. CHARS_PER_LINE: render a single synthetic bullet of increasing length in an otherwise
     empty resume, binary-searching for the longest text that still fits one physical line
     in the PDF (checked via `pypdf`'s layout-mode extraction, which preserves visual line
     breaks even within a wrapped paragraph).
  2. LINES_PER_PAGE: render a synthetic resume with N one-line bullets (each safely under
     the CHARS_PER_LINE just measured), binary-searching for the largest N that still fits
     on page 1. `LINES_PER_PAGE` is then the count of non-blank layout lines on that page —
     i.e. the real capacity of a full page in this template, header and section chrome
     included, since a 1-page target is the primary use case (`config.DEFAULT_PAGE_TARGET`).
  3. Sanity-check both known-good anchors from CLAUDE.md/PLAN.md: the full 39-bullet
     superset renders to 3 pages, and the 13-bullet current-resume subset renders to 1 page.
  4. Write the two constants to `data/calibration/<backend>.json`.

    python scripts/calibrate.py

The measurements describe one engine rendering one template, so they are stored per PDF
backend: Word and LibreOffice wrap identically on this template but differ by one line of
page capacity. Re-run this after changing the template, its fonts or margins, or the
converter — and note that it needs whichever engine `config.PDF_BACKEND` names.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor import config, data, render  # noqa: E402
from resume_tailor.data import Bullet, Experience, MasterResume  # noqa: E402

_WORDS = (
    "Delivered scalable systems by partnering across engineering and product teams to "
    "ship measurable improvements in latency accuracy and reliability for production "
    "workloads under real world constraints and deadlines "
)

_CURRENT_RESUME_BULLET_IDS = {
    "aol_b1", "aol_b2", "aol_b3",
    "vnpt_b1", "vnpt_b2",
    "uci_b1", "uci_b2",
    "aeth_b1", "aeth_b2", "aeth_b3",
    "t2s_b1", "t2s_b2", "t2s_b3",
}


def _text_of_length(n: int) -> str:
    """A realistic, word-wrappable string of exactly `n` characters."""
    repeated = (_WORDS * (n // len(_WORDS) + 2))[:n]
    return repeated


def _nonblank_lines(pdf_path: Path, page_index: int) -> list[str]:
    from pypdf import PdfReader

    page = PdfReader(str(pdf_path)).pages[page_index]
    text = page.extract_text(extraction_mode="layout")
    return [line for line in text.split("\n") if line.strip()]


def _single_bullet_resume(base: MasterResume, text: str) -> MasterResume:
    """A minimal resume: one experience entry, one bullet, no projects or skills.

    Skills are cleared too, not just projects: they still render even with an empty
    projects list (build_context never filters them out), so a "SKILLS" section would
    otherwise land right after the calibration bullet on page 1 and get counted as part
    of its wrap.
    """
    resume = base.model_copy(deep=True)
    resume.experience = [
        Experience(
            company="Calibration Co",
            title="Calibration Role",
            location="",
            start="2025-01",
            end="2025-02",
            bullets=[Bullet(id="calib_1", text=text, tags=["calibration"])],
        )
    ]
    resume.projects = []
    resume.skills = []
    return resume


def _n_bullet_resume(base: MasterResume, n: int, bullet_text: str) -> MasterResume:
    """One experience entry with `n` short one-line bullets, no projects."""
    resume = base.model_copy(deep=True)
    resume.experience = [
        Experience(
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
    ]
    resume.projects = []
    return resume


def _render_pages(resume: MasterResume, stub: str) -> tuple[Path, int]:
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
        # The EDUCATION section has its own "●" bullet, so anchor on the synthetic job's
        # title line instead and take everything after it as the calibration bullet's
        # wrapped lines (it is the only bullet in "Calibration Co"). "PROJECTS" and
        # "SKILLS" headers print even with empty lists, so drop those too.
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

    print(f"  anchor check: 39 bullets -> {full_pages} page(s) (expected 3) OK")
    print(f"  anchor check: 13-bullet subset -> {subset_pages} page(s) (expected 1) OK")


def write_calibration(chars_per_line: int, lines_per_page: int) -> Path:
    """Record the measurements as data, keyed by the PDF backend that produced them.

    Writes `<CALIBRATION_DIR>/<backend>.json` rather than editing `config.py`. Two reasons
    it is a file and not a source edit: the container's source tree may be read-only, and
    Word and LibreOffice genuinely need different numbers — LibreOffice fits one line
    fewer per page on this template — so there is no single pair of constants to write.
    """
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


def main() -> int:
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        print("Template not built. Run: python scripts/build_template.py", file=sys.stderr)
        return 1

    base = data.load()

    print(f"PDF backend: {config.PDF_BACKEND}")
    print("Calibrating CHARS_PER_LINE (binary search on single-bullet wrap point)...")
    chars_per_line = calibrate_chars_per_line(base)
    print(f"  CHARS_PER_LINE = {chars_per_line}")

    print("Calibrating LINES_PER_PAGE (binary search on page-1 bullet capacity)...")
    lines_per_page = calibrate_lines_per_page(base, chars_per_line)
    print(f"  LINES_PER_PAGE = {lines_per_page}")

    print("Verifying known-good anchors...")
    verify_known_anchors()

    path = write_calibration(chars_per_line, lines_per_page)
    print(
        f"\nWrote CHARS_PER_LINE = {chars_per_line}, LINES_PER_PAGE = {lines_per_page} "
        f"for backend '{config.PDF_BACKEND}' to {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
