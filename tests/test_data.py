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

from resume_tailor.data import _alias_rewrites, _validate_cli

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
