"""Tests for the built-in vocabulary packs in `library_seeds.py`.

Every built-in pack must satisfy the same invariants a user-authored pack is validated
against on write (`libraries.validate_pack`) — these tests check that generically, so a
future pack addition is caught the same way a bad user submission would be, rather than
relying on someone reading the table by eye.

`finance-consulting` also gets tests pinned to the *specific claims* its own comments
make about a real resume it was grounded in (see `library_seeds.py`) — including one
regression that exists specifically to correct an earlier, wrong claim: the resume's two
exact-duplicate verb repeats ("collaborated", "received") are already caught by
`rewrite.verb_collisions`'s exact-duplicate rule with `core-tech` alone; the new pack's
real, verifiable contribution is the alias table and the near-synonym rule, tested below.
"""

from __future__ import annotations

from resume_tailor import config, libraries, library_seeds, rewrite


def _effective_for(pack: library_seeds.Pack) -> libraries.EffectiveLibrary:
    converted = libraries._pack_from_seed(pack)
    return libraries.EffectiveLibrary(
        tag_aliases=converted.tag_aliases,
        verb_families={f: tuple(v) for f, v in converted.verb_families.items()},
        verb_index={v: f for f, vs in converted.verb_families.items() for v in vs},
        diagnostics=[],
    )


def test_every_builtin_pack_is_internally_valid():
    empty = libraries.EffectiveLibrary(tag_aliases={}, verb_families={}, verb_index={}, diagnostics=[])
    for pack_id, seed in library_seeds.BUILTIN_PACKS.items():
        pack = libraries._pack_from_seed(seed)
        errors = libraries.validate_pack(pack, against=empty)
        assert errors == [], f"{pack_id}: {errors}"


def test_every_builtin_pack_composes_cleanly_with_core_tech():
    core_effective = _effective_for(library_seeds.BUILTIN_PACKS["core-tech"])
    for pack_id, seed in library_seeds.BUILTIN_PACKS.items():
        if pack_id == "core-tech":
            continue
        pack = libraries._pack_from_seed(seed)
        errors = libraries.validate_pack(pack, against=core_effective)
        assert errors == [], f"{pack_id}: {errors}"


def test_finance_consulting_has_no_alias_chain_against_core_tech():
    """No `finance-consulting` alias key/value collides with a core-tech alias key/value
    in a way that would form a chain once both are enabled — belt-and-braces alongside
    `validate_pack`, using the actual composition path a user would hit."""
    state = libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "finance-consulting"])
    packs = {
        "core-tech": libraries._pack_from_seed(library_seeds.BUILTIN_PACKS["core-tech"]),
        "finance-consulting": libraries._pack_from_seed(
            library_seeds.BUILTIN_PACKS["finance-consulting"]
        ),
    }
    aliases: dict[str, str] = {}
    for pack_id in state.enabled_packs:
        aliases.update(packs[pack_id].tag_aliases)
    for value in aliases.values():
        assert value not in aliases, f"{value!r} is both a value and a key — a chain"


# --------------------------------------------------------------------------------------
# finance-consulting: claims pinned against the real resume it was grounded in
# --------------------------------------------------------------------------------------

#: Opening verbs from the actual resume's bullets (see library_seeds.py's comment),
#: reduced to just the words `rewrite.opening_verb` extracts from them.
_RESUME_OPENERS = {
    "partnered": "lead",  # already covered by core-tech
    "recruited": None,  # covered only once finance-consulting is enabled
    "received": None,
    "collaborated": None,
    "tracked": None,
    "promoted": None,
}


def test_finance_consulting_classifies_the_resume_openers_core_tech_does_not(monkeypatch):
    monkeypatch.setattr(config, "VERB_FAMILIES", dict(library_seeds.BUILTIN_PACKS["core-tech"]["verb_families"]))
    for verb in ("recruited", "received", "collaborated", "tracked", "promoted"):
        assert config.verb_family(verb) is None, f"{verb} should be unclassified under core-tech alone"

    merged = dict(library_seeds.BUILTIN_PACKS["core-tech"]["verb_families"])
    for family, verbs in library_seeds.BUILTIN_PACKS["finance-consulting"]["verb_families"].items():
        merged[family] = tuple(merged.get(family, ())) + tuple(verbs)
    monkeypatch.setattr(config, "VERB_FAMILIES", merged)

    assert config.verb_family("recruited") == "recruit"
    assert config.verb_family("received") == "gained"
    assert config.verb_family("collaborated") == "collaborate"
    assert config.verb_family("tracked") == "track"
    assert config.verb_family("promoted") == "promote"


def test_exact_duplicate_verb_repeats_are_already_caught_without_the_new_pack():
    """Corrects an earlier wrong claim: this does NOT depend on finance-consulting.
    `rewrite.verb_collisions`'s exact-duplicate rule matches on the literal word, with
    no family lookup at all, so `core-tech` alone already flags both repeats."""
    texts = {
        "b7": "Collaborated with peers and Deloitte consultants to solve a case",
        "b12": "Collaborated on the planning and execution of the Heartbeat Bazaar",
        "b6": "Received exposure to financial analysis, forecasting",
        "b16": "Received a trial implementation of a sexual education course",
    }
    collisions = rewrite.verb_collisions(texts)
    assert "b12" in collisions and "collaborated" in collisions["b12"]
    assert "b16" in collisions and "received" in collisions["b16"]


def test_finance_consulting_verb_families_catch_a_near_synonym_cluster_core_tech_cannot(
    monkeypatch,
):
    """The pack's real, verifiable verb-side contribution: three *different* words from
    the same new family (not an exact repeat) only trip the near-synonym rule once
    finance-consulting supplies the family `core-tech` has no opinion on."""
    texts = {
        "a": "Collaborated with the audit team on quarterly review.",
        "b": "Consulted with department heads on budget allocation.",
        "c": "Liaised with external vendors on contract terms.",
    }

    monkeypatch.setattr(config, "VERB_FAMILIES", dict(library_seeds.BUILTIN_PACKS["core-tech"]["verb_families"]))
    assert rewrite.verb_collisions(texts) == {}

    merged = dict(library_seeds.BUILTIN_PACKS["core-tech"]["verb_families"])
    for family, verbs in library_seeds.BUILTIN_PACKS["finance-consulting"]["verb_families"].items():
        merged[family] = tuple(merged.get(family, ())) + tuple(verbs)
    monkeypatch.setattr(config, "VERB_FAMILIES", merged)

    collisions = rewrite.verb_collisions(texts)
    assert "c" in collisions  # the third same-family opener is the one that overflows


def test_finance_consulting_aliases_close_a_measured_spelling_gap(monkeypatch):
    """Pins the alias table's own claim: these three posting-style spellings matched
    none of the resume's actual skill wording before this pack existed."""
    monkeypatch.setattr(config, "TAG_ALIASES", dict(library_seeds.BUILTIN_PACKS["core-tech"]["tag_aliases"]))
    for term in ("google workspace", "ms office", "kpis"):
        assert config.canonical_tag(term) == term  # unchanged: no alias under core-tech alone

    monkeypatch.setattr(
        config,
        "TAG_ALIASES",
        {
            **library_seeds.BUILTIN_PACKS["core-tech"]["tag_aliases"],
            **library_seeds.BUILTIN_PACKS["finance-consulting"]["tag_aliases"],
        },
    )
    assert config.canonical_tag("google workspace") == "google drive suite"
    assert config.canonical_tag("ms office") == "microsoft 365"
    assert config.canonical_tag("kpis") == "kpi"
