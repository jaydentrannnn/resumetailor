"""Export, import and reset one profile's data (Settings → Data).

- `export_zip(workspace_id)`: the profile's data and template folders, and optionally
  its generated files, as one zip with a ``manifest.json``. The SQLite database is
  copied through SQLite's backup API, so a write landing mid-export cannot tear it.
  Secrets are never included (API keys and the Workday password live in the OS
  keychain), nor are the session token, caches or logs.
- `import_zip(raw, label)`: always creates a **new** profile from an export and never
  overwrites an existing one, so an import can never destroy data. The user switches
  to it like any other profile.
- `reset_workspace(workspace_id)`: "Delete all data" for one profile. Its folders move
  to ``<DATA_ROOT>/.trash/<id>-<stamp>/`` rather than being deleted, then start empty.

Callers hold the idle guards (`template_ops.LOCK`, queue not busy): see the routes.
"""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath

from resume_tailor import config, workspace
from resume_tailor.storage import db

FORMAT = "resumetailor-export"
FORMAT_VERSION = 1
#: Never exported: credentials and machine-local state.
_EXCLUDED_NAMES = frozenset({"secrets.enc", ".secret_key", ".session_token"})
_EXCLUDED_SUFFIXES = (".db-wal", ".db-shm", ".tmp")
_ROOTS = ("DATA_DIR", "TEMPLATES_DIR", "OUTPUT_DIR")
MAX_IMPORT_BYTES = 2 * 1024**3
MAX_IMPORT_FILES = 50_000


class TransferError(RuntimeError):
    """An export/import/reset request that cannot be carried out (message is user-facing)."""


def _version() -> str:
    try:
        return metadata.version("resume-tailor")
    except metadata.PackageNotFoundError:
        return "unknown"


def _label(workspace_id: str) -> str:
    try:
        return workspace.resolve(workspace_id).label
    except Exception:  # noqa: BLE001 - a missing registry entry just means no label
        return workspace_id


def _skip(path: Path) -> bool:
    return path.name in _EXCLUDED_NAMES or path.name.endswith(_EXCLUDED_SUFFIXES)


def export_zip(workspace_id: str, *, include_output: bool = True) -> bytes:
    paths = config.workspace_paths(workspace_id)
    roots = [r for r in _ROOTS if include_output or r != "OUTPUT_DIR"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": FORMAT,
                    "format_version": FORMAT_VERSION,
                    "app_version": _version(),
                    "db_schema": db.SCHEMA_VERSION,
                    "workspace_id": workspace_id,
                    "label": _label(workspace_id),
                    "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "includes_output": include_output,
                    "secrets_included": False,
                },
                indent=2,
            ),
        )
        for root_key in roots:
            root = paths[root_key]
            if not root.is_dir():
                continue
            prefix = root_key.removesuffix("_DIR").lower()
            for path in sorted(root.rglob("*")):
                if not path.is_file() or _skip(path):
                    continue
                arcname = f"{prefix}/{path.relative_to(root).as_posix()}"
                if path.name == db.DB_NAME:
                    archive.writestr(arcname, _db_snapshot(path))
                else:
                    archive.write(path, arcname)
    return buffer.getvalue()


def _db_snapshot(path: Path) -> bytes:
    """A consistent copy of a live SQLite file (WAL included)."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "snapshot.db"
        source = sqlite3.connect(path)
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        return target.read_bytes()


def _safe_member(name: str) -> PurePosixPath | None:
    """The archive path if it is a plain relative path under a known root, else None."""
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or "\\" in name or not pure.parts:
        return None
    if pure.parts[0] not in {"data", "templates", "output"} or len(pure.parts) < 2:
        return None
    return pure


def read_manifest(raw: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise TransferError("This is not a ResumeTailor export (no readable manifest).") from exc
    if manifest.get("format") != FORMAT:
        raise TransferError("This zip was not made by ResumeTailor's Export.")
    if int(manifest.get("format_version", 0)) > FORMAT_VERSION:
        raise TransferError("This export comes from a newer ResumeTailor. Update the app first.")
    if int(manifest.get("db_schema", 0)) > db.SCHEMA_VERSION:
        raise TransferError("This export's database is newer than this app. Update the app first.")
    return manifest


def import_zip(raw: bytes, label: str | None = None) -> workspace.WorkspaceEntry:
    """Create a new profile holding the export's files. Returns its registry entry."""
    manifest = read_manifest(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [
            m for m in archive.infolist() if not m.is_dir() and m.filename != "manifest.json"
        ]
        if len(members) > MAX_IMPORT_FILES:
            raise TransferError("This export has too many files to import.")
        if sum(m.file_size for m in members) > MAX_IMPORT_BYTES:
            raise TransferError("This export is larger than 2 GB and cannot be imported.")
        planned: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for member in members:
            safe = _safe_member(member.filename)
            if safe is None:
                raise TransferError(f"Refusing an unsafe path in the export: {member.filename!r}")
            planned.append((member, safe))

        entry = _create_unique(label or f"{manifest.get('label') or 'Imported'} (imported)")
        paths = config.workspace_paths(entry.id)
        roots = {
            "data": paths["DATA_DIR"],
            "templates": paths["TEMPLATES_DIR"],
            "output": paths["OUTPUT_DIR"],
        }
        for member, safe in planned:
            target = roots[safe.parts[0]].joinpath(*safe.parts[1:])
            if safe.parts[0] == "data" and safe.parts[1:] == ("workspace.json",):
                continue  # the new profile keeps its own identity file
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)
    return entry


def _create_unique(label: str) -> workspace.WorkspaceEntry:
    base = label.strip()[:50] or "Imported"
    for n in range(1, 100):
        try:
            return workspace.create(base if n == 1 else f"{base} {n}")
        except workspace.WorkspaceError as exc:
            if "already exists" not in str(exc):
                raise TransferError(str(exc)) from exc
    raise TransferError("Could not find a free profile name for the import.")


def reset_workspace(workspace_id: str) -> Path:
    """Move a profile's folders to the trash and start it empty. Returns the trash dir."""
    paths = config.workspace_paths(workspace_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    trash = config.DATA_ROOT / ".trash" / f"{workspace_id}-{stamp}"
    trash.mkdir(parents=True, exist_ok=True)
    db.close_all()
    keep = paths["DATA_DIR"] / "workspace.json"
    identity = keep.read_bytes() if keep.exists() else None
    for root_key in ("DATA_DIR", "TEMPLATES_DIR", "OUTPUT_DIR", "CACHE_DIR"):
        root = paths[root_key]
        if not root.exists():
            continue
        try:
            shutil.move(str(root), str(trash / root_key.removesuffix("_DIR").lower()))
        except OSError as exc:
            raise TransferError(
                f"Could not move {root.name} aside ({exc}). Close any program using these "
                "files and try again; nothing was deleted."
            ) from exc
        root.mkdir(parents=True, exist_ok=True)
    if identity is not None:
        keep.write_bytes(identity)
    workspace._write_default_settings(paths["SETTINGS_PATH"])
    workspace._write_default_libraries(paths["LIBRARIES_PATH"])
    workspace.ensure_master_resume(workspace_id)
    return trash
