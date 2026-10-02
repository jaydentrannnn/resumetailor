"""Template uploads: validation, the upload cache, analysis and remapping."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import docx

from resume_tailor import config
from resume_tailor.document import (
    analysis_types,
    docx_normalize,
    template_analyze,
)
from resume_tailor.web.schemas import (
    TemplateAnalyzeResponse,
    TemplateFieldCandidateOut,
    TemplateIssueOut,
    TemplateParagraphOut,
    TemplateSectionOut,
)

from . import template_ops


def _validate_upload_bytes(raw: bytes, filename: str) -> None:
    """Raise TemplateValidationError for bad extension, size, or empty payload."""
    name = Path(filename).name
    if not name.lower().endswith(".docx"):
        raise template_ops.TemplateValidationError("Upload must be a .docx file.")
    if len(raw) > template_ops._MAX_UPLOAD_BYTES:
        raise template_ops.TemplateValidationError(
            f"Upload is {len(raw)} bytes; maximum is {template_ops._MAX_UPLOAD_BYTES}."
        )
    if not raw:
        raise template_ops.TemplateValidationError("Upload is empty.")

def _upload_cache_dir() -> Path:
    """Directory holding uploaded bytes for the wizard's remap/preview steps.

    Keyed by the upload's own sha256 so the remap and preview endpoints never need to
    re-upload the file — the wizard already sent it once, to `/analyze`. Lives under
    the active workspace's own `output/` root (via `config.OUTPUT_DIR`, one of the
    globals `set_active_workspace` rebinds), so switching profiles never leaks one
    workspace's in-progress upload into another's.
    """
    return config.OUTPUT_DIR / "template" / "uploads"

def _prune_upload_cache(*, max_age_seconds: float = 24 * 3600) -> None:
    """Delete cached uploads older than `max_age_seconds`.

    A wizard session that is abandoned mid-flow (tab closed after analyze, before
    install or reset) would otherwise leak its upload forever; this runs opportunistically
    whenever a new upload is cached, which is cheap and frequent enough that unbounded
    growth never accumulates.

    Globs every file, not just `*.docx`: `preview_source`/`preview_draft` also cache
    rendered `{sha}.source.pdf`/`{sha}.draft.pdf` alongside the upload in this same
    directory, and a `*.docx`-only glob left those — the largest, most PII-dense
    artifacts here — never aged out. `entry.unlink()` on something that isn't a
    plain file (there shouldn't be any) raises `OSError`, already caught below.
    """
    directory = _upload_cache_dir()
    if not directory.exists():
        return
    cutoff = datetime.now(UTC).timestamp() - max_age_seconds
    for entry in directory.glob("*"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            pass

def _cache_upload(raw: bytes, sha: str, *, origin_sha: str | None = None) -> None:
    """Persist an analyzed upload's bytes for later remap/preview calls.

    `origin_sha` is the hash of the file as the user uploaded it, before `prepare`
    converted or cleaned it. Install looks the prepared bytes up by it, because a
    LibreOffice conversion is not byte-for-byte repeatable.
    """
    _prune_upload_cache()
    directory = _upload_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{sha}.docx").write_bytes(raw)
    if origin_sha and origin_sha != sha:
        (directory / f"{sha}.origin").write_text(origin_sha, encoding="ascii")

def _prepared_for(raw: bytes, sha: str) -> bytes | None:
    """The cached prepared upload `sha`, if it was made from exactly these bytes."""
    directory = _upload_cache_dir()
    origin = directory / f"{sha}.origin"
    path = directory / f"{sha}.docx"
    if not re.fullmatch(r"[0-9a-f]{64}", sha or "") or not origin.exists() or not path.exists():
        return None
    if origin.read_text(encoding="ascii").strip() != hashlib.sha256(raw).hexdigest():
        return None
    return path.read_bytes()

def prepare_upload(raw: bytes, filename: str, *, convert_bullets: bool = False):
    """`docx_normalize.prepare`, with its errors as `TemplateValidationError`."""
    if len(raw) > template_ops._MAX_UPLOAD_BYTES:
        raise template_ops.TemplateValidationError(
            f"Upload is {len(raw)} bytes; maximum is {template_ops._MAX_UPLOAD_BYTES}."
        )
    try:
        return docx_normalize.prepare(raw, filename, convert_bullets=convert_bullets)
    except docx_normalize.UploadFormatError as exc:
        raise template_ops.TemplateValidationError(str(exc)) from exc

def _load_cached_upload(sha: str) -> bytes:
    """Load a previously analyzed upload's bytes by its sha256.

    Raises `TemplateValidationError` (400, not 404/500) when the cache has expired or
    the wizard is pointing at a sha that was never analyzed — both are "start over",
    the same class of problem as a bad upload.
    """
    directory = _upload_cache_dir()
    path = directory / f"{sha}.docx"
    # Defense in depth: every caller today reaches `sha` through a schema field
    # already pattern-constrained to a bare hex digest (`web/schemas.py`'s
    # `_SHA256_HEX_PATTERN`), which cannot contain `/` or `..`. This second check
    # means a future caller that skips that schema still cannot escape the cache
    # directory, since `pathlib` itself does not normalise `..`.
    if directory.resolve() not in path.resolve().parents:
        raise template_ops.TemplateValidationError(
            "This upload is no longer available for preview/remap — analyze the file "
            "again."
        )
    if not path.exists():
        raise template_ops.TemplateValidationError(
            "This upload is no longer available for preview/remap — analyze the file "
            "again."
        )
    return path.read_bytes()

def clear_upload_cache() -> None:
    """Drop every cached upload — called after a successful install, once the wizard's
    staged file has become the live template and has no further use as a cache entry."""
    directory = _upload_cache_dir()
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)

def _analysis_to_response(result: analysis_types.AnalyzeResult) -> TemplateAnalyzeResponse:
    """Shared `AnalyzeResult` -> wire-shape conversion for `analyze_upload`/`remap_upload`."""
    return TemplateAnalyzeResponse(
        source_sha256=result.source_sha256,
        paragraphs=[
            TemplateParagraphOut(**p.model_dump()) for p in result.paragraphs
        ],
        sections=[TemplateSectionOut(**s.model_dump()) for s in result.sections],
        field_candidates=[
            TemplateFieldCandidateOut(
                field=c.field,
                paragraph_id=c.span.paragraph_id,
                start=c.span.start,
                end=c.span.end,
                confidence=c.confidence,
                preview=c.preview,
                section_heading_paragraph_id=c.section_heading_paragraph_id,
            )
            for c in result.field_candidates
        ],
        suggested_profile=(
            result.suggested_profile.model_dump(mode="json")
            if result.suggested_profile is not None
            else None
        ),
        issues=[TemplateIssueOut(**i.model_dump()) for i in result.issues],
        ready=result.ready,
    )

def analyze_upload(
    raw: bytes, filename: str, *, convert_bullets: bool = False
) -> TemplateAnalyzeResponse:
    """Analyse an uploaded DOCX without writing under templates/.

    The upload is converted/cleaned first (`docx_normalize.prepare`); what it changed is
    reported as non-blocking issues, and the cleaned bytes are what gets cached.
    """
    origin_sha = hashlib.sha256(raw).hexdigest()
    prepared = prepare_upload(raw, filename, convert_bullets=convert_bullets)
    raw, filename = prepared.raw, prepared.filename
    _validate_upload_bytes(raw, filename)
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        try:
            docx.Document(str(tmp_path))
        except Exception as exc:
            raise template_ops.TemplateValidationError(
                f"File is not a readable .docx: {exc}"
            ) from exc
        result = template_analyze.analyze_docx(raw=raw)
    finally:
        tmp_path.unlink(missing_ok=True)

    _cache_upload(raw, result.source_sha256, origin_sha=origin_sha)
    result = result.model_copy(update={"issues": [*prepared.notices, *result.issues]})
    return _analysis_to_response(result)

def remap_upload(source_sha256: str, overrides: dict[int, str | None]) -> TemplateAnalyzeResponse:
    """Re-run analysis on a previously uploaded file with specific headings' kinds
    forced by the user, bypassing every heuristic gate for just those paragraphs (see
    `template_analyze._analyze_document`'s `overrides` parameter)."""
    raw = _load_cached_upload(source_sha256)
    result = template_analyze.analyze_docx(raw=raw, overrides=overrides)
    return _analysis_to_response(result)
