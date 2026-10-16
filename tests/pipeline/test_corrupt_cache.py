"""A corrupt cache file is a miss: the stage recomputes and atomically replaces it."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.content.data import Bullet
from resume_tailor.infra import atomic
from resume_tailor.pipeline import relevance
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from resume_tailor.pipeline.relevance import BulletScore, ScoreTable


class _Response:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _ScoringClient:
    def __init__(self, table, calls):
        self._table, self._calls = table, calls
        self.messages = self

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return _Response(self._table)


def _reqs() -> JobRequirements:
    return JobRequirements(
        title="Engineer", seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def test_corrupt_score_cache_is_recomputed_and_replaced(monkeypatch, tmp_path):
    bullets = [Bullet(id="a", text="Built a Python service.", tags=["python"])]
    table = ScoreTable(scores=[BulletScore(id="a", relevance=8.0, reason="fits")])
    calls: list[dict] = []
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(relevance.llm, "client_for", lambda purpose: _ScoringClient(table, calls))

    path = relevance._score_cache_path(bullets, _reqs())
    path.write_text('{"scores": [{"id": "a", "relev', encoding="utf-8")  # a torn write

    assert relevance.score_table(bullets, _reqs()) == {"a": 8.0}, "scored, not keyword-only"
    assert len(calls) == 1
    assert ScoreTable.model_validate_json(path.read_text(encoding="utf-8")) == table
    assert not list(tmp_path.glob("*.tmp")), "the replacement went through a temp file"

    assert relevance.score_table(bullets, _reqs()) == {"a": 8.0}
    assert len(calls) == 1, "the repaired file is a hit"


def test_read_cached_treats_missing_and_invalid_files_as_misses(tmp_path):
    path = tmp_path / "x.json"
    assert atomic.read_cached(path, ScoreTable) is None
    path.write_text('{"scores": [{"id": 1}]}', encoding="utf-8")
    assert atomic.read_cached(path, ScoreTable) is None
    assert path.exists(), "a miss never deletes: another job may have just rewritten it"
    path.write_bytes(b"\xff\xfe\x00")
    assert atomic.read_cached(path, ScoreTable) is None
