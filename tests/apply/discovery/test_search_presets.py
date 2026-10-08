"""Keyword-search presets: phrase building, title filters and the HTTP routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resume_tailor.apply.discovery import search_presets, source_watchlists
from resume_tailor.web.app import app
from resume_tailor.web.schemas import SourceConfig


def _filters(preset: search_presets.SearchPreset):
    source = SourceConfig(
        id="s", kind="job_search", provider="adzuna", query=preset.query,
        include=list(preset.include), exclude=list(preset.exclude),
    )
    return source_watchlists.source_keyword_filters(source)


def test_every_position_level_pair_builds_a_valid_search():
    for position in search_presets.POSITIONS:
        for level in search_presets.LEVELS:
            preset = search_presets.build_search([position.id], level.id)
            phrases = [p.strip() for p in preset.query.split(",")]
            assert 1 <= len(phrases) <= search_presets.MAX_PHRASES
            assert all(phrases)
            SourceConfig(id="s", kind="job_search", provider="adzuna", query=preset.query)


def test_phrases_cover_every_chosen_position_round_robin():
    preset = search_presets.build_search(
        ["investment-banking", "accounting-audit", "strategy-consulting"], "intern"
    )
    assert preset.query.split(", ") == [
        "investment banking analyst intern",
        "audit associate intern",
        "strategy consultant intern",
        "m&a analyst intern",
        "accounting analyst intern",
    ]


def test_duplicate_positions_are_collapsed():
    one = search_presets.build_search(["fpa"], "new_grad")
    assert search_presets.build_search(["fpa", "fpa"], "new_grad") == one


def test_new_grad_keeps_untagged_entry_titles_but_skips_senior_ones():
    include, exclude, _ = _filters(search_presets.build_search(["investment-banking"], "new_grad"))
    assert include is None
    assert not exclude.search("Investment Banking Analyst")
    assert exclude.search("Senior Financial Analyst")
    assert exclude.search("Vice President, Capital Markets")


def test_intern_level_never_keeps_internal_or_international_titles():
    include, _, _ = _filters(search_presets.build_search(["accounting-audit"], "intern"))
    assert include.search("Audit Intern") and include.search("Summer Analyst, M&A")
    for title in ("Internal Audit Analyst", "International Tax Associate"):
        assert not include.search(title)


@pytest.mark.parametrize(
    ("positions", "level"),
    [([], "intern"), (["nope"], "intern"), (["fpa"], "senior")],
)
def test_bad_choices_raise(positions, level):
    with pytest.raises(ValueError):
        search_presets.build_search(positions, level)


def test_industries_reference_real_positions_and_ids_are_unique():
    ids = {p.id for p in search_presets.POSITIONS}
    assert len(ids) == len(search_presets.POSITIONS)
    for industry in search_presets.INDUSTRIES:
        assert industry.positions and set(industry.positions) <= ids


def test_routes_list_choices_and_build_a_search():
    with TestClient(app) as client:
        choices = client.get("/api/apply/search-presets").json()
        assert {p["id"] for p in choices["levels"]} == {"intern", "new_grad", "off_cycle", "program"}
        assert any(i["id"] == "consulting" for i in choices["industries"])
        built = client.get(
            "/api/apply/search-presets/build",
            params={"positions": ["investment-banking", "markets"], "level": "intern"},
        ).json()
        assert built["query"].startswith("investment banking analyst intern, sales and trading")
        assert "intern" in built["include"] and "senior" in built["exclude"]
        bad = client.get(
            "/api/apply/search-presets/build", params={"positions": ["nope"], "level": "intern"}
        )
        assert bad.status_code == 422


def test_catalog_adzuna_searches_match_what_the_presets_build():
    from resume_tailor.apply.discovery import source_catalog

    expected = {
        "adzuna-finance-intern": (["investment-banking", "financial-analyst", "accounting-audit"], "intern"),
        "adzuna-finance-newgrad": (["investment-banking", "financial-analyst", "accounting-audit"], "new_grad"),
        "adzuna-consulting-intern": (["strategy-consulting", "tech-consulting", "business-analyst"], "intern"),
        "adzuna-consulting-newgrad": (["strategy-consulting", "tech-consulting", "business-analyst"], "new_grad"),
    }
    entries = {e.id: e for e in source_catalog.bundled().entries}
    for entry_id, (positions, level) in expected.items():
        built = search_presets.build_search(positions, level)
        template = entries[entry_id].template
        assert template.query == built.query, entry_id
        assert template.include == list(built.include), entry_id
        assert template.exclude == list(built.exclude), entry_id
        assert entries[entry_id].levels == [level], entry_id
