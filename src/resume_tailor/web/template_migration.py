"""Startup migration: every saved fixed-mode template becomes generic (movable sections).

Runs once per server start, before requests are served, for every workspace: each
template-library entry, then the live slot. Idempotent — a generic profile is skipped —
and conservative: the fixed profile and tagged template are copied to `fixed_backup/`
first (never overwritten by a later run), the new template is built and verified in a
temp dir, and only then are the files replaced. Any failure leaves the template fixed
and is noted in its profile's warnings. A `fixed_pinned` marker (written by "Revert to
fixed layout") keeps an entry fixed for good.

The live slot mirrors the active library entry when both hold the same baseline, so the
two can never disagree; otherwise it is converted on its own. When the active
workspace's live template converts, its resume's section titles are synced right away;
another workspace's sync is deferred to its next activation (`section_title_sync`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from resume_tailor import config, workspace
from resume_tailor.document import (
    calibration_cache,
    template_build,
    template_convert,
    template_profile,
    template_verify,
)
from resume_tailor.web import section_title_sync, template_ops, template_preview

_log = logging.getLogger(__name__)

PROFILE = "template_profile.json"
TAGGED = "main_template.docx"
BASELINE = "original_export.docx"
BACKUP_DIR = template_ops.FIXED_BACKUP_DIR
PIN_MARKER = template_ops.FIXED_PIN_MARKER
#: Warning recorded on a profile whose conversion failed (prefix; the reason follows).
FAILED_PREFIX = "Could not switch to movable sections:"


@dataclass
class SlotResult:
    """What happened to one template slot."""

    path: Path
    status: str  # "converted" | "failed" | "skipped"
    detail: str = ""


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _back_up(slot: Path) -> None:
    """Copy the fixed profile + tagged template aside, once. A backup left by an earlier
    interrupted run is the original fixed state and is never overwritten."""
    backup = slot / BACKUP_DIR
    if backup.exists():
        return
    staging = slot / (BACKUP_DIR + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    for name in (PROFILE, TAGGED):
        if (slot / name).exists():
            shutil.copy2(slot / name, staging / name)
    staging.rename(backup)


def _note_failure(profile_path: Path, profile, reason: str) -> None:
    message = f"{FAILED_PREFIX} {reason}"
    if message in profile.warnings:
        return
    kept = [w for w in profile.warnings if not w.startswith(FAILED_PREFIX)]
    template_profile.save_profile(
        profile.model_copy(update={"warnings": [*kept, message]}), profile_path
    )


def convert_slot(slot: Path) -> SlotResult:
    """Convert the fixed-mode template in `slot` (a dir holding profile, tagged template
    and baseline) to generic in place, backing the fixed files up first."""
    profile_path, tagged, baseline = slot / PROFILE, slot / TAGGED, slot / BASELINE
    if not (profile_path.exists() and baseline.exists()):
        return SlotResult(slot, "skipped", "no profile")
    if (slot / PIN_MARKER).exists():
        return SlotResult(slot, "skipped", "pinned to fixed")
    profile = template_profile.load_profile(profile_path)
    if profile is None or profile.section_mode == "generic":
        return SlotResult(slot, "skipped", "already generic")

    try:
        converted = template_convert.to_generic(profile, baseline)
        with tempfile.TemporaryDirectory() as tmp:
            staged_tagged = Path(tmp) / TAGGED
            staged_profile = Path(tmp) / PROFILE
            template_build.build_from_profile(baseline, staged_tagged, converted)
            blockers = [
                i.message
                for i in template_verify.verify_tagged(staged_tagged, converted)
                if i.blocking
            ]
            if blockers:
                raise template_convert.ConversionError("; ".join(blockers))
            kept = [w for w in converted.warnings if not w.startswith(FAILED_PREFIX)]
            converted = converted.model_copy(update={"warnings": kept})
            template_profile.save_profile(converted, staged_profile)
            _back_up(slot)
            # Tagged template first, profile last: an interruption between the two leaves
            # a fixed profile, which the next start converts again from the backup-safe
            # state.
            os.replace(staged_tagged, tagged)
            os.replace(staged_profile, profile_path)
    except Exception as exc:  # noqa: BLE001 - one bad template must not stop the rest
        _log.warning("template %s stays fixed: %s", slot, exc)
        try:
            _note_failure(profile_path, profile, str(exc))
        except Exception:  # noqa: BLE001
            _log.exception("could not record the conversion failure for %s", slot)
        return SlotResult(slot, "failed", str(exc))
    return SlotResult(slot, "converted")


def _active_entry(library: Path) -> Path | None:
    try:
        active_id = json.loads((library / "index.json").read_text(encoding="utf-8")).get(
            "active_id"
        )
    except (OSError, ValueError):
        return None
    if not active_id:
        return None
    entry = library / active_id
    return entry if entry.is_dir() else None


def _migrate_live(templates: Path, library: Path) -> SlotResult:
    """Bring the live slot in line with the active library entry when they share a
    baseline (copying the entry's files), else convert the live slot on its own."""
    live_profile = template_profile.load_profile(templates / PROFILE) if (
        templates / PROFILE
    ).exists() else None
    if live_profile is None or live_profile.section_mode == "generic":
        return SlotResult(templates, "skipped", "already generic")
    entry = _active_entry(library)
    if entry is not None and _sha(entry / BASELINE) == _sha(templates / BASELINE):
        entry_profile = template_profile.load_profile(entry / PROFILE)
        if entry_profile is None or entry_profile.section_mode != "generic":
            return SlotResult(templates, "skipped", "active entry stays fixed")
        _back_up(templates)
        shutil.copy2(entry / TAGGED, templates / TAGGED)
        shutil.copy2(entry / PROFILE, templates / PROFILE)
        return SlotResult(templates, "converted")
    return convert_slot(templates)


def migrate_workspace(workspace_id: str, *, active: bool) -> list[SlotResult]:
    """Convert every fixed template in one workspace. The caller holds
    `template_ops.LOCK`."""
    paths = config.workspace_paths(workspace_id)
    templates, library = paths["TEMPLATES_DIR"], paths["TEMPLATE_LIBRARY_DIR"]
    results: list[SlotResult] = []
    if library.is_dir():
        for entry in sorted(p for p in library.iterdir() if p.is_dir()):
            results.append(convert_slot(entry))
    live = _migrate_live(templates, library)
    results.append(live)
    if live.status == "converted":
        if active:
            profile = template_profile.load_profile()
            if profile is not None:
                section_title_sync.sync_unlocked(profile)
            template_preview.invalidate_preview()
            calibration_cache.activate()
        else:
            (templates / section_title_sync.PENDING_MARKER).touch()
    return results


def migrate_all() -> list[SlotResult]:
    """Convert every fixed template in every workspace. Never raises."""
    results: list[SlotResult] = []
    try:
        with template_ops.LOCK:
            for entry in workspace.list_workspaces():
                try:
                    results += migrate_workspace(entry.id, active=entry.is_active)
                except Exception:  # noqa: BLE001 - next workspace still gets its turn
                    _log.exception("template migration failed for workspace %s", entry.id)
    except Exception:  # noqa: BLE001 - startup must not fail on a migration
        _log.exception("template migration failed")
    converted = [r for r in results if r.status == "converted"]
    if converted:
        _log.info("switched %d template(s) to movable sections", len(converted))
    return results
