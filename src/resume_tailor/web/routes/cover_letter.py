"""Cover-letter layout settings and their preview (the Template page's Cover letter card)."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from resume_tailor import config
from resume_tailor.document import cover_settings
from resume_tailor.document.cover_settings import CoverSettings
from resume_tailor.web import cover_letter_own, cover_preview, template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import CoverLetterSettingsResponse

router = APIRouter()


def _response(settings: CoverSettings) -> CoverLetterSettingsResponse:
    return CoverLetterSettingsResponse(
        settings=settings,
        fields=cover_preview.letterhead_fields(),
        own_letter=config.COVER_OWN_PATH.exists(),
    )


@router.get("/api/cover-letter/settings", response_model=CoverLetterSettingsResponse)
def get_cover_settings() -> CoverLetterSettingsResponse:
    """The active profile's cover-letter settings (defaults when never saved)."""
    return _response(cover_settings.load())


@router.put("/api/cover-letter/settings", response_model=CoverLetterSettingsResponse)
def put_cover_settings(body: CoverSettings) -> CoverLetterSettingsResponse:
    """Save the active profile's cover-letter settings. Under `template_ops.LOCK` so a
    save racing a profile switch cannot land in the other profile (see `put_settings`)."""
    with template_ops.LOCK:
        cover_settings.save(body)
    return _response(body)


@router.post("/api/cover-letter/preview")
def preview_cover_letter(body: CoverSettings) -> FileResponse:
    """PNG of a sample letter under `body` — unsaved settings preview before saving."""
    try:
        path = cover_preview.preview(body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/api/cover-letter/starter")
def starter_letter() -> Response:
    """Your current cover letter with «fields» in place of the words, to restyle in Word
    and upload back as your own letter."""
    try:
        raw = cover_letter_own.starter()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    disposition = f'attachment; filename="{cover_letter_own.STARTER_NAME}"'
    return Response(raw, media_type=_DOCX, headers={"Content-Disposition": disposition})


@router.post("/api/cover-letter/own", response_model=CoverLetterSettingsResponse)
def upload_own_letter(file: UploadFile = File(...)) -> CoverLetterSettingsResponse:
    """Use an uploaded letter (with «fields») for every cover letter from now on.

    A letter that can't be used is a 422 whose `detail.problems` lists why."""
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish first.",
        )
    raw = file.file.read()
    with template_ops.LOCK:
        try:
            settings = cover_letter_own.upload(raw, file.filename or "letter.docx")
        except cover_letter_own.OwnLetterError as exc:
            raise HTTPException(
                status_code=422, detail={"message": str(exc), "problems": exc.problems}
            ) from exc
    return _response(settings)


@router.delete("/api/cover-letter/own", response_model=CoverLetterSettingsResponse)
def remove_own_letter() -> CoverLetterSettingsResponse:
    """Stop using the uploaded letter; letters are built from the resume template again."""
    with template_ops.LOCK:
        return _response(cover_letter_own.remove())
