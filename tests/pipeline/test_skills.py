"""Tests for the tailored skills-list stage.

No network: LLM calls are stubbed at `llm.client_for` with a shared reply queue, matching
the house convention in `tests/pipeline/test_expand.py` / `tests/pipeline/test_rewrite.py`.
"""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.content.data import (
    Bullet,
    Contact,
    Experience,
    MasterResume,
    Project,
    SkillGroup,
)
from resume_tailor.infra import llm
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from resume_tailor.pipeline.skills import (
    SelectedSkillLLM,
    SkillsSelectionLLM,
    _accept,
    build_pool,
    format_markdown,
    paste_line,
    pool_key,
    select_skills,
)


def _bullet(bid: str, text: str, tags: list[str]) -> Bullet:
    return Bullet(id=bid, text=text, tags=tags)


def _reqs(*keywords: Keyword) -> JobRequirements:
    return JobRequirements(title="Software Engineer", seniority="entry", keywords=list(keywords))


def _kw(phrase: str, canonical: str, importance: str = "must_have") -> Keyword:
    return Keyword(phrase=phrase, canonical=canonical, importance=importance)


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, replies: list):
        self._replies = replies
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if not self._replies:
            raise AssertionError("skills fake client has no replies left")
        return _FakeResponse(self._replies.pop(0))


class _FakeClient:
    def __init__(self, replies: list, recorder: list):
        self.messages = _FakeMessages(replies)
        recorder.append(self.messages)


@pytest.fixture
def skills_calls(monkeypatch, tmp_path):
    """Stub `llm.client_for` with a shared reply queue; isolate the cache dir."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    config.CACHE_DIR.mkdir()
    config.resolve("claude")

    replies: list = []
    recorders: list = []

    def client_for(purpose: str):
        assert purpose == "skills"
        return _FakeClient(replies, recorders)

    monkeypatch.setattr(llm, "client_for", client_for)

    def queue(*parsed):
        replies.extend(parsed)
        return recorders

    yield queue
    config.resolve("claude")


# ---------------------------------------------------------------------------
# build_pool
# ---------------------------------------------------------------------------


def test_build_pool_merges_project_tech_with_bullet_tag():
    """A project-tech label and a bullet tag naming the same tool merge into one candidate."""
    resume = MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        projects=[Project(id="rag-bot", name="RAG Bot", tech=["FastAPI"])],
        experience=[
            Experience(
                company="Alpha Co",
                title="Engineer",
                start="2024",
                end="Present",
                bullets=[_bullet("a1", "Shipped endpoints.", ["fastapi"])],
            )
        ],
    )
    pool = build_pool(resume, _reqs())
    matches = [c for c in pool if c.key == pool_key("fastapi")]
    assert len(matches) == 1
    candidate = matches[0]
    assert candidate.label == "FastAPI"
    assert any(s.startswith("project:") for s in candidate.sources)
    assert "tag" in candidate.sources


def test_build_pool_prefers_skills_section_wording():
    """A skills-group item's spelling wins over a project-tech spelling of the same key."""
    resume = MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        skills=[SkillGroup(label="Tools", items=["Postgres"])],
        projects=[Project(id="p1", name="P", tech=["PostgreSQL"])],
    )
    pool = build_pool(resume, _reqs())
    assert pool_key("Postgres") == pool_key("PostgreSQL")
    matches = [c for c in pool if c.key == pool_key("Postgres")]
    assert len(matches) == 1
    assert matches[0].label == "Postgres"


def test_build_pool_does_not_merge_narrower_labels():
    """`labels_are_equivalent`'s narrowing branch must not reach pool construction.

    "retrieval" and "hybrid retrieval & reranking" are related but not the same claim —
    collapsing them would let the tile silently drop half of what the resume claims.
    """
    resume = MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        skills=[SkillGroup(label="AI/ML", items=["hybrid retrieval & reranking"])],
        experience=[
            Experience(
                company="Alpha Co",
                title="Engineer",
                start="2024",
                end="Present",
                bullets=[_bullet("a1", "Built search.", ["retrieval"])],
            )
        ],
    )
    pool = build_pool(resume, _reqs())
    labels = {c.label for c in pool}
    assert "hybrid retrieval & reranking" in labels
    assert "retrieval" in labels
    assert len(pool) == 2


