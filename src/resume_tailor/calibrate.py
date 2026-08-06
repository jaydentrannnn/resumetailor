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

from resume_tailor import config, data, render, template_profile
from resume_tailor.data import Bullet, Experience, ExperienceSection, MasterResume


class CalibrationError(RuntimeError):
    """Raised when a measurement cannot be trusted enough to write to disk.

    Two distinct failure modes both raise this, deliberately never write
    `write_calibration`'s output, and deliberately never get downgraded to a warning:

    - A binary search collapsed to one of its own search bounds instead of bracketing a
      real crossover (`_check_not_collapsed`) — the bound is not a measurement.
    - The self-consistency check (`verify_chars_per_line_boundary`) found the resulting
      constant does not actually predict what the renderer does.

    `verify_known_anchors` stays a soft warning (it is owner-specific — hardcoded bullet
    ids and page counts for one person's resume); these two are resume-independent and
    therefore safe to hard-fail on.
    """


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


def _static_heading_texts() -> set[str]:
    """Heading text that renders unconditionally on the calibration probe page even
    though `_single_bullet_resume`/`_n_bullet_resume` give it zero entries — text that
    must be excluded before counting how many lines the bullet under test itself wrapped
    to, or a search can never find a length that "wraps to exactly one line" and walks
    every candidate down to its floor instead.

    Only Projects and Skills are ever emptied by the probe resumes (Education keeps its
    real entries; the new Experience section is exactly what is being measured), so only
    those two matter here.

    Source of truth is the *active template profile*, not `resume.sections[].title`:
    - Under `section_mode="fixed"`, a section's heading paragraph is a static, always-
      rendered paragraph baked in at build time — its text is whatever the uploaded
      resume's heading said (a profile install, unlike the legacy path, does not force
      it to literally read "PROJECTS"/"SKILLS"). A resume whose heading said "Selected
      Projects" broke the old hardcoded `("PROJECTS", "SKILLS")` filter: that heading
      line survived every filter attempt, so `len(wrapped_lines) == 1` was never true,
      and the search walked all the way down to its floor. That produced exactly the
      chars_per_line=20 value this module once wrote to disk.
    - Under `section_mode="generic"`, a zero-entry section renders no heading at all
      (see `render.build_context`'s `if not rendered_entries: continue`), so nothing
      needs filtering — an empty set is correct.
    - With no profile at all (legacy build), the physical headings are exactly
      `template_build.SECTIONS`'s hardcoded literals.
    """
    profile = template_profile.load_profile()
    if profile is None:
        return {"EDUCATION", "WORK EXPERIENCES", "PROJECTS", "SKILLS"}
    if profile.section_mode == "generic":
        return set()
    texts: set[str] = set()
    if profile.projects is not None:
        texts.add(profile.projects.heading_text.strip().upper())
    if profile.skills is not None:
        texts.add(profile.skills.heading_text.strip().upper())
    return texts


def _wrapped_line_count(pdf_path: Path, stop_titles: set[str]) -> int:
    """How many physical lines the "Calibration Role" bullet took on page 1.

    Raises `CalibrationError` (rather than letting a bare `next()` raise `StopIteration`)
    when the probe entry cannot be found at all — most likely because it overflowed onto
    page 2, which the caller needs to know about, not silently misread as "zero lines".
    """
    lines = _nonblank_lines(pdf_path, 0)
    try:
        role_idx = next(i for i, line in enumerate(lines) if "Calibration Role" in line)
    except StopIteration as exc:
        raise CalibrationError(
            "Could not find the 'Calibration Role' probe entry on page 1 of the "
            f"rendered PDF ({pdf_path}) — it may have overflowed onto page 2. "
            f"Rendered lines: {lines!r}"
        ) from exc
    return sum(
        1 for line in lines[role_idx + 1 :] if line.strip().upper() not in stop_titles
    )


def _check_not_collapsed(value: int, low_bound: int, high_bound: int, label: str) -> None:
    """Raise when a binary search's result sits exactly on a search bound.

    A search that never finds a real crossover walks every candidate the same
    direction and stops at the bound — which looks identical to a converged result
    unless the caller checks for it. The bound is not a measurement; writing it to
    disk is exactly how a previous run silently capped every rewritten bullet at
    ~15-35 characters.
    """
    if value in (low_bound, high_bound):
        raise CalibrationError(
            f"{label} search collapsed to its search bound ({value}, searched "
            f"[{low_bound}, {high_bound}]) instead of bracketing a real crossover. "
            "This does not mean the layout truly wraps at this size — the search never "
            "found where wrapping actually happens, most likely because a section "
            "heading that should have rendered unconditionally (see "
            "`_static_heading_texts`) was not being excluded correctly. Not writing "
            "this value."
        )


