"""The vocabulary dictionary: the built-in table plus the user's app-wide additions.

`config.TAG_ALIASES` / `config.VERB_FAMILIES` come from here. The built-in dictionary
(`library_seeds/dictionary.json`) is always on; the user layers additions (new terms, new
spellings of a term, new opening verbs) and hidden built-ins on top, in one app-wide
`libraries/vocabulary.json` under `DATA_ROOT` — shared by every profile, never rebound per
workspace. Built-in entries are never deleted, only hidden; the user's own are removed.

Each workspace's `libraries.json` now holds only its pending/rejected proposals (drafted
from that profile's runs). It used to also select which vocabulary *packs* were enabled
and hold per-profile overrides; `migrate_legacy` folds those overrides (and any
user-authored pack in the old `libraries/packs/` store) into the app-wide additions once.

No vocabulary change rewrites resume data: bullet tags are stored as typed and
canonicalised at match time (`content/bullet_tags.py`), so an alias only ever widens
matching. That is why there is no impact preview or confirmation step any more.

`resolve_effective()` composes the tables and `apply_to_config()` rebinds `config`'s —
always to *new* dict objects, never mutated in place, because `config.verb_family`'s
index cache is invalidated by identity. `reload()` runs from `workspace.bootstrap` /
`workspace.activate` and after every write here.

This module owns no locks: a mutating caller that could race a job holds
`JobQueue.busy()` and `template_ops.LOCK` first, enforced at the routes. Imports `config`
and `library_seeds`; never `llm` or `web`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .. import config, library_seeds
from . import library_models

_MAX_LEN = 120


# --------------------------------------------------------------------------------------
# Paths and I/O
# --------------------------------------------------------------------------------------
def store_root() -> Path:
    """Root of the app-wide vocabulary store, under `DATA_ROOT` (never per-workspace).

    The test seam: `tests/conftest.py` monkeypatches this to a temp directory so a bare
    test run never reads (or is broken by) a real installation's additions.
    """
    return config.DATA_ROOT / "libraries"


def vocabulary_path() -> Path:
    return store_root() / "vocabulary.json"


def workspace_file(workspace_id: str | None = None) -> Path:
    """Path to `libraries.json` for `workspace_id`, or the active workspace if None."""
    if workspace_id is None:
        return config.LIBRARIES_PATH
    return config.workspace_paths(workspace_id)["LIBRARIES_PATH"]


def _read_model[M: BaseModel](path: Path, model: type[M]) -> M:
    """`model` from `path`; missing, unreadable or malformed all degrade to the default."""
    if path.exists():
        try:
            return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError):
            pass
    return model()


def _write_model(path: Path, value: BaseModel) -> None:
    """Atomic write: temp file, then `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    _invalidate_memo()


def read_user_vocabulary() -> library_models.UserVocabulary:
    return _read_model(vocabulary_path(), library_models.UserVocabulary)


def write_user_vocabulary(user: library_models.UserVocabulary) -> None:
    _write_model(vocabulary_path(), user)


def read_workspace_state(workspace_id: str | None = None) -> library_models.WorkspaceLibraryState:
    """Read `libraries.json`. Never raises, like `workspace.load_settings`."""
    return _read_model(workspace_file(workspace_id), library_models.WorkspaceLibraryState)


def write_workspace_state(
    state: library_models.WorkspaceLibraryState, workspace_id: str | None = None
) -> None:
    _write_model(workspace_file(workspace_id), state)


# --------------------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------------------
#: Memoised effective table, keyed by the vocabulary file it was composed from.
_MEMO: dict[Path, library_models.EffectiveLibrary] = {}


def _invalidate_memo() -> None:
    _MEMO.clear()


def _norm(value: str) -> str:
    return value.strip().lower()


def resolve_effective(
    user: library_models.UserVocabulary | None = None,
) -> library_models.EffectiveLibrary:
    """Built-in dictionary − hidden + additions. `user` composes a draft without a write."""
    if user is not None:
        return _compose(user)
    key = vocabulary_path()
    if key not in _MEMO:
        _MEMO[key] = _compose(read_user_vocabulary())
    return _MEMO[key]


def _compose(user: library_models.UserVocabulary) -> library_models.EffectiveLibrary:
    hidden_terms = {_norm(t) for t in user.hidden_terms}
    hidden_aliases = {_norm(a) for a in user.hidden_aliases}
    hidden_verbs = {_norm(v) for v in user.hidden_verbs}
    diagnostics: list[str] = []

    terms = {t for t in library_seeds.load()["terms"] if t not in hidden_terms}
    aliases = {
        alias: term
        for alias, term in library_seeds.builtin_aliases().items()
        if term in terms and alias not in hidden_aliases
    }
    terms |= {_norm(t) for t in user.terms if _norm(t)}
    for raw_alias, raw_term in user.tag_aliases.items():
        alias, term = _norm(raw_alias), _norm(raw_term)
        if alias and term and alias != term:
            aliases[alias] = term
            terms.add(term)
    # Chain repair: an alias whose target is itself an alias key is dropped, keeping every
    # target a fixed point (`config.canonical_tag(v) == v`) whatever the file says.
    keys = set(aliases)
    for alias, term in list(aliases.items()):
        if term in keys:
            diagnostics.append(f"{alias!r} -> {term!r} skipped: {term!r} is itself an alias.")
            del aliases[alias]
    terms -= set(aliases)

    verb_index = {
        verb: family
        for family, verbs in library_seeds.builtin_verb_families().items()
        for verb in verbs
        if verb not in hidden_verbs
    }
    for raw_verb, raw_family in user.verb_families.items():
        verb, family = _norm(raw_verb), _norm(raw_family)
        if verb and family:
            verb_index[verb] = family
    families: dict[str, list[str]] = {}
    for verb, family in verb_index.items():
        families.setdefault(family, []).append(verb)

    return library_models.EffectiveLibrary(
        tag_aliases=aliases,
        verb_families={f: tuple(sorted(v)) for f, v in families.items()},
        verb_index=verb_index,
        terms=frozenset(terms),
        diagnostics=diagnostics,
    )


# --------------------------------------------------------------------------------------
# Edits (each returns the new UserVocabulary; the caller writes and reloads)
# --------------------------------------------------------------------------------------
def _check(value: str, what: str) -> str:
    value = _norm(value)
    if not value:
        raise library_models.LibraryError(f"The {what} cannot be empty.")
    if len(value) > _MAX_LEN:
        raise library_models.LibraryError(f"The {what} is longer than {_MAX_LEN} characters.")
    return value


def add_alias(
    user: library_models.UserVocabulary, alias: str, term: str
) -> library_models.UserVocabulary:
    """Record `alias` as another name for `term` (an existing or brand-new term)."""
    alias, term = _check(alias, "spelling"), _check(term, "term")
    effective = resolve_effective(user)
    term = effective.tag_aliases.get(term, term)  # adding to "py" means adding to "python"
    if alias == term:
        raise library_models.LibraryError(f"{alias!r} is already the term itself.")
    if alias in effective.terms:
        raise library_models.LibraryError(
            f"{alias!r} is its own term in the dictionary, so it can't also be another name."
        )
    current = effective.tag_aliases.get(alias)
    if current is not None and current != term and alias not in user.tag_aliases:
        raise library_models.LibraryError(f"{alias!r} already means {current!r}.")
    return user.model_copy(update={"tag_aliases": {**user.tag_aliases, alias: term}})


def add_term(user: library_models.UserVocabulary, term: str) -> library_models.UserVocabulary:
    term = _check(term, "term")
    effective = resolve_effective(user)
    if term in effective.tag_aliases:
        raise library_models.LibraryError(
            f"{term!r} is already another name for {effective.tag_aliases[term]!r}."
        )
    if term in effective.terms:
        raise library_models.LibraryError(f"{term!r} is already in the dictionary.")
    return user.model_copy(update={"terms": sorted({*user.terms, term})})


def add_verb(
    user: library_models.UserVocabulary, verb: str, family: str
) -> library_models.UserVocabulary:
    verb, family = _check(verb, "verb"), _check(family, "family")
    if not verb.isalpha():
        raise library_models.LibraryError("A verb is a single word of letters only.")
    if family not in resolve_effective(user).verb_families:
        raise library_models.LibraryError(f"Unknown verb family {family!r}.")
    return user.model_copy(update={"verb_families": {**user.verb_families, verb: family}})


def remove_addition(
    user: library_models.UserVocabulary, kind: str, value: str
) -> library_models.UserVocabulary:
    """Delete one of the user's own entries; built-ins can only be hidden."""
    value = _norm(value)
    if kind == "alias" and value in user.tag_aliases:
        return user.model_copy(
            update={"tag_aliases": {k: v for k, v in user.tag_aliases.items() if k != value}}
        )
    if kind == "term" and value in user.terms:
        return user.model_copy(update={
            "terms": [t for t in user.terms if t != value],
            "tag_aliases": {k: v for k, v in user.tag_aliases.items() if v != value},
        })
    if kind == "verb" and value in user.verb_families:
        return user.model_copy(
            update={"verb_families": {k: v for k, v in user.verb_families.items() if k != value}}
        )
    raise library_models.LibraryError(f"{value!r} is not one of your additions.")


_HIDDEN_FIELD = {"term": "hidden_terms", "alias": "hidden_aliases", "verb": "hidden_verbs"}


def _builtin(kind: str) -> set[str]:
    seed = library_seeds.load()
    if kind == "term":
        return set(seed["terms"])
    if kind == "alias":
        return set(library_seeds.builtin_aliases())
    return {v for verbs in seed["verb_families"].values() for v in verbs}


def set_hidden(
    user: library_models.UserVocabulary, kind: str, value: str, hidden: bool
) -> library_models.UserVocabulary:
    """Hide (or show again) one built-in term, spelling or verb."""
    if kind not in _HIDDEN_FIELD:
        raise library_models.LibraryError(f"Unknown entry kind {kind!r}.")
    value = _norm(value)
    if value not in _builtin(kind):
        raise library_models.LibraryError(f"{value!r} is not a built-in {kind}.")
    field = _HIDDEN_FIELD[kind]
    current = set(getattr(user, field))
    current = current | {value} if hidden else current - {value}
    return user.model_copy(update={field: sorted(current)})


# --------------------------------------------------------------------------------------
# Browsing view (the Vocabulary page's searchable list)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Item:
    value: str
    builtin: bool
    hidden: bool


@dataclass(frozen=True)
class Entry:
    kind: str  # "term" | "family"
    name: str
    builtin: bool
    hidden: bool
    items: list[Item]


def dictionary_view() -> list[Entry]:
    """Every term (with its spellings) and verb family, flagged built-in/yours/hidden."""
    user = read_user_vocabulary()
    seed = library_seeds.load()
    hidden_terms, hidden_aliases = set(user.hidden_terms), set(user.hidden_aliases)
    hidden_verbs = set(user.hidden_verbs)

    spellings: dict[str, list[Item]] = {}
    for term, aliases in seed["terms"].items():
        spellings[term] = [Item(a, True, a in hidden_aliases) for a in aliases]
    for alias, term in user.tag_aliases.items():
        spellings.setdefault(term, []).append(Item(alias, False, False))
    for term in user.terms:
        spellings.setdefault(term, [])
    entries = [
        Entry("term", term, term in seed["terms"], term in hidden_terms,
              sorted(items, key=lambda i: i.value))
        for term, items in spellings.items()
    ]

    verbs: dict[str, list[Item]] = {
        family: [Item(v, True, v in hidden_verbs) for v in members]
        for family, members in seed["verb_families"].items()
    }
    for verb, family in user.verb_families.items():
        verbs.setdefault(family, []).append(Item(verb, False, False))
    entries += [
        Entry("family", family, True, False, sorted(items, key=lambda i: i.value))
        for family, items in verbs.items()
    ]
    return sorted(entries, key=lambda e: (e.kind != "term", e.name))


# --------------------------------------------------------------------------------------
# One-time migration from vocabulary packs
# --------------------------------------------------------------------------------------
def migrate_legacy() -> list[str]:
    """Fold every workspace's pack-era overrides and user-authored packs into the
    app-wide additions. Idempotent (`migrated_workspaces`, `packs/` renamed once done).

    Enabled packs need no migration: every shipped pack is part of the dictionary now.
    A shipped pack the user had edited is folded like a user-authored one — its extra
    aliases/verbs become additions; edits that *removed* a shipped entry can't be told
    apart from the merge and are reported instead.
    """
    user = read_user_vocabulary()
    notes: list[str] = []
    changed = False
    builtin_aliases = library_seeds.builtin_aliases()
    builtin_verbs = {
        v: f for f, vs in library_seeds.builtin_verb_families().items() for v in vs
    }

    def fold(aliases: dict[str, str], verbs: dict[str, str], source: str) -> None:
        nonlocal user, changed
        for raw_alias, raw_term in aliases.items():
            alias, term = _norm(raw_alias), _norm(raw_term)
            if not alias or not term or builtin_aliases.get(alias) == term:
                continue
            existing = user.tag_aliases.get(alias)
            if existing and existing != term:
                notes.append(f"{source}: kept {alias!r} -> {existing!r} over {term!r}.")
                continue
            user = user.model_copy(update={"tag_aliases": {**user.tag_aliases, alias: term}})
            changed = True
        for raw_verb, raw_family in verbs.items():
            verb, family = _norm(raw_verb), _norm(raw_family)
            if verb and family and builtin_verbs.get(verb) != family:
                user = user.model_copy(
                    update={"verb_families": {**user.verb_families, verb: family}}
                )
                changed = True

    workspaces_dir = store_root().parent / config.WORKSPACES_DIRNAME
    candidates = sorted(workspaces_dir.glob("*/libraries.json")) if workspaces_dir.exists() else []
    for path in candidates:
        workspace_id = path.parent.name
        if workspace_id in user.migrated_workspaces:
            continue
        state = _read_model(path, library_models.WorkspaceLibraryState)
        legacy = state.overrides
        fold(legacy.tag_aliases, legacy.verb_families, f"profile {workspace_id}")
        removed = [a for a in legacy.tag_aliases_removed if _norm(a) in builtin_aliases]
        verbs_removed = [v for v in legacy.verb_families_removed if _norm(v) in builtin_verbs]
        if removed or verbs_removed:
            user = user.model_copy(update={
                "hidden_aliases": sorted({*user.hidden_aliases, *map(_norm, removed)}),
                "hidden_verbs": sorted({*user.hidden_verbs, *map(_norm, verbs_removed)}),
            })
        user = user.model_copy(
            update={"migrated_workspaces": [*user.migrated_workspaces, workspace_id]}
        )
        changed = True
        if state.enabled_packs or legacy != library_models.LegacyOverrides():
            _write_model(path, state.model_copy(update={
                "enabled_packs": [], "overrides": library_models.LegacyOverrides(),
            }))

    packs_dir = store_root() / "packs"
    if packs_dir.is_dir():
        for child in sorted(packs_dir.glob("*.json")):
            try:
                raw = json.loads(child.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                notes.append(f"pack {child.stem}: unreadable, skipped.")
                continue
            verbs = {
                v: family for family, vs in raw.get("verb_families", {}).items() for v in vs
            }
            fold(raw.get("tag_aliases", {}), verbs, f"pack {child.stem}")
        shutil.move(str(packs_dir), str(store_root() / "packs.migrated"))

    if changed:
        write_user_vocabulary(user)
    return notes


# --------------------------------------------------------------------------------------
# Fingerprint, apply, reload, reset
# --------------------------------------------------------------------------------------
def effective_fingerprint(effective: library_models.EffectiveLibrary | None = None) -> str:
    """Digest of the composed tables, for `propose.py`'s cache key."""
    eff = effective if effective is not None else resolve_effective()
    payload = "\n".join([
        *(f"a:{k}={v}" for k, v in sorted(eff.tag_aliases.items())),
        *(f"t:{t}" for t in sorted(eff.terms)),
        *(f"v:{verb}={family}" for verb, family in sorted(eff.verb_index.items())),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def apply_to_config() -> library_models.EffectiveLibrary:
    """Rebind `config.TAG_ALIASES` / `config.VERB_FAMILIES` to new dicts (never mutate)."""
    effective = resolve_effective()
    config.set_vocabulary(dict(effective.tag_aliases), dict(effective.verb_families))
    return effective


def reload() -> library_models.EffectiveLibrary:
    """Run the one-time migration if needed, drop the memo, and rebind `config`'s tables."""
    # A read-only or half-written store must never block startup.
    with contextlib.suppress(OSError):
        migrate_legacy()
    _invalidate_memo()
    return apply_to_config()


def reset() -> None:
    """Restore `config`'s tables to the built-in dictionary. Test seam — pairs with
    monkeypatching `store_root` in `tests/conftest.py`."""
    _invalidate_memo()
    config.set_vocabulary(library_seeds.builtin_aliases(), library_seeds.builtin_verb_families())
