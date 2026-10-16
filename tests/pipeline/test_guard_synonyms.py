"""The rewrite guard excuses a skill renamed in the safe direction (`licensed_synonyms`)."""

from __future__ import annotations

from resume_tailor.content.data import Bullet
from resume_tailor.pipeline import bullet_checks


def _offenders(source: str, rewritten: str, tags: list[str] | None = None) -> list[str]:
    return bullet_checks.guard_offenders([Bullet(id="b1", text=source, tags=tags or [])],
                                         rewritten)


def test_the_canonical_name_of_a_source_skill_passes():
    assert _offenders("Built REST endpoints with Postgres.",
                      "Built REST endpoints with PostgreSQL.") == []


def test_a_narrow_name_generalised_passes_but_never_the_reverse():
    assert _offenders("Built lookups in VLOOKUP.", "Built lookups in Excel.") == []
    assert _offenders("Built models in Excel.", "Built models with VLOOKUP.") == ["VLOOKUP"]


def test_spelling_out_a_source_acronym_passes():
    assert _offenders("Prototyped RAG pipelines.",
                      "Prototyped Retrieval-Augmented Generation pipelines.") == []


def test_an_extra_skill_licenses_its_canonical_name():
    assert _offenders("Built REST endpoints.", "Built REST endpoints on PostgreSQL.",
                      ["postgres"]) == []


def test_a_skill_the_source_never_states_still_fails():
    assert _offenders("Built REST endpoints.", "Built REST endpoints on PostgreSQL.") == [
        "PostgreSQL"
    ]