def test_pool_cap_keeps_jd_matched_candidates(monkeypatch):
    """Truncation to `limit` never drops a candidate the posting actually asked for."""
    resume = MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        experience=[
            Experience(
                company="Alpha Co",
                title="Engineer",
                start="2024",
                end="Present",
                bullets=[
                    _bullet("a1", "x", ["skill-a"]),
                    _bullet("a2", "x", ["skill-b"]),
                    _bullet("a3", "x", ["skill-c"]),
                    _bullet("a4", "x", ["skill-d"]),
                    _bullet("a5", "x", ["skill-e"]),
                ],
            )
        ],
    )
    reqs = _reqs(_kw("Skill B", "skill-b"), _kw("Skill D", "skill-d"))
    pool = build_pool(resume, reqs, limit=3)
    assert len(pool) == 3
    keys = {c.key for c in pool}
    assert "skill-b" in keys
    assert "skill-d" in keys


# ---------------------------------------------------------------------------
# _accept: membership, tiering, force-include, ordering, cap
# ---------------------------------------------------------------------------


def _resume_with_tags(*tag_lists: list[str]) -> MasterResume:
    return MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        experience=[
            Experience(
                company="Alpha Co",
                title="Engineer",
                start="2024",
                end="Present",
                bullets=[
                    _bullet(f"a{i}", "text", tags) for i, tags in enumerate(tag_lists)
                ],
            )
        ],
    )


def test_accept_drops_unknown_skill_with_warning():
    """A skill outside the pool is dropped, never raises."""
    resume = _resume_with_tags(["python"])
    pool = build_pool(resume, _reqs())
    suggestions, warnings = _accept(
        [SelectedSkillLLM(skill="python"), SelectedSkillLLM(skill="kubernetes")],
        pool,
        _reqs(),
    )
    assert [s.skill for s in suggestions] == ["python"]
    assert any("dropped unknown skill" in w and "kubernetes" in w for w in warnings)


def test_tier_required_preferred_additional():
    """Exact-canonical must_have -> required; nice_to_have -> preferred; unmatched -> additional."""
    resume = _resume_with_tags(["skill-a"], ["skill-b"], ["skill-c"])
    reqs = _reqs(
        _kw("Skill A", "skill-a", importance="must_have"),
        _kw("Skill B", "skill-b", importance="nice_to_have"),
    )
    pool = build_pool(resume, reqs)
    suggestions, _ = _accept(
        [
            SelectedSkillLLM(skill="skill-a"),
            SelectedSkillLLM(skill="skill-b"),
            SelectedSkillLLM(skill="skill-c"),
        ],
        pool,
        reqs,
    )
    tier_by_skill = {s.pool_label: s.tier for s in suggestions}
    assert tier_by_skill["skill-a"] == "required"
    assert tier_by_skill["skill-b"] == "preferred"
    assert tier_by_skill["skill-c"] == "additional"
    assert next(s for s in suggestions if s.pool_label == "skill-c").jd_phrase == ""


def test_tier_near_miss_matches_via_labels_are_equivalent():
    """A JD canonical that only fuzzy-matches the pool label still gets tiered from the keyword."""
    resume = _resume_with_tags(["group relative policy optimization"])
    reqs = _reqs(_kw("GRPO", "grpo", importance="nice_to_have"))
    pool = build_pool(resume, reqs)
    suggestions, _ = _accept(
        [SelectedSkillLLM(skill="group relative policy optimization")], pool, reqs
    )
    assert len(suggestions) == 1
    assert suggestions[0].tier == "preferred"
    assert suggestions[0].jd_phrase == "GRPO"


