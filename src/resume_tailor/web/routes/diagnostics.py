"""`GET /api/diagnostics.zip`: a support bundle with personal data and secrets redacted.

The bundle holds the app log (already redacted at write time), versions, platform,
the per-stage backend routing (model names only, never keys), the fit calibration in
use, and the active profile's settings. Settings pass through `logs.redact` too, and the
master resume, applicant profile, application registry and generated documents are
deliberately left out: support needs to see what the app did, not who the user is.
"""

from __future__ import annotations

import io
import json
import platform
import sys
import zipfile
from datetime import UTC, datetime
from importlib import metadata

from fastapi import APIRouter
from fastapi.responses import Response

from resume_tailor import config, logs, workspace

router = APIRouter()


def _version() -> str:
    try:
        return metadata.version("resume-tailor")
    except metadata.PackageNotFoundError:
        return "unknown"


def build_bundle() -> bytes:
    """Assemble the diagnostics zip in memory."""
    buffer = io.BytesIO()
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app_version": _version(),
        "python": sys.version,
        "platform": platform.platform(),
        "active_workspace": config.active_workspace_id(),
        "pdf_backend": config.PDF_BACKEND,
        "calibration": {
            "source": config.CALIBRATION_SOURCE,
            "chars_per_line": config.CHARS_PER_LINE,
            "lines_per_page": config.LINES_PER_PAGE,
            "rejection": config.CALIBRATION_REJECTION,
        },
        "backends": config.backend_specs_snapshot(),
        "log_dir_configured": logs.log_dir() is not None,
    }
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("summary.json", json.dumps(summary, indent=2, default=str))
        try:
            settings = workspace.load_settings()
        except Exception as exc:  # noqa: BLE001 - a bad settings file is itself diagnostic
            settings = {"error": str(exc)}
        bundle.writestr(
            "settings.redacted.json", logs.redact(json.dumps(settings, indent=2, default=str))
        )
        for path in logs.log_files():
            # Logs are redacted when written; redact again so older lines written
            # before a new pattern existed are covered too.
            text = path.read_text(encoding="utf-8", errors="replace")
            bundle.writestr(f"logs/{path.name}", logs.redact(text))
    return buffer.getvalue()


@router.get("/api/diagnostics.zip")
def get_diagnostics() -> Response:
    """Download the redacted support bundle."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=build_bundle(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="resumetailor-diagnostics-{stamp}.zip"'
        },
    )
