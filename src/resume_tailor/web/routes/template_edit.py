"""Edit layout in Word: the session behind the Template page's button (desktop only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from resume_tailor.web import state as web_state
from resume_tailor.web import template_edit, template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import TemplateAnalyzeResponse, TemplateEditStatus

router = APIRouter()

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _desktop_only() -> None:
    if not web_state.desktop:
        raise HTTPException(
            status_code=404, detail="Editing the layout in Word is available in the desktop app."
        )


@router.get("/api/template/edit-session", response_model=TemplateEditStatus)
def edit_status() -> TemplateEditStatus:
    """Whether a layout file is open and whether it was saved since (polled by the UI)."""
    if not web_state.desktop:
        return TemplateEditStatus(active=False)
    return template_edit.status()


@router.post("/api/template/edit-session", response_model=TemplateEditStatus)
def start_edit() -> TemplateEditStatus:
    """Write the active template's layout file and open it in Word (or LibreOffice)."""
    _desktop_only()
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish first.",
        )
    with template_ops.LOCK:
        try:
            return template_edit.start()
        except template_edit.EditSessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/template/edit-session/open", response_model=TemplateEditStatus)
def reopen_edit() -> TemplateEditStatus:
    """Open the session's layout file again."""
    _desktop_only()
    try:
        return template_edit.reopen()
    except template_edit.EditSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/template/edit-session/import", response_model=TemplateAnalyzeResponse)
def import_edit() -> TemplateAnalyzeResponse:
    """Read the saved layout file back as an analysis for the template wizard.

    Applies nothing: the wizard previews it and installs only on confirmation."""
    _desktop_only()
    with template_ops.LOCK:
        try:
            return template_edit.read_back()
        except template_edit.EditSessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/template/edit-session/file/{sha}")
def edit_file(sha: str) -> Response:
    """The read-back file, for the wizard to install as its upload."""
    _desktop_only()
    try:
        raw = template_edit.realised(sha)
    except template_ops.TemplateValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=raw, media_type=_DOCX)


@router.delete("/api/template/edit-session", status_code=204)
def end_edit() -> Response:
    """End the session and delete the layout file."""
    _desktop_only()
    with template_ops.LOCK:
        template_edit.end()
    return Response(status_code=204)
