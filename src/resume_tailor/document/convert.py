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

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .. import config
from ..infra import telemetry


#: Per-thread private Word instance kept alive between `keep_active` conversions.
_WORD = threading.local()
#: `wdFormatPDF` / `wdDoNotSaveChanges`.
_WD_FORMAT_PDF = 17
_WD_DO_NOT_SAVE = 0


def _convert_word(docx_path: Path, pdf_path: Path, *, keep_active: bool) -> None:
    """Convert with Microsoft Word over COM. Windows only.

    Always a private, invisible Word (`DispatchEx`), never the user's: `Dispatch`
    (what docx2pdf uses) attaches to a Word the person already has open and `Quit()`
    then closes it under them — documents and all — which the Edit-layout-in-Word
    round trip makes routine. `keep_active` keeps this thread's instance for the next
    call (the fit loop measures several drafts per run; Word's ~9s startup is paid
    once); the call without it quits the instance. COM is per thread and every job runs
    on its own, so each thread initialises COM and owns its instance.
    """
    import pythoncom  # pywin32
    import win32com.client

    if getattr(_WORD, "app", None) is None:
        pythoncom.CoInitialize()
        try:
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            app.DisplayAlerts = 0
        except Exception:
            pythoncom.CoUninitialize()
            raise
        _WORD.app = app
    app = _WORD.app
    try:
        doc = app.Documents.Open(
            str(docx_path.resolve()), ReadOnly=True, AddToRecentFiles=False, Visible=False
        )
        try:
            doc.SaveAs(str(pdf_path.resolve()), FileFormat=_WD_FORMAT_PDF)
        finally:
            doc.Close(_WD_DO_NOT_SAVE)
    except Exception:
        keep_active = False  # never reuse an instance that just failed
        raise
    finally:
        if not keep_active:
            _release_word(pythoncom)


def _release_word(pythoncom) -> None:
    """Quit this thread's private Word and release COM. Quit errors are ignored: the
    instance may already be gone (the failure that brought us here)."""
    app, _WORD.app = _WORD.app, None
    try:
        app.Quit(_WD_DO_NOT_SAVE)
    except Exception:  # noqa: BLE001 - a dead RPC server raises com_error
        pass
    finally:
        pythoncom.CoUninitialize()


#: Prefix of the LibreOffice user profiles this module creates under the temp dir.
_PROFILE_PREFIX = "rt_lo_"
#: A profile left by a crashed process is removed once it is this old.
_STALE_PROFILE_SECONDS = 24 * 3600

_SOFFICE_LOCK = threading.Lock()
_CONVERSION_LOCK = threading.Lock()
_profile_dir: Path | None = None


def _parallel_profiles() -> bool:
    """RESUME_TAILOR_SOFFICE_PARALLEL=1: a throwaway profile per call, no lock."""
    return os.environ.get("RESUME_TAILOR_SOFFICE_PARALLEL", "").strip() in {"1", "true", "yes"}


def _prune_stale_profiles(root: Path) -> None:
    cutoff = time.time() - _STALE_PROFILE_SECONDS
    for path in root.glob(f"{_PROFILE_PREFIX}*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _shared_profile() -> Path:
    """This process's LibreOffice profile, created on first use and removed at exit.

    Creating a profile is the largest part of a cold `soffice` start, and the fit loop
    converts several drafts per run, so one profile is reused for the life of the
    process. It is per process (named by pid), never shared across processes: a second
    `soffice` on the same profile hands its job to the first instance's pipe instead
    of converting, which fails intermittently.
    """
    global _profile_dir
    if _profile_dir is None:
        root = Path(tempfile.gettempdir())
        _prune_stale_profiles(root)
        _profile_dir = root / f"{_PROFILE_PREFIX}{os.getpid()}_{uuid.uuid4().hex[:8]}"
        atexit.register(shutil.rmtree, _profile_dir, ignore_errors=True)
    return _profile_dir


def _reset_shared_profile() -> None:
    """Throw away the shared profile (a stale lock or a corrupt profile)."""
    if _profile_dir is not None:
        shutil.rmtree(_profile_dir, ignore_errors=True)


def _profile_uri(profile: Path) -> str:
    """``-env:UserInstallation`` value. `as_uri` is ``file:///C:/...`` on Windows;
    the old ``file://`` + posix path gave ``file://C:/...``, which names a host "C:".
    """
    return profile.resolve().as_uri()


def _run_soffice(
    docx_path: Path, outdir: Path, profile: Path, target: str = "pdf"
) -> subprocess.CompletedProcess:
    cmd = [
        config.SOFFICE_BINARY,
        f"-env:UserInstallation={_profile_uri(profile)}",
        "--headless",
        "--norestore",
        "--convert-to",
        target,
        "--outdir",
        str(outdir),
        str(docx_path.resolve()),
    ]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.SOFFICE_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        msg = f"LibreOffice binary not found at {config.SOFFICE_BINARY!r}."
        if sys.platform == "darwin":
            msg += " Install LibreOffice or set SOFFICE_BINARY."
        else:
            msg += " Install libreoffice-writer or set SOFFICE_BINARY."
        raise RuntimeError(msg) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"LibreOffice did not finish converting {docx_path.name} within "
            f"{config.SOFFICE_TIMEOUT:.0f}s."
        ) from exc


