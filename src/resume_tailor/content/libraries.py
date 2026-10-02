"""Vocabulary libraries: user-editable tag-alias and verb-family packs.

`config.TAG_ALIASES` / `config.VERB_FAMILIES` used to be hardcoded literals — this module
is what makes them data instead. A **pack** (`Pack`) is a named bundle of aliases and verb
families, either shipped (`library_seeds/` JSON bundled in the package) or user-authored
(`data/libraries/packs/<id>.json`, the central store — under `DATA_ROOT`, which
`config.set_active_workspace` never rebinds, so it is shared across every profile and
survives the Docker bind mount). Each workspace selects which packs are enabled and may
hold its own alias/verb overrides, in `data/workspaces/<id>/libraries.json`
(`workspace_file`).

`resolve_effective()` composes enabled packs (in list order, last wins) plus overrides
into the tables the rest of the pipeline actually reads, and `apply_to_config()` rebinds
`config.TAG_ALIASES` / `config.VERB_FAMILIES` to the result — always to a *new* dict
object, never mutated in place, because `config.verb_family`'s index cache is invalidated
by identity. `reload()` is called from `workspace.bootstrap` / `workspace.activate` right
after `config.set_active_workspace(...)`, and from every mutating route in this module's
web-layer callers, after the write.

This module owns no locks. It inherits `config.set_active_workspace`'s contract: a caller
that mutates state here while a job or template operation could be touching the same
workspace must hold `JobQueue.busy()` and `template_ops.LOCK` first — enforced at the
routes, not here. Imports `config`, `library_seeds`, and `data` (for `alias_impact`, which
needs to read the master resume); never `llm` or `web`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .. import config, library_seeds
from . import library_models

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

_PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def store_root() -> Path:
    """Root of the central pack store, under `DATA_ROOT` (never rebound per-workspace).

    The test seam: `tests/conftest.py` monkeypatches this to a temp directory so a bare
    test run never reads (or is broken by) a real installation's approved packs.
    """
    return config.DATA_ROOT / "libraries"


def _index_path() -> Path:
    return store_root() / "index.json"


def _pack_path(pack_id: str) -> Path:
    """The on-disk path for `pack_id`'s shadow file.

    Every read/write/delete/reset of a pack funnels through here, so this is the one
    place `_PACK_ID_RE` needs enforcing to cover all of them — previously only
    `write_pack`/`new_pack_id` checked it. Not just POSIX traversal (a `/`-containing
    id can't reach a route param, and pack ids never arrive in a JSON body): on Windows,
    `PureWindowsPath('.../packs') / 'C:foo'` discards the left side entirely and
    resolves to `C:foo.json`, so an unvalidated id here is a drive-relative escape,
    not merely a same-directory one.
    """
    if not _PACK_ID_RE.match(pack_id):
        raise library_models.LibraryError(f"Invalid pack id: {pack_id!r}")
    return store_root() / "packs" / f"{pack_id}.json"


def workspace_file(workspace_id: str | None = None) -> Path:
    """Path to `libraries.json` for `workspace_id`, or the active workspace if None.

    Mirrors `workspace.settings_path`'s shape exactly.
    """
    if workspace_id is None:
        return config.LIBRARIES_PATH
    return config.workspace_paths(workspace_id)["LIBRARIES_PATH"]


def new_pack_id(label: str, *, existing: Iterable[str]) -> str:
    """A filesystem-friendly id derived from `label`, unique against `existing`.

    Mirrors `workspace.new_workspace_id`. `existing` should include built-in pack ids
    (`list_packs()` supplies both) so a new pack can never shadow `core-tech`.
    """
    existing_set = set(existing)
    base = config.slugify(label) or "pack"
    if base not in existing_set and _PACK_ID_RE.match(base):
        return base
    candidate = f"{base}-{secrets.token_hex(2)}"
    while candidate in existing_set or not _PACK_ID_RE.match(candidate):
        candidate = f"{base}-{secrets.token_hex(2)}"
    return candidate


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------------------
# Pack registry I/O
# --------------------------------------------------------------------------------------


def _read_pack_index() -> library_models._PackIndex:
    path = _index_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            try:
                return library_models._PackIndex.model_validate(raw)
            except ValidationError:
                pass
    return _rebuild_pack_index()


def _rebuild_pack_index() -> library_models._PackIndex:
    """Recover the registry by scanning `packs/*.json`, the `workspace._rebuild_index`
    precedent for a lost or corrupt `index.json`."""
    packs_dir = store_root() / "packs"
    entries: list[library_models._PackIndexEntry] = []
    if packs_dir.exists():
        for child in sorted(packs_dir.glob("*.json")):
            try:
                raw = json.loads(child.read_text(encoding="utf-8"))
                pack = library_models.Pack.model_validate(raw)
            except (OSError, json.JSONDecodeError, ValidationError):
                continue
            if pack.id != child.stem:
                continue
            entries.append(
                library_models._PackIndexEntry(
                    id=pack.id,
                    label=pack.label,
                    description=pack.description,
                    created_at=pack.created_at,
                    updated_at=pack.updated_at,
                )
            )
    index = library_models._PackIndex(packs=entries)
    if entries:
        _write_pack_index(index)
    return index


def _write_pack_index(index: library_models._PackIndex) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(index.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------------------
# Pack CRUD
# --------------------------------------------------------------------------------------


def _pack_from_seed(seed: library_seeds.Pack) -> library_models.Pack:
    return library_models.Pack(
        id=seed["id"],
        label=seed["label"],
        description=seed.get("description", ""),
        tag_aliases=dict(seed["tag_aliases"]),
        verb_families={family: list(verbs) for family, verbs in seed["verb_families"].items()},
    )


def is_builtin_pack(pack_id: str) -> bool:
    """Whether `pack_id` names a shipped (package-bundled) pack rather than a
    user-authored one. Lets `web/app.py` report this without importing
    `library_seeds` itself."""
    return pack_id in library_seeds.shipped_pack_ids()


def is_customized_pack(pack_id: str) -> bool:
    """Whether a store file shadows the shipped copy for `pack_id`."""
    return _pack_path(pack_id).exists()


def read_pack(pack_id: str) -> library_models.Pack:
    """A shipped or user-authored pack by id. Store file wins over the shipped seed.
    Raises `LibraryError` if neither exists."""
    path = _pack_path(pack_id)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return library_models.Pack.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise library_models.LibraryError(f"Pack {pack_id!r} is corrupt: {exc}") from exc
    seed = library_seeds.BUILTIN_PACKS.get(pack_id)
    if seed is not None:
        return _pack_from_seed(seed)
    raise library_models.LibraryError(f"Unknown pack: {pack_id!r}")


def list_packs() -> list[library_models.PackMeta]:
    """Shipped packs first (via `read_pack` so shadows show edited counts), then
    user-authored packs from the registry not already listed.

    A registry entry whose pack file has since gone missing or corrupt is skipped
    rather than raised — a listing must not crash the whole Settings tab over one bad
    pack; `resolve_effective` is where a *selected* missing pack becomes a diagnostic.
    """
    out: list[library_models.PackMeta] = []
    seen: set[str] = set()

    for seed in library_seeds.BUILTIN_PACKS.values():
        pack_id = seed["id"]
        seen.add(pack_id)
        try:
            pack = read_pack(pack_id)
        except library_models.LibraryError:
            continue
        out.append(
            library_models.PackMeta(
                id=pack.id,
                label=pack.label,
                description=pack.description,
                builtin=True,
                customized=is_customized_pack(pack_id),
                tag_alias_count=len(pack.tag_aliases),
                verb_count=sum(len(v) for v in pack.verb_families.values()),
                created_at=pack.created_at,
                updated_at=pack.updated_at,
            )
        )

    for entry in _read_pack_index().packs:
        if entry.id in seen:
            continue
        try:
            pack = read_pack(entry.id)
        except library_models.LibraryError:
            continue
        seen.add(pack.id)
        out.append(
            library_models.PackMeta(
                id=pack.id,
                label=pack.label,
                description=pack.description,
                builtin=False,
                customized=False,
                tag_alias_count=len(pack.tag_aliases),
                verb_count=sum(len(v) for v in pack.verb_families.values()),
                created_at=pack.created_at,
                updated_at=pack.updated_at,
            )
        )
    return out


def write_pack(pack: library_models.Pack, *, force: bool = False) -> library_models.Pack:
    """Validate and atomically write a pack to the store. Shipped ids are allowed —
    the write creates or updates a shadow file that `read_pack` prefers over the seed.

    Preserves `created_at` across an update by reading the existing file first; sets
    both timestamps on a brand-new pack. Returns the pack actually written (with
    timestamps filled in), not the input.
    """
    if not _PACK_ID_RE.match(pack.id):
        raise library_models.LibraryError(
            f"Invalid pack id {pack.id!r}: must match {_PACK_ID_RE.pattern!r}."
        )

    baseline = resolve_effective(exclude_pack_id=pack.id)
    errors = validate_pack(pack, against=baseline, force=force)
    if errors:
        raise library_models.LibraryValidationError(errors)

    now = _now_iso()
    path = _pack_path(pack.id)
    created_at = pack.created_at
    if not created_at:
        if path.exists():
            try:
                created_at = library_models.Pack.model_validate_json(
                    path.read_text(encoding="utf-8")
                ).created_at
            except (OSError, ValidationError):
                created_at = now
        else:
            created_at = now
    to_write = pack.model_copy(update={"created_at": created_at or now, "updated_at": now})

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(to_write.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)

    index = _read_pack_index()
    entries = [e for e in index.packs if e.id != pack.id]
    entries.append(
        library_models._PackIndexEntry(
            id=to_write.id,
            label=to_write.label,
            description=to_write.description,
            created_at=to_write.created_at,
            updated_at=to_write.updated_at,
        )
    )
    _write_pack_index(library_models._PackIndex(packs=entries))
    _invalidate_memo()
    return to_write


def delete_pack(pack_id: str) -> None:
    """Remove a user-authored pack. Refuses a shipped id.

    A workspace that still lists `pack_id` in `enabled_packs` is left as-is —
    `resolve_effective` skips a missing pack with a diagnostic rather than erroring, so
    deleting a pack out from under an active selection degrades gracefully.
    """
    if is_builtin_pack(pack_id):
        raise library_models.LibraryError(f"{pack_id!r} is a shipped pack and cannot be deleted.")
    path = _pack_path(pack_id)
    if not path.exists():
        raise library_models.LibraryError(f"Unknown pack: {pack_id!r}")
    path.unlink()
    index = _read_pack_index()
    _write_pack_index(library_models._PackIndex(packs=[e for e in index.packs if e.id != pack_id]))
    _invalidate_memo()


def reset_pack(pack_id: str) -> None:
    """Delete a shipped pack's shadow file, restoring the bundled seed on next read.

    Raises `LibraryError` when `pack_id` is not shipped, when no shadow exists, or
    when the store file is missing/corrupt.
    """
    if not is_builtin_pack(pack_id):
        raise library_models.LibraryError(f"{pack_id!r} is not a shipped pack and cannot be reset.")
    path = _pack_path(pack_id)
    if not path.exists():
        raise library_models.LibraryError(
            f"Pack {pack_id!r} has no customized copy to reset."
        )
    path.unlink()
    index = _read_pack_index()
    _write_pack_index(library_models._PackIndex(packs=[e for e in index.packs if e.id != pack_id]))
    _invalidate_memo()


# --------------------------------------------------------------------------------------
# Per-workspace state I/O
# --------------------------------------------------------------------------------------


def read_workspace_state(workspace_id: str | None = None) -> library_models.WorkspaceLibraryState:
    """Read `libraries.json`. Never raises — missing, unreadable, or malformed all
    degrade to the default state (`core-tech` enabled, nothing else), the same
    tolerance `workspace.load_settings` gives `settings.json`."""
    path = workspace_file(workspace_id)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            try:
                return library_models.WorkspaceLibraryState.model_validate(raw)
            except ValidationError:
                pass
    return library_models.WorkspaceLibraryState()


def write_workspace_state(
    state: library_models.WorkspaceLibraryState, workspace_id: str | None = None
) -> None:
    """Atomically write `libraries.json`: temp file, then `os.replace`."""
    path = workspace_file(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    _invalidate_memo()


# --------------------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------------------

#: Memoised result for the active workspace only (the hot path — every pipeline run and
#: every `apply_to_config()` call reads it). Explicit lookups for a *different*
#: workspace (`resolve_effective(workspace_id=...)`, used by pack validation previews
#: and workspace duplication) are always recomputed fresh rather than cached under a
#: second key, which would risk staleness with no invalidation signal.
_ACTIVE_MEMO: dict[Path, library_models.EffectiveLibrary] = {}


def _invalidate_memo() -> None:
    """Drop the memoised effective table. Called by every write in this module
    (`write_pack`, `delete_pack`, `write_workspace_state`) so `resolve_effective()`
    never silently serves a result computed before that write — cheap to recompute
    (a few hundred dict entries), so clearing unconditionally rather than trying to
    determine whether *this* write actually affects the active workspace is the safer
    default. Distinct from `reload()`, which additionally rebinds `config`'s tables —
    that stays caller-driven (after a route's write, or a workspace switch)."""
    _ACTIVE_MEMO.clear()


def resolve_effective(
    workspace_id: str | None = None, *, exclude_pack_id: str | None = None,
    state: library_models.WorkspaceLibraryState | None = None,
) -> library_models.EffectiveLibrary:
    """The composed alias/verb tables for `workspace_id`, or the active workspace.

    `exclude_pack_id` composes as if that pack were not enabled, without touching
    `enabled_packs` on disk. `write_pack` uses this to validate a pack being updated
    against everything *else* — without it, re-saving an already-enabled pack with a
    tweaked alias would spuriously conflict with its own current-on-disk version, since
    that old version is still part of `enabled_packs`' composition until the write
    lands. Bypasses the memo like an explicit `workspace_id` does.
    """
    if workspace_id is not None or exclude_pack_id is not None or state is not None:
        return _resolve_effective_uncached(
            workspace_id, exclude_pack_id=exclude_pack_id, state=state
        )
    key = config.LIBRARIES_PATH
    if key not in _ACTIVE_MEMO:
        _ACTIVE_MEMO[key] = _resolve_effective_uncached(None)
    return _ACTIVE_MEMO[key]


def _resolve_effective_uncached(
    workspace_id: str | None, *, exclude_pack_id: str | None = None,
    state: library_models.WorkspaceLibraryState | None = None,
) -> library_models.EffectiveLibrary:
    state = state if state is not None else read_workspace_state(workspace_id)
    diagnostics: list[str] = []

    aliases: dict[str, str] = {}
    verb_owner: dict[str, str] = {}  # verb -> family
    verb_source: dict[str, str] = {}  # verb -> id of the pack that last claimed it
    pack_labels: dict[str, str] = {}

    for pack_id in state.enabled_packs:
        if pack_id == exclude_pack_id:
            continue
        try:
            pack = read_pack(pack_id)
        except library_models.LibraryError:
            diagnostics.append(f"Pack {pack_id!r} is enabled but no longer exists; skipped.")
            continue
        pack_labels[pack_id] = pack.label

        for raw_k, raw_v in pack.tag_aliases.items():
            k, v = raw_k.strip().lower(), raw_v.strip().lower()
            if k and v:
                aliases[k] = v

        for family, verbs in pack.verb_families.items():
            for raw_verb in verbs:
                verb = raw_verb.strip().lower()
                if not verb:
                    continue
                prev_family = verb_owner.get(verb)
                prev_pack = verb_source.get(verb)
                if prev_family is not None and prev_pack != pack_id:
                    prev_label = pack_labels.get(prev_pack, prev_pack or "?")
                    diagnostics.append(
                        f"{verb!r} moved from {prev_family!r} ({prev_label}) to "
                        f"{family!r} ({pack.label})."
                    )
                verb_owner[verb] = family
                verb_source[verb] = pack_id

    for raw_k, raw_v in state.overrides.tag_aliases.items():
        k, v = raw_k.strip().lower(), raw_v.strip().lower()
        if k and v:
            aliases[k] = v
    for raw_verb, raw_family in state.overrides.verb_families.items():
        verb, family = raw_verb.strip().lower(), raw_family.strip().lower()
        if verb and family:
            verb_owner[verb] = family

    for raw_k in state.overrides.tag_aliases_removed:
        aliases.pop(raw_k.strip().lower(), None)
    for raw_verb in state.overrides.verb_families_removed:
        verb_owner.pop(raw_verb.strip().lower(), None)

    # Drop empty/self-aliases before the chain check so a self-alias never counts as a
    # "key" a chain could route through.
    aliases = {k: v for k, v in aliases.items() if k and v and k != v}

    # Chain repair: any alias whose target is itself a key is dropped, keeping every
    # surviving value a fixed point (`config.canonical_tag(v) == v`) no matter what a
    # hand-edited pack or override says. Snapshotting `keys` before the loop is what
    # makes a single pass sufficient — see `libraries.py`'s module docstring for why.
    keys = set(aliases)
    for k, v in list(aliases.items()):
        if v in keys:
            diagnostics.append(
                f"Alias {k!r} -> {v!r} dropped to break a chain: {v!r} is itself an "
                f"alias key elsewhere in the effective table."
            )
            del aliases[k]

    verb_families: dict[str, list[str]] = {}
    for verb, family in verb_owner.items():
        verb_families.setdefault(family, []).append(verb)
    verb_families_t = {family: tuple(sorted(verbs)) for family, verbs in verb_families.items()}

    return library_models.EffectiveLibrary(
        tag_aliases=aliases,
        verb_families=verb_families_t,
        verb_index=dict(verb_owner),
        diagnostics=diagnostics,
    )


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------

_MAX_ALIASES = 2000
_MAX_ALIAS_LEN = 120
_MAX_FAMILIES = 60
_MAX_VERBS_PER_FAMILY = 500


def validate_pack(
    pack: library_models.Pack,
    *,
    against: library_models.EffectiveLibrary | None = None,
    force: bool = False,
) -> list[str]:
    """Everything checked before a pack is written. Empty list means OK.

    `against` is the effective table this pack would be composed into — defaults to the
    active workspace's. Every rule here mirrors a real cross-pack failure mode:
    self-aliasing, chains (both directions), a verb double-booked within one pack, and
    (unless `force`) silently overwriting what another pack already claims.
    """
    errors: list[str] = []
    baseline = against if against is not None else resolve_effective()

    if not _PACK_ID_RE.match(pack.id):
        errors.append(f"Invalid pack id {pack.id!r}: must match {_PACK_ID_RE.pattern!r}.")
    if not pack.label.strip():
        errors.append("Pack label cannot be empty.")

    aliases = pack.tag_aliases
    if len(aliases) > _MAX_ALIASES:
        errors.append(f"Too many aliases ({len(aliases)} > {_MAX_ALIASES}).")

    pack_keys = {raw_k.strip().lower() for raw_k in aliases}
    for raw_k, raw_v in aliases.items():
        k, v = raw_k.strip().lower(), raw_v.strip().lower()
        if not k or not v:
            errors.append(f"Alias {raw_k!r} -> {raw_v!r}: key and value must be non-empty.")
            continue
        if len(k) > _MAX_ALIAS_LEN or len(v) > _MAX_ALIAS_LEN:
            errors.append(f"Alias {raw_k!r} -> {raw_v!r} exceeds {_MAX_ALIAS_LEN} characters.")
        if k == v:
            errors.append(f"Alias {raw_k!r} maps to itself.")
            continue
        if v in pack_keys:
            errors.append(
                f"Alias {raw_k!r} -> {raw_v!r} chains: {raw_v!r} is itself an alias key "
                f"in this pack."
            )
        if k in baseline.tag_aliases.values():
            errors.append(
                f"{raw_k!r} is already used as an alias target in the effective table; "
                f"adding it as a key would create a chain."
            )
        if v in baseline.tag_aliases:
            errors.append(
                f"{raw_v!r} is already an alias key in the effective table (-> "
                f"{baseline.tag_aliases[v]!r}); mapping to it would create a chain."
            )
        existing_target = baseline.tag_aliases.get(k)
        if existing_target is not None and existing_target != v and not force:
            errors.append(
                f"{raw_k!r} already maps to {existing_target!r} in the effective table; "
                f"pass force=true to override it."
            )

    families = pack.verb_families
    if len(families) > _MAX_FAMILIES:
        errors.append(f"Too many verb families ({len(families)} > {_MAX_FAMILIES}).")
    seen_verbs: dict[str, str] = {}
    for family, verbs in families.items():
        if not config.slugify(family):
            errors.append(f"Invalid family id {family!r}.")
        if len(verbs) > _MAX_VERBS_PER_FAMILY:
            errors.append(
                f"Family {family!r} has too many verbs ({len(verbs)} > "
                f"{_MAX_VERBS_PER_FAMILY})."
            )
        for raw_verb in verbs:
            verb = raw_verb.strip().lower()
            if not verb or not verb.isalpha():
                errors.append(
                    f"Verb {raw_verb!r} in family {family!r} must be alphabetic."
                )
                continue
            if verb in seen_verbs and seen_verbs[verb] != family:
                errors.append(
                    f"Verb {verb!r} appears in both {seen_verbs[verb]!r} and "
                    f"{family!r} within this pack."
                )
            seen_verbs[verb] = family

    return errors


# --------------------------------------------------------------------------------------
# Fingerprint, apply, reload, reset
# --------------------------------------------------------------------------------------


def effective_fingerprint(effective: library_models.EffectiveLibrary | None = None) -> str:
    """Digest of the composed alias + verb tables, for `propose.py`'s cache key."""
    eff = effective if effective is not None else resolve_effective()
    payload = "\n".join(
        [
            *(f"a:{k}={v}" for k, v in sorted(eff.tag_aliases.items())),
            *(f"v:{verb}={family}" for verb, family in sorted(eff.verb_index.items())),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def apply_to_config(workspace_id: str | None = None) -> library_models.EffectiveLibrary:
    """Rebind `config.TAG_ALIASES` / `config.VERB_FAMILIES` to the resolved tables.

    Always assigns new dict objects — never mutates the existing ones in place — since
    `config.verb_family`'s index cache is invalidated by identity
    (`_VERB_INDEX_SOURCE is not VERB_FAMILIES`). Mirrors `config.set_active_workspace`'s
    "rebind, don't mutate" contract for the path globals.
    """
    effective = resolve_effective(workspace_id)
    config.set_vocabulary(dict(effective.tag_aliases), dict(effective.verb_families))
    return effective


def reload(workspace_id: str | None = None) -> library_models.EffectiveLibrary:
    """Drop the memo and rebind `config`'s tables.

    Call after any write in this module, and from `workspace.bootstrap` /
    `workspace.activate` immediately after `config.set_active_workspace(...)` — mirrors
    the existing `reload_calibration()` call in the same spot.
    """
    _invalidate_memo()
    return apply_to_config(workspace_id)


def reset() -> None:
    """Restore `config`'s tables to the built-in `core-tech` pack alone, dropping the
    memo. Test seam — pairs with monkeypatching `store_root` in `tests/conftest.py`."""
    _invalidate_memo()
    core = library_seeds.BUILTIN_PACKS["core-tech"]
    config.set_vocabulary(
        dict(core["tag_aliases"]),
        {family: tuple(verbs) for family, verbs in core["verb_families"].items()},
    )
