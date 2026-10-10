"""Template library operations: list, rename, delete, activate, and record an install."""

from __future__ import annotations

import json
import shutil

import docx

from resume_tailor import config
from resume_tailor.document import calibration_cache
from resume_tailor.document import (
    template_profile,
)
from resume_tailor.web.schemas import (
    TemplateBuildResponse,
    TemplateLibraryResponse,
)

from . import (
    template_info,
    template_install,
    template_library_store,
    template_ops,
    template_preview,
)


def list_library() -> TemplateLibraryResponse:
    """Seed Default if needed, then return all named library entries."""
    with template_ops.LOCK:
        return _list_library()


def _list_library() -> TemplateLibraryResponse:
    """List/heal library state while the caller holds template_ops.LOCK."""
    template_library_store._library_seed_if_empty()
    active_id = template_library_store._read_library_index().get("active_id")
    entries = [
        template_library_store._entry_to_schema(m, active_id=active_id)
        for m in template_library_store._iter_library_metas()
    ]
    # If index points nowhere but we have entries matching live sha, heal active.
    if active_id is None and entries:
        sha = template_library_store._sha256_file(config.BASELINE_TEMPLATE_PATH)
        match = template_library_store._find_entry_by_sha(sha)
        if match is not None:
            active_id = match["id"]
            template_library_store._write_library_index(active_id=active_id)
            entries = [
                template_library_store._entry_to_schema(m, active_id=active_id)
                for m in template_library_store._iter_library_metas()
            ]
    return TemplateLibraryResponse(
        entries=entries,
        active_id=str(active_id) if active_id else None,
    )

def rename_library_entry(entry_id: str, label: str) -> TemplateLibraryResponse:
    """Rename a library entry; labels must stay unique (case-insensitive)."""
    cleaned = template_library_store._normalize_library_label(label)
    with template_ops.LOCK:
        meta = template_library_store._load_entry_meta(entry_id)
        if meta is None:
            raise template_ops.TemplateValidationError(f"Unknown template library id: {entry_id}")
        if template_library_store._label_taken(cleaned, except_id=entry_id):
            raise template_ops.TemplateValidationError(
                f"A saved template named “{cleaned}” already exists."
            )
        meta["label"] = cleaned
        meta_path = template_library_store._library_entry_dir(entry_id) / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return list_library()

def delete_library_entry(entry_id: str) -> TemplateLibraryResponse:
    """Delete a non-active library entry from disk."""
    with template_ops.LOCK:
        meta = template_library_store._load_entry_meta(entry_id)
        if meta is None:
            raise template_ops.TemplateValidationError(f"Unknown template library id: {entry_id}")
        active_id = template_library_store._read_library_index().get("active_id")
        if entry_id == active_id:
            raise template_ops.TemplateValidationError(
                "Cannot delete the active template. Activate another first."
            )
        shutil.rmtree(template_library_store._library_entry_dir(entry_id), ignore_errors=False)
    return list_library()

