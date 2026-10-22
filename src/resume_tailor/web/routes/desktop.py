"""Desktop app file and window actions: Save as…, Show in folder, Open, window title.

The browser build gets 404 for all of them; its UI offers plain downloads instead.

Save as… takes the file's bytes from the page (the same bytes its download link
serves) and asks the shell for a path through the native Save dialog
(`infra/desktop_shell.py`), so one route covers every downloadable file and the page
never chooses where anything is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from pydantic import BaseModel

from resume_tailor.infra import autostart, desktop_shell, local_files
from resume_tailor.web import state as web_state
from resume_tailor.web.routes import run_lookup
from resume_tailor.web.schemas import DesktopSaveResult, DesktopTitleRequest

router = APIRouter()

#: Largest file Save as… accepts (a data export with every run's output fits).
MAX_SAVE_BYTES = 1024 * 1024 * 1024

FileKind = Literal["resume-pdf", "resume-docx", "cover-pdf", "cover-docx"]
FileAction = Literal["open", "reveal"]


def _desktop_only() -> None:
    if not web_state.desktop:
        raise HTTPException(status_code=404, detail="Available in the desktop app only.")


def _safe_name(name: str) -> str:
    """The file name part only: no folders, no characters Windows refuses."""
    base = Path(name.replace("\\", "/")).name
    cleaned = "".join("_" if c in '<>:"|?*' or ord(c) < 32 else c for c in base).strip(" .")
    return cleaned or "ResumeTailor file"


@router.post("/api/desktop/save-as", response_model=DesktopSaveResult)
async def save_as(request: Request, name: str) -> DesktopSaveResult:
    """Write the request body where the person chooses in the native Save dialog."""
    _desktop_only()
    body = await request.body()
    if len(body) > MAX_SAVE_BYTES:
        raise HTTPException(status_code=413, detail="The file is too large to save.")
    filename = _safe_name(name)
    ext = Path(filename).suffix
    try:
        chosen = await run_in_threadpool(desktop_shell.ask_save_path, filename, ext)
    except desktop_shell.ShellUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if chosen is None:
        return DesktopSaveResult(saved=False)
    target = Path(chosen)
    if ext and target.suffix.lower() != ext.lower():
        target = target.with_name(target.name + ext)
    try:
        await run_in_threadpool(target.write_bytes, body)
    except OSError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Could not save to {target}: {exc.strerror or exc}. "
            "If the file is open in another program, close it and try again.",
        ) from exc
    return DesktopSaveResult(saved=True, path=str(target))


def _job_file(job_id: str, kind: FileKind) -> Path:
    """A finished run's deliverable on disk, or 404/409 like its download route."""
    if kind == "resume-pdf":
        return run_lookup._job_artifact(job_id, ".pdf")
    if kind == "resume-docx":
        return run_lookup._job_artifact(job_id, ".docx")
    out_dir = run_lookup._finished_run_dir(job_id)
    path = out_dir / ("cover.pdf" if kind == "cover-pdf" else "cover.docx")
    if kind == "cover-pdf":
        run_lookup._rebuild_missing_pdf(path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Cover letter was not produced for this job.")
    return path


@router.post("/api/jobs/{job_id}/files/{kind}/{action}", status_code=204)
def file_action(job_id: str, kind: FileKind, action: FileAction) -> Response:
    """Open a run's file in its program (a .docx in Word) or show it in its folder."""
    _desktop_only()
    path = _job_file(job_id, kind)
    if action == "reveal":
        local_files.reveal(path)
    elif path.suffix == ".docx":
        local_files.open_in_word_processor(path)
    else:
        local_files.open_default(path)
    return Response(status_code=204)


@router.post("/api/desktop/title", status_code=204)
def window_title(body: DesktopTitleRequest) -> Response:
    """Set the app window's title (the page's title cannot reach it)."""
    _desktop_only()
    desktop_shell.set_title(body.title)
    return Response(status_code=204)


class AutostartUpdate(BaseModel):
    enabled: bool


@router.get("/api/desktop/autostart")
def get_autostart() -> dict:
    """Whether the app launches when the computer starts (desktop only)."""
    _desktop_only()
    return {"enabled": autostart.is_enabled(), "supported": autostart.shell_exe() is not None}


@router.put("/api/desktop/autostart")
def put_autostart(body: AutostartUpdate) -> dict:
    """Enable or disable launch at login (desktop only)."""
    _desktop_only()
    try:
        enabled = autostart.set_enabled(body.enabled)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"enabled": enabled, "supported": True}
