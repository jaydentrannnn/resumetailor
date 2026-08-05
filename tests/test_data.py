"""Tests for `data._alias_rewrites` and the `--validate` CLI.

Focused on the alias-visibility feature added to `--validate`: `Bullet._normalise_tags`
runs `config.canonical_tag` silently at load time, so a tag typed as `"performance
measurement"` becomes `"performance"` with nothing telling the person who typed it that
happened. `_alias_rewrites` is what makes that transform visible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from resume_tailor import config
from resume_tailor.data import MasterResume, _alias_rewrites, _validate_cli, to_legacy_dict

_RESUME_TEMPLATE: dict = {
    "contact": {"name": "Test User", "email": "test@example.com"},
    "education": [],
    "experience": [
        {
            "company": "Acme",
            "title": "Engineer",
            "start": "2020",
            "end": "2021",
            "bullets": [],
        }
    ],
    "projects": [],
    "skills": [],
}


def _resume_with_tags(*tags: str) -> dict:
    resume = json.loads(json.dumps(_RESUME_TEMPLATE))
    resume["experience"][0]["bullets"] = [
        {"id": "b1", "text": "Did a thing.", "tags": list(tags)}
    ]
    return resume


def test_no_rewrites_when_every_tag_is_already_canonical():
    assert _alias_rewrites(_resume_with_tags("python", "docker")) == []


def test_reports_a_tag_the_alias_table_rewrites():
    assert _alias_rewrites(_resume_with_tags("ml", "python")) == [("ml", "machine learning")]


def test_deduplicates_the_same_raw_tag_seen_twice():
    resume = json.loads(json.dumps(_RESUME_TEMPLATE))
    resume["experience"][0]["bullets"] = [
        {"id": "b1", "text": "A.", "tags": ["ml"]},
        {"id": "b2", "text": "B.", "tags": ["ml"]},
    ]
    assert _alias_rewrites(resume) == [("ml", "machine learning")]


def test_a_pure_case_fold_is_not_reported_as_an_alias_rewrite():
    """"Python" -> "python" is expected canonicalisation, not a surprising substitution —
    only genuine `TAG_ALIASES` hits belong in this output."""
    assert _alias_rewrites(_resume_with_tags("Python")) == []


def test_validate_cli_prints_alias_rewrites(tmp_path: Path, monkeypatch, capsys):
    resume = _resume_with_tags("ml", "python")
    path = tmp_path / "master_resume.json"
    path.write_text(json.dumps(resume), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["data.py", "--validate", "--path", str(path)])
    assert _validate_cli() == 0
    out = capsys.readouterr().out
    assert "'ml' -> 'machine learning'" in out


def test_validate_cli_omits_the_rewrite_line_when_nothing_was_rewritten(
    tmp_path: Path, monkeypatch, capsys
):
    resume = _resume_with_tags("python")
    path = tmp_path / "master_resume.json"
    path.write_text(json.dumps(resume), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["data.py", "--validate", "--path", str(path)])
    assert _validate_cli() == 0
    out = capsys.readouterr().out
    assert "rewritten by TAG_ALIASES" not in out


# ----------------------------------------------------------------------------------------
# Experience.id auto-fill and uniqueness
#
# Files written before this field existed have every experience id blank; these tests
# pin the auto-fill behaviour that keeps them loading, and the collision handling that
# keeps auto-filled ids distinct within one file.
# ----------------------------------------------------------------------------------------


def _resume_with_experience(*entries: dict) -> dict:
    resume = json.loads(json.dumps(_RESUME_TEMPLATE))
    resume["experience"] = [
        {"company": "Acme", "title": "Engineer", "start": "2020", "end": "2021", "bullets": []}
        | entry
        for entry in entries
    ]
    return resume


def test_blank_experience_id_autofills_from_company_slug():
    resume = MasterResume.model_validate(
        _resume_with_experience({"company": "Bank of America"})
    )
    assert resume.experience[0].id == "bank-of-america"


def test_explicit_experience_id_is_left_alone():
    resume = MasterResume.model_validate(_resume_with_experience({"id": "my-custom-id"}))
    assert resume.experience[0].id == "my-custom-id"


def test_two_blank_entries_at_the_same_company_get_distinct_ids():
    resume = MasterResume.model_validate(
        _resume_with_experience({"company": "Acme"}, {"company": "Acme"})
    )
    ids = [e.id for e in resume.experience]
    assert ids == ["acme", "acme-2"]


def test_blank_id_avoids_colliding_with_an_explicit_one():
    resume = MasterResume.model_validate(
        _resume_with_experience({"id": "acme"}, {"company": "Acme"})
    )
    ids = [e.id for e in resume.experience]
    assert ids == ["acme", "acme-2"]


def test_a_resume_written_before_this_field_existed_still_loads():
    """Every entry blank (the pre-migration shape) fills in without colliding."""
    resume = MasterResume.model_validate(
        _resume_with_experience({"company": "Acme"}, {"company": "Globex"})
    )
    ids = [e.id for e in resume.experience]
    assert ids == ["acme", "globex"]
    assert len(set(ids)) == len(ids)


def test_duplicate_explicit_experience_id_raises():
    try:
        MasterResume.model_validate(
            _resume_with_experience({"id": "dup"}, {"id": "dup"})
        )
    except Exception as exc:  # pydantic ValidationError wraps the raised ValueError
        assert "duplicate entry id" in str(exc)
    else:
        raise AssertionError("expected duplicate entry id to raise")


# ----------------------------------------------------------------------------------------
# Legacy -> `sections` migration
#
# A pre-`sections` file has top-level `education`/`experience`/`projects`/`skills` lists.
# `_migrate_legacy_sections` folds those into `sections` at load time so every existing
# file, fixture, and test-constructed resume keeps working through the `experience` /
# `projects` / `education` / `skills` read-only properties.
# ----------------------------------------------------------------------------------------


def test_migration_produces_four_default_sections_in_fixed_order():
    resume = MasterResume.model_validate(json.loads(json.dumps(_RESUME_TEMPLATE)))
    assert [(s.id, s.kind) for s in resume.sections] == [
        ("education", "education"),
        ("experience", "experience"),
        ("projects", "project"),
        ("skills", "skills"),
    ]
    assert resume.sections[1].title == config.DEFAULT_SECTION_TITLES["experience"]


def test_all_bullets_order_matches_pre_migration_order_for_the_real_master_resume():
    """`rewrite._score_cache_path` hashes `all_bullets()` in list order — if migrating a
    legacy file changed that order, every cached relevance score would silently
    invalidate. Compares against the raw JSON's own experience-then-projects order,
    independent of any pipeline code."""
    path = config.MASTER_RESUME_PATH
    if not path.exists():
        import pytest

        pytest.skip("data/master_resume.json is gitignored and not present here")
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = [
        bullet["id"]
        for section_key in ("experience", "projects")
        for entry in raw.get(section_key, [])
        for bullet in entry.get("bullets", [])
    ]
    resume = MasterResume.model_validate(raw)
    assert [b.id for b in resume.all_bullets()] == expected


def test_a_sections_native_file_loads_without_migrating():
    native = {
        "contact": {"name": "Test User", "email": "test@example.com"},
        "sections": [
            {
                "id": "leadership",
                "kind": "experience",
                "title": "LEADERSHIP EXPERIENCE",
                "entries": [
                    {
                        "company": "Club",
                        "title": "President",
                        "start": "2024",
                        "end": "2025",
                        "bullets": [{"id": "b1", "text": "Led a thing.", "tags": ["leadership"]}],
                    }
                ],
            }
        ],
    }
    resume = MasterResume.model_validate(native)
    assert [s.id for s in resume.sections] == ["leadership"]
    assert resume.experience[0].company == "Club"


def test_duplicate_entry_id_across_two_different_sections_raises():
    native = {
        "contact": {"name": "Test User", "email": "test@example.com"},
        "sections": [
            {
                "id": "experience",
                "kind": "experience",
                "title": "Experience",
                "entries": [
                    {"id": "dup", "company": "A", "title": "T", "start": "2020", "end": "2021"}
                ],
            },
            {
                "id": "projects",
                "kind": "project",
                "title": "Projects",
                "entries": [{"id": "dup", "name": "P"}],
            },
        ],
    }
    try:
        MasterResume.model_validate(native)
    except Exception as exc:
        assert "duplicate entry id" in str(exc)
    else:
        raise AssertionError("expected duplicate entry id to raise")


def test_model_dump_then_validate_is_a_fixpoint():
    resume = MasterResume.model_validate(json.loads(json.dumps(_RESUME_TEMPLATE)))
    dumped_once = resume.model_dump(by_alias=True)
    resume_again = MasterResume.model_validate(dumped_once)
    assert resume_again.model_dump(by_alias=True) == dumped_once


def test_to_legacy_dict_round_trips_through_model_validate():
    resume = MasterResume.model_validate(json.loads(json.dumps(_RESUME_TEMPLATE)))
    legacy = to_legacy_dict(resume)
    assert "sections" not in legacy
    assert legacy["experience"][0]["company"] == "Acme"
    reloaded = MasterResume.model_validate(legacy)
    assert reloaded.model_dump(by_alias=True) == resume.model_dump(by_alias=True)
