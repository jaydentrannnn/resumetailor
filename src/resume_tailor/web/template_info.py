"""What the active template is: files, calibration, profile summary and preview paths."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import (
    template_profile,
)
from resume_tailor.web.schemas import (
    CalibrationInfo,
    TemplateFileInfo,
    TemplateInfoResponse,
    TemplateProfileSummary,
)

from . import template_library_store


def _file_info(path: Path) -> TemplateFileInfo:
    """Build a TemplateFileInfo for `path`, whether or not it exists."""
    if not path.exists():
        return TemplateFileInfo(exists=False, path=str(path))
    stat = path.stat()
    return TemplateFileInfo(
        exists=True,
        path=str(path),
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(
            timespec="seconds"
        ),
    )

def _other_backend_calibrations(*, exclude: str) -> list[str]:
    """Backend names (other than `exclude`) that already have a calibration file.

    Used to explain a "fallback" calibration state precisely: fit constants are not
    portable between Word and LibreOffice (they lay text out slightly differently), so
    a file present for the *other* backend cannot silently cover for a missing one —
    but a user seeing "fallback" with no further detail has no way to know that a real
    measurement exists at all, just for the wrong engine.
    """
    return [
        backend
        for backend in config.PDF_BACKENDS
        if backend != exclude and (config.CALIBRATION_DIR / f"{backend}.json").exists()
    ]

def _calibration_info(tagged: Path) -> CalibrationInfo:
    """Report fit-constant freshness relative to the tagged template's mtime."""
    cal_path = config.CALIBRATION_DIR / f"{config.PDF_BACKEND}.json"
    source = config.CALIBRATION_SOURCE
    rejection = config.CALIBRATION_REJECTION
    chars = config.CHARS_PER_LINE
    lines = config.LINES_PER_PAGE

    if not tagged.exists():
        return CalibrationInfo(
            source=source,
            chars_per_line=chars,
            lines_per_page=lines,
            stale=True,
            message="Tagged template is missing; generate it before calibrating.",
        )

    if rejection:
        # A file exists on disk but its numbers were implausible (see
        # `config.PLAUSIBLE_CHARS_PER_LINE`/`PLAUSIBLE_LINES_PER_PAGE`) — distinct from
        # "no file at all" below, and must be checked first: `cal_path.exists()` is
        # True here, so the next branch's "no calibration file" message would be wrong.
        return CalibrationInfo(
            source=source,
            chars_per_line=chars,
            lines_per_page=lines,
            stale=True,
            message=rejection,
        )

    calibrated_at = (
        datetime.fromtimestamp(cal_path.stat().st_mtime, UTC).isoformat()
        if cal_path.exists()
        else None
    )
    if not cal_path.exists() or source == "fallback":
        other = _other_backend_calibrations(exclude=config.PDF_BACKEND)
        hint = (
            f" A calibration file exists for {', '.join(other)}, but fit constants are "
            "not portable between PDF backends — that measurement cannot be reused here."
            if other
            else ""
        )
        return CalibrationInfo(
            source=source,
            chars_per_line=chars,
            lines_per_page=lines,
            stale=True,
            message=(
                "Page fit isn't tuned for this template yet, so page length is estimated. "
                "Use “Tune page fit” (or run `python scripts/calibrate.py`)." + hint
            ),
            calibrated_at=calibrated_at,
        )

    # Module-level CHARS_PER_LINE / LINES_PER_PAGE were loaded at import time; if the
    # template is newer than the cal file, those numbers describe a previous layout.
    stale = tagged.stat().st_mtime > cal_path.stat().st_mtime
    return CalibrationInfo(
        source=source,
        chars_per_line=chars,
        lines_per_page=lines,
        stale=stale,
        message=(
            "The template changed after page fit was tuned. Use “Tune page fit” (or run "
            "`python scripts/calibrate.py`)."
            if stale
            else None
        ),
        calibrated_at=calibrated_at,
    )

def _profile_summary() -> TemplateProfileSummary:
    """Summarise the active template profile for the Template tab."""
    profile = template_profile.load_profile()
    if profile is None:
        return TemplateProfileSummary(exists=False)
    return TemplateProfileSummary(
        exists=True,
        schema_version=profile.schema_version,
        enabled=profile.enabled.model_dump(),
        warnings=list(profile.warnings),
        contact_separator=profile.contact.separator if profile.contact else None,
    )

def _preview_paths() -> tuple[Path, Path]:
    """Return `(preview.docx, preview.pdf)` under `output/template/`."""
    directory = config.OUTPUT_DIR / "template"
    return directory / "preview.docx", directory / "preview.pdf"

def info() -> TemplateInfoResponse:
    """Collect baseline/tagged metadata, master-resume counts, and calibration status."""
    baseline = _file_info(config.BASELINE_TEMPLATE_PATH)
    tagged = _file_info(config.DEFAULT_TEMPLATE_PATH)
    experience_entries = 0
    project_entries = 0
    bullets = 0
    try:
        resume = data.load()
        experience_entries = len(resume.experience)
        project_entries = len(resume.projects)
        bullets = len(resume.all_bullets())
    except (FileNotFoundError, ValueError):
        pass

    active_id, active_label = template_library_store._library_active_meta()
    _, pdf_path = _preview_paths()
    return TemplateInfoResponse(
        baseline=baseline,
        tagged=tagged,
        experience_entries=experience_entries,
        project_entries=project_entries,
        bullets=bullets,
        calibration=_calibration_info(config.DEFAULT_TEMPLATE_PATH),
        preview_available=pdf_path.exists(),
        profile=_profile_summary(),
        active_library_id=active_id,
        active_label=active_label,
    )
