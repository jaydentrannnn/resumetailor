"""Open or reveal a file on the person's own machine (desktop app only).

Used by Edit layout in Word (`web/template_edit.py`) and by the document actions Open
in Word / Open / Show in folder (`web/routes/desktop.py`). Each call starts the OS
program and returns at once; nothing waits for it to close.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_MAC_WORD = Path("/Applications/Microsoft Word.app")


def open_in_word_processor(path: Path) -> None:
    """Open a ``.docx`` in Word (else LibreOffice on macOS).

    Never Pages: it cannot save a .docx back in place, so a save would never arrive.
    """
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        app = "Microsoft Word" if _MAC_WORD.exists() else "LibreOffice"
        subprocess.Popen(["open", "-a", app, str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607


def open_default(path: Path) -> None:
    """Open a file in the program the OS uses for its type (a PDF in the PDF reader)."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607


def reveal(path: Path) -> None:
    """Show the file selected in Explorer / Finder (Linux: open its folder)."""
    if sys.platform == "win32":
        # One command line, not a list: Popen would quote "/select,C:\a b\c.pdf" whole,
        # and Explorer then ignores /select and opens a default folder instead.
        subprocess.Popen(f'explorer /select,"{path.resolve()}"')  # noqa: S603, S607
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])  # noqa: S603, S607