def _check_in_band(value: int, band: tuple[int, int], label: str) -> None:
    """Raise when a measurement falls outside the plausible range for any real resume
    template — a backstop for a collapse that lands one step off its search bound
    rather than exactly on it, which `_check_not_collapsed` alone would miss."""
    lo, hi = band
    if not (lo <= value <= hi):
        raise CalibrationError(
            f"{label} measured {value}, outside the plausible range [{lo}, {hi}]. Not "
            f"writing this value — inspect the rendered PDFs under {config.OUTPUT_DIR} "
            "before re-running."
        )


def calibrate_chars_per_line(base: MasterResume) -> int:
    """Binary search the longest single-bullet text that still fits one physical line.

    Raises `CalibrationError` if the search collapses to a bound or lands outside the
    plausible band — see `_check_not_collapsed`/`_check_in_band`.
    """
    stop_titles = _static_heading_texts()
    low_bound, high_bound = 20, 220
    low, high = low_bound, high_bound
    while low < high:
        mid = (low + high + 1) // 2
        resume = _single_bullet_resume(base, _text_of_length(mid))
        pdf, _ = _render_pages(resume, "chars")
        if _wrapped_line_count(pdf, stop_titles) == 1:
            low = mid
        else:
            high = mid - 1
    _check_not_collapsed(low, low_bound, high_bound, "CHARS_PER_LINE")
    _check_in_band(low, config.PLAUSIBLE_CHARS_PER_LINE, "CHARS_PER_LINE")
    return low


def calibrate_lines_per_page(base: MasterResume, chars_per_line: int) -> int:
    """Binary search the largest bullet count that still fits on page 1, then measure
    how many physical lines that many bullets actually occupy.

    The search variable (bullet count) and the returned metric (line count) are
    different units — collapse-checked separately from band-checked for that reason.
    """
    one_line_text = _text_of_length(max(10, chars_per_line - 15))

    low_bound, high_bound = 5, 90
    low, high = low_bound, high_bound
    while low < high:
        mid = (low + high + 1) // 2
        resume = _n_bullet_resume(base, mid, one_line_text)
        _, pages = _render_pages(resume, "lines")
        if pages == 1:
            low = mid
        else:
            high = mid - 1
    _check_not_collapsed(low, low_bound, high_bound, "LINES_PER_PAGE bullet-count search")

    resume = _n_bullet_resume(base, low, one_line_text)
    pdf, pages = _render_pages(resume, "lines_final")
    assert pages == 1
    result = len(_nonblank_lines(pdf, 0))
    _check_in_band(result, config.PLAUSIBLE_LINES_PER_PAGE, "LINES_PER_PAGE")
    return result


def verify_chars_per_line_boundary(base: MasterResume, chars_per_line: int) -> None:
    """Resume-independent falsification check: a bullet of exactly `chars_per_line`
    characters must still render as one physical line, and one 15 characters longer
    must wrap to two.

    Unlike `verify_known_anchors` (hardcoded bullet ids and page counts for one
    person's resume, so a mismatch might just mean the resume changed), this holds for
    any master resume — a failure here means `chars_per_line` does not actually predict
    what the renderer does, so it is safe, and necessary, to hard-fail on.
    """
    stop_titles = _static_heading_texts()

    resume = _single_bullet_resume(base, _text_of_length(chars_per_line))
    pdf, _ = _render_pages(resume, "verify_one_line")
    if _wrapped_line_count(pdf, stop_titles) != 1:
        raise CalibrationError(
            f"A {chars_per_line}-character bullet did not render as one line at "
            f"CHARS_PER_LINE={chars_per_line}. The measurement is not self-consistent."
        )

    resume = _single_bullet_resume(base, _text_of_length(chars_per_line + 15))
    pdf, _ = _render_pages(resume, "verify_two_line")
    if _wrapped_line_count(pdf, stop_titles) != 2:
        raise CalibrationError(
            f"A {chars_per_line + 15}-character bullet did not wrap to two lines at "
            f"CHARS_PER_LINE={chars_per_line}. The measurement is not self-consistent."
        )


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
    warnings (constants are still written) so a web install is not rolled back. This is
    distinct from the resume-independent self-consistency check
    (`verify_chars_per_line_boundary`), which always runs and always hard-fails —
    `CalibrationError` propagates out of this function, and `write_calibration` is never
    reached, so a bad measurement is never written regardless of `verify_anchors`.
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

    lines.append("Verifying CHARS_PER_LINE is self-consistent…")
    verify_chars_per_line_boundary(base, chars_per_line)
    lines.append("  boundary check OK")

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
