"""Tests for `libraries.py`: the dictionary + app-wide additions, hiding, the one-time
pack migration, and the fingerprint.

`tests/conftest.py`'s autouse `_isolated_libraries` redirects `libraries.store_root()`
into a fresh `tmp_path` and calls `libraries.reset()` around every test, so each starts
from the built-in dictionary alone — the same default a fresh install has.
"""

from __future__ import annotations

import json

import pytest

from resume_tailor import config, library_seeds
from resume_tailor.content import libraries, library_models

UV = library_models.UserVocabulary


def _save(user: library_models.UserVocabulary) -> None:
    libraries.write_user_vocabulary(user)
    libraries.reload()


# --------------------------------------------------------------------------------------
# Defaults and read tolerance
# --------------------------------------------------------------------------------------
def test_defaults_equal_the_builtin_dictionary():
    eff = libraries.resolve_effective()
    assert eff.tag_aliases == library_seeds.builtin_aliases()
    assert eff.terms == frozenset(library_seeds.load()["terms"])
    assert eff.diagnostics == []


def test_corrupt_vocabulary_file_degrades_to_defaults():
    libraries.vocabulary_path().parent.mkdir(parents=True)
    libraries.vocabulary_path().write_text("{not json", encoding="utf-8")
    assert libraries.read_user_vocabulary() == UV()


def test_old_workspace_file_still_validates():
    path = libraries.workspace_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled_packs": ["core-tech"], "overrides": {}}), "utf-8")
    assert libraries.read_workspace_state().enabled_packs == ["core-tech"]


# --------------------------------------------------------------------------------------
# Additions
# --------------------------------------------------------------------------------------
def test_add_alias_to_an_existing_term():
    _save(libraries.add_alias(UV(), "Postgres", "postgresql"))
    assert config.canonical_tag("postgres") == "postgresql"


def test_add_alias_through_an_alias_lands_on_its_term():
    user = libraries.add_alias(UV(), "python3", "py")
    assert user.tag_aliases == {"python3": "python"}


def test_add_alias_creates_a_new_term():
    _save(libraries.add_alias(UV(), "qxw", "quuxware"))
    assert "quuxware" in libraries.resolve_effective().terms
    assert config.canonical_tag("QXW") == "quuxware"


def test_add_alias_refuses_a_term_and_a_conflicting_builtin():
    with pytest.raises(library_models.LibraryError):
        libraries.add_alias(UV(), "python", "java")
    with pytest.raises(library_models.LibraryError, match="already means"):
        libraries.add_alias(UV(), "py", "pytorch")


def test_add_alias_may_retarget_the_users_own_alias():
    user = libraries.add_alias(UV(), "sql", "mysql")
    user = libraries.add_alias(user, "sql", "postgresql")
    assert user.tag_aliases == {"sql": "postgresql"}


def test_add_term_and_refusals():
    user = libraries.add_term(UV(), "Quuxware")
    assert user.terms == ["quuxware"]
    with pytest.raises(library_models.LibraryError):
        libraries.add_term(user, "quuxware")
    with pytest.raises(library_models.LibraryError, match="another name"):
        libraries.add_term(UV(), "py")


def test_add_verb_requires_a_known_family_and_letters():
    _save(libraries.add_verb(UV(), "zorped", "build"))
    assert config.verb_family("zorped") == "build"
    with pytest.raises(library_models.LibraryError):
        libraries.add_verb(UV(), "zorped", "nope")
    with pytest.raises(library_models.LibraryError):
        libraries.add_verb(UV(), "re-built", "build")


def test_remove_addition_only_removes_the_users_own():
    user = libraries.add_term(libraries.add_alias(UV(), "qxw", "quuxware"), "flarnhub")
    assert libraries.remove_addition(user, "alias", "qxw").tag_aliases == {}
    assert libraries.remove_addition(user, "term", "flarnhub").terms == []
    with pytest.raises(library_models.LibraryError, match="not one of your additions"):
        libraries.remove_addition(user, "alias", "py")


def test_removing_a_term_that_only_an_alias_created():
    user = libraries.add_alias(UV(), "sql", "mysql")
    assert libraries.remove_addition(user, "term", "mysql").tag_aliases == {}


def test_removing_a_term_drops_its_aliases():
    user = libraries.add_alias(libraries.add_term(UV(), "quuxware"), "qxw", "quuxware")
    assert libraries.remove_addition(user, "term", "quuxware").tag_aliases == {}


# --------------------------------------------------------------------------------------
# Hiding built-ins
# --------------------------------------------------------------------------------------
def test_hiding_a_builtin_alias_and_showing_it_again():
    _save(libraries.set_hidden(UV(), "alias", "py", True))
    assert config.canonical_tag("py") == "py"
    _save(libraries.set_hidden(libraries.read_user_vocabulary(), "alias", "py", False))
    assert config.canonical_tag("py") == "python"


