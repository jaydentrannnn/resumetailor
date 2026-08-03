"""Workspace ("Profile") registry, migration, and path-rebinding — no network, no Word.

`bootstrap` is stubbed for every other test module by the autouse fixture in
`conftest.py`, so it is imported directly here (bypassing the `workspace.bootstrap`
attribute the stub patches) to exercise the real implementation.
"""

from __future__ import annotations

import json

import pytest

from resume_tailor import config, workspace
from resume_tailor.workspace import WorkspaceError, bootstrap


@pytest.fixture
def isolated_roots(tmp_path, monkeypatch):
    """Point every workspace-relevant config path at an isolated tmp_path tree."""
    data_root = tmp_path / "data"
    templates_root = tmp_path / "templates"
    output_root = tmp_path / "output"
    data_root.mkdir()
    templates_root.mkdir()
    output_root.mkdir()

    monkeypatch.delenv("RESUME_TAILOR_CALIBRATION_DIR", raising=False)
    for name, value in (
        ("DATA_ROOT", data_root),
        ("TEMPLATES_ROOT", templates_root),
        ("OUTPUT_ROOT", output_root),
        ("CACHE_ROOT", output_root),
        ("DATA_DIR", data_root),
        ("TEMPLATES_DIR", templates_root),
        ("OUTPUT_DIR", output_root),
        ("CACHE_DIR", output_root),
        ("MASTER_RESUME_PATH", data_root / "master_resume.json"),
        ("SETTINGS_PATH", data_root / "settings.json"),
        ("DEFAULT_TEMPLATE_PATH", templates_root / "main_template.docx"),
        ("BASELINE_TEMPLATE_PATH", templates_root / "original_export.docx"),
        ("TEMPLATE_PROFILE_PATH", templates_root / "template_profile.json"),
        ("TEMPLATE_LIBRARY_DIR", templates_root / "library"),
        ("_ACTIVE_WORKSPACE_ID", None),
    ):
        monkeypatch.setattr(config, name, value)
    return {"data": data_root, "templates": templates_root, "output": output_root}


def _seed_legacy_layout(roots: dict) -> None:
    (roots["data"] / "master_resume.json").write_text(
        json.dumps({"contact": {"name": "Ada Lovelace"}}), encoding="utf-8"
    )
    (roots["templates"] / "original_export.docx").write_bytes(b"fake baseline")
    (roots["templates"] / "main_template.docx").write_bytes(b"fake tagged")


def test_bootstrap_migrates_legacy_layout(isolated_roots):
    _seed_legacy_layout(isolated_roots)

    result = bootstrap()

    assert result.migrated
    assert result.active_id == "default"
    assert config.active_workspace_id() == "default"
    assert config.MASTER_RESUME_PATH.exists()
    assert json.loads(config.MASTER_RESUME_PATH.read_text())["contact"]["name"] == "Ada Lovelace"
    assert config.DEFAULT_TEMPLATE_PATH.exists()
    # Legacy files are copied, never moved.
    assert (isolated_roots["data"] / "master_resume.json").exists()
    assert (isolated_roots["templates"] / "main_template.docx").exists()

    index = json.loads((isolated_roots["data"] / "workspaces" / "index.json").read_text())
    assert index["active_id"] == "default"
    assert [e["id"] for e in index["entries"]] == ["default"]


def test_bootstrap_is_idempotent(isolated_roots):
    _seed_legacy_layout(isolated_roots)
    first = bootstrap()
    assert first.migrated

    second = bootstrap()
    assert not second.migrated
    assert second.active_id == "default"


def test_bootstrap_with_no_legacy_files_creates_usable_default(isolated_roots):
    """Nothing to migrate still yields a *usable* Default, not a half-built one.

    The seeded placeholder matters because an active profile with no master resume
    404s the editor and fails every template install — see
    `test_create_without_copy_from_seeds_a_loadable_resume`.
    """
    from resume_tailor import data

    result = bootstrap()

    assert result.migrated
    assert result.active_id == "default"
    assert config.MASTER_RESUME_PATH.exists()
    assert data.load().contact.name == "Your Name"


