"""Template install, analysis, previews and saved-template library routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from resume_tailor.document import default_templates
from resume_tailor.document.template_profile import TemplateProfile
from resume_tailor.web import (
    template_defaults,
    template_info,
    template_install,
    template_library,
    template_preview,
    template_uploads,
    template_state,
)
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.schemas import (
    CalibrateResponse,
    DefaultTemplatesResponse,
    TemplateAnalyzeResponse,
    TemplateBuildResponse,
    TemplateInfoResponse,
    TemplateLibraryRenameRequest,
    TemplateLibraryResponse,
    TemplatePreviewDraftRequest,
    TemplateRemapRequest,
)
from resume_tailor.web.template_ops import TemplateBuildError, TemplateValidationError

router = APIRouter()
_log = logging.getLogger(__name__)


@router.get("/api/template", response_model=TemplateInfoResponse)
def get_template() -> TemplateInfoResponse:
    """Current baseline and tagged template metadata for the Template tab."""
    return template_info.info()


@router.get("/api/template/preview.pdf")
def template_preview_pdf(revision: str | None = None) -> FileResponse:
    """Inline PDF of the tagged template filled with the full master resume."""
    try:
        path = (
            template_preview.ensure_preview(revision)
            if revision is not None else template_preview.ensure_preview()
        )
    except template_preview.StalePreview as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        # PDF conversion unavailable (no Word / LibreOffice).
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to render template preview: {exc}"
        ) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename="template-preview.pdf",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=31536000, immutable" if revision else "no-cache",
        },
    )


@router.get("/api/template/state")
def get_template_state() -> dict:
    return template_state.snapshot()


@router.post("/api/template/analyze", response_model=TemplateAnalyzeResponse)
def analyze_template(
    file: UploadFile = File(...), convert_bullets: str | None = Form(None)
) -> TemplateAnalyzeResponse:
    """Preflight an uploaded baseline without writing under templates/.

    Truthy `convert_bullets` turns typed bullets ("•" + tab) into a real Word list in
    the server's copy (`docx_normalize`), for a file the analyzer flagged.

    A plain `def`: `template_uploads.analyze_upload` does real synchronous work (docx
    parsing, full structural analysis), so this must run in FastAPI's threadpool
    rather than block the event loop.
    """
    raw = file.file.read()
    filename = file.filename or "upload.docx"
    try:
        return template_uploads.analyze_upload(raw, filename, convert_bullets=_truthy(convert_bullets))
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/template/analyze/remap", response_model=TemplateAnalyzeResponse)
def remap_template(body: TemplateRemapRequest) -> TemplateAnalyzeResponse:
    """Re-analyze a previously uploaded baseline with specific headings' kinds forced
    by the user — a real server round trip so the wizard's confirm step reflects the
    analyzer's own downstream logic (entry splitting, field reconciliation, dates
    checks), not a client-side guess at what re-classifying a heading would do.
    """
    try:
        return template_uploads.remap_upload(body.source_sha256, body.overrides)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/template/preview/source")
def preview_source_template(body: TemplateRemapRequest) -> FileResponse:
    """PDF of the uploaded baseline as-is, for the wizard's side-by-side comparison.

    Reuses `TemplateRemapRequest` for its `source_sha256` field only; `overrides` is
    ignored here (nothing to remap — this is the original document, unmodified).
    """
    try:
        path = template_preview.preview_source(body.source_sha256)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename="source-preview.pdf",
        content_disposition_type="inline",
    )


@router.post("/api/template/preview/draft")
def preview_draft_template(body: TemplatePreviewDraftRequest) -> FileResponse:
    """PDF of the master resume rendered through a staged (not-yet-installed) profile
    — lets the wizard show what installing this exact mapping would produce, without
    touching the live template slot.
    """
    try:
        path = template_preview.preview_draft(body.source_sha256, body.profile)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid template profile: {exc}") from exc
    except TemplateBuildError as exc:
        # Must come before `except RuntimeError` — `TemplateBuildError` is a
        # `RuntimeError` subclass, and a mapping problem (this) is a different failure
        # from `render.to_pdf` genuinely having no PDF backend available (below).
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "log": exc.log},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename="draft-preview.pdf",
        content_disposition_type="inline",
    )


@router.post("/api/template", response_model=TemplateBuildResponse)
def upload_template(
    file: UploadFile = File(...),
    profile: str = Form(...),
    calibrate: str | None = Form(None),
    label: str | None = Form(None),
    convert_bullets: str | None = Form(None),
) -> TemplateBuildResponse:
    """Replace the baseline export and regenerate the tagged template.

    Required multipart field `profile` is a JSON TemplateProfile, confirmed through
    `POST /api/template/analyze` (and optionally `/analyze/remap`) first — there is no
    hard-coded-heading fallback; a resume whose layout the analyzer cannot map is a
    blocking issue on that response, not something this route silently guesses at.

    Optional multipart field `calibrate` (truthy: ``1``/``true``/``yes``) measures fit
    constants after a successful install and hot-reloads them in-process.

    Optional multipart field `label` names the library snapshot (default: filename stem).

    Refuses while a tailoring job is queued or running so the fit loop never
    measures against a template that is mid-rebuild.

    A plain `def`: `template_install.install_baseline` shells out to a subprocess build,
    smoke-renders, verifies, and optionally runs `calibrate.run` (Word/LibreOffice) —
    minutes of blocking work that must run in FastAPI's threadpool, not the event
    loop, or the SSE keepalive on every other open connection stalls with it.
    """
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish before "
            "replacing the template.",
        )

    raw = file.file.read()
    filename = file.filename or "upload.docx"
    try:
        parsed_profile = TemplateProfile.model_validate_json(profile)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid template profile: {exc}",
        ) from exc
    do_calibrate = (calibrate or "").strip().lower() in ("1", "true", "yes", "on")
    try:
        return template_install.install_baseline(
            raw,
            filename,
            profile=parsed_profile,
            do_calibrate=do_calibrate,
            label=label,
            convert_bullets=_truthy(convert_bullets),
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateBuildError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "log": exc.log},
        ) from exc


@router.post("/api/template/calibrate", response_model=CalibrateResponse)
def calibrate_template() -> CalibrateResponse:
    """Measure page-fit constants for the active template (the "Tune page fit" button)."""
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; tune page fit after it finishes.",
        )
    try:
        return template_install.calibrate_now()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/template/library", response_model=TemplateLibraryResponse)
def get_template_library() -> TemplateLibraryResponse:
    """List named template snapshots; seeds Default from live when the library is empty."""
    return template_library.list_library()


@router.post("/api/template/library/{entry_id}/activate", response_model=TemplateBuildResponse)
def activate_template_library_entry(
    entry_id: str,
    calibrate: str | None = None,
) -> TemplateBuildResponse:
    """Copy a library snapshot into the live template slot.

    Optional query `calibrate=true` measures fit constants after activation.
    Refuses while a tailoring job is busy.

    A plain `def`: this had no `await` at all despite being declared `async def` —
    `template_library.activate_library_entry` (a file copy plus optional calibration) ran
    fully synchronously on the event loop regardless.
    """
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish before "
            "switching templates.",
        )
    do_calibrate = (calibrate or "").strip().lower() in ("1", "true", "yes", "on")
    try:
        return template_state.switched(template_library.activate_library_entry(
            entry_id, do_calibrate=do_calibrate
        ))
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateBuildError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "log": exc.log},
        ) from exc


@router.post(
    "/api/template/library/{entry_id}/revert-fixed", response_model=TemplateBuildResponse
)
def revert_template_library_entry(entry_id: str) -> TemplateBuildResponse:
    """Undo the automatic switch to movable sections for one saved template: restore its
    fixed layout and keep it fixed. Refuses while a tailoring job is busy."""
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish before "
            "changing templates.",
        )
    try:
        return template_state.switched(template_library.revert_library_entry_to_fixed(entry_id))
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateBuildError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "log": exc.log},
        ) from exc


@router.patch("/api/template/library/{entry_id}", response_model=TemplateLibraryResponse)
def rename_template_library_entry(
    entry_id: str,
    body: TemplateLibraryRenameRequest,
) -> TemplateLibraryResponse:
    """Rename a saved template; labels must be unique (case-insensitive)."""
    try:
        return template_library.rename_library_entry(entry_id, body.label)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/template/library/{entry_id}/thumb.png")
def template_library_thumbnail(entry_id: str) -> FileResponse:
    """First page of a saved template's baseline, as a PNG for the gallery card."""
    try:
        path = template_preview.library_thumbnail(entry_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such saved template.") from exc
    except RuntimeError as exc:
        # PDF conversion unavailable (no Word / LibreOffice): the card shows a placeholder.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.delete("/api/template/library/{entry_id}", response_model=TemplateLibraryResponse)
def delete_template_library_entry(entry_id: str) -> TemplateLibraryResponse:
    """Delete a non-active library entry."""
    try:
        return template_library.delete_library_entry(entry_id)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/template/defaults", response_model=DefaultTemplatesResponse)
def get_default_templates() -> DefaultTemplatesResponse:
    """The built-in starter templates and whether each is already saved."""
    return template_defaults.list_defaults()


@router.post("/api/template/defaults/{name}/install", response_model=TemplateBuildResponse)
def install_default_template(name: str, calibrate: str | None = None) -> TemplateBuildResponse:
    """Make a built-in starter template the active template (`calibrate=true` tunes fit)."""
    if get_queue().busy():
        raise HTTPException(
            status_code=409,
            detail="A tailoring job is in progress; wait for it to finish before "
            "switching templates.",
        )
    try:
        return template_state.switched(
            template_defaults.install_default(name, do_calibrate=_truthy(calibrate))
        )
    except default_templates.UnknownTemplate as exc:
        raise HTTPException(status_code=404, detail="No such default template.") from exc
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateBuildError as exc:
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "log": exc.log}
        ) from exc


@router.get("/api/template/defaults/{name}/thumb.png")
def default_template_thumbnail(name: str) -> FileResponse:
    """First page of a starter template's design, as a PNG for the gallery card."""
    try:
        path = template_defaults.default_thumbnail(name)
    except default_templates.UnknownTemplate as exc:
        raise HTTPException(status_code=404, detail="No such default template.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")
