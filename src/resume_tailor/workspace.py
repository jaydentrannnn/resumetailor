"""Workspace ("Profile") registry: master resume, templates, calibration, and settings,
switched together as a single unit.

A workspace is a self-contained directory tree replicated under each storage root
(`config.workspace_paths`): `data/workspaces/<id>/`, `templates/workspaces/<id>/`,
`output/workspaces/<id>/`. Switching workspaces means rebinding `config`'s path globals
via `config.set_active_workspace` — every module downstream resolves paths through
`config.X` attribute access, so nothing else needs to change.

This module is core, not web: `tailor.py`, `scripts/build_template.py`, and
`scripts/calibrate.py` all call `bootstrap()` directly, so it must never import
`resume_tailor.web`. The web layer (`web/app.py`) calls the functions here and maps
them onto HTTP routes; it owns the `JobQueue.busy()` / `template_ops.LOCK` guards that
must be held before `activate()`, `create(copy_from=...)`, or `delete()` — this module
only serialises against its own concurrent registry writes via `_LOCK`.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from resume_tailor import config
from resume_tailor.labels import label_taken, normalize_label

#: Serialises registry mutations (create/rename/delete/activate) against each other.
#: Does NOT serialise against Word/LibreOffice — callers needing that also take
#: `template_ops.LOCK`, always acquired before this one.
_LOCK = threading.Lock()

_LABEL_MAX = 80
_DEFAULT_ID = "default"
_DEFAULT_LABEL = "Default"


class WorkspaceError(ValueError):
    """Raised for an unknown id, a duplicate label, or a refused delete."""


@dataclass(frozen=True)
class WorkspaceEntry:
    """One row of the registry, plus cheap on-disk presence checks for the UI."""

    id: str
    label: str
    created_at: str
    is_active: bool = False
    has_master_resume: bool = False
    has_template: bool = False


@dataclass(frozen=True)
class BootstrapResult:
    active_id: str
    #: True only on the call that performed the legacy-layout migration.
    migrated: bool
    log: str = ""


# --------------------------------------------------------------------------------------
# Registry I/O
# --------------------------------------------------------------------------------------


def _registry_root() -> Path:
    root = config.DATA_ROOT / config.WORKSPACES_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path() -> Path:
    return _registry_root() / "index.json"


def _meta_path(workspace_id: str) -> Path:
    return config.workspace_paths(workspace_id)["DATA_DIR"] / "workspace.json"


def read_index() -> dict:
    """Load `index.json`, healing from per-workspace `workspace.json` files if it is
    missing, unreadable, or malformed.

    A workspace spans three storage roots, so it cannot be re-enumerated by scanning
    one directory the way the template library can — `workspace.json` inside each
    workspace's data dir is what makes the registry recoverable if `index.json` is
    lost or corrupted.
    """
    path = _index_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
            return raw
    return _rebuild_index()


def _rebuild_index() -> dict:
    root = _registry_root()
    entries: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / "workspace.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict) or meta.get("id") != child.name:
            continue
        entries.append(
            {
                "id": meta["id"],
                "label": str(meta.get("label") or meta["id"]),
                "created_at": str(meta.get("created_at") or ""),
            }
        )
    index = {"active_id": entries[0]["id"] if entries else None, "entries": entries}
    if entries:
        write_index(index)
    return index


def write_index(index: dict) -> None:
    """Persist the registry atomically: write a temp file, then `os.replace`."""
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _find_entry(index: dict, workspace_id: str) -> dict:
    for entry in index.get("entries", []):
        if entry.get("id") == workspace_id:
            return entry
    raise WorkspaceError(f"Unknown profile: {workspace_id!r}")


def _entry_from_meta(meta: dict, *, active_id: str | None) -> WorkspaceEntry:
    workspace_id = str(meta["id"])
    paths = config.workspace_paths(workspace_id)
    return WorkspaceEntry(
        id=workspace_id,
        label=str(meta.get("label") or workspace_id),
        created_at=str(meta.get("created_at") or ""),
        is_active=workspace_id == active_id,
        has_master_resume=paths["MASTER_RESUME_PATH"].exists(),
        has_template=paths["DEFAULT_TEMPLATE_PATH"].exists(),
    )


def _slugify(label: str) -> str:
    return config.slugify(label)


def new_workspace_id(label: str, *, existing: Iterable[str]) -> str:
    """A filesystem-friendly id derived from `label`.

    These directories are bind-mounted and browsed by hand, so `swe-newgrad` beats
    an opaque timestamp+hex id. A random suffix is appended only on collision (or
    when the label slugs to nothing), and the id never changes on a later rename.
    """
    existing_set = set(existing)
    base = _slugify(label) or "profile"
    if base not in existing_set:
        return base
    candidate = f"{base}-{secrets.token_hex(2)}"
    while candidate in existing_set:
        candidate = f"{base}-{secrets.token_hex(2)}"
    return candidate


# --------------------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------------------


def list_workspaces() -> list[WorkspaceEntry]:
    index = read_index()
    active_id = index.get("active_id")
    return [_entry_from_meta(e, active_id=active_id) for e in index.get("entries", [])]


def resolve(workspace_id: str) -> WorkspaceEntry:
    """Look up a workspace by id, raising `WorkspaceError` if it is not registered."""
    index = read_index()
    entry = _find_entry(index, workspace_id)
    return _entry_from_meta(entry, active_id=index.get("active_id"))


def _write_meta(workspace_id: str, meta: dict) -> None:
    path = _meta_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def _write_default_settings(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "defaults": {}}, indent=2) + "\n",
        encoding="utf-8",
    )


#: Smallest structurally valid `MasterResume`: `contact` is the only required field, and
#: within it only `name` and `email` lack defaults. Everything else is an empty list the
#: user fills in from the Master resume tab.
_STARTER_RESUME = {
    "contact": {"name": "Your Name", "email": "you@example.com"},
    "education": [],
    "experience": [],
    "projects": [],
    "skills": [],
    "tag_vocabulary": [],
}


def ensure_master_resume(workspace_id: str | None = None) -> bool:
    """Write a placeholder `master_resume.json` if the workspace has none. Returns True
    if one was written.

    A workspace without this file is broken in three separate places — the editor 404s,
    `template_ops._smoke_render` (and therefore every template install) raises
    `FileNotFoundError`, and a tailoring run cannot start — so a profile created without
    `copy_from` has to start with *something* loadable rather than nothing. Only ever
    writes when the file is absent, so it can never clobber real content.
    """
    path = (
        config.MASTER_RESUME_PATH
        if workspace_id is None
        else config.workspace_paths(workspace_id)["MASTER_RESUME_PATH"]
    )
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_STARTER_RESUME, indent=2) + "\n", encoding="utf-8")
    return True


def _copy_workspace_files(source: dict[str, Path], dest: dict[str, Path]) -> None:
    """Duplicate one workspace's content into another's (already-created) directories.

    Copies the master resume, settings, the live template trio, the template library,
    template backups, and calibration. LLM caches (`CACHE_DIR`) are deliberately not
    copied — they are regenerable, and a cache miss costs at most one extra call.
    """
    if source["MASTER_RESUME_PATH"].exists():
        shutil.copy2(source["MASTER_RESUME_PATH"], dest["MASTER_RESUME_PATH"])
    if source["SETTINGS_PATH"].exists():
        shutil.copy2(source["SETTINGS_PATH"], dest["SETTINGS_PATH"])
    else:
        _write_default_settings(dest["SETTINGS_PATH"])
    for key in ("BASELINE_TEMPLATE_PATH", "DEFAULT_TEMPLATE_PATH", "TEMPLATE_PROFILE_PATH"):
        if source[key].exists():
            shutil.copy2(source[key], dest[key])
    if source["TEMPLATE_LIBRARY_DIR"].exists():
        shutil.copytree(
            source["TEMPLATE_LIBRARY_DIR"], dest["TEMPLATE_LIBRARY_DIR"], dirs_exist_ok=True
        )
    source_backups = source["BASELINE_TEMPLATE_PATH"].parent / "backups"
    if source_backups.exists():
        dest_backups = dest["BASELINE_TEMPLATE_PATH"].parent / "backups"
        shutil.copytree(source_backups, dest_backups, dirs_exist_ok=True)
    if source["CALIBRATION_DIR"].exists():
        shutil.copytree(source["CALIBRATION_DIR"], dest["CALIBRATION_DIR"], dirs_exist_ok=True)


def create(label: str, *, copy_from: str | None = None) -> WorkspaceEntry:
    """Register a new, empty workspace, or a duplicate of `copy_from`.

    Caller is responsible for the `JobQueue.busy()` / `template_ops.LOCK` guard when
    `copy_from` is set — this reads another workspace's live template files.
    """
    cleaned = normalize_label(label, max_len=_LABEL_MAX, what="Profile name")
    with _LOCK:
        index = read_index()
        entries = index.get("entries", [])
        if label_taken(cleaned, (e["label"] for e in entries)):
            raise WorkspaceError(f"A profile named {cleaned!r} already exists.")
        if copy_from is not None:
            _find_entry(index, copy_from)  # raises if the source is unknown

        workspace_id = new_workspace_id(cleaned, existing=(e["id"] for e in entries))
        paths = config.workspace_paths(workspace_id)
        for key in ("DATA_DIR", "TEMPLATES_DIR", "OUTPUT_DIR", "CACHE_DIR"):
            paths[key].mkdir(parents=True, exist_ok=True)

        if copy_from is not None:
            _copy_workspace_files(config.workspace_paths(copy_from), paths)
        else:
            _write_default_settings(paths["SETTINGS_PATH"])
        # Also covers a duplicate whose *source* had no master resume.
        ensure_master_resume(workspace_id)

        meta = {
            "id": workspace_id,
            "label": cleaned,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _write_meta(workspace_id, meta)

        entries.append(meta)
        index["entries"] = entries
        write_index(index)
        return _entry_from_meta(meta, active_id=index.get("active_id"))


def rename(workspace_id: str, label: str) -> WorkspaceEntry:
    """Change a workspace's display label. Never moves its directory."""
    cleaned = normalize_label(label, max_len=_LABEL_MAX, what="Profile name")
    with _LOCK:
        index = read_index()
        entry = _find_entry(index, workspace_id)
        others = (e["label"] for e in index.get("entries", []) if e["id"] != workspace_id)
        if label_taken(cleaned, others):
            raise WorkspaceError(f"A profile named {cleaned!r} already exists.")
        entry["label"] = cleaned
        write_index(index)

        meta_path = _meta_path(workspace_id)
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        meta["id"] = workspace_id
        meta["label"] = cleaned
        meta.setdefault("created_at", entry.get("created_at", ""))
        _write_meta(workspace_id, meta)
        return _entry_from_meta(entry, active_id=index.get("active_id"))


