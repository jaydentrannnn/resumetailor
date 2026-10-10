"""Startup switch of saved fixed-mode templates to movable sections, the title sync that
follows it, and "Revert to fixed layout"."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import docx

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import template_analyze, template_build, template_profile
from resume_tailor.web import section_title_sync, template_migration, template_ops
from tests.fixtures import _docx_bytes, _standard_resume, as_fixed
from tests.web.helpers import _point_templates_at


def _fixed_slot(slot: Path) -> Path:
    """A template slot holding a fixed-mode build of `_standard_resume`."""
    slot.mkdir(parents=True, exist_ok=True)
    raw = _docx_bytes(_standard_resume)
    baseline = slot / "original_export.docx"
    baseline.write_bytes(raw)
    suggested = template_analyze.analyze_docx(raw=raw).suggested_profile
    assert suggested is not None
    fixed = as_fixed(suggested)
    template_profile.save_profile(fixed, slot / "template_profile.json")
    template_build.build_from_profile(baseline, slot / "main_template.docx", fixed)
    return slot


def _mode(slot: Path) -> str:
    return template_profile.load_profile(slot / "template_profile.json").section_mode


def _tagged_text(slot: Path) -> str:
    return "\n".join(p.text for p in docx.Document(str(slot / "main_template.docx")).paragraphs)


def test_fixed_slot_converts_and_keeps_a_backup(tmp_path):
    slot = _fixed_slot(tmp_path / "entry")
    fixed_profile = (slot / "template_profile.json").read_bytes()
    fixed_tagged = (slot / "main_template.docx").read_bytes()

    result = template_migration.convert_slot(slot)

    assert result.status == "converted"
    assert _mode(slot) == "generic"
    assert "{%p for section in sections %}" in _tagged_text(slot)
    backup = slot / template_ops.FIXED_BACKUP_DIR
    assert (backup / "template_profile.json").read_bytes() == fixed_profile
    assert (backup / "main_template.docx").read_bytes() == fixed_tagged


def test_conversion_is_idempotent(tmp_path):
    slot = _fixed_slot(tmp_path / "entry")
    template_migration.convert_slot(slot)
    converted = (slot / "template_profile.json").read_bytes()
    assert template_migration.convert_slot(slot).status == "skipped"
    assert (slot / "template_profile.json").read_bytes() == converted


def test_pinned_slot_stays_fixed(tmp_path):
    slot = _fixed_slot(tmp_path / "entry")
    (slot / template_ops.FIXED_PIN_MARKER).touch()
    assert template_migration.convert_slot(slot).status == "skipped"
    assert _mode(slot) == "fixed"


def test_failed_build_leaves_the_slot_fixed_with_a_warning(tmp_path, monkeypatch):
    slot = _fixed_slot(tmp_path / "entry")
    tagged = (slot / "main_template.docx").read_bytes()

    def boom(*_a, **_k):
        raise RuntimeError("build exploded")

    monkeypatch.setattr(template_migration.template_build, "build_from_profile", boom)
    result = template_migration.convert_slot(slot)

    assert result.status == "failed"
    profile = template_profile.load_profile(slot / "template_profile.json")
    assert profile.section_mode == "fixed"
    assert any(w.startswith(template_migration.FAILED_PREFIX) for w in profile.warnings)
    assert (slot / "main_template.docx").read_bytes() == tagged
    assert not (slot / template_ops.FIXED_BACKUP_DIR).exists()
    # A repeat failure doesn't stack a second copy of the warning.
    template_migration.convert_slot(slot)
    again = template_profile.load_profile(slot / "template_profile.json")
    assert sum(w.startswith(template_migration.FAILED_PREFIX) for w in again.warnings) == 1


def test_legacy_profile_without_section_mode_converts(tmp_path):
    slot = _fixed_slot(tmp_path / "entry")
    path = slot / "template_profile.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("section_mode", "sections", "heading_prototype", "spacing", "layout", "paragraph_count"):
        raw.pop(key, None)
    raw["schema_version"] = 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert template_migration.convert_slot(slot).status == "converted"
    assert _mode(slot) == "generic"


def _workspace(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """A workspace whose live slot and active library entry share one fixed template."""
    templates = tmp_path / "ws"
    library = templates / "library"
    entry = _fixed_slot(library / "e1")
    (library / "index.json").write_text(json.dumps({"active_id": "e1"}), encoding="utf-8")
    for name in ("original_export.docx", "main_template.docx", "template_profile.json"):
        shutil.copy2(entry / name, templates / name)
    monkeypatch.setattr(
        template_migration.config,
        "workspace_paths",
        lambda _id: {"TEMPLATES_DIR": templates, "TEMPLATE_LIBRARY_DIR": library},
    )
    return templates, entry


def test_inactive_workspace_defers_its_title_sync(tmp_path, monkeypatch):
    templates, entry = _workspace(tmp_path, monkeypatch)
    synced = []
    monkeypatch.setattr(section_title_sync, "sync_unlocked", lambda p: synced.append(p))

    results = template_migration.migrate_workspace("other", active=False)

    assert [r.status for r in results] == ["converted", "converted"]
    assert _mode(entry) == "generic" and _mode(templates) == "generic"
    # The live slot mirrors the converted entry byte for byte.
    assert (templates / "main_template.docx").read_bytes() == (
        entry / "main_template.docx"
    ).read_bytes()
    assert (templates / section_title_sync.PENDING_MARKER).exists()
    assert synced == []


def test_active_workspace_syncs_titles_now(tmp_path, monkeypatch):
    templates, _ = _workspace(tmp_path, monkeypatch)
    synced = []
    monkeypatch.setattr(section_title_sync, "sync_unlocked", lambda p: synced.append(p))
    monkeypatch.setattr(config, "TEMPLATE_PROFILE_PATH", templates / "template_profile.json")
    monkeypatch.setattr(template_migration.template_preview, "invalidate_preview", lambda: None)
    monkeypatch.setattr(template_migration.calibration_cache, "activate", lambda: None)

    template_migration.migrate_workspace("me", active=True)

    assert len(synced) == 1 and synced[0].section_mode == "generic"
    assert not (templates / section_title_sync.PENDING_MARKER).exists()


def test_pinned_active_entry_keeps_the_live_slot_fixed(tmp_path, monkeypatch):
    templates, entry = _workspace(tmp_path, monkeypatch)
    (entry / template_ops.FIXED_PIN_MARKER).touch()
    results = template_migration.migrate_workspace("other", active=False)
    assert [r.status for r in results] == ["skipped", "skipped"]
    assert _mode(templates) == "fixed"


def test_sync_renames_resume_sections_and_records_a_version(client):
    suggested = template_analyze.analyze_docx(raw=_docx_bytes(_standard_resume)).suggested_profile
    education = next(s for s in suggested.sections if s.kind == "education")
    profile = suggested.model_copy(
        update={"sections": [education.model_copy(update={"title": "Schooling"})]}
    )
    changes = section_title_sync.sync_active(profile)
    assert changes == [("EDUCATION", "Schooling")]
    assert [s.title for s in data.load().sections if s.kind == "education"] == ["Schooling"]
    assert section_title_sync.sync_active(profile) == []


def test_pending_sync_runs_once_on_activation(client, tmp_path, monkeypatch):
    templates = _point_templates_at(tmp_path, monkeypatch)
    _fixed_slot(templates)
    template_migration.convert_slot(templates)
    (templates / section_title_sync.PENDING_MARKER).touch()

    resume = data.load()
    resume.sections[0].title = "Old title"
    config.MASTER_RESUME_PATH.write_text(resume.model_dump_json(by_alias=True), encoding="utf-8")

    with template_ops.LOCK:
        changes = section_title_sync.apply_pending_unlocked()

    assert resume.sections[0].kind == "education"
    assert changes == [("Old title", "EDUCATION")]
    assert not (templates / section_title_sync.PENDING_MARKER).exists()
    with template_ops.LOCK:
        assert section_title_sync.apply_pending_unlocked() == []


def test_revert_restores_the_fixed_layout_and_pins_it(client, tmp_path, monkeypatch):
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    library = templates / "library"
    entry = _fixed_slot(library / "e1")
    (entry / "meta.json").write_text(
        json.dumps({"id": "e1", "label": "Mine", "created_at": "", "has_profile": True}),
        encoding="utf-8",
    )
    (library / "index.json").write_text(json.dumps({"active_id": None}), encoding="utf-8")
    fixed_profile = (entry / "template_profile.json").read_bytes()
    template_migration.convert_slot(entry)

    listed = c.get("/api/template/library").json()["entries"]
    assert listed[0]["section_mode"] == "generic" and listed[0]["can_revert_fixed"] is True

    res = c.post("/api/template/library/e1/revert-fixed")
    assert res.status_code == 200, res.text
    assert (entry / "template_profile.json").read_bytes() == fixed_profile
    assert (entry / template_ops.FIXED_PIN_MARKER).exists()
    assert template_migration.convert_slot(entry).status == "skipped"

    listed = c.get("/api/template/library").json()["entries"]
    assert listed[0]["section_mode"] == "fixed" and listed[0]["can_revert_fixed"] is False
    assert c.post("/api/template/library/e1/revert-fixed").status_code == 400
