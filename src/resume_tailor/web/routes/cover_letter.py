"""Cover-letter layout settings and their preview (the Template page's Cover letter card)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from resume_tailor.document import cover_settings
from resume_tailor.document.cover_settings import CoverSettings
from resume_tailor.web import cover_preview, template_ops
from resume_tailor.web.schemas import CoverLetterSettingsResponse

router = APIRouter()


def _response(settings: CoverSettings) -> CoverLetterSettingsResponse:
    return CoverLetterSettingsResponse(
        settings=settings, fields=cover_preview.letterhead_fields()
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
