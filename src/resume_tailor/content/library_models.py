"""Vocabulary-library models and errors: packs, overrides, proposals and the effective table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------
class LibraryError(ValueError):
    """Raised for an unknown pack id, a refused write, or a shipped-pack delete attempt."""

class LibraryValidationError(LibraryError):
    """Raised by `write_pack` when `validate_pack` finds problems. Carries every error,
    not just the first, so a caller (the API route) can report the whole list at once."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors

# --------------------------------------------------------------------------------------
# On-disk models
# --------------------------------------------------------------------------------------
class _Strict(BaseModel):
    """Reject unknown keys so a typo'd field fails loudly, matching `data._Strict`."""

    model_config = ConfigDict(extra="forbid")

class Pack(_Strict):
    """One named bundle of aliases and verb families — built-in or user-authored.

    `verb_families` values are lists here (JSON has no tuples); `resolve_effective`
    converts to the `tuple[str, ...]` shape `config.VERB_FAMILIES` uses.
    """

    schema_version: int = 1
    id: str
    label: str
    description: str = ""
    tag_aliases: dict[str, str] = Field(default_factory=dict)
    verb_families: dict[str, list[str]] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

class _PackIndexEntry(_Strict):
    id: str
    label: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""

class _PackIndex(_Strict):
    schema_version: int = 1
    packs: list[_PackIndexEntry] = Field(default_factory=list)

class LibraryOverrides(_Strict):
    """A workspace's own additions and removals, layered on top of its enabled packs."""

    tag_aliases: dict[str, str] = Field(default_factory=dict)
    tag_aliases_removed: list[str] = Field(default_factory=list)
    #: verb -> family. One family per overridden verb, same shape as a resolved
    #: `verb_index` entry, not a `Pack`'s `family -> [verbs]` shape.
    verb_families: dict[str, str] = Field(default_factory=dict)
    verb_families_removed: list[str] = Field(default_factory=list)

ProposalKind = Literal["tag_alias", "verb_family"]

class LibraryProposal(_Strict):
    """One LLM-drafted addition awaiting approval. See `propose.py` (Phase 4)."""

    id: str
    kind: ProposalKind
    alias: str | None = None
    canonical: str | None = None
    verb: str | None = None
    family: str | None = None
    rationale: str = ""
    source: Literal["run", "manual"] = "manual"
    created_at: str = ""

class RejectedEntry(_Strict):
    """A previously-declined proposal, kept so it is never re-proposed."""

    kind: ProposalKind
    alias: str | None = None
    canonical: str | None = None
    verb: str | None = None
    family: str | None = None

class WorkspaceLibraryState(_Strict):
    """The on-disk shape of one workspace's `libraries.json`."""

    schema_version: int = 1
    enabled_packs: list[str] = Field(default_factory=lambda: ["core-tech"])
    overrides: LibraryOverrides = Field(default_factory=LibraryOverrides)
    proposals: list[LibraryProposal] = Field(default_factory=list)
    rejected: list[RejectedEntry] = Field(default_factory=list)

# --------------------------------------------------------------------------------------
# Computed views (not persisted)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PackMeta:
    """Summary row for the Settings tab's pack list — no full alias/verb bodies."""

    id: str
    label: str
    description: str = ""
    #: True when the pack is shipped with the package (resettable, not deletable).
    builtin: bool = False
    #: True when a store file shadows the shipped copy for this id.
    customized: bool = False
    tag_alias_count: int = 0
    verb_count: int = 0
    created_at: str = ""
    updated_at: str = ""

@dataclass(frozen=True)
class EffectiveLibrary:
    """The composed tables one workspace's enabled packs + overrides resolve to."""

    tag_aliases: dict[str, str]
    verb_families: dict[str, tuple[str, ...]]
    #: verb -> family, the flat form `config.verb_family` ultimately indexes.
    verb_index: dict[str, str]
    #: Human-readable notes about what composition had to work around: a missing pack,
    #: a cross-pack verb collision, or an alias chain that was dropped to keep
    #: `canonical_tag` idempotent. Never raised as errors — see the module docstring.
    diagnostics: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class AliasImpact:
    """What approving one alias would rewrite in the current master resume, if anything."""

    alias: str
    canonical: str
    #: Non-empty when `alias` is currently used as a literal tag or vocabulary entry —
    #: the signal that approving this alias would rewrite existing content, not just
    #: widen future JD matching.
    affected_tags: list[str]
    #: (entry label, bullet id) pairs carrying the affected tag, for the impact preview.
    affected_bullets: list[tuple[str, str]]