def test_ordering_required_first_preserves_model_order_within_tier():
    """Output is tier-sorted (required first); the model's order survives within a tier."""
    resume = _resume_with_tags(["skill-a"], ["skill-b"], ["skill-z"])
    reqs = _reqs(
        _kw("Skill A", "skill-a"),
        _kw("Skill B", "skill-b"),
    )
    pool = build_pool(resume, reqs)
    suggestions, _ = _accept(
        [
            SelectedSkillLLM(skill="skill-z"),  # additional
            SelectedSkillLLM(skill="skill-b"),  # required, second in model order
            SelectedSkillLLM(skill="skill-a"),  # required, first in model order
        ],
        pool,
        reqs,
    )
    assert [s.pool_label for s in suggestions] == ["skill-b", "skill-a", "skill-z"]


def test_display_rename_accepted_when_jd_anchored_and_equivalent():
    """A JD-anchored respelling of the same key (via TAG_ALIASES) is applied."""
    resume = MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        skills=[SkillGroup(label="Tools", items=["Postgres"])],
    )
    reqs = _reqs(_kw("PostgreSQL", "postgresql", importance="nice_to_have"))
    pool = build_pool(resume, reqs)
    suggestions, warnings = _accept(
        [SelectedSkillLLM(skill="Postgres", display="PostgreSQL")], pool, reqs
    )
    assert suggestions[0].skill == "PostgreSQL"
    assert suggestions[0].pool_label == "Postgres"
    assert not any("rejected display" in w for w in warnings)


def test_display_rename_rejected_when_not_jd_anchored():
    """A respelling the posting never mentioned is rejected; pool spelling is kept."""
    resume = MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        skills=[SkillGroup(label="Tools", items=["Postgres"])],
    )
    reqs = _reqs()
    pool = build_pool(resume, reqs)
    suggestions, warnings = _accept(
        [SelectedSkillLLM(skill="Postgres", display="PostgreSQL")], pool, reqs
    )
    assert suggestions[0].skill == "Postgres"
    assert any("rejected display" in w for w in warnings)


def test_display_rename_rejected_when_narrowing():
    """A respelling that drops part of the claim is rejected even when JD-anchored."""
    resume = MasterResume(
        contact=Contact(name="Test", email="t@example.com"),
        skills=[SkillGroup(label="AI/ML", items=["hybrid retrieval & reranking"])],
    )
    reqs = _reqs(_kw("retrieval", "retrieval"))
    pool = build_pool(resume, reqs)
    suggestions, warnings = _accept(
        [SelectedSkillLLM(skill="hybrid retrieval & reranking", display="retrieval")],
        pool,
        reqs,
    )
    assert suggestions[0].skill == "hybrid retrieval & reranking"
    assert any("rejected display" in w for w in warnings)


def test_force_include_exact_must_have_omitted_by_model():
    """An exact-canonical must-have the model forgot is force-included, with a warning."""
    resume = _resume_with_tags(["skill-a"], ["skill-b"])
    reqs = _reqs(_kw("Skill A", "skill-a", importance="must_have"))
    pool = build_pool(resume, reqs)
    suggestions, warnings = _accept([SelectedSkillLLM(skill="skill-b")], pool, reqs)
    labels = {s.pool_label for s in suggestions}
    assert "skill-a" in labels
    assert next(s for s in suggestions if s.pool_label == "skill-a").tier == "required"
    assert any("added" in w and "skill-a" in w for w in warnings)


def test_force_include_does_not_fire_on_fuzzy_only_match():
    """A must-have that only fuzzy-matches the pool is NOT force-included — a real judgement
    call the model is entitled to make, not something code should override."""
    resume = _resume_with_tags(["group relative policy optimization"])
    reqs = _reqs(_kw("GRPO", "grpo", importance="must_have"))
    pool = build_pool(resume, reqs)
    suggestions, warnings = _accept([], pool, reqs)
    assert suggestions == []
    assert not any("added" in w for w in warnings)


