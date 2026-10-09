"""Master resume read/write, validation, import and merge routes."""

from __future__ import annotations

import json
import logging
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import docx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from resume_tailor import config
from resume_tailor.content import bullet_tags, data, edu_dates, resume_versions
from resume_tailor.content.data import MasterResume
from resume_tailor.document import template_analyze
from resume_tailor.importing import (
    import_common,
    import_layout,
    import_merge,
    pdf_lines,
    resume_import,
    resume_import_pdf,
)
from resume_tailor.pipeline import tag_infer
from resume_tailor.web import skill_refresh, template_ops, template_uploads
from resume_tailor.web.schemas import (
    BulletSkillsResponse,
    MasterResumeImportResponse,
    MasterResumeMergeResponse,
    ValidateResponse,
)

router = APIRouter()
_log = logging.getLogger(__name__)


@router.get("/api/master-resume")
def get_master_resume() -> dict[str, Any]:
    """Return the current master resume as JSON for the editor.

    `sections`-shaped, matching what `PUT` writes — the editor speaks this format
    natively. `PUT` still accepts the pre-`sections` shape too (anything that never
    migrated), via `MasterResume._migrate_legacy_sections`'s before-validator.
    """
    try:
        resume = data.load()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # See the matching comment on `get_resume_outline`: bad user data, not a
        # server fault, and the editor is exactly where this needs to surface.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resume.model_dump(by_alias=True)


def _backup_master_resume(path: Path) -> Path | None:
    """Copy `path` to a timestamped `.bak.json` sibling if it exists, returning that
    backup's path (`None` if there was nothing to back up). Shared by
    `_write_master_resume` (`put_master_resume`/`merge_master_resume`, every save) and
    `approve_library_proposals` (only when approving would rewrite an existing tag) so
    all three use the identical naming."""
    if not path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(f".{stamp}.bak.json")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def _write_master_resume(resume: MasterResume, note: str = "") -> Path | None:
    """Back up the previous file (if any) and write `resume` to
    `config.MASTER_RESUME_PATH`, returning the backup's path. Shared by
    `put_master_resume`, `merge_master_resume` and `restore_master_resume_version` so
    the write+backup path is defined once.

    Also records the version history (`resume_versions`): first the file as it was, if
    it was edited outside the app since the last recorded save, then the new text. A
    history failure is logged and never fails the save itself.
    """
    path = config.MASTER_RESUME_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _record_version(None)
    backup = _backup_master_resume(path)

    # Structured education months for application forms, read from the printed dates
    # where the student left them empty (`edu_dates`).
    for education in resume.education:
        edu_dates.fill(education)
    # Round-trip through the model so tags are canonicalised and unknown keys stripped
    # before anything hits disk — same guarantees `data.load` enforces on the way in.
    payload = resume.model_dump(by_alias=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    _record_version(text, note)
    skill_refresh.schedule(resume)
    return backup


def _record_version(text: str | None, note: str = "") -> None:
    """`resume_versions.record` (or `sync_external` for ``None``), never raising."""
    try:
        if text is None:
            resume_versions.sync_external()
        else:
            resume_versions.record(text, note)
    except Exception:  # noqa: BLE001 - history is a convenience; the save must land
        _log.warning("could not record master resume version", exc_info=True)


@router.put("/api/master-resume")
def put_master_resume(body: dict[str, Any]) -> ValidateResponse:
    """Validate and save a new master resume, keeping a timestamped backup of the old one.

    A rejected write is a 400, matching the sibling `merge_master_resume` route — a
    mutating route reporting "wrote nothing" as HTTP 200 is exactly the case a caller
    is least likely to check for. The write itself is held under `template_ops.LOCK`:
    `_write_master_resume` resolves `config.MASTER_RESUME_PATH` at call time, which
    `activate_workspace` rebinds under the same lock — without it, a save racing a
    profile switch can land in the *new* workspace's file instead of the one the user
    was actually editing.
    """
    try:
        resume = MasterResume.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            ),
        ) from exc

    with template_ops.LOCK:
        _write_master_resume(resume, note="saved in the editor")

    bullets = resume.all_bullets()
    tags = sorted({t for b in bullets for t in b.tags})
    return ValidateResponse(
        ok=True,
        summary={
            "name": resume.contact.name,
            "experience": len(resume.experience),
            "projects": len(resume.projects),
            "bullets": len(bullets),
            "tags": len(tags),
        },
    )