def delete(workspace_id: str) -> None:
    """Remove a workspace's registry entry and its files.

    Refuses the active workspace (switch first) and the last remaining one — a
    workspace-less state has nothing for `config`'s path globals to point at. Caller
    is responsible for the `JobQueue.busy()` / `template_ops.LOCK` guard.
    """
    with _LOCK:
        index = read_index()
        _find_entry(index, workspace_id)  # raises if unknown
        entries = index.get("entries", [])
        if index.get("active_id") == workspace_id:
            raise WorkspaceError("Cannot delete the active profile. Switch to another profile first.")
        if len(entries) <= 1:
            raise WorkspaceError("Cannot delete the only profile.")
        index["entries"] = [e for e in entries if e["id"] != workspace_id]
        write_index(index)

    paths = config.workspace_paths(workspace_id)
    for key in ("DATA_DIR", "TEMPLATES_DIR", "OUTPUT_DIR", "CACHE_DIR"):
        shutil.rmtree(paths[key], ignore_errors=True)


def activate(workspace_id: str) -> WorkspaceEntry:
    """Persist `workspace_id` as active and rebind `config`'s path globals to it.

    Caller is responsible for the `JobQueue.busy()` / `template_ops.LOCK` guard —
    rebinding mid-job or mid-render would silently mix one workspace's content with
    another's paths.
    """
    with _LOCK:
        index = read_index()
        entry = _find_entry(index, workspace_id)
        index["active_id"] = workspace_id
        write_index(index)
        config.set_active_workspace(workspace_id, create_dirs=True)
        # Self-heal profiles created before `create` seeded a starter resume — without
        # this they stay broken (editor 404, template install fails) on every switch.
        ensure_master_resume()
        return _entry_from_meta(entry, active_id=workspace_id)


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


