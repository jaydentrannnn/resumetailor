"""Vocabulary models and errors: the user's additions, proposals and the effective table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------
class LibraryError(ValueError):
    """Raised for a refused vocabulary write (bad entry, chain, unknown built-in)."""

# --------------------------------------------------------------------------------------
# On-disk models
# --------------------------------------------------------------------------------------
class _Strict(BaseModel):
    """Reject unknown keys so a typo'd field fails loudly, matching `data._Strict`."""

    model_config = ConfigDict(extra="forbid")

class UserVocabulary(_Strict):
    """The app-wide `libraries/vocabulary.json`: what the user layered on the dictionary.

    Shared by every profile (under `DATA_ROOT`, never rebound per workspace). Built-in
    entries are never deleted, only hidden; the user's own entries are removed outright.
    """

    schema_version: int = 1
    #: alias -> canonical, both lowercase.
    tag_aliases: dict[str, str] = Field(default_factory=dict)
    #: New canonical terms with no alias yet (an alias's target is a term implicitly).
    terms: list[str] = Field(default_factory=list)
    #: verb -> family. One family per verb.
    verb_families: dict[str, str] = Field(default_factory=dict)
    hidden_terms: list[str] = Field(default_factory=list)
    hidden_aliases: list[str] = Field(default_factory=list)
    hidden_verbs: list[str] = Field(default_factory=list)
    #: Workspace ids whose legacy pack selection/overrides were already folded in.
    migrated_workspaces: list[str] = Field(default_factory=list)

class LegacyOverrides(_Strict):
    """A workspace's pre-dictionary additions/removals; read once by the migration."""

    tag_aliases: dict[str, str] = Field(default_factory=dict)
    tag_aliases_removed: list[str] = Field(default_factory=list)
    verb_families: dict[str, str] = Field(default_factory=dict)
    verb_families_removed: list[str] = Field(default_factory=list)

ProposalKind = Literal["tag_alias", "verb_family"]

class LibraryProposal(_Strict):
    """One LLM-drafted addition awaiting approval. See `propose.py`."""

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
    """The on-disk shape of one workspace's `libraries.json`: its pending proposals.

    `enabled_packs` and `overrides` are the retired pack layer, kept only so an old file
    still validates; the migration moves `overrides` into `UserVocabulary` and empties it.
    """

    schema_version: int = 1
    enabled_packs: list[str] = Field(default_factory=list)
    overrides: LegacyOverrides = Field(default_factory=LegacyOverrides)
    proposals: list[LibraryProposal] = Field(default_factory=list)
    rejected: list[RejectedEntry] = Field(default_factory=list)

# --------------------------------------------------------------------------------------
# Computed views (not persisted)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class EffectiveLibrary:
    """The dictionary after the user's additions and hidden entries are applied."""

    tag_aliases: dict[str, str]
    verb_families: dict[str, tuple[str, ...]]
    #: verb -> family, the flat form `config.verb_family` ultimately indexes.
    verb_index: dict[str, str]
    #: Every canonical term, with or without aliases — the detection candidates.
    terms: frozenset[str] = frozenset()
    #: Notes about what composition had to work around (a user alias that would chain).
    diagnostics: list[str] = field(default_factory=list)