@router.get("/api/master-resume/versions")
def list_master_resume_versions() -> dict[str, Any]:
    """Saved versions, newest first (see `resume_versions`)."""
    with template_ops.LOCK:
        return {"versions": resume_versions.list_versions(), "keep": resume_versions.KEEP}


@router.post("/api/master-resume/restore/{version}")
def restore_master_resume_version(version: int) -> dict[str, Any]:
    """Write an earlier version back as the current master resume (itself a new version,
    so a restore can be undone the same way)."""
    with template_ops.LOCK:
        text = resume_versions.text_of(version)
        if text is None:
            raise HTTPException(status_code=404, detail=f"Version {version} is not kept.")
        try:
            resume = MasterResume.model_validate_json(text)
        except ValidationError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Version {version} no longer validates against the current format.",
            ) from exc
        _write_master_resume(resume, note=f"restored version {version}")
    return {"resume": resume.model_dump(by_alias=True), "restored": version}


@router.get("/api/master-resume/skills", response_model=BulletSkillsResponse)
def get_bullet_skills() -> BulletSkillsResponse:
    """The skills each saved bullet shows beyond its Extra skills — detected in the text
    and inferred by the model — plus whether a background refresh is still running.
    Reads only: no model call (`skill_refresh` fills the cache after every save)."""
    running, error = skill_refresh.status()
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError):
        return BulletSkillsResponse(running=running, error=error)
    extra = bullet_tags.resume_terms(resume)
    try:
        with skill_refresh.pinned_tailor():
            inferred = tag_infer.cached(resume).skills
    except ValueError:  # unusable routing settings: show detection alone
        inferred = {}
    bullets: dict[str, list[str]] = {}
    waiting = 0
    for bullet in resume.all_bullets():
        have = {config.canonical_tag(t) for t in bullet.tags}
        shown: dict[str, str] = {}
        for canonical, surface in bullet_tags.detect(bullet.text, extra):
            shown.setdefault(canonical, surface)
        if bullet.text not in inferred:
            waiting += 1
        for skill in inferred.get(bullet.text, []):
            shown.setdefault(config.canonical_tag(skill), skill)
        bullets[bullet.id] = [s for c, s in shown.items() if c not in have]
    return BulletSkillsResponse(running=running, error=error, waiting=waiting, bullets=bullets)


@router.post("/api/master-resume/validate", response_model=ValidateResponse)
def validate_master_resume(body: dict[str, Any]) -> ValidateResponse:
    """Dry-run validation for the editor — does not write anything."""
    try:
        resume = MasterResume.model_validate(body)
    except ValidationError as exc:
        return ValidateResponse(
            ok=False,
            errors=[f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()],
        )

    bullets = resume.all_bullets()
    tags = sorted({t for b in bullets for t in b.tags})
    return ValidateResponse(
        ok=True,
        summary={
            "name": resume.contact.name,
            "experience": len(resume.experience),
            "projects": len(resume.projects),
            "bullets": len(bullets),
            "metrics": sum(1 for b in bullets if b.metric),
            "tags": len(tags),
        },
    )


