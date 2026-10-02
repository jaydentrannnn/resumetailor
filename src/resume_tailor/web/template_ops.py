"""Shared base of the Template tab's filesystem operations: `LOCK`, limits, errors.

The operations themselves live in the `template_*` siblings that import this module:
`template_info` (inspect), `template_library_store` / `template_library` (named
snapshots), `template_preview`, `template_uploads` (analyze/remap), `template_install`
(build, calibrate, install) and `template_defaults` (bundled templates).

All Word/LibreOffice work is serialised behind `LOCK` so a preview render and a
rebuild never overlap. `scripts/build_template.py` remains the sole CLI producer of
`main_template.docx`; this module shells out to it (or calls `template_build` for
staged profile installs).

Named library snapshots live under `templates/library/`; the live slot remains the
single `original_export.docx` / `main_template.docx` / `template_profile.json` trio.
"""

from __future__ import annotations

import threading

#: Reject uploads larger than this before writing anything under templates/.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: Cap on named library entries (user must delete before adding more).
_LIBRARY_MAX_ENTRIES = 20

#: Max length for a user-facing library label.
_LIBRARY_LABEL_MAX = 80

#: Serialises preview render and baseline install so Word/LibreOffice is never concurrent.
LOCK = threading.Lock()


class TemplateValidationError(ValueError):
    """Raised when an upload fails a pre-install check (extension, size, OOXML)."""


class TemplateBuildError(RuntimeError):
    """Raised when template build fails; `.log` holds stdout/stderr or smoke-render detail."""

    def __init__(self, message: str, *, log: str = "") -> None:
        """Store the failure message and the captured build log."""
        super().__init__(message)
        self.log = log
