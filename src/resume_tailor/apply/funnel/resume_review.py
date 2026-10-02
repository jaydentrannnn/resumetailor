"""Version-bound review before an application uses a flagged resume."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.pipeline import resume_quality

from . import store, store_models


class ReviewState(BaseModel):
    quality: resume_quality.ResumeQuality = Field(default_factory=resume_quality.ResumeQuality)
    warnings: list[str] = Field(default_factory=list)
    revision: str = ""
    acknowledged: bool = False
    required: bool = False


def state(app: store_models.Application) -> ReviewState:
    if not app.job_id:
        return ReviewState()
    out_dir = config.OUTPUT_DIR / "jobs" / app.job_id
    quality = resume_quality.read(out_dir)
    digest = hashlib.sha256(app.job_id.encode())
    digest.update(quality.model_dump_json().encode())
    try:
        # Both artifacts matter: Fill can attach either format.
        for name in ("tailored.docx", "tailored.pdf"):
            path = out_dir / name
            digest.update(name.encode())
            digest.update(path.read_bytes() if path.exists() else b"missing")
    except OSError:
        quality = resume_quality.ResumeQuality(verified=False)
        digest.update(b"unreadable")
    revision = digest.hexdigest()
    warnings = quality.warnings
    acknowledged = app.resume_ack_revision == revision
    return ReviewState(
        quality=quality,
        warnings=warnings,
        revision=revision,
        acknowledged=acknowledged,
        required=bool(warnings) and not acknowledged,
    )


def acknowledge(application_id: str, revision: str) -> store_models.Application:
    def update(app: store_models.Application) -> None:
        current = state(app)
        if not current.quality.verified:
            raise ValueError("Resume quality could not be verified; Prepare again before Fill")
        if not revision or revision != current.revision:
            raise ValueError("This resume changed; review its current warnings again")
        app.resume_ack_revision = revision
        app.resume_ack_at = datetime.now(UTC).isoformat()

    return store.update(application_id, update)
