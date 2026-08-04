"""Tests for `libraries.py`: pack storage, composition, validation, and the
tag-alias/verb-family fingerprint.

`tests/conftest.py`'s autouse `_isolated_libraries` fixture redirects
`libraries.store_root()` and `config.DATA_DIR` into a fresh `tmp_path` for every test
and calls `libraries.reset()` before and after, so every test here starts from the
built-in `core-tech` pack alone with no on-disk state — the same default a fresh
install has.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from resume_tailor import config, data, libraries, library_seeds


def _pack(pack_id: str, **kwargs) -> libraries.Pack:
    fields = {
        "id": pack_id,
        "label": kwargs.pop("label", pack_id.title()),
        "tag_aliases": {},
        "verb_families": {},
    }
    fields.update(kwargs)
    return libraries.Pack(**fields)


def _resume_with_tags(*tags: str) -> data.MasterResume:
    return data.MasterResume.model_validate(
        {
            "contact": {"name": "Test User", "email": "test@example.com"},
            "experience": [
                {
                    "company": "Acme",
                    "title": "Engineer",
                    "start": "2020",
                    "end": "2021",
                    "bullets": [{"id": "b1", "text": "Did a thing.", "tags": list(tags)}],
                }
            ],
        }
    )


# --------------------------------------------------------------------------------------
# Defaults and read tolerance
# --------------------------------------------------------------------------------------


def test_defaults_equal_the_builtin_tables():
    eff = libraries.resolve_effective()
    core = library_seeds.BUILTIN_PACKS["core-tech"]
    assert eff.tag_aliases == core["tag_aliases"]
    assert set(eff.verb_families) == set(core["verb_families"])
    for family, verbs in core["verb_families"].items():
        assert set(eff.verb_families[family]) == set(verbs)
    assert eff.diagnostics == []


def test_corrupt_workspace_file_degrades_to_defaults():
    path = libraries.workspace_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    state = libraries.read_workspace_state()

    assert state.enabled_packs == ["core-tech"]
    assert state.overrides.tag_aliases == {}


def test_missing_workspace_file_returns_defaults():
    assert not libraries.workspace_file().exists()
    state = libraries.read_workspace_state()
    assert state == libraries.WorkspaceLibraryState()


def test_missing_pack_id_is_skipped_with_a_diagnostic():
    state = libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "ghost"])
    libraries.write_workspace_state(state)

    eff = libraries.resolve_effective()

    assert eff.tag_aliases == library_seeds.BUILTIN_PACKS["core-tech"]["tag_aliases"]
    assert any("ghost" in d for d in eff.diagnostics)


# --------------------------------------------------------------------------------------
# Composition order
# --------------------------------------------------------------------------------------


def test_pack_order_decides_alias_precedence():
    libraries.write_pack(_pack("a", tag_aliases={"x": "alpha"}))
    libraries.write_pack(_pack("b", tag_aliases={"x": "beta"}))

    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["a", "b"])
    )
    assert libraries.resolve_effective().tag_aliases["x"] == "beta"

    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["b", "a"])
    )
    assert libraries.resolve_effective().tag_aliases["x"] == "alpha"


def test_pack_order_decides_verb_precedence():
    libraries.write_pack(_pack("a", verb_families={"care": ["administered"]}))
    libraries.write_pack(_pack("b", verb_families={"operate": ["administered"]}))

    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["a", "b"])
    )
    assert libraries.resolve_effective().verb_index["administered"] == "operate"

    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["b", "a"])
    )
    assert libraries.resolve_effective().verb_index["administered"] == "care"


def test_cross_pack_verb_collision_is_a_diagnostic_not_an_error():
    libraries.write_pack(_pack("a", verb_families={"care": ["administered"]}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a"])
    )

    eff = libraries.resolve_effective()

    assert eff.verb_index["administered"] == "care"
    assert any("administered" in d for d in eff.diagnostics)


def test_removals_win_over_additions():
    state = libraries.WorkspaceLibraryState(
        enabled_packs=["core-tech"],
        overrides=libraries.LibraryOverrides(
            tag_aliases={"foo": "bar"},
            tag_aliases_removed=["foo", "py"],
            verb_families={"triaged": "analyse"},
            verb_families_removed=["triaged", "designed"],
        ),
    )
    libraries.write_workspace_state(state)

    eff = libraries.resolve_effective()

    assert "foo" not in eff.tag_aliases
    assert "py" not in eff.tag_aliases
    assert "triaged" not in eff.verb_index
    assert "designed" not in eff.verb_index


def test_overrides_win_over_packs():
    state = libraries.WorkspaceLibraryState(
        enabled_packs=["core-tech"],
        overrides=libraries.LibraryOverrides(tag_aliases={"py": "override-target"}),
    )
    libraries.write_workspace_state(state)

    assert libraries.resolve_effective().tag_aliases["py"] == "override-target"


def test_resolver_drops_a_chain():
    """Two packs, each individually valid against the baseline at the moment it was
    written, can still compose into a chain once *both* are enabled together —
    `validate_pack` only checks a pack against what is enabled *at write time*, so this
    is a case its checks cannot catch and `resolve_effective`'s own repair must.

    Every alias value must remain a fixed point of canonical_tag, the same invariant
    `test_config.py::test_no_transitive_alias_resolution` pins for the built-in table.
    """
    libraries.write_pack(_pack("a", tag_aliases={"foo": "bar"}))
    libraries.write_pack(_pack("b", tag_aliases={"bar": "baz"}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a", "b"])
    )

    eff = libraries.resolve_effective()

    # foo -> bar -> baz would be a two-hop chain; foo -> bar must be dropped so every
    # surviving value (here, "baz") is a fixed point.
    assert "foo" not in eff.tag_aliases
    assert eff.tag_aliases["bar"] == "baz"
    for value in eff.tag_aliases.values():
        assert value not in eff.tag_aliases
    assert any("chain" in d.lower() for d in eff.diagnostics)


# --------------------------------------------------------------------------------------
# Pack CRUD
# --------------------------------------------------------------------------------------


def test_write_pack_refuses_a_builtin_id():
    with pytest.raises(libraries.LibraryError):
        libraries.write_pack(_pack("core-tech"))


def test_delete_pack_refuses_a_builtin_id():
    with pytest.raises(libraries.LibraryError):
        libraries.delete_pack("core-tech")


def test_delete_pack_refuses_an_unknown_id():
    with pytest.raises(libraries.LibraryError):
        libraries.delete_pack("nonexistent")


def test_read_pack_raises_for_an_unknown_id():
    with pytest.raises(libraries.LibraryError):
        libraries.read_pack("nonexistent")


def test_list_packs_includes_builtin_and_user_packs():
    libraries.write_pack(_pack("nursing", label="Nursing"))

    ids = {p.id for p in libraries.list_packs()}

    assert "core-tech" in ids
    assert "nursing" in ids
    core = next(p for p in libraries.list_packs() if p.id == "core-tech")
    assert core.builtin is True
    nursing = next(p for p in libraries.list_packs() if p.id == "nursing")
    assert nursing.builtin is False


def test_write_pack_is_atomic():
    libraries.write_pack(_pack("a", tag_aliases={"x": "y"}))

    packs_dir = libraries.store_root() / "packs"
    tmp_files = list(packs_dir.glob("*.tmp"))

    assert tmp_files == []
    assert (packs_dir / "a.json").exists()


def test_write_pack_preserves_created_at_across_an_update():
    written = libraries.write_pack(_pack("a", tag_aliases={"x": "y"}))
    created_at = written.created_at
    assert created_at

    updated = libraries.write_pack(_pack("a", tag_aliases={"x": "y", "p": "q"}))

    assert updated.created_at == created_at
    assert updated.updated_at >= created_at


def test_updating_an_enabled_pack_does_not_conflict_with_its_own_prior_version():
    """Regression: `validate_pack`'s default baseline is `resolve_effective()`, which
    (before `write_pack` started excluding the pack being written) still contained the
    pack's own *old* contents while it was enabled — so re-saving an enabled pack with
    a tweaked value for an existing key always looked like a conflict with itself and
    needed `force=True` just to keep going."""
    libraries.write_pack(_pack("a", tag_aliases={"x": "y"}))
    libraries.write_workspace_state(libraries.WorkspaceLibraryState(enabled_packs=["a"]))
    assert libraries.resolve_effective().tag_aliases["x"] == "y"

    updated = libraries.write_pack(_pack("a", tag_aliases={"x": "z"}))

    assert updated.tag_aliases["x"] == "z"


def test_new_pack_id_avoids_existing_ids():
    existing = {p.id for p in libraries.list_packs()}
    assert "core-tech" in existing

    new_id = libraries.new_pack_id("Core Tech", existing=existing)

    assert new_id != "core-tech"


def test_deleting_an_enabled_pack_degrades_to_a_diagnostic_not_a_crash():
    libraries.write_pack(_pack("a", tag_aliases={"x": "y"}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a"])
    )
    assert libraries.resolve_effective().tag_aliases["x"] == "y"

    libraries.delete_pack("a")

    eff = libraries.resolve_effective()
    assert "x" not in eff.tag_aliases
    assert any("a" in d for d in eff.diagnostics)


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_validate_rejects_self_alias():
    errors = libraries.validate_pack(_pack("a", tag_aliases={"python": "python"}))
    assert any("maps to itself" in e for e in errors)


def test_validate_rejects_a_chain_within_one_pack():
    errors = libraries.validate_pack(
        _pack("a", tag_aliases={"x": "y", "y": "z"})
    )
    assert any("chains" in e for e in errors)


def test_validate_rejects_a_verb_in_two_families_within_one_pack():
    errors = libraries.validate_pack(
        _pack("a", verb_families={"build": ["led"], "lead": ["led"]})
    )
    assert any("led" in e and "both" in e for e in errors)


def test_validate_rejects_an_empty_alias_key():
    errors = libraries.validate_pack(_pack("a", tag_aliases={"": "python"}))
    assert any("non-empty" in e for e in errors)


def test_validate_rejects_a_non_alpha_verb():
    errors = libraries.validate_pack(_pack("a", verb_families={"build": ["re-factored"]}))
    assert any("alphabetic" in e for e in errors)


def test_validate_rejects_a_key_that_is_already_an_effective_value():
    # core-tech already has "ml" -> "machine learning", so "machine learning" is an
    # effective value; using it as a new key would create a two-hop cycle.
    errors = libraries.validate_pack(_pack("a", tag_aliases={"machine learning": "ml"}))
    assert any("already used as an alias target" in e for e in errors)


def test_validate_rejects_a_value_that_is_already_an_effective_key():
    errors = libraries.validate_pack(_pack("a", tag_aliases={"foo": "ml"}))
    assert any("already an alias key" in e for e in errors)


def test_validate_rejects_a_conflicting_target_without_force():
    errors = libraries.validate_pack(_pack("a", tag_aliases={"py": "not-python"}))
    assert any("force=true" in e for e in errors)


def test_validate_allows_a_conflicting_target_with_force():
    errors = libraries.validate_pack(
        _pack("a", tag_aliases={"py": "not-python"}), force=True
    )
    assert errors == []


def test_write_pack_raises_library_validation_error_with_every_message():
    with pytest.raises(libraries.LibraryValidationError) as excinfo:
        libraries.write_pack(_pack("a", tag_aliases={"python": "python"}))
    assert excinfo.value.errors
    assert any("maps to itself" in e for e in excinfo.value.errors)


def test_pack_id_must_match_the_slug_pattern():
    with pytest.raises(libraries.LibraryError):
        libraries.write_pack(_pack("Not A Valid Id!"))


# --------------------------------------------------------------------------------------
# apply_to_config / reload / reset
# --------------------------------------------------------------------------------------


def test_apply_to_config_rebinds_both_tables_and_invalidates_the_verb_index():
    libraries.write_pack(_pack("a", verb_families={"custom": ["zorped"]}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a"])
    )

    libraries.apply_to_config()

    assert config.verb_family("zorped") == "custom"
    assert config.verb_family("designed") == "build"


def test_writes_invalidate_the_memo_but_leave_config_unrebound():
    """`write_pack`/`write_workspace_state` bust the memo (so `resolve_effective()`
    never serves a stale result) but do not touch `config.TAG_ALIASES` — only
    `reload()`/`apply_to_config()` do that. The two are deliberately separate: a write
    should never silently change what the running pipeline uses until something calls
    `reload()`, e.g. from a route, after the caller has decided the write should take
    effect immediately."""
    libraries.write_pack(_pack("a", tag_aliases={"x": "y"}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a"])
    )

    assert "x" in libraries.resolve_effective().tag_aliases
    assert "x" not in config.TAG_ALIASES

    libraries.reload()

    assert "x" in config.TAG_ALIASES
    assert config.TAG_ALIASES.get("x") == "y"


def test_reset_restores_the_builtin_table_only():
    libraries.write_pack(_pack("a", tag_aliases={"x": "y"}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a"])
    )
    libraries.reload()
    assert "x" in config.TAG_ALIASES

    libraries.reset()

    assert config.TAG_ALIASES == library_seeds.BUILTIN_PACKS["core-tech"]["tag_aliases"]
    assert "x" not in config.TAG_ALIASES


# --------------------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------------------


def test_effective_fingerprint_is_stable_under_key_reordering():
    reordered = dict(reversed(list(library_seeds.BUILTIN_PACKS["core-tech"]["tag_aliases"].items())))
    a = libraries.effective_fingerprint(
        libraries.EffectiveLibrary(
            tag_aliases=library_seeds.BUILTIN_PACKS["core-tech"]["tag_aliases"],
            verb_families={},
            verb_index={},
            diagnostics=[],
        )
    )
    b = libraries.effective_fingerprint(
        libraries.EffectiveLibrary(
            tag_aliases=reordered, verb_families={}, verb_index={}, diagnostics=[]
        )
    )
    assert a == b


def test_effective_fingerprint_changes_when_aliases_change():
    before = libraries.effective_fingerprint()
    libraries.write_pack(_pack("a", tag_aliases={"x": "y"}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a"])
    )
    after = libraries.effective_fingerprint()
    assert before != after


# --------------------------------------------------------------------------------------
# Alias impact
# --------------------------------------------------------------------------------------


def test_alias_impact_distinguishes_additive_from_rewriting():
    resume = _resume_with_tags("python", "docker")

    impacts = libraries.alias_impact({"rust": "rust-lang", "python": "py-lang"}, resume=resume)
    by_alias = {i.alias: i for i in impacts}

    assert by_alias["rust"].affected_tags == []
    assert by_alias["rust"].affected_bullets == []

    assert by_alias["python"].affected_tags == ["python"]
    assert by_alias["python"].affected_bullets == [("Acme", "b1")]


def test_alias_impact_missing_resume_returns_additive_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", tmp_path / "no-such-resume.json")

    impacts = libraries.alias_impact({"x": "y"})

    assert impacts == [
        libraries.AliasImpact(alias="x", canonical="y", affected_tags=[], affected_bullets=[])
    ]