def settings_path(workspace_id: str | None = None) -> Path:
    """Path to `settings.json` for `workspace_id`, or the active workspace if None."""
    if workspace_id is None:
        return config.SETTINGS_PATH
    return config.workspace_paths(workspace_id)["SETTINGS_PATH"]


def load_settings(workspace_id: str | None = None) -> dict:
    """Read `settings.json` as a plain dict `{schema_version, defaults}`.

    Missing, unreadable, or malformed files fall back to an empty `defaults` dict
    rather than raising — the web layer validates `defaults` through the `JobSettings`
    pydantic model, which fills in every field's own default, so a corrupt file just
    behaves like a fresh one instead of 500ing the settings endpoint.
    """
    path = settings_path(workspace_id)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            defaults = raw.get("defaults")
            return {
                "schema_version": raw.get("schema_version", 1),
                "defaults": defaults if isinstance(defaults, dict) else {},
            }
    return {"schema_version": 1, "defaults": {}}


def save_settings(defaults: dict, workspace_id: str | None = None) -> None:
    """Atomically write `defaults` (already-validated, e.g. via `JobSettings`) to disk."""
    path = settings_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"schema_version": 1, "defaults": defaults}, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


# --------------------------------------------------------------------------------------
# Bootstrap & migration
# --------------------------------------------------------------------------------------