def activate_library_entry(
    entry_id: str,
    *,
    do_calibrate: bool = False,
) -> TemplateBuildResponse:
    """Copy a library snapshot into the live slot; optionally recalibrate.

    Preserves the current live set as a new library entry when its baseline sha is
    not already present. Does not re-run `build_template` — tagged files travel with
    the snapshot.
    """
    with template_ops.LOCK:
        meta = template_library_store._load_entry_meta(entry_id)
        if meta is None:
            raise template_ops.TemplateValidationError(f"Unknown template library id: {entry_id}")

        entry_dir = template_library_store._library_entry_dir(entry_id)
        src_baseline = entry_dir / "original_export.docx"
        src_tagged = entry_dir / "main_template.docx"
        src_profile = entry_dir / "template_profile.json"
        if not src_baseline.exists() or not src_tagged.exists():
            raise template_ops.TemplateValidationError(
                f"Library entry {entry_id} is incomplete (missing baseline or tagged)."
            )

        # Preserve orphan live content before overwrite (may raise if library full).
        template_library_store._library_preserve_orphan_live()

        baseline = config.BASELINE_TEMPLATE_PATH
        tagged = config.DEFAULT_TEMPLATE_PATH
        profile_file = template_profile.profile_path()
        baseline.parent.mkdir(parents=True, exist_ok=True)

        previous_baseline = baseline.read_bytes() if baseline.exists() else None
        previous_tagged = tagged.read_bytes() if tagged.exists() else None
        previous_profile = profile_file.read_bytes() if profile_file.exists() else None

        def _restore() -> None:
            """Roll live files back after a failed activate commit."""
            if previous_baseline is not None:
                baseline.write_bytes(previous_baseline)
            elif baseline.exists():
                baseline.unlink()
            if previous_tagged is not None:
                tagged.write_bytes(previous_tagged)
            elif tagged.exists():
                tagged.unlink()
            if previous_profile is not None:
                profile_file.write_bytes(previous_profile)
            elif profile_file.exists():
                profile_file.unlink()

        try:
            # Smoke-open the tagged snapshot before committing.
            docx.Document(str(src_tagged))
            calibration_cache.remember()
            shutil.copy2(src_baseline, baseline)
            shutil.copy2(src_tagged, tagged)
            if src_profile.exists():
                shutil.copy2(src_profile, profile_file)
            elif profile_file.exists():
                profile_file.unlink()
        except Exception as exc:
            _restore()
            raise template_ops.TemplateBuildError(
                f"Failed to activate library template: {exc}",
                log=str(exc),
            ) from exc

        template_library_store._write_library_index(active_id=entry_id)
        calibration_cache.activate()
        template_preview.invalidate_preview()
        log = f"Activated library template “{meta.get('label', entry_id)}” ({entry_id})."

    if do_calibrate:
        log = template_install._maybe_calibrate(log, do_calibrate=True)
    return TemplateBuildResponse(ok=True, log=log, info=template_info.info())

def revert_library_entry_to_fixed(entry_id: str) -> TemplateBuildResponse:
    """Restore the fixed-mode layout an entry had before it was switched to movable
    sections, and pin it so the startup migration never switches it again. An active
    entry is re-activated so the live template follows."""
    with template_ops.LOCK:
        meta = template_library_store._load_entry_meta(entry_id)
        if meta is None:
            raise template_ops.TemplateValidationError(f"Unknown template library id: {entry_id}")
        entry_dir = template_library_store._library_entry_dir(entry_id)
        backup = entry_dir / template_ops.FIXED_BACKUP_DIR
        if not backup.is_dir():
            raise template_ops.TemplateValidationError(
                "This template has no fixed layout to restore."
            )
        for item in backup.iterdir():
            shutil.copy2(item, entry_dir / item.name)
        (entry_dir / template_ops.FIXED_PIN_MARKER).touch()
        shutil.rmtree(backup)
        active_id, _ = template_library_store._library_active_meta()
        log = f"Restored the fixed layout of “{meta.get('label', entry_id)}”."
    if active_id == entry_id:
        activated = activate_library_entry(entry_id)
        return TemplateBuildResponse(ok=True, log=f"{log}\n{activated.log}", info=activated.info)
    return TemplateBuildResponse(ok=True, log=log, info=template_info.info())

def _library_record_after_install(*, label: str, source_filename: str) -> None:
    """Snapshot the just-installed live slot and mark it active."""
    cleaned = template_library_store._normalize_library_label(label)
    # Cap / uniqueness were checked before install; re-check in case of races.
    if template_library_store._label_taken(cleaned):
        # Install already committed — disambiguate rather than failing the install.
        base = cleaned
        n = 2
        while template_library_store._label_taken(cleaned):
            cleaned = f"{base} ({n})"
            n += 1
    if len(template_library_store._iter_library_metas()) >= template_ops._LIBRARY_MAX_ENTRIES:
        # Extremely unlikely after pre-check; skip snapshot rather than raise.
        return
    meta = template_library_store._snapshot_live_to_library(
        label=cleaned, source_filename=source_filename
    )
    template_library_store._write_library_index(active_id=meta["id"])
