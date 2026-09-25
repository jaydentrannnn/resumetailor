"""`/api/automation` and submit evidence: the auto-submit guard rails (plan P4-S).

- ``GET/PUT /api/automation``: the "Pause all automation" switch in the header, and
  how many automatic submits the last 24 hours used against the daily cap.
- ``GET /api/applications/{id}/submit-evidence``: the audit folders `fill.py` writes
  around each automatic submit (``submit-<UTC stamp>/{before,after}.{json,png}``). The
  files themselves are served from the ``…/{stamp}/{name}`` route below.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from resume_tailor import config, workspace
from resume_tailor.apply import store, submit_guard
from resume_tailor.web.schemas import JobSettings

router = APIRouter()

_STAMP_RE = re.compile(r"^submit-\d{8}T\d{6}Z$")
_FILES = ("before.json", "before.png", "after.json", "after.png")


class AutomationState(BaseModel):
    paused: bool
    changed_at: str = ""
    auto_submits_24h: int = 0
    max_per_day: int = 0


class AutomationUpdate(BaseModel):
    paused: bool


class SubmitEvidence(BaseModel):
    stamp: str
    files: list[str]
    url: str = ""
    status: str = ""
    confirmation: str = ""


class SubmitEvidenceResponse(BaseModel):
    evidence: list[SubmitEvidence]


def _state() -> AutomationState:
    state = submit_guard.automation_state()
    try:
        settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
        max_per_day = settings.auto_submit_max_per_day
    except Exception:  # noqa: BLE001 - the switch must work even with broken settings
        max_per_day = 0
    since = datetime.now(UTC) - submit_guard.CAP_WINDOW
    used = sum(1 for _ in submit_guard.auto_submits(store.load_all().values(), since=since))
    return AutomationState(
        paused=state["paused"],
        changed_at=state["changed_at"],
        auto_submits_24h=used,
        max_per_day=max_per_day,
    )


@router.get("/api/automation", response_model=AutomationState)
def get_automation() -> AutomationState:
    return _state()


@router.put("/api/automation", response_model=AutomationState)
def put_automation(body: AutomationUpdate) -> AutomationState:
    submit_guard.set_paused(body.paused)
    return _state()


def _evidence_dirs(application_id: str) -> list[Path]:
    """Every output folder this application's fills may have used, that exists."""
    app = store.get(application_id)
    if app is None:
        raise HTTPException(status_code=404, detail="No such application.")
    root = config.APPLICATIONS_OUTPUT_DIR.resolve()
    folders: list[Path] = []
    for name in dict.fromkeys([application_id, app.canonical_key, app.source_job_id]):
        if not name:
            continue
        folder = (config.APPLICATIONS_OUTPUT_DIR / name).resolve()
        if folder.is_relative_to(root) and folder != root and folder.is_dir():
            folders.append(folder)
    return folders


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


@router.get(
    "/api/applications/{application_id}/submit-evidence",
    response_model=SubmitEvidenceResponse,
)
def list_submit_evidence(application_id: str) -> SubmitEvidenceResponse:
    found: dict[str, SubmitEvidence] = {}
    for folder in _evidence_dirs(application_id):
        for child in folder.iterdir():
            if not (child.is_dir() and _STAMP_RE.match(child.name)):
                continue
            after = _read_json(child / "after.json")
            before = _read_json(child / "before.json")
            found[child.name] = SubmitEvidence(
                stamp=child.name,
                files=[name for name in _FILES if (child / name).is_file()],
                url=str(after.get("url") or before.get("url") or ""),
                status=str(after.get("status") or ""),
                confirmation=str(after.get("confirmation") or ""),
            )
    return SubmitEvidenceResponse(evidence=[found[k] for k in sorted(found, reverse=True)])


@router.get("/api/applications/{application_id}/submit-evidence/{stamp}/{name}")
def get_submit_evidence_file(application_id: str, stamp: str, name: str) -> FileResponse:
    if not _STAMP_RE.match(stamp) or name not in _FILES:
        raise HTTPException(status_code=404, detail="No such file.")
    for folder in _evidence_dirs(application_id):
        path = folder / stamp / name
        if path.is_file():
            media = "image/png" if name.endswith(".png") else "application/json"
            return FileResponse(path, media_type=media)
    raise HTTPException(status_code=404, detail="No such file.")
