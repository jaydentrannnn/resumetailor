"""Filesystem operations for the Template tab: inspect, preview, install.

All Word/LibreOffice work is serialised behind `_LOCK` so a preview render and a
rebuild never overlap. `scripts/build_template.py` remains the sole producer of
`main_template.docx` — this module only shells out to it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import docx

from resume_tailor import config, data, render
from resume_tailor.web.schemas import (
    CalibrationInfo,
    TemplateBuildResponse,
    TemplateFileInfo,
    TemplateInfoResponse,
)

#: Reject uploads larger than this before writing anything under templates/.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: Serialises preview render and baseline install so Word/LibreOffice is never concurrent.
_LOCK = threading.Lock()


class TemplateValidationError(ValueError):
    """Raised when an upload fails a pre-install check (extension, size, OOXML)."""


class TemplateBuildError(RuntimeError):
    """Raised when `scripts/build_template.py` exits non-zero; `.log` holds its output."""

    def __init__(self, message: str, *, log: str = "") -> None:
        """Store the failure message and the captured build script stdout+stderr."""
        super().__init__(message)
        self.log = log


def _file_info(path: Path) -> TemplateFileInfo:
    """Build a TemplateFileInfo for `path`, whether or not it exists."""
    if not path.exists():
        return TemplateFileInfo(exists=False, path=str(path))
    stat = path.stat()
    return TemplateFileInfo(
        exists=True,
        path=str(path),
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds"
        ),
    )


def _calibration_info(tagged: Path) -> CalibrationInfo:
    """Report fit-constant freshness relative to the tagged template's mtime."""
    cal_path = config.CALIBRATION_DIR / f"{config.PDF_BACKEND}.json"
    source = config.CALIBRATION_SOURCE
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

    if not cal_path.exists() or source == "fallback":
        return CalibrationInfo(
            source=source,
            chars_per_line=chars,
            lines_per_page=lines,
            stale=True,
            message=(
                "No calibration file for this PDF backend. Run "
                "`python scripts/calibrate.py` then restart the server."
            ),
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
            "Template is newer than calibration. Run `python scripts/calibrate.py` "
            "then restart the server."
            if stale
            else None
        ),
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

    _, pdf_path = _preview_paths()
    return TemplateInfoResponse(
        baseline=baseline,
        tagged=tagged,
        experience_entries=experience_entries,
        project_entries=project_entries,
        bullets=bullets,
        calibration=_calibration_info(config.DEFAULT_TEMPLATE_PATH),
        preview_available=pdf_path.exists(),
    )


def ensure_preview() -> Path:
    """Render the full master resume through the tagged template and return its PDF path.

    Regenerates only when `main_template.docx` is newer than the cached PDF (or the PDF
    is missing). Raises `RuntimeError` when PDF conversion is unavailable so the route
    can return 503 instead of a broken frame.
    """
    with _LOCK:
        tagged = config.DEFAULT_TEMPLATE_PATH
        if not tagged.exists():
            raise FileNotFoundError(
                f"Tagged template not found: {tagged}. "
                "Upload a baseline or run `python scripts/build_template.py`."
            )

        docx_path, pdf_path = _preview_paths()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        needs_render = (
            not pdf_path.exists()
            or not docx_path.exists()
            or tagged.stat().st_mtime > pdf_path.stat().st_mtime
        )
        if not needs_render:
            return pdf_path

        resume = data.load()
        render.render(resume, out=docx_path)
        # Propagate RuntimeError from convert so the UI can say "no PDF backend".
        render.to_pdf(docx_path, pdf_path)
        return pdf_path


def invalidate_preview() -> None:
    """Delete the cached preview so the next `ensure_preview` regenerates it."""
    docx_path, pdf_path = _preview_paths()
    for path in (docx_path, pdf_path):
        if path.exists():
            path.unlink()


def _run_build() -> tuple[int, str]:
    """Shell out to `scripts/build_template.py`. Returns `(exit_code, combined_log)`.

    Kept as a named function so tests can monkeypatch it without hitting Word or the
    real build script.
    """
    script = config.PROJECT_ROOT / "scripts" / "build_template.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(config.PROJECT_ROOT),
        check=False,
    )
    log = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, log


def install_baseline(raw: bytes, filename: str) -> TemplateBuildResponse:
    """Validate an uploaded .docx, replace the baseline, rebuild the tagged template.

    On build failure the previous baseline is restored byte-for-byte. Raises
    `TemplateValidationError` for bad inputs and `TemplateBuildError` when the build
    script exits non-zero (after restore).
    """
    name = Path(filename).name
    if not name.lower().endswith(".docx"):
        raise TemplateValidationError("Upload must be a .docx file.")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise TemplateValidationError(
            f"Upload is {len(raw)} bytes; maximum is {_MAX_UPLOAD_BYTES}."
        )
    if not raw:
        raise TemplateValidationError("Upload is empty.")

    with _LOCK:
        # Confirm OOXML before touching templates/: write to a temp file and open it.
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            docx.Document(str(tmp_path))
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            raise TemplateValidationError(
                f"File is not a readable .docx: {exc}"
            ) from exc

        baseline = config.BASELINE_TEMPLATE_PATH
        baseline.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        previous: bytes | None = None

        if baseline.exists():
            previous = baseline.read_bytes()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = baseline.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"original_export.{stamp}.docx"
            shutil.copy2(baseline, backup)

        # Atomic-ish replace: move the validated temp file into place.
        shutil.move(str(tmp_path), str(baseline))

        exit_code, log = _run_build()
        if exit_code != 0:
            if previous is not None:
                baseline.write_bytes(previous)
            raise TemplateBuildError(
                "build_template.py failed; previous baseline restored."
                if previous is not None
                else "build_template.py failed.",
                log=log.strip() or f"(exit {exit_code}, no output)",
            )

        invalidate_preview()
        return TemplateBuildResponse(ok=True, log=log.strip(), info=info())
