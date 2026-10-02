"""Template previews: cached live/library previews and upload-draft previews."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import (
    render,
    template_build,
    template_profile,
    thumbnails,
)
from resume_tailor.document.template_profile import TemplateProfile

from . import template_info, template_library_store, template_ops, template_uploads


def ensure_preview() -> Path:
    """Render the full master resume through the tagged template and return its PDF path.

    Regenerates when the cached PDF is missing or older than **either** of its two
    inputs. Raises `RuntimeError` when PDF conversion is unavailable so the route can
    return 503 instead of a broken frame.
    """
    with template_ops.LOCK:
        tagged = config.DEFAULT_TEMPLATE_PATH
        if not tagged.exists():
            raise FileNotFoundError(
                f"Tagged template not found: {tagged}. "
                "Upload a baseline or run `python scripts/build_template.py`."
            )

        docx_path, pdf_path = template_info._preview_paths()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # The preview is the master resume rendered *through* the tagged template, so
        # both files are inputs. Keying staleness on the template alone meant editing
        # the resume never invalidated the cache — the Template tab kept serving the
        # pre-edit PDF indefinitely, including after an explicit Refresh. Checking
        # mtime (rather than having the editor call `invalidate_preview`) also covers
        # a master_resume.json edited by hand or by the CLI.
        newest_input = max(
            (p.stat().st_mtime for p in (tagged, config.MASTER_RESUME_PATH) if p.exists()),
            default=0.0,
        )
        needs_render = (
            not pdf_path.exists()
            or not docx_path.exists()
            or newest_input > pdf_path.stat().st_mtime
        )
        if not needs_render:
            return pdf_path

        resume = data.load()
        render.render(resume, out=docx_path)
        # Propagate RuntimeError from convert so the UI can say "no PDF backend".
        render.to_pdf(docx_path, pdf_path)
        return pdf_path

def library_thumbnail(entry_id: str) -> Path:
    """Cached first-page PNG of a saved template's baseline export (the gallery card).

    Raises `FileNotFoundError` for an unknown entry and `RuntimeError` when no PDF
    engine is available (the card then shows a placeholder).
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", entry_id):
        raise FileNotFoundError(entry_id)
    with template_ops.LOCK:
        if template_library_store._load_entry_meta(entry_id) is None:
            raise FileNotFoundError(entry_id)
        entry_dir = template_library_store._library_entry_dir(entry_id)
        return thumbnails.docx_thumbnail(
            entry_dir / "original_export.docx", entry_dir / "thumb.png"
        )

def invalidate_preview() -> None:
    """Delete the cached preview so the next `ensure_preview` regenerates it."""
    docx_path, pdf_path = template_info._preview_paths()
    for path in (docx_path, pdf_path):
        if path.exists():
            path.unlink()

def preview_source(source_sha256: str) -> Path:
    """Convert a previously uploaded (not-yet-installed) baseline to PDF, for the
    wizard's side-by-side comparison. Raises `RuntimeError` when no PDF backend is
    available, matching `ensure_preview`'s contract for the same 503 the route returns."""
    raw = template_uploads._load_cached_upload(source_sha256)
    directory = template_uploads._upload_cache_dir()
    docx_path = directory / f"{source_sha256}.source.docx"
    pdf_path = directory / f"{source_sha256}.source.pdf"
    # Keyed by the upload's own sha256, so the source bytes for a given path can never
    # change underneath it — an existing PDF here is never stale, unlike `ensure_preview`'s
    # mtime check (which exists only because *that* cache's docx input can be re-rendered
    # in place from an edited master resume).
    if pdf_path.exists():
        return pdf_path
    docx_path.write_bytes(raw)
    with template_ops.LOCK:
        render.to_pdf(docx_path, pdf_path)
    return pdf_path

def preview_draft(source_sha256: str, profile: TemplateProfile | dict) -> Path:
    """Build a staged profile into a temp tagged template and render the master resume
    through it, without touching the live template slot — lets the wizard show what
    installing this exact mapping would produce before committing to it.

    Runs the same build `_install_with_profile` does, minus the atomic commit: no
    baseline/tagged/profile file under `templates/` is ever written or replaced.
    """
    confirmed = (
        profile if isinstance(profile, TemplateProfile) else TemplateProfile.model_validate(profile)
    )
    raw = template_uploads._load_cached_upload(source_sha256)

    directory = template_uploads._upload_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with template_ops.LOCK, tempfile.TemporaryDirectory() as stage_dir:
        stage = Path(stage_dir)
        staged_src = stage / "baseline.docx"
        staged_tagged = stage / "main_template.docx"
        staged_src.write_bytes(raw)
        # `build_from_profile` raises plain `RuntimeError` for every mapping problem
        # (a missing field, a paragraph id out of range, …) — indistinguishable, to a
        # bare `except RuntimeError`, from `render.to_pdf` below genuinely having no
        # PDF backend available. Re-raising as `TemplateBuildError` (unlike
        # `_install_with_profile`'s equivalent wrap, this one only wraps the build
        # call, not the render/PDF steps) lets the route tell "your mapping is
        # incomplete" from "install LibreOffice" apart.
        try:
            template_build.build_from_profile(staged_src, staged_tagged, confirmed)
        except Exception as exc:
            raise template_ops.TemplateBuildError(
                f"Draft build failed: {exc}", log=str(exc)
            ) from exc

        docx_path = directory / f"{source_sha256}.draft.docx"
        pdf_path = directory / f"{source_sha256}.draft.pdf"
        render.render(
            data.load(),
            template=staged_tagged,
            out=docx_path,
            layout=template_profile.active_layout(confirmed),
        )
        render.to_pdf(docx_path, pdf_path)
    return pdf_path