def test_max_skills_suggested_trims_additional_first(monkeypatch):
    """Truncation to `MAX_SKILLS_SUGGESTED` cuts additional-tier skills first."""
    monkeypatch.setattr(config, "MAX_SKILLS_SUGGESTED", 2)
    resume = _resume_with_tags(["skill-a"], ["skill-b"], ["skill-c"])
    reqs = _reqs(_kw("Skill A", "skill-a", importance="must_have"))
    pool = build_pool(resume, reqs)
    suggestions, _ = _accept(
        [
            SelectedSkillLLM(skill="skill-c"),
            SelectedSkillLLM(skill="skill-b"),
            SelectedSkillLLM(skill="skill-a"),
        ],
        pool,
        reqs,
    )
    assert len(suggestions) == 2
    assert suggestions[0].pool_label == "skill-a"


# ---------------------------------------------------------------------------
# select_skills: caching, cross-backend invalidation, drop-unknown never fatal
# ---------------------------------------------------------------------------


def test_unparseable_response_never_raises_when_swallowed(skills_calls):
    """`select_skills` itself raises on a None parse (mirrors `expand`); callers swallow it."""
    resume = _resume_with_tags(["python"])
    reqs = _reqs()
    skills_calls(None)
    with pytest.raises(RuntimeError):
        select_skills(resume, reqs, use_cache=False)


def test_cache_reuse_and_cache_key_changes_with_backend(skills_calls):
    """A second call with the same backend hits cache; switching backends forces a miss."""
    resume = _resume_with_tags(["python"])
    reqs = _reqs()
    reply = SkillsSelectionLLM(selected=[SelectedSkillLLM(skill="python")])
    skills_calls(reply)
    config.resolve("claude")

    first = select_skills(resume, reqs, use_cache=True)
    assert first.skills

    second = select_skills(resume, reqs, use_cache=True)
    assert [s.skill for s in second.skills] == [s.skill for s in first.skills]

    config.resolve("ollama")
    with pytest.raises(AssertionError, match="no replies"):
        select_skills(resume, reqs, use_cache=True)


def test_hallucinated_skill_dropped_before_cache_write(skills_calls):
    """A skill outside the pool never survives to a cached reuse or the returned plan."""
    resume = _resume_with_tags(["python"])
    reqs = _reqs()
    reply = SkillsSelectionLLM(
        selected=[SelectedSkillLLM(skill="python"), SelectedSkillLLM(skill="kubernetes")]
    )
    skills_calls(reply)
    plan = select_skills(resume, reqs, use_cache=False)
    assert [s.skill for s in plan.skills] == ["python"]
    assert any("kubernetes" in w for w in plan.warnings)


def test_empty_pool_returns_empty_plan_without_calling_model(skills_calls):
    """No evidence in the resume -> no call is made, no error."""
    resume = MasterResume(contact=Contact(name="Test", email="t@example.com"))
    reqs = _reqs()
    recorders = skills_calls()
    plan = select_skills(resume, reqs, use_cache=False)
    assert plan.skills == []
    assert plan.pool_size == 0
    assert recorders == []


# ---------------------------------------------------------------------------
# paste_line / format_markdown
# ---------------------------------------------------------------------------


def test_paste_line_and_format_markdown():
    from resume_tailor.pipeline.skills import SkillsPlan, SkillSuggestion

    plan = SkillsPlan(
        skills=[
            SkillSuggestion(
                skill="Python", pool_label="python", tier="required", jd_phrase="Python"
            ),
            SkillSuggestion(skill="Docker", pool_label="docker", tier="additional"),
        ],
        model="openai:gemma4:cloud",
        pool_size=2,
    )
    assert paste_line(plan) == "Python, Docker"
    text = format_markdown(plan)
    assert text.startswith("Python, Docker")
    assert "Required:" in text
    assert "Python — Python" in text
    assert "Additional:" in text
    assert "Docker" in text


def test_format_markdown_empty_plan():
    from resume_tailor.pipeline.skills import SkillsPlan

    assert format_markdown(SkillsPlan()) == ""