def test_hiding_a_term_hides_its_aliases_and_detection():
    eff = libraries.resolve_effective(libraries.set_hidden(UV(), "term", "python", True))
    assert "python" not in eff.terms
    assert "py" not in eff.tag_aliases


def test_hiding_a_builtin_verb():
    _save(libraries.set_hidden(UV(), "verb", "designed", True))
    assert config.verb_family("designed") is None


def test_only_builtins_can_be_hidden():
    with pytest.raises(library_models.LibraryError, match="not a built-in"):
        libraries.set_hidden(UV(), "alias", "qxw", True)


# --------------------------------------------------------------------------------------
# Composition safety
# --------------------------------------------------------------------------------------
def test_a_hand_edited_chain_is_dropped_with_a_diagnostic():
    eff = libraries.resolve_effective(UV(tag_aliases={"pyy": "py"}))
    assert "pyy" not in eff.tag_aliases
    assert eff.diagnostics


def test_writes_invalidate_the_memo_but_leave_config_unrebound():
    libraries.write_user_vocabulary(UV(tag_aliases={"x": "y"}))
    assert "x" in libraries.resolve_effective().tag_aliases
    assert "x" not in config.TAG_ALIASES
    libraries.reload()
    assert config.TAG_ALIASES.get("x") == "y"


def test_reset_restores_the_builtin_dictionary():
    _save(UV(tag_aliases={"x": "y"}))
    libraries.reset()
    assert library_seeds.builtin_aliases() == config.TAG_ALIASES


def test_effective_fingerprint_changes_with_additions():
    before = libraries.effective_fingerprint()
    libraries.write_user_vocabulary(UV(terms=["quuxware"]))
    assert libraries.effective_fingerprint() != before


# --------------------------------------------------------------------------------------
# Browsing view
# --------------------------------------------------------------------------------------
def test_dictionary_view_flags_builtin_yours_and_hidden():
    _save(libraries.set_hidden(libraries.add_alias(UV(), "python3", "python"), "alias", "py", True))
    python = next(e for e in libraries.dictionary_view() if e.name == "python")
    flags = {i.value: (i.builtin, i.hidden) for i in python.items}
    assert flags["py"] == (True, True)
    assert flags["python3"] == (False, False)
    assert any(e.kind == "family" and e.name == "build" for e in libraries.dictionary_view())


# --------------------------------------------------------------------------------------
# One-time migration from packs
# --------------------------------------------------------------------------------------
def _legacy_workspace(workspace_id: str, payload: dict) -> None:
    path = libraries.store_root().parent / config.WORKSPACES_DIRNAME / workspace_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "libraries.json").write_text(json.dumps(payload), encoding="utf-8")


def test_migration_folds_every_profiles_overrides_once():
    _legacy_workspace("default", {
        "enabled_packs": ["core-tech"],
        "overrides": {"tag_aliases": {"sql": "mysql"}, "verb_families": {"zorped": "build"},
                      "tag_aliases_removed": ["py"]},
    })
    _legacy_workspace("nina", {"enabled_packs": ["core-tech", "marketing"]})
    libraries.reload()

    user = libraries.read_user_vocabulary()
    assert user.tag_aliases == {"sql": "mysql"}
    assert user.verb_families == {"zorped": "build"}
    assert user.hidden_aliases == ["py"]
    assert sorted(user.migrated_workspaces) == ["default", "nina"]
    assert config.canonical_tag("sql") == "mysql"
    cleared = json.loads(
        (libraries.store_root().parent / "workspaces" / "default" / "libraries.json").read_text()
    )
    assert cleared["overrides"]["tag_aliases"] == {} and cleared["enabled_packs"] == []

    libraries.reload()  # idempotent
    assert libraries.read_user_vocabulary() == user


def test_migration_folds_user_authored_packs_and_renames_the_store():
    packs = libraries.store_root() / "packs"
    packs.mkdir(parents=True)
    (packs / "nursing.json").write_text(json.dumps({
        "id": "nursing", "label": "Nursing",
        "tag_aliases": {"bls": "basic life support", "py": "python"},
        "verb_families": {"care": ["triaged"]},
    }), encoding="utf-8")
    libraries.reload()

    user = libraries.read_user_vocabulary()
    assert user.tag_aliases == {"bls": "basic life support"}  # "py" was already built in
    assert user.verb_families == {"triaged": "care"}
    assert not packs.exists() and (libraries.store_root() / "packs.migrated").is_dir()
