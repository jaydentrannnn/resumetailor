"""Per-bullet tag suggestions (ED4): pure matching over the vocabulary and pack aliases."""

from __future__ import annotations

from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.tag_suggest import LIMIT, suggest_tags
from resume_tailor.web.app import app

ALIASES = {"dcf": "discounted cash flow", "ms excel": "excel", "ml": "machine learning"}


def _canonical(raw: str) -> str:
    cleaned = raw.strip().lower()
    return ALIASES.get(cleaned, cleaned)


def _tags(text, existing=(), vocabulary=()):
    return [s["tag"] for s in suggest_tags(text, existing, vocabulary, ALIASES, _canonical)]


def test_alias_and_canonical_matches_come_back_canonical_in_text_order():
    text = "Built DCF models in MS Excel to support machine learning pricing"
    assert _tags(text) == ["discounted cash flow", "excel", "machine learning"]


def test_existing_tags_are_not_suggested_even_by_alias():
    assert _tags("Built a DCF in Excel", existing=["Discounted Cash Flow"]) == ["excel"]


def test_whole_words_only_and_longest_phrase_wins():
    vocabulary = ["go", "learning", "sql", "postgresql"]
    assert _tags("Used google and PostgreSQL", vocabulary=vocabulary) == ["postgresql"]
    assert _tags("Continuous learning", vocabulary=vocabulary) == ["learning"]


def test_short_names_need_capitals():
    vocabulary = ["r", "c++"]
    assert _tags("Wrote a r script", vocabulary=vocabulary) == []
    assert _tags("Modeled churn in R and C++", vocabulary=vocabulary) == ["r", "c++"]


def test_limit():
    vocabulary = [f"skill{i}" for i in range(20)]
    assert len(_tags(" ".join(vocabulary), vocabulary=vocabulary)) == LIMIT


def test_route_uses_the_active_aliases(monkeypatch):
    monkeypatch.setattr(config, "TAG_ALIASES", dict(ALIASES))
    with TestClient(app) as c:
        res = c.post(
            "/api/master-resume/suggest-tags",
            json={"text": "Ran a DCF on SQL data", "tags": [], "vocabulary": ["SQL"]},
        )
    assert res.status_code == 200
    assert res.json()["suggestions"] == [
        {"tag": "discounted cash flow", "matched": "DCF"},
        {"tag": "sql", "matched": "SQL"},
    ]
