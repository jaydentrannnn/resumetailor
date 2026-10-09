"""The built-in vocabulary dictionary: tag aliases and verb families bundled with the package.

One always-on table (`dictionary.json`), replacing the five per-field packs it was merged
from (core-tech, finance-consulting, accounting, marketing, ops-supply-chain). Packs were
dropped because no two of them ever claimed the same alias key or verb, and once matching
tags are detected from bullet text (`content/bullet_tags.py`) an entry that never appears
in a resume or posting does nothing — so a finance alias costs an engineering resume
nothing, while a per-profile on/off switch only added a way to get matching wrong.

`terms` maps each canonical term to the other spellings that mean it; `verb_families`
maps a family name to its opening verbs. Users layer app-wide additions and hidden
built-ins on top (`libraries.resolve_effective`); this file itself is read-only.

Invariants (pinned by `tests/content/test_library_seeds.py`):
- No alias is also a canonical term (no `a -> b -> c` chains).
- No alias belongs to two terms, and no verb to two families.
- Bare student-ambiguous abbreviations are not aliases at all ("ib", "ap", "ar" mean
  International Baccalaureate and Advanced Placement on a student resume as often as
  investment banking or accounts payable); the multi-character spellings ("a/p", "ibd")
  carry those meanings instead. For the same reason "mrr" (monthly recurring revenue vs
  mean reciprocal rank) and "10k" ("10k+ users" vs the SEC filing) were dropped in the merge.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import TypedDict


class Dictionary(TypedDict):
    """The shipped dictionary, verb lists normalised to tuples."""

    terms: dict[str, tuple[str, ...]]
    verb_families: dict[str, tuple[str, ...]]


@lru_cache(maxsize=1)
def load() -> Dictionary:
    """Read `dictionary.json` once."""
    raw = resources.files(__package__).joinpath("dictionary.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    return Dictionary(
        terms={term: tuple(aliases) for term, aliases in data["terms"].items()},
        verb_families={family: tuple(verbs) for family, verbs in data["verb_families"].items()},
    )


def builtin_aliases() -> dict[str, str]:
    """The built-in alias table, flattened to `alias -> canonical`."""
    return {alias: term for term, aliases in load()["terms"].items() for alias in aliases}


def builtin_verb_families() -> dict[str, tuple[str, ...]]:
    """The built-in verb families, `family -> verbs`."""
    return dict(load()["verb_families"])
