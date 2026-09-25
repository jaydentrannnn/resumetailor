"""Settings-page routes: model connection test, installed local models, PDF engine test,
and profile data export / import / reset (`data_transfer`)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import docx
import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from resume_tailor import config, convert, data_transfer, libraries, llm, workspace
from resume_tailor.apply import daily as apply_daily
from resume_tailor.apply import operations as apply_operations
from resume_tailor.apply import store as apply_store
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue, model_routing
from resume_tailor.web.schemas import JobSettings

router = APIRouter()

_LOCAL_BASES = {
    "ollama": lambda: config.OLLAMA_BASE_URL,
    "lmstudio": lambda: config.LMSTUDIO_BASE_URL,
}


class ModelTestRequest(BaseModel):
    #: Settings to test with; omitted = the profile's saved defaults.
    settings: JobSettings | None = None


class _Ping(BaseModel):
    ok: bool = Field(description="Always true.")


@router.post("/api/models/test")
def test_model(body: ModelTestRequest) -> dict[str, Any]:
    """One tiny call through the extraction stage's backend: proves the key and model work.

    Only ever runs when the user presses "Test" (on a paid backend it costs a fraction
    of a cent). Failures come back as ``ok: false`` with the provider's message.
    """
    settings = body.settings or JobSettings.model_validate(workspace.load_settings()["defaults"])
    profile, overrides, effort = model_routing(settings)
    started = time.monotonic()
    label = profile
    try:
        with config.pinned(profile, overrides=overrides, effort=effort):
            backend = config.backend_for("extract")
            label = f"{backend.origin or backend.provider}:{backend.model}"
            client = llm.client_for("extract")
            client.messages.parse(
                model=backend.model,
                max_tokens=256,
                system='Reply with the JSON object {"ok": true} and nothing else.',
                messages=[{"role": "user", "content": "Connection test."}],
                output_format=_Ping,
            )
    except Exception as exc:  # noqa: BLE001 - every failure is reported, not raised
        return {"ok": False, "model": label, "detail": str(exc)}
    return {
        "ok": True,
        "model": label,
        "detail": f"Answered in {time.monotonic() - started:.1f}s.",
    }


@router.get("/api/models/local")
def local_models(origin: str = "ollama") -> dict[str, Any]:
    """Models installed on a local server (Ollama / LM Studio), for a picker."""
    base = _LOCAL_BASES.get(origin)
    if base is None:
        raise HTTPException(status_code=400, detail=f"Unknown local server {origin!r}.")
    base_url = base()
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=3.0)
        response.raise_for_status()
        models = sorted(
            str(item.get("id")) for item in response.json().get("data", []) if item.get("id")
        )
    except (httpx.HTTPError, ValueError) as exc:
        return {"reachable": False, "base_url": base_url, "models": [], "detail": str(exc)}
    return {"reachable": True, "base_url": base_url, "models": models, "detail": ""}


@router.post("/api/pdf/test")
def test_pdf() -> dict[str, Any]:
    """Convert a one-line document with the configured PDF engine and time it."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="rt-pdf-test-") as tmp:
        source = Path(tmp) / "test.docx"
        document = docx.Document()
        document.add_paragraph("ResumeTailor PDF engine test.")
        document.save(source)
        try:
            convert.convert(source, Path(tmp) / "test.pdf")
        except RuntimeError as exc:
            return {"ok": False, "backend": config.PDF_BACKEND, "detail": str(exc)}
    return {
        "ok": True,
        "backend": config.PDF_BACKEND,
        "detail": f"Converted in {time.monotonic() - started:.1f}s.",
    }


def _require_idle(action: str) -> None:
    if get_queue().busy():
        raise HTTPException(409, f"A tailoring run is in progress; wait before {action}.")
    if apply_daily.daily_busy() or apply_operations.active() is not None:
        raise HTTPException(409, f"An Apply operation is running; wait before {action}.")


def _dir_bytes(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


@router.get("/api/data/info")
def data_info() -> dict[str, Any]:
    """Where this profile's files live, and how much space they take."""
    return {
        "workspace_id": config.active_workspace_id(),
        "data_dir": str(config.DATA_DIR),
        "templates_dir": str(config.TEMPLATES_DIR),
        "output_dir": str(config.OUTPUT_DIR),
        "data_bytes": _dir_bytes(config.DATA_DIR),
        "output_bytes": _dir_bytes(config.OUTPUT_DIR),
    }


@router.get("/api/data/export.zip")
def export_data(include_output: bool = True) -> Response:
    """Download this profile as a zip (never includes API keys or passwords)."""
    workspace_id = config.active_workspace_id()
    if workspace_id is None:
        raise HTTPException(409, "No active profile.")
    with template_ops.LOCK:
        raw = data_transfer.export_zip(workspace_id, include_output=include_output)
    stamp = time.strftime("%Y%m%d")
    return Response(
        content=raw,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="resumetailor-{workspace_id}-{stamp}.zip"'
        },
    )


@router.post("/api/data/import")
async def import_data(file: UploadFile = File(...)) -> dict[str, Any]:
    """Create a new profile from an export zip. Existing profiles are never touched."""
    raw = await file.read()
    if len(raw) > data_transfer.MAX_IMPORT_BYTES:
        raise HTTPException(413, "This file is larger than 2 GB.")
    with template_ops.LOCK:
        try:
            entry = data_transfer.import_zip(raw)
        except data_transfer.TransferError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"id": entry.id, "label": entry.label}


class ResetRequest(BaseModel):
    confirm: str


@router.post("/api/data/reset")
def reset_data(body: ResetRequest) -> dict[str, Any]:
    """"Delete all data" for the active profile: its files move to a trash folder."""
    if body.confirm != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm.")
    workspace_id = config.active_workspace_id()
    if workspace_id is None:
        raise HTTPException(409, "No active profile.")
    with template_ops.LOCK:
        _require_idle("deleting data")
        try:
            trash = data_transfer.reset_workspace(workspace_id)
        except data_transfer.TransferError as exc:
            raise HTTPException(409, str(exc)) from exc
        apply_store._cache = None
        apply_store._imported.clear()
        config.set_active_workspace(workspace_id, create_dirs=True)
        libraries.reload()
    return {"trash": str(trash)}
