"""The template library on disk: index, entry metadata, snapshots, seeding and room."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from resume_tailor import config
from resume_tailor.content.labels import label_taken, normalize_label
from resume_tailor.document import (
    template_profile,
)
from resume_tailor.web.schemas import (
    TemplateLibraryEntry,
)

from . import template_ops


# ---------------------------------------------------------------------------
# Named template library
# ---------------------------------------------------------------------------
def _library_root() -> Path:
    """Return the library directory (creates it on demand)."""
    root = config.TEMPLATE_LIBRARY_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root

def _library_index_path() -> Path:
    """Path to the lightweight `{active_id}` index file."""
    return _library_root() / "index.json"

def _library_entry_dir(entry_id: str) -> Path:
    """Directory for one library snapshot."""
    return _library_root() / entry_id

def _read_library_index() -> dict:
    """Load `index.json`, or an empty active pointer when missing/corrupt."""
    path = _library_index_path()
    if not path.exists():
        return {"active_id": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active_id": None}
    if not isinstance(data, dict):
        return {"active_id": None}
    return {"active_id": data.get("active_id")}

def _write_library_index(*, active_id: str | None) -> None:
    """Persist the active library pointer."""
    path = _library_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"active_id": active_id}, indent=2) + "\n",
        encoding="utf-8",
    )

def _normalize_library_label(label: str) -> str:
    """Strip and validate a library label; raise TemplateValidationError if invalid."""
    try:
        return normalize_label(
            label, max_len=template_ops._LIBRARY_LABEL_MAX, what="Template label"
        )
    except ValueError as exc:
        raise template_ops.TemplateValidationError(str(exc)) from exc

def _default_label_from_filename(filename: str) -> str:
    """Derive a library label from an upload filename stem."""
    stem = Path(filename).stem.strip() or "Untitled"
    # Collapse runs of whitespace / underscores for a readable default.
    stem = re.sub(r"[\s_]+", " ", stem).strip()
    return _normalize_library_label(stem[:template_ops._LIBRARY_LABEL_MAX])

def _sha256_file(path: Path) -> str | None:
    """Return hex SHA-256 of a file, or None if it does not exist."""
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _new_library_id() -> str:
    """Allocate a filesystem-safe unique library entry id."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(2)}"

def _load_entry_meta(entry_id: str) -> dict | None:
    """Load `meta.json` for `entry_id`, or None if missing/invalid."""
    meta_path = _library_entry_dir(entry_id) / "meta.json"
    if not meta_path.exists():
        return None
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("id") != entry_id:
        return None
    return raw

def _iter_library_metas() -> list[dict]:
    """Return all valid entry metas, newest first."""
    root = _library_root()
    metas: list[dict] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        meta = _load_entry_meta(child.name)
        if meta is not None:
            metas.append(meta)
    metas.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return metas

def _library_active_meta() -> tuple[str | None, str | None]:
    """Return `(active_id, active_label)` from the index, or `(None, None)`."""
    active_id = _read_library_index().get("active_id")
    if not active_id:
        return None, None
    meta = _load_entry_meta(str(active_id))
    if meta is None:
        return None, None
    return str(active_id), str(meta.get("label") or active_id)

def _label_taken(label: str, *, except_id: str | None = None) -> bool:
    """True when another entry already uses `label` (case-insensitive)."""
    others = (
        str(meta.get("label") or "")
        for meta in _iter_library_metas()
        if not (except_id and meta.get("id") == except_id)
    )
    return label_taken(label, others)

def _entry_to_schema(meta: dict, *, active_id: str | None) -> TemplateLibraryEntry:
    """Build an API entry from on-disk meta."""
    entry_id = str(meta["id"])
    entry_dir = _library_entry_dir(entry_id)
    baseline = entry_dir / "original_export.docx"
    size = baseline.stat().st_size if baseline.exists() else None
    section_mode = _section_mode(entry_dir / "template_profile.json")
    return TemplateLibraryEntry(
        id=entry_id,
        label=str(meta.get("label") or entry_id),
        created_at=str(meta.get("created_at") or ""),
        source_filename=meta.get("source_filename"),
        size_bytes=size,
        has_profile=bool(meta.get("has_profile")),
        is_active=entry_id == active_id,
        section_mode=section_mode,
        can_revert_fixed=(
            section_mode == "generic" and (entry_dir / template_ops.FIXED_BACKUP_DIR).is_dir()
        ),
    )


