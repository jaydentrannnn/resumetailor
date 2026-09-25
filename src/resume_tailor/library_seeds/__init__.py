"""Shipped vocabulary packs: tag-alias and verb-family tables bundled with the package.

`config.py` initialises `TAG_ALIASES` / `VERB_FAMILIES` from `BUILTIN_PACKS["core-tech"]`
at import time, and `libraries.py` unions these into the same registry as any
user-authored pack under `data/libraries/packs/`. Each pack is a JSON file in this
directory, read once via `importlib.resources` and memoised — edits land in the store
and shadow the shipped copy (see `libraries.read_pack`).

Every value here must already satisfy the invariants `libraries.validate_pack` enforces
on a user pack: alias values are fixed points of the alias table (no `a -> b -> c`
chains), and a verb appears in exactly one family within a pack. `tests/test_config.py`
and `tests/test_libraries.py` pin both for this pack specifically.

**core-tech** — The original single-industry tables, unchanged, as the always-available
default pack. Every user starts with this enabled and nothing else. Retrieval/LLM
vocabulary aliases exist because a posting and a resume rarely spell these the same way,
and every miss here costs a relevant bullet its score.

**finance-consulting** — Grounded in one real early-career finance/consulting resume
(nonprofit fundraising, a Deloitte mentorship program, an internal-audit internship),
not invented from general knowledge alone — every alias and verb below is either the
resume's own wording or a spelling/synonym a posting in this field would plausibly use
for it.

The alias table closes a measured gap on that resume: "Google Workspace", "MS Office",
and "KPIs" — all plausible posting spellings — matched none of its own tag/skill wording
("Google Drive Suite", "Microsoft 365", "KPI") before this pack existed. The verb
families are forward-looking rather than a fix for anything already broken on that resume:
`collaborated` and `received` each open two of its bullets, but `rewrite.verb_collisions`'s
exact-duplicate rule already catches an identical repeated word with no family table
involved (see `tests/test_library_seeds.py`) — what these families add is coverage for
the *near-synonym* rule (three-plus related-but-different openers, e.g. a rewrite that
lands on "recruited" for one bullet and "sourced" for another), which `core-tech`
cannot see for any of these verbs today.

It also carries the finance/banking vocabulary postings use: valuation and modeling terms
(DCF, LBO, comps, M&A), the Excel sub-features a posting names instead of "Excel", and
the data terminals (Bloomberg, Capital IQ). Plus the analytics tools every business field
shares (Power BI, EViews), since onboarding enables it for all business students.

**accounting**, **marketing**, **ops-supply-chain** — The rest of the Business/Finance/
Econ launch set, enabled together by onboarding's "Business" field. Three rules keep them
safe to enable at once, and `tests/test_library_seeds.py` pins all three:
- New verbs join the existing family names (`analyse`, `improve`, `lead`, `write`, …) and
  every verb is claimed by exactly one pack, so enabling several never "moves" a verb.
- No alias value is another pack's key, so no chain is dropped.
- Bare student-ambiguous abbreviations ("ib", "ap", "ar") are not keys at all: on a
  student's resume they mean International Baccalaureate and Advanced Placement as often
  as investment banking or accounts payable. The multi-character spellings ("a/p", "ibd")
  carry those meanings instead.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import TypedDict


class Pack(TypedDict):
    """One shipped vocabulary pack — same shape as before the JSON migration."""

    id: str
    label: str
    description: str
    tag_aliases: dict[str, str]
    verb_families: dict[str, tuple[str, ...]]


def _load_pack_json(name: str) -> Pack:
    """Read one shipped pack JSON and normalise verb lists to tuples."""
    raw = resources.files(__package__).joinpath(name).read_text(encoding="utf-8")
    data = json.loads(raw)
    pack_id = data["id"]
    if pack_id != name.removesuffix(".json"):
        raise ValueError(
            f"Pack id {pack_id!r} does not match filename {name!r}."
        )
    verb_families = {
        family: tuple(verbs)
        for family, verbs in data.get("verb_families", {}).items()
    }
    return Pack(
        id=pack_id,
        label=data["label"],
        description=data.get("description", ""),
        tag_aliases=dict(data.get("tag_aliases", {})),
        verb_families=verb_families,
    )


@lru_cache(maxsize=1)
def _load_all_packs() -> dict[str, Pack]:
    """Load every `*.json` in this package directory, keyed by pack id."""
    packs: dict[str, Pack] = {}
    for entry in resources.files(__package__).iterdir():
        if entry.name.endswith(".json"):
            pack = _load_pack_json(entry.name)
            packs[pack["id"]] = pack
    return packs


def shipped_pack_ids() -> frozenset[str]:
    """Ids of every pack shipped with the package."""
    return frozenset(_load_all_packs())


#: Every shipped pack, keyed by id. `libraries.list_packs()` unions this with the
#: user-authored packs on disk; `libraries.read_pack` falls back here when no store
#: file exists. All disabled by default in a fresh workspace's `libraries.json` (only
#: "core-tech" is enabled), so adding an entry here never changes existing behaviour
#: until a user opts in.
BUILTIN_PACKS: dict[str, Pack] = _load_all_packs()
