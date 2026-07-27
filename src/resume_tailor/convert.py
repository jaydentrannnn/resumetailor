"""DOCX to PDF conversion, one implementation per rendering engine.

Split out of `render.py` so the rest of the pipeline never learns which engine is in use.
Both backends satisfy the same contract:

    convert(docx_path, pdf_path, keep_active=...) -> None,
    raising RuntimeError on any failure

`render.to_pdf` is the only caller, and `fit.fit` already treats a `RuntimeError` from
that path as "measurement unavailable, fall back to the character budget" — so a missing
Word install or a missing LibreOffice binary degrades a run rather than killing it.

Why two engines rather than one: Word lays the document out most faithfully but exists
only on Windows, and the fit loop needs a real page count on every iteration. LibreOffice
runs in a Linux container, which is what makes the web UI deployable. They do not measure
identically, so each carries its own calibration — see `config._load_calibration`.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

from . import config


def _convert_word(docx_path: Path, pdf_path: Path, *, keep_active: bool) -> None:
    """Convert with Microsoft Word over COM. Windows only.

    `keep_active` leaves Word running afterwards. The fit loop measures several drafts per
    run and passes True for every call but the last, which avoids paying Word's ~9s
    startup on each retry.
    """
    from docx2pdf import convert

    convert(str(docx_path.resolve()), str(pdf_path.resolve()), keep_active=keep_active)


def _convert_soffice(docx_path: Path, pdf_path: Path, *, keep_active: bool) -> None:
    """Convert with LibreOffice headless.

    `keep_active` is accepted and ignored: LibreOffice is invoked as a one-shot process,
    so there is no persistent instance to hold open. The parameter exists only so the two
    backends share a signature.

    Two details that are easy to get wrong:

    - `--convert-to pdf` writes `<stem>.pdf` into `--outdir` and offers no way to name the
      file, so the result is moved into place afterwards.
    - Concurrent invocations that share a user profile directory silently serialise (or
      fail outright) on LibreOffice's single-instance lock, so each call gets a private
      throwaway profile via `-env:UserInstallation`.
    """
    outdir = pdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)
    profile = Path(os.environ.get("TMPDIR", "/tmp")) / f"lo_{uuid.uuid4().hex}"

    cmd = [
        config.SOFFICE_BINARY,
        f"-env:UserInstallation=file://{profile.as_posix()}",
        "--headless",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(outdir),
        str(docx_path.resolve()),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.SOFFICE_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"LibreOffice binary not found at {config.SOFFICE_BINARY!r}. Install "
            f"libreoffice-writer or set SOFFICE_BINARY."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"LibreOffice did not finish converting {docx_path.name} within "
            f"{config.SOFFICE_TIMEOUT:.0f}s."
        ) from exc

    # LibreOffice is cheerfully unreliable about exit codes: it can report success while
    # writing nothing at all. The produced file is the only trustworthy signal, so the
    # return code is used for the error message rather than for the decision.
    produced = outdir / f"{docx_path.stem}.pdf"
    if not produced.exists():
        raise RuntimeError(
            f"LibreOffice did not produce a PDF for {docx_path.name} "
            f"(exit {completed.returncode}): {completed.stderr.strip() or 'no stderr'}"
        )

    if produced != pdf_path:
        produced.replace(pdf_path)


_BACKENDS = {"word": _convert_word, "soffice": _convert_soffice}


def convert(
    docx_path: Path, pdf_path: Path, *, keep_active: bool = False, backend: str | None = None
) -> Path:
    """Convert `docx_path` to `pdf_path` using the configured engine.

    Raises RuntimeError with an actionable message on any failure, including an unknown
    backend name. Returns the PDF path for convenience.
    """
    name = backend or config.PDF_BACKEND
    try:
        impl = _BACKENDS[name]
    except KeyError:
        raise RuntimeError(
            f"Unknown PDF backend {name!r}; expected one of {tuple(_BACKENDS)}."
        ) from None

    try:
        impl(docx_path, pdf_path, keep_active=keep_active)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - COM in particular raises a wide variety
        raise RuntimeError(
            f"{name} could not convert {docx_path.name} to PDF ({exc})."
        ) from exc

    if not pdf_path.exists():
        raise RuntimeError(f"Conversion reported success but {pdf_path} was not created.")
    return pdf_path