def test_migration_rolls_back_and_leaves_legacy_on_failure(isolated_roots, monkeypatch):
    _seed_legacy_layout(isolated_roots)
    # Force the template-library copy step (which never runs today, since no legacy
    # library exists) to fail by making the docx copy itself blow up instead — that
    # keeps the failure inside the try/except that owns cleanup.
    real_copy2 = workspace.shutil.copy2

    def _boom(src, dst, *a, **kw):
        if str(src).endswith("main_template.docx"):
            raise OSError("simulated disk failure")
        return real_copy2(src, dst, *a, **kw)

    monkeypatch.setattr(workspace.shutil, "copy2", _boom)

    with pytest.raises(OSError):
        bootstrap()

    # No registry was written, and the partial workspace dir was cleaned up.
    assert not (isolated_roots["data"] / "workspaces" / "index.json").exists()
    assert not (isolated_roots["data"] / "workspaces" / "default").exists()
    # Legacy layout is completely untouched.
    assert (isolated_roots["data"] / "master_resume.json").exists()
    assert (isolated_roots["templates"] / "main_template.docx").exists()

    # And a retry after the transient failure (now resolved) succeeds cleanly.
    monkeypatch.setattr(workspace.shutil, "copy2", real_copy2)
    result = bootstrap()
    assert result.migrated


def test_workspace_flag_does_not_persist_active_id(isolated_roots):
    _seed_legacy_layout(isolated_roots)
    bootstrap()  # migrates + activates "default"
    workspace.create("Data Science")

    # Simulate `--workspace data-science` on a one-off CLI invocation.
    result = bootstrap(workspace_id="data-science")

    assert result.active_id == "data-science"
    assert config.active_workspace_id() == "data-science"
    index = json.loads((isolated_roots["data"] / "workspaces" / "index.json").read_text())
    assert index["active_id"] == "default", "explicit --workspace must not persist"


def test_set_active_workspace_rebinds_all_paths(isolated_roots):
    config.set_active_workspace("demo", create_dirs=True)

    assert config.active_workspace_id() == "demo"
    ws_root = isolated_roots["data"] / "workspaces" / "demo"
    assert config.DATA_DIR == ws_root
    assert config.MASTER_RESUME_PATH == ws_root / "master_resume.json"
    assert config.SETTINGS_PATH == ws_root / "settings.json"
    assert config.CALIBRATION_DIR == ws_root / "calibration"
    templates_root = isolated_roots["templates"] / "workspaces" / "demo"
    assert config.DEFAULT_TEMPLATE_PATH == templates_root / "main_template.docx"
    assert config.BASELINE_TEMPLATE_PATH == templates_root / "original_export.docx"
    assert config.TEMPLATE_PROFILE_PATH == templates_root / "template_profile.json"
    assert config.TEMPLATE_LIBRARY_DIR == templates_root / "library"
    assert config.OUTPUT_DIR == isolated_roots["output"] / "workspaces" / "demo"


def test_create_duplicate_copies_resume_and_templates(isolated_roots):
    bootstrap()  # empty "default"
    (config.MASTER_RESUME_PATH).write_text(json.dumps({"contact": {"name": "Grace Hopper"}}))
    config.DEFAULT_TEMPLATE_PATH.write_bytes(b"tagged bytes")
    config.BASELINE_TEMPLATE_PATH.write_bytes(b"baseline bytes")

    entry = workspace.create("Data Science", copy_from="default")

    assert entry.id == "data-science"
    assert entry.has_master_resume
    assert entry.has_template
    dup_paths = config.workspace_paths("data-science")
    assert json.loads(dup_paths["MASTER_RESUME_PATH"].read_text())["contact"]["name"] == "Grace Hopper"
    assert dup_paths["DEFAULT_TEMPLATE_PATH"].read_bytes() == b"tagged bytes"


def test_create_without_copy_from_seeds_a_loadable_resume(isolated_roots):
    """A profile created without duplicating is immediately usable.

    Regression: it used to be created with only settings.json, which left it broken in
    three places at once — the editor 404d, `template_ops._smoke_render` raised
    FileNotFoundError so every template install failed, and no run could start.
    """
    from resume_tailor import data

    bootstrap()
    entry = workspace.create("Nina")

    assert entry.has_master_resume
    paths = config.workspace_paths(entry.id)
    assert paths["MASTER_RESUME_PATH"].exists()

    workspace.activate(entry.id)
    # This is exactly the call `_smoke_render` makes before any template install.
    assert data.load().contact.name == "Your Name"