def _convert_soffice(docx_path: Path, pdf_path: Path, *, keep_active: bool) -> None:
    """Convert with LibreOffice headless.

    `keep_active` is accepted and ignored: LibreOffice is invoked as a one-shot process,
    so there is no persistent instance to hold open. The parameter exists only so the two
    backends share a signature.

    Details that are easy to get wrong:

    - `--convert-to pdf` writes `<stem>.pdf` into `--outdir` and offers no way to name the
      file, so the result is moved into place afterwards.
    - Concurrent invocations that share a user profile directory silently serialise (or
      fail outright) on LibreOffice's single-instance lock. Calls in this process share
      one profile (`_shared_profile`) under `_SOFFICE_LOCK`; with
      RESUME_TAILOR_SOFFICE_PARALLEL=1 each call gets a throwaway profile instead.
    - A conversion that produces nothing on the shared profile is retried once on a
      fresh profile: a crash can leave a stale lock or a half-written profile behind,
      and every later call would fail the same way.
    """
    outdir = pdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)
    produced = outdir / f"{docx_path.stem}.pdf"
    # A leftover from an earlier conversion would read as success below.
    produced.unlink(missing_ok=True)

    if _parallel_profiles():
        profile = Path(tempfile.gettempdir()) / f"{_PROFILE_PREFIX}call_{uuid.uuid4().hex}"
        try:
            completed = _run_soffice(docx_path, outdir, profile)
        finally:
            shutil.rmtree(profile, ignore_errors=True)
    else:
        with _SOFFICE_LOCK:
            completed = _run_soffice(docx_path, outdir, _shared_profile())
            if not produced.exists():
                _reset_shared_profile()
                completed = _run_soffice(docx_path, outdir, _shared_profile())

    # LibreOffice is cheerfully unreliable about exit codes: it can report success while
    # writing nothing at all. The produced file is the only trustworthy signal, so the
    # return code is used for the error message rather than for the decision.
    if not produced.exists():
        raise RuntimeError(
            f"LibreOffice did not produce a PDF for {docx_path.name} "
            f"(exit {completed.returncode}): {completed.stderr.strip() or 'no stderr'}"
        )

    if produced != pdf_path:
        produced.replace(pdf_path)


_BACKENDS = {"word": _convert_word, "soffice": _convert_soffice}


@telemetry.stage("pdf_conversion")
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
        with telemetry.span("pdf_lock_wait"):
            _CONVERSION_LOCK.acquire()
        try:
            with telemetry.span("pdf_engine"):
                impl(docx_path, pdf_path, keep_active=keep_active)
        finally:
            _CONVERSION_LOCK.release()
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - COM in particular raises a wide variety
        raise RuntimeError(
            f"{name} could not convert {docx_path.name} to PDF ({exc})."
        ) from exc

    if not pdf_path.exists():
        raise RuntimeError(f"Conversion reported success but {pdf_path} was not created.")
    return pdf_path


#: Word-processor formats LibreOffice can turn into .docx for import (P3-D7).
CONVERTIBLE_SUFFIXES = (".doc", ".odt", ".rtf")


def to_docx(src: Path, outdir: Path) -> Path:
    """Convert a .doc/.odt/.rtf file to .docx with LibreOffice (whatever the PDF
    backend is: Word's COM path only exports PDF). Raises RuntimeError on failure."""
    outdir.mkdir(parents=True, exist_ok=True)
    produced = outdir / f"{src.stem}.docx"
    produced.unlink(missing_ok=True)
    with _SOFFICE_LOCK:
        completed = _run_soffice(src, outdir, _shared_profile(), target="docx")
        if not produced.exists():
            _reset_shared_profile()
            completed = _run_soffice(src, outdir, _shared_profile(), target="docx")
    if not produced.exists():
        raise RuntimeError(
            f"LibreOffice could not convert {src.name} to .docx "
            f"(exit {completed.returncode}): {completed.stderr.strip() or 'no stderr'}"
        )
    return produced
