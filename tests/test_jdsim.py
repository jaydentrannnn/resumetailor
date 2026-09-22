"""Tests for JD-similarity reuse recommendations."""

from __future__ import annotations

from resume_tailor import jdsim
from resume_tailor.jd import JobRequirements, Keyword


def _reqs(seniority: str = "entry") -> JobRequirements:
    """Minimal requirements fixture with the given seniority."""
    return JobRequirements(
        title="Engineer",
        seniority=seniority,  # type: ignore[arg-type]
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def test_jaccard_identical_is_one():
    tokens = jdsim.tokenize("python fastapi rag pipeline")
    assert jdsim.jaccard(tokens, tokens) == 1.0


def test_jaccard_disjoint_is_zero():
    assert jdsim.jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_empty_is_zero():
    assert jdsim.jaccard(set(), set()) == 0.0


def test_recommend_reuse_at_high_overlap():
    text = "python fastapi rag vector database semantic search ranking"
    rec, score = jdsim.recommend_reuse(text, text, current_requirements=_reqs(), prior_requirements=_reqs())
    assert rec == "reuse"
    assert score == 1.0


def test_recommend_reuse_with_edits_band():
    """Overlap in [0.45, 0.72) recommends reuse_with_edits."""
    # 4 shared of 7 union ≈ 0.571
    a = "alpha beta gamma delta epsilon"
    b = "alpha beta gamma delta zeta eta theta"
    rec, score = jdsim.recommend_reuse(a, b)
    assert 0.45 <= score < 0.72
    assert rec == "reuse_with_edits"


def test_recommend_regenerate_at_low_overlap():
    rec, score = jdsim.recommend_reuse(
        "python fastapi rag",
        "sales quota crm pipeline territory management",
    )
    assert score < 0.45
    assert rec == "regenerate"


def test_seniority_mismatch_forces_regenerate():
    """Validated seniority mismatch wins over high lexical overlap."""
    text = "python fastapi rag vector database semantic search"
    rec, score = jdsim.recommend_reuse(
        text,
        text,
        current_requirements=_reqs("intern"),
        prior_requirements=_reqs("senior"),
    )
    assert score == 1.0
    assert rec == "regenerate"


def test_tokenize_lowercases_and_strips_punctuation():
    assert "python" in jdsim.tokenize("Python, FastAPI!")
    assert "fastapi" in jdsim.tokenize("Python, FastAPI!")