def test_activate_heals_a_workspace_missing_its_resume(isolated_roots):
    """Switching to a profile created before seeding existed repairs it in place."""
    from resume_tailor import data

    bootstrap()
    workspace.create("Nina")
    config.workspace_paths("nina")["MASTER_RESUME_PATH"].unlink()

    workspace.activate("nina")

    assert config.MASTER_RESUME_PATH.exists()
    assert data.load().contact.name == "Your Name"


def test_bootstrap_heals_the_active_workspace(isolated_roots):
    """A restart with a broken active profile repairs it, not just an explicit switch."""
    bootstrap()
    workspace.create("Nina")
    workspace.activate("nina")
    config.MASTER_RESUME_PATH.unlink()

    bootstrap()

    assert config.MASTER_RESUME_PATH.exists()


def test_ensure_master_resume_never_overwrites_existing_content(isolated_roots):
    """Seeding is create-if-absent only — it must never clobber a real resume."""
    bootstrap()
    real = json.dumps({
        "contact": {"name": "Real Person", "email": "real@example.com"},
        "education": [], "experience": [], "projects": [], "skills": [], "tag_vocabulary": [],
    })
    config.MASTER_RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MASTER_RESUME_PATH.write_text(real, encoding="utf-8")

    assert workspace.ensure_master_resume() is False
    bootstrap()

    assert json.loads(config.MASTER_RESUME_PATH.read_text())["contact"]["name"] == "Real Person"


def test_create_rejects_duplicate_label_case_insensitively(isolated_roots):
    bootstrap()
    workspace.create("Data Science")

    with pytest.raises(WorkspaceError):
        workspace.create("data science")


def test_create_rejects_unknown_copy_from(isolated_roots):
    bootstrap()

    with pytest.raises(WorkspaceError):
        workspace.create("New One", copy_from="does-not-exist")


def test_rename_rejects_duplicate_label_case_insensitively(isolated_roots):
    bootstrap()
    workspace.create("Data Science")

    with pytest.raises(WorkspaceError):
        workspace.rename("default", "DATA SCIENCE")


def test_rename_keeps_the_same_directory(isolated_roots):
    bootstrap()
    workspace.create("Data Science")
    original_dir = config.workspace_paths("data-science")["DATA_DIR"]
    original_dir.mkdir(parents=True, exist_ok=True)
    marker = original_dir / "master_resume.json"
    marker.write_text("{}", encoding="utf-8")

    workspace.rename("data-science", "Machine Learning")

    entries = {e.id: e.label for e in workspace.list_workspaces()}
    assert entries["data-science"] == "Machine Learning"
    # The id (and therefore the on-disk directory) never changes on rename.
    assert config.workspace_paths("data-science")["DATA_DIR"] == original_dir
    assert marker.exists()


def test_delete_refuses_active_and_last(isolated_roots):
    bootstrap()
    workspace.create("Data Science")

    with pytest.raises(WorkspaceError):
        workspace.delete("default")  # active

    workspace.activate("data-science")
    workspace.delete("default")  # now inactive, fine

    with pytest.raises(WorkspaceError):
        workspace.delete("data-science")  # last remaining


def test_activate_persists_and_rebinds(isolated_roots):
    bootstrap()
    workspace.create("Data Science")

    workspace.activate("data-science")

    assert config.active_workspace_id() == "data-science"
    index = json.loads((isolated_roots["data"] / "workspaces" / "index.json").read_text())
    assert index["active_id"] == "data-science"


def test_settings_round_trip(isolated_roots):
    bootstrap()

    workspace.save_settings({"pages": 2, "model": "ollama"})
    loaded = workspace.load_settings()

    assert loaded["defaults"]["pages"] == 2
    assert loaded["defaults"]["model"] == "ollama"


def test_settings_missing_file_returns_empty_defaults(isolated_roots):
    bootstrap()
    assert workspace.load_settings() == {"schema_version": 1, "defaults": {}}


def test_settings_corrupt_file_falls_back_to_empty_defaults(isolated_roots):
    bootstrap()
    config.SETTINGS_PATH.write_text("{not valid json", encoding="utf-8")

    assert workspace.load_settings() == {"schema_version": 1, "defaults": {}}