def _section_mode(profile_file: Path) -> str | None:
    """The saved profile's `section_mode` (legacy profiles without one are fixed)."""
    try:
        raw = json.loads(profile_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(raw.get("section_mode") or "fixed")

def _snapshot_live_to_library(
    *,
    label: str,
    source_filename: str | None,
) -> dict:
    """Copy the live baseline/tagged/profile into a new library entry.

    Requires the live baseline and tagged template to exist. Caller must hold
    `LOCK` (or accept races) and have already validated label uniqueness / cap.
    """
    baseline = config.BASELINE_TEMPLATE_PATH
    tagged = config.DEFAULT_TEMPLATE_PATH
    if not baseline.exists():
        raise template_ops.TemplateValidationError("No live baseline to save into the library.")
    if not tagged.exists():
        raise template_ops.TemplateValidationError(
            "No tagged template to save; rebuild before adding to the library."
        )

    entry_id = _new_library_id()
    entry_dir = _library_entry_dir(entry_id)
    entry_dir.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(baseline, entry_dir / "original_export.docx")
        shutil.copy2(tagged, entry_dir / "main_template.docx")
        profile_file = template_profile.profile_path()
        has_profile = profile_file.exists()
        if has_profile:
            shutil.copy2(profile_file, entry_dir / "template_profile.json")
        sha = _sha256_file(entry_dir / "original_export.docx")
        meta = {
            "id": entry_id,
            "label": label,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source_filename": source_filename,
            "sha256": sha,
            "has_profile": has_profile,
        }
        (entry_dir / "meta.json").write_text(
            json.dumps(meta, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(entry_dir, ignore_errors=True)
        raise
    return meta

def _find_entry_by_sha(sha: str | None) -> dict | None:
    """Return the first library meta whose baseline sha256 matches `sha`."""
    if not sha:
        return None
    for meta in _iter_library_metas():
        if meta.get("sha256") == sha:
            return meta
    return None

def _library_seed_if_empty() -> None:
    """If the library is empty and a live baseline exists, register it as Default."""
    if _iter_library_metas():
        return
    if not config.BASELINE_TEMPLATE_PATH.exists():
        return
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        return
    meta = _snapshot_live_to_library(label="Default", source_filename=None)
    _write_library_index(active_id=meta["id"])

def _library_ensure_room_for_new(*, label: str) -> None:
    """Raise if the library cannot accept a new entry with `label`."""
    label = _normalize_library_label(label)
    if _label_taken(label):
        raise template_ops.TemplateValidationError(
            f"A saved template named “{label}” already exists. Choose another label."
        )
    if len(_iter_library_metas()) >= template_ops._LIBRARY_MAX_ENTRIES:
        raise template_ops.TemplateValidationError(
            f"Template library is full ({template_ops._LIBRARY_MAX_ENTRIES} saved). "
            "Delete one before installing another."
        )

def _library_preserve_orphan_live() -> None:
    """If live baseline bytes are not in the library, snapshot them before overwrite.

    Uses label ``Default`` when the library is empty, otherwise an ``Autosaved …``
    stamp. No-op when live is missing or already matched by sha256. Raises when the
    library is at capacity and the orphan cannot be saved.
    """
    if not config.BASELINE_TEMPLATE_PATH.exists():
        return
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        return
    sha = _sha256_file(config.BASELINE_TEMPLATE_PATH)
    if _find_entry_by_sha(sha) is not None:
        return
    metas = _iter_library_metas()
    if len(metas) >= template_ops._LIBRARY_MAX_ENTRIES:
        raise template_ops.TemplateValidationError(
            f"Template library is full ({template_ops._LIBRARY_MAX_ENTRIES} saved) and the "
            "current live template is not saved. Delete one before replacing."
        )
    label = "Default" if not metas else (
        f"Autosaved {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC"
    )
    # Disambiguate if the autosaved label somehow collides.
    base = label
    n = 2
    while _label_taken(label):
        label = f"{base} ({n})"
        n += 1
    # Do not change active_id — caller is about to replace live content.
    _snapshot_live_to_library(label=label, source_filename=None)