@router.post("/api/master-resume/import", response_model=MasterResumeImportResponse)
def import_master_resume(
    file: UploadFile = File(...),
    use_model: str | None = Form(None),
) -> MasterResumeImportResponse:
    """Parse an uploaded .docx or PDF into a `MasterResume` draft — content, not just layout.

    A PDF (by extension or its ``%PDF`` signature) goes through `resume_import_pdf`;
    truthy `use_model` adds that module's guarded model-assisted structuring pass,
    pinned to `config.ONE_OFF_PROFILE` (`config.pinned`) — not a tailoring job, so it
    never touches `config._ACTIVE` or falls through to `backend_for`'s claude default.

    Writes nothing: the editor loads the result as unsaved state and the user saves
    through the existing `PUT /api/master-resume`, same as a hand edit. Bullets carry no
    Extra skills; the skills they show are computed at run time (`bullet_tags`).

    A plain `def`, not `async def`: this does real work synchronously (docx parsing,
    structural analysis, and — with `use_model` — a live blocking LLM call), so FastAPI
    must run it in its threadpool rather than on the event loop, or every other request
    (including any open SSE stream) stalls for the duration.
    """
    raw = file.file.read()
    filename = file.filename or "upload.docx"
    known_tags = import_common._default_vocabulary()
    # brand-new workspace with no master resume yet
    with suppress(FileNotFoundError, ValueError):
        known_tags |= set(data.load().tag_vocabulary)
    if filename.lower().endswith(".pdf") or raw[:5] == b"%PDF-":
        imported = _import_pdf(raw, known_tags, _truthy(use_model))
    else:
        imported = _import_docx(raw, filename, known_tags)
    return MasterResumeImportResponse(
        resume=imported.resume.model_dump(by_alias=True), warnings=imported.warnings
    )


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _import_pdf(raw: bytes, known_tags: set[str], use_model: bool) -> import_common.ImportedResume:
    if not raw:
        raise HTTPException(status_code=400, detail="Upload is empty.")
    if len(raw) > template_ops._MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload is {len(raw)} bytes; maximum is {template_ops._MAX_UPLOAD_BYTES}.",
        )
    try:
        with config.pinned(config.ONE_OFF_PROFILE):
            return resume_import_pdf.import_pdf(raw, known_tags=known_tags, use_model=use_model)
    except pdf_lines.PdfImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _import_docx(raw: bytes, filename: str, known_tags: set[str]) -> import_common.ImportedResume:
    """Content import from a Word file. The upload is converted/cleaned first; typed
    bullets always become a list here (it is a private copy, never a template). A layout
    that can't become a template is still read, in reading order."""
    try:
        prepared = template_uploads.prepare_upload(raw, filename, convert_bullets=True)
        raw, filename = prepared.raw, prepared.filename
        template_uploads._validate_upload_bytes(raw, filename)
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            try:
                doc = docx.Document(str(tmp_path))
            except Exception as exc:
                raise template_ops.TemplateValidationError(
                    f"File is not a readable .docx: {exc}"
                ) from exc
            result = template_analyze.analyze_docx(raw=raw)
            if any(
                i.blocking and i.code in import_layout.LAYOUT_BLOCKERS for i in result.issues
            ):
                imported = import_layout.import_content_only(doc, known_tags=known_tags)
            else:
                imported = resume_import.import_from_analysis(result, doc, known_tags=known_tags)
            imported.warnings[:0] = [n.message for n in prepared.notices]
            return imported
        finally:
            tmp_path.unlink(missing_ok=True)
    except template_ops.TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/master-resume/merge", response_model=MasterResumeMergeResponse)
def merge_master_resume(body: dict[str, Any]) -> MasterResumeMergeResponse:
    """Fold an already-parsed draft (typically the `.resume` from `POST
    /api/master-resume/import`) into the current master resume and save the result.

    Unlike `PUT`, entries/sections in the current resume with no counterpart in `body`
    are left untouched rather than replaced — see `import_merge.merge_into` for the
    matching rules. A workspace with no master resume yet merges against an empty one
    (contact seeded from `body`), the same tolerance `import_master_resume` already
    applies to `data.load()` failing.

    The read-merge-write sequence runs entirely under `template_ops.LOCK`, not just the
    final write: `data.load()` and `_write_master_resume` both resolve `config`'s
    rebindable path globals, and a workspace switch landing between the read and the
    write would merge workspace A's existing content with the incoming draft and save
    the result into workspace B's file.
    """
    try:
        incoming = MasterResume.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            ),
        ) from exc

    with template_ops.LOCK:
        try:
            existing = data.load()
        except (FileNotFoundError, ValueError):
            existing = MasterResume(contact=incoming.contact, sections=[])

        merged, stats = import_merge.merge_into(existing, incoming)
        backup = _write_master_resume(merged, note="merged an import")

    return MasterResumeMergeResponse(
        resume=merged.model_dump(by_alias=True),
        updated=stats.updated,
        added=stats.added,
        added_sections=stats.added_sections,
        warnings=stats.warnings,
        backup=backup.name if backup else None,
    )