def _register_existing(workspace_id: str, label: str) -> WorkspaceEntry:
    """Register an on-disk workspace directory that has no registry entry yet.

    Used to recover from a migration that copied files but crashed before writing
    `index.json` — the files are real, so re-running the copy would be wrong; this
    just catches the registry up to what is already on disk.
    """
    meta_path = _meta_path(workspace_id)
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    meta.setdefault("id", workspace_id)
    meta.setdefault("label", label)
    meta.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _write_meta(workspace_id, meta)

    index = read_index()
    entries = index.get("entries", [])
    if not any(e["id"] == workspace_id for e in entries):
        entries.append(meta)
    index["entries"] = entries
    index["active_id"] = workspace_id
    write_index(index)
    return _entry_from_meta(meta, active_id=workspace_id)


def _migrate_legacy(default_id: str = _DEFAULT_ID) -> BootstrapResult:
    """Copy today's single-slot `data/` + `templates/` layout into a "Default" workspace.

    Copies, never moves: cross-root `shutil.move` is not atomic, and a partial move
    would leave the app on neither layout with no good recovery. Copying makes
    rollback "delete the new tree" and leaves the legacy files untouched either way,
    so a failed attempt can simply be retried on the next process start.
    """
    paths = config.workspace_paths(default_id)
    log_lines: list[str] = []

    if paths["DATA_DIR"].exists() and any(paths["DATA_DIR"].iterdir()):
        # A previous attempt copied files but never reached the final index.json
        # write below (e.g. the process was killed mid-migration). Do not re-copy
        # over it — just catch the registry up to what is already on disk.
        entry = _register_existing(default_id, _DEFAULT_LABEL)
        return BootstrapResult(active_id=entry.id, migrated=True, log="resumed a partial migration")

    try:
        for key in ("DATA_DIR", "TEMPLATES_DIR", "OUTPUT_DIR", "CACHE_DIR"):
            paths[key].mkdir(parents=True, exist_ok=True)

        legacy_master = config.DATA_ROOT / "master_resume.json"
        if legacy_master.exists():
            shutil.copy2(legacy_master, paths["MASTER_RESUME_PATH"])
            log_lines.append(f"copied {legacy_master}")

        legacy_calibration = config.DATA_ROOT / "calibration"
        if legacy_calibration.exists():
            shutil.copytree(legacy_calibration, paths["CALIBRATION_DIR"], dirs_exist_ok=True)
            log_lines.append(f"copied {legacy_calibration}")

        for name, key in (
            ("original_export.docx", "BASELINE_TEMPLATE_PATH"),
            ("main_template.docx", "DEFAULT_TEMPLATE_PATH"),
            ("template_profile.json", "TEMPLATE_PROFILE_PATH"),
        ):
            legacy_file = config.TEMPLATES_ROOT / name
            if legacy_file.exists():
                shutil.copy2(legacy_file, paths[key])
                log_lines.append(f"copied {legacy_file}")

        legacy_library = config.TEMPLATES_ROOT / "library"
        if legacy_library.exists():
            shutil.copytree(legacy_library, paths["TEMPLATE_LIBRARY_DIR"], dirs_exist_ok=True)
            log_lines.append(f"copied {legacy_library}")

        legacy_backups = config.TEMPLATES_ROOT / "backups"
        if legacy_backups.exists():
            dest_backups = paths["BASELINE_TEMPLATE_PATH"].parent / "backups"
            shutil.copytree(legacy_backups, dest_backups, dirs_exist_ok=True)
            log_lines.append(f"copied {legacy_backups}")

        _write_default_settings(paths["SETTINGS_PATH"])

        meta = {
            "id": default_id,
            "label": _DEFAULT_LABEL,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _write_meta(default_id, meta)
        write_index({"active_id": default_id, "entries": [meta]})
    except Exception:
        for key in ("DATA_DIR", "TEMPLATES_DIR", "OUTPUT_DIR", "CACHE_DIR"):
            shutil.rmtree(paths[key], ignore_errors=True)
        raise

    return BootstrapResult(active_id=default_id, migrated=True, log="\n".join(log_lines))


def bootstrap(*, workspace_id: str | None = None, migrate: bool = True) -> BootstrapResult:
    """Resolve and activate a workspace, migrating the legacy layout on first boot.

    Resolution order: an explicit `workspace_id` (process-local only — never persisted
    as the registry's active pointer, so a CLI `--workspace` override can't silently
    flip a running server's profile); else the registry's `active_id`; else the first
    registered entry (healing a stale pointer); else a fresh migration of the legacy
    single-slot layout; else an empty "Default" workspace when `migrate=False`.

    Idempotent: once a registry with a valid `active_id` exists, this only reads
    `index.json` and rebinds paths. Safe to call on every process start.

    Always leaves the active workspace with a loadable `master_resume.json`
    (`ensure_master_resume`), including on the migration path when there was no legacy
    file to copy — an active profile that 404s the editor and fails every template
    install is never the more useful outcome.
    """
    if workspace_id is not None:
        resolve(workspace_id)  # raises WorkspaceError if unknown
        config.set_active_workspace(workspace_id, create_dirs=True)
        ensure_master_resume()
        return BootstrapResult(active_id=workspace_id, migrated=False)

    index = read_index()
    entries = index.get("entries", [])
    active_id = index.get("active_id")

    if active_id and any(e["id"] == active_id for e in entries):
        config.set_active_workspace(active_id, create_dirs=True)
        ensure_master_resume()
        return BootstrapResult(active_id=active_id, migrated=False)

    if entries:
        healed_id = entries[0]["id"]
        index["active_id"] = healed_id
        write_index(index)
        config.set_active_workspace(healed_id, create_dirs=True)
        ensure_master_resume()
        return BootstrapResult(active_id=healed_id, migrated=False)

    if migrate:
        result = _migrate_legacy()
        config.set_active_workspace(result.active_id, create_dirs=True)
        ensure_master_resume()
        return result

    entry = create(_DEFAULT_LABEL)
    index = read_index()
    index["active_id"] = entry.id
    write_index(index)
    config.set_active_workspace(entry.id, create_dirs=True)
    ensure_master_resume()
    return BootstrapResult(active_id=entry.id, migrated=False)
