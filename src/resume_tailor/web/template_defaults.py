"""The bundled default templates: list, install and thumbnail."""

from __future__ import annotations

import hashlib
from pathlib import Path

from resume_tailor import config
from resume_tailor.document import (
    default_templates,
    thumbnails,
)
from resume_tailor.web.schemas import (
    DefaultTemplateOut,
    DefaultTemplatesResponse,
    TemplateBuildResponse,
)

from . import template_install, template_library, template_library_store, template_ops


# --- built-in default templates (P3-T) ---------------------------------------------
def list_defaults() -> DefaultTemplatesResponse:
    """The starter templates, each marked with its library entry when already saved.

    With several saved copies of one starter, the active copy wins, else the one
    ``install_default`` would reactivate (``_find_entry_by_sha``), so the card and the
    "Use" button always agree.
    """
    _active_id, _ = template_library_store._library_active_meta()
    metas = template_library_store._iter_library_metas()
    out = []
    for name in default_templates.names():
        spec = default_templates.design(name)
        sha = hashlib.sha256(default_templates.build(name)).hexdigest()
        copies = [meta for meta in metas if meta.get("sha256") == sha]
        meta = next((m for m in copies if m["id"] == _active_id), None) or (
            template_library_store._find_entry_by_sha(sha) if copies else None
        )
        out.append(
            DefaultTemplateOut(
                name=name,
                label=spec.label,
                description=spec.description,
                education_first=spec.education_first,
                library_id=meta["id"] if meta else None,
                is_active=bool(meta) and meta["id"] == _active_id,
            )
        )
    return DefaultTemplatesResponse(templates=out)

def _unused_label(label: str) -> str:
    candidate, n = label, 2
    while template_library_store._label_taken(candidate):
        candidate = f"{label} ({n})"
        n += 1
    return candidate

def install_default(name: str, *, do_calibrate: bool = False) -> TemplateBuildResponse:
    """Make default template ``name`` the active template.

    The baseline is built in memory (`default_templates.build`) and then installed
    exactly like an upload: analyze, `template_build`, verify, commit. When the library
    already holds this design (same bytes, same hash), that entry is activated instead
    of saving a second copy.

    Raises `default_templates.UnknownTemplate` for an unknown name.
    """
    raw, result = default_templates.analyzed(name)
    spec = default_templates.design(name)
    with template_ops.LOCK:
        existing = template_library_store._find_entry_by_sha(result.source_sha256)
    if existing is not None:
        return template_library.activate_library_entry(existing["id"], do_calibrate=do_calibrate)
    with template_ops.LOCK:
        label = _unused_label(spec.label)
    return template_install.install_baseline(
        raw,
        f"{name}.docx",
        profile=result.suggested_profile,
        do_calibrate=do_calibrate,
        label=label,
    )

def default_thumbnail(name: str) -> Path:
    """Cached first-page PNG of a default template's design (its sample content).

    Raises `default_templates.UnknownTemplate` for an unknown name and `RuntimeError`
    when no PDF engine is available.
    """
    raw = default_templates.build(name)
    digest = hashlib.sha256(raw).hexdigest()[:16]
    folder = config.OUTPUT_DIR / "template" / "defaults"
    folder.mkdir(parents=True, exist_ok=True)
    baseline = folder / f"{name}-{digest}.docx"
    with template_ops.LOCK:
        if not baseline.exists():
            baseline.write_bytes(raw)
        return thumbnails.docx_thumbnail(baseline, folder / f"{name}-{digest}.png")
