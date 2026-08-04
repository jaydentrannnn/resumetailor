"""Tests for the pure, deterministic half of the pipeline.

The LLM calls are not tested here — they cost money and are non-deterministic. What is
tested is everything that guards them: scoring, selection, and the fabrication check that
decides whether a rewrite is allowed to ship.
"""

from __future__ import annotations

import pytest

from resume_tailor import config, rewrite
from resume_tailor.data import Bullet, Experience, Project, load
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor.rewrite import (
    BulletScore,
    ScoreTable,
    check_fabrication,
    score,
    score_entry,
    select,
    select_entries,
    select_within_entries,
    selectable_total,
)


def bullet(bid: str, text: str, tags: list[str], metric: bool = False) -> Bullet:
    return Bullet(id=bid, text=text, tags=tags, metric=metric)


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, table: ScoreTable):
        self._table = table

    def parse(self, **kwargs):
        return _FakeResponse(self._table)


class _FakeScoringClient:
    """Stands in for the Anthropic client in score-table tests. No network, no key."""

    def __init__(self, table: ScoreTable):
        self.messages = _FakeMessages(table)


def requirements(*keywords: tuple[str, ...]) -> JobRequirements:
    """Build requirements from (canonical, importance) or (canonical, importance, kind)."""
    return JobRequirements(
        title="Test Role",
        seniority="entry",
        keywords=[
            Keyword(  # type: ignore[arg-type]
                phrase=kw[0], canonical=kw[0], importance=kw[1],
                **({"kind": kw[2]} if len(kw) > 2 else {}),
            )
            for kw in keywords
        ],
    )


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


def test_must_have_outweighs_nice_to_have():
    reqs = requirements(("python", "must_have"), ("react", "nice_to_have"))
    py = bullet("a", "Built a service.", ["python"])
    react = bullet("b", "Built a UI.", ["react"])
    assert score(py, reqs) > score(react, reqs)


def test_metric_bonus_breaks_ties_but_only_when_relevant():
    reqs = requirements(("python", "must_have"))
    plain = bullet("a", "Built a service.", ["python"])
    quantified = bullet("b", "Built a service, 40% faster.", ["python"], metric=True)
    assert score(quantified, reqs) > score(plain, reqs)

    # A metric on an irrelevant bullet must not manufacture relevance out of nothing,
    # otherwise every quantified bullet floats to the top of every posting.
    irrelevant = bullet("c", "Packed 100 boxes.", ["logistics"], metric=True)
    assert score(irrelevant, reqs) == 0.0


def test_score_uses_canonical_tags():
    # "py3" in the master data normalises to "python" at load time, so a posting asking
    # for python must still match it.
    assert config.canonical_tag("py3") == "python"
    reqs = requirements(("python", "must_have"))
    assert score(bullet("a", "x", ["py3"]), reqs) > 0


# --------------------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------------------


def test_select_preserves_original_order():
    reqs = requirements(("python", "must_have"))
    bullets = [
        bullet("first", "Least relevant.", ["logistics"]),
        bullet("second", "Most relevant.", ["python"]),
        bullet("third", "Also relevant.", ["python"]),
    ]
    picked = select(bullets, reqs, limit=2)
    # "second" and "third" outrank "first", but must come back in document order.
    assert [b.id for b in picked] == ["second", "third"]


def test_select_respects_limit_and_zero():
    reqs = requirements(("python", "must_have"))
    bullets = [bullet(str(i), "x", ["python"]) for i in range(5)]
    assert len(select(bullets, reqs, limit=3)) == 3
    assert select(bullets, reqs, limit=0) == []


def test_select_still_fills_when_nothing_matches():
    """An entry with no relevant bullets should render lines, not an empty gap."""
    reqs = requirements(("rust", "must_have"))
    bullets = [bullet("a", "x", ["python"]), bullet("b", "y", ["sql"])]
    assert len(select(bullets, reqs, limit=2)) == 2


# --------------------------------------------------------------------------------------
# Entry selection — experience and projects ranked separately
# --------------------------------------------------------------------------------------


def test_select_entries_ranks_sections_independently():
    """The point of separate ranking: strong projects must not evict a relevant job."""
    reqs = requirements(("python", "must_have"))
    resume = load()

    jobs = select_entries(resume.experience, reqs, limit=3)
    projects = select_entries(resume.projects, reqs, limit=2)

    assert len(jobs) == 3
    assert len(projects) == 2
    # Nothing from one section can appear in the other's results.
    assert {j.company for j in jobs}.isdisjoint({p.name for p in projects})


def test_select_entries_preserves_document_order():
    reqs = requirements(("python", "must_have"))
    resume = load()

    chosen = select_entries(resume.experience, reqs, limit=3)
    order = [e.company for e in resume.experience]
    assert [e.company for e in chosen] == [c for c in order if c in {e.company for e in chosen}]


def test_score_entry_sums_its_bullets():
    reqs = requirements(("python", "must_have"))
    rich = Experience(
        company="Rich", title="t", start="2025-01", end="2025-02",
        bullets=[bullet("r1", "x", ["python"]), bullet("r2", "y", ["python"])],
    )
    thin = Experience(
        company="Thin", title="t", start="2025-01", end="2025-02",
        bullets=[bullet("t1", "x", ["python"])],
    )
    assert score_entry(rich, reqs) > score_entry(thin, reqs)


def test_every_selected_entry_keeps_at_least_one_bullet():
    """An entry that won its slot must render; build_context omits bullet-less entries."""
    reqs = requirements(("rust", "must_have"))  # nothing matches, so all scores are 0
    resume = load()
    entries = select_entries(resume.experience, reqs, limit=3)

    # A limit below the entry count must still leave every entry represented.
    picked = select_within_entries(entries, reqs, limit=1)
    covered = {e.company for e in entries for b in e.bullets if b in picked}
    assert covered == {e.company for e in entries}


def test_extra_budget_goes_to_the_strongest_bullets():
    reqs = requirements(("python", "must_have"))
    resume = load()
    entries = select_entries(resume.experience, reqs, limit=3)

    floors = select_within_entries(entries, reqs, limit=len(entries))
    richer = select_within_entries(entries, reqs, limit=len(entries) + 2)

    assert len(floors) == len(entries)
    assert len(richer) == len(entries) + 2
    assert set(b.id for b in floors) <= set(b.id for b in richer)


def test_flat_pool_selection_unchanged_by_default():
    """`experience_share=None, max_per_entry=None` must reproduce the original flat-pool
    floors+select algorithm exactly (pinned per CLAUDE.md/the plan's equivalence
    requirement), not just something with the same size.
    """
    reqs = requirements(("python", "must_have"))
    resume = load()
    entries = [
        *select_entries(resume.experience, reqs, limit=3),
        *select_entries(resume.projects, reqs, limit=2),
    ]

    floors = [max(e.bullets, key=lambda b: score(b, reqs)) for e in entries if e.bullets]
    kept = {id(b) for b in floors}
    pool = [b for e in entries for b in e.bullets if id(b) not in kept]
    kept |= {id(b) for b in select(pool, reqs, limit=10 - len(floors))}
    expected = [b for e in entries for b in e.bullets if id(b) in kept]

    actual = select_within_entries(entries, reqs, limit=10)
    assert [b.id for b in actual] == [b.id for b in expected]


# --------------------------------------------------------------------------------------
# Section weighting (experience_share) and per-entry cap (max_per_entry)
# --------------------------------------------------------------------------------------


def _exp(company: str, *bullets: Bullet) -> Experience:
    return Experience(company=company, title="t", start="2024-01", end="2024-02", bullets=list(bullets))


def _proj(name: str, *bullets: Bullet) -> Project:
    return Project(id=name, name=name, bullets=list(bullets))


def test_experience_share_moves_budget_from_projects_to_experience():
    """A flat pool lets keyword-dense project bullets out-rank low-scoring experience
    bullets for the whole discretionary budget; a high experience_share reverses that at
    the same overall limit.
    """
    reqs = requirements(("python", "must_have"))
    exp = _exp("Exp1", bullet("e1", "x", ["misc"]), bullet("e2", "x", ["misc"]), bullet("e3", "x", ["misc"]))
    proj = _proj("Proj1", bullet("p1", "x", ["python"]), bullet("p2", "x", ["python"]), bullet("p3", "x", ["python"]))
    entries = [exp, proj]

    flat = select_within_entries(entries, reqs, limit=4)
    flat_exp = sum(1 for b in flat if b.id.startswith("e"))
    flat_proj = sum(1 for b in flat if b.id.startswith("p"))
    assert (flat_exp, flat_proj) == (1, 3)  # project's keyword match wins the flat pool

    weighted = select_within_entries(entries, reqs, limit=4, experience_share=0.75)
    weighted_exp = sum(1 for b in weighted if b.id.startswith("e"))
    weighted_proj = sum(1 for b in weighted if b.id.startswith("p"))
    assert (weighted_exp, weighted_proj) == (3, 1)
    assert len(weighted) == 4


def test_experience_share_extremes_never_drop_a_floor():
    """share=0.0 and share=1.0 must still leave every entry its one floor bullet."""
    reqs = requirements(("python", "must_have"))
    exp = _exp("Exp1", bullet("e1", "x", ["misc"]), bullet("e2", "x", ["misc"]))
    proj = _proj("Proj1", bullet("p1", "x", ["python"]), bullet("p2", "x", ["python"]))
    entries = [exp, proj]

    starved_exp = select_within_entries(entries, reqs, limit=4, experience_share=0.0)
    assert sum(1 for b in starved_exp if b.id.startswith("e")) >= 1
    assert sum(1 for b in starved_exp if b.id.startswith("p")) >= 1

    starved_proj = select_within_entries(entries, reqs, limit=4, experience_share=1.0)
    assert sum(1 for b in starved_proj if b.id.startswith("e")) >= 1
    assert sum(1 for b in starved_proj if b.id.startswith("p")) >= 1


def test_max_per_entry_caps_richest_entry_and_spills_the_rest():
    """A capped entry's forfeited slot goes to the next-best bullet elsewhere, so the
    overall selection still reaches `limit` rather than shrinking.
    """
    reqs = requirements(("python", "must_have"))
    exp = _exp(
        "Exp1",
        bullet("a1", "x", ["misc"]),
        bullet("a2", "x", ["misc"]),
        bullet("a3", "x", ["misc"]),
    )
    proj = _proj(
        "Proj1",
        bullet("p1", "x", ["python"]),
        bullet("p2", "x", ["python"]),
        bullet("p3", "x", ["python"]),
    )
    entries = [exp, proj]

    uncapped = select_within_entries(entries, reqs, limit=4)
    assert sum(1 for b in uncapped if b.id.startswith("p")) == 3  # project takes all it can

    capped = select_within_entries(entries, reqs, limit=4, max_per_entry=2)
    assert len(capped) == 4  # still reaches the limit — the freed slot spilled to Exp1
    assert sum(1 for b in capped if b.id.startswith("p")) == 2
    assert sum(1 for b in capped if b.id.startswith("a")) == 2


def test_experience_share_spillover_when_a_section_cannot_fill_its_budget():
    """A share requesting more than a section can supply spills the surplus to the other
    section rather than stranding it (and shrinking the total below `limit`).
    """
    reqs = requirements(("python", "must_have"))
    exp = _exp("Exp1", bullet("e1", "x", ["misc"]))  # only one bullet available
    proj = _proj(
        "Proj1",
        bullet("p1", "x", ["python"]),
        bullet("p2", "x", ["python"]),
        bullet("p3", "x", ["python"]),
        bullet("p4", "x", ["python"]),
    )
    entries = [exp, proj]

    selected = select_within_entries(entries, reqs, limit=5, experience_share=0.9)
    assert len(selected) == 5  # exp can only give 1; the other 4 must come from proj
    assert sum(1 for b in selected if b.id.startswith("e")) == 1
    assert sum(1 for b in selected if b.id.startswith("p")) == 4


def test_selectable_total():
    exp = _exp("Exp1", bullet("e1", "x", ["misc"]), bullet("e2", "x", ["misc"]))
    proj = _proj("Proj1", bullet("p1", "x", ["misc"]), bullet("p2", "x", ["misc"]), bullet("p3", "x", ["misc"]))
    entries = [exp, proj]

    assert selectable_total(entries) == 5
    assert selectable_total(entries, max_per_entry=2) == 4  # proj's 3rd bullet is unreachable
    assert selectable_total(entries, max_per_entry=10) == 5  # cap above every entry's size is a no-op


# --------------------------------------------------------------------------------------
# Soft-skill weighting
# --------------------------------------------------------------------------------------


def test_soft_must_have_scores_below_a_technical_one():
    """A broad soft tag must not buy the same score as a named technology.

    Soft tags sit on nearly every entry including the volunteer and support roles, so at
    full must-have weight a posting naming three of them as required could float a
    non-technical entry over a relevant job.
    """
    reqs = requirements(("python", "must_have"), ("communication", "must_have", "soft"))
    tech = bullet("a", "Built a service.", ["python"])
    soft = bullet("b", "Explained things.", ["communication"])

    assert score(tech, reqs) == config.MUST_HAVE_WEIGHT
    assert score(soft, reqs) == config.SOFT_SKILL_WEIGHT
    assert score(soft, reqs) < score(tech, reqs)


def test_soft_must_have_still_outscores_a_nice_to_have():
    """Discounted, not dismissed — the posting did say it was required."""
    reqs = requirements(("communication", "must_have", "soft"), ("react", "nice_to_have"))
    soft = bullet("a", "Explained things.", ["communication"])
    nice = bullet("b", "Built a UI.", ["react"])
    assert score(soft, reqs) > score(nice, reqs)


def test_kind_defaults_to_technical_weight():
    """An unclassified keyword keeps full weight rather than being quietly discounted."""
    reqs = requirements(("python", "must_have"))
    assert reqs.keywords[0].kind == "technical"
    assert score(bullet("a", "x", ["python"]), reqs) == config.MUST_HAVE_WEIGHT


def test_nice_to_have_weight_is_unaffected_by_kind():
    tech = requirements(("react", "nice_to_have"))
    soft = requirements(("teamwork", "nice_to_have", "soft"))
    assert score(bullet("a", "x", ["react"]), tech) == score(
        bullet("b", "x", ["teamwork"]), soft
    )


# --------------------------------------------------------------------------------------
# Semantic relevance — the optional second signal
# --------------------------------------------------------------------------------------


def test_semantic_none_reproduces_keyword_only_scoring():
    """Pins the regression: the semantic layer must be inert unless asked for."""
    reqs = requirements(("python", "must_have"))
    b = bullet("a", "Built a service.", ["python"], metric=True)
    assert score(b, reqs, semantic=None) == score(b, reqs)
    assert score(b, reqs, semantic={}) == score(b, reqs)


def test_semantic_weight_of_zero_is_a_no_op(monkeypatch):
    """`SEMANTIC_WEIGHT = 0.0` is the A/B control, so it must be exactly keyword-only."""
    monkeypatch.setattr(config, "SEMANTIC_WEIGHT", 0.0)
    reqs = requirements(("python", "must_have"))
    b = bullet("a", "Built a service.", ["python"])
    assert score(b, reqs, semantic={"a": 10.0}) == score(b, reqs)


def test_semantic_score_is_added_and_scaled():
    reqs = requirements(("python", "must_have"))
    b = bullet("a", "Built a service.", ["python"])
    expected = config.MUST_HAVE_WEIGHT + config.SEMANTIC_WEIGHT * 8.0
    assert score(b, reqs, semantic={"a": 8.0}) == pytest.approx(expected)


def test_semantic_relevance_can_rescue_a_bullet_with_no_matching_tag():
    """The whole point: domain resonance that no tag encodes still has to reach the ranking."""
    reqs = requirements(("python", "must_have"))
    tagged = bullet("a", "Built a service.", ["python"])
    untagged = bullet("b", "Advised students on course planning.", ["mentorship"])

    assert score(untagged, reqs) == 0.0
    assert score(untagged, reqs, semantic={"b": 10.0}) > score(tagged, reqs)


def test_metric_bonus_applies_to_a_semantic_only_match():
    """The bonus is gated on relevance, and semantic relevance is relevance."""
    reqs = requirements(("python", "must_have"))
    b = bullet("a", "Packed 100 boxes.", ["logistics"], metric=True)

    assert score(b, reqs) == 0.0
    scored = score(b, reqs, semantic={"a": 4.0})
    assert scored == pytest.approx(config.SEMANTIC_WEIGHT * 4.0 + config.METRIC_BONUS)


def test_semantic_reaches_entry_and_bullet_selection():
    reqs = requirements(("python", "must_have"))
    weak = Experience(
        company="Weak", title="T", start="2024-01", end="2024-02",
        bullets=[bullet("w1", "Did a thing.", ["logistics"])],
    )
    strong = Experience(
        company="Strong", title="T", start="2024-01", end="2024-02",
        bullets=[bullet("s1", "Built a service.", ["python"])],
    )

    assert [e.company for e in select_entries([weak, strong], reqs, limit=1)] == ["Strong"]
    chosen = select_entries([weak, strong], reqs, limit=1, semantic={"w1": 10.0})
    assert [e.company for e in chosen] == ["Weak"]


def test_unscored_bullets_fall_back_to_their_keyword_score():
    """A bullet the model omitted must not be treated as irrelevant."""
    reqs = requirements(("python", "must_have"))
    b = bullet("missing", "Built a service.", ["python"])
    assert score(b, reqs, semantic={"other": 10.0}) == config.MUST_HAVE_WEIGHT


# --------------------------------------------------------------------------------------
# Score table — id mapping and clamping (the API call itself is not tested)
# --------------------------------------------------------------------------------------


def test_score_table_maps_ids_and_clamps(monkeypatch, tmp_path):
    """Unknown ids are dropped and values clamped: this number is multiplied into the rank."""
    bullets = [bullet("a", "x", ["python"]), bullet("b", "y", ["sql"])]
    table = ScoreTable(
        scores=[
            BulletScore(id="a", relevance=99.0, reason="way over"),
            BulletScore(id="b", relevance=-5.0, reason="way under"),
            BulletScore(id="ghost", relevance=7.0, reason="not a real bullet"),
        ]
    )

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rewrite.config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(
        rewrite.llm, "client_for", lambda purpose: _FakeScoringClient(table)
    )

    result = rewrite.score_table(bullets, requirements(("python", "must_have")))

    assert result == {"a": 10.0, "b": 0.0}


def test_score_table_is_empty_without_bullets():
    assert rewrite.score_table([], requirements(("python", "must_have"))) == {}


def test_score_cache_key_covers_bullet_text():
    """Editing a bullet must not silently reuse the score computed for its old wording."""
    reqs = requirements(("python", "must_have"))
    before = rewrite._score_cache_path([bullet("a", "Original text.", ["python"])], reqs)
    after = rewrite._score_cache_path([bullet("a", "Edited text.", ["python"])], reqs)
    assert before != after


def test_score_cache_key_covers_the_posting():
    b = [bullet("a", "x", ["python"])]
    one = rewrite._score_cache_path(b, requirements(("python", "must_have")))
    two = rewrite._score_cache_path(b, requirements(("sql", "must_have")))
    assert one != two


# --------------------------------------------------------------------------------------
# Fabrication guard — the correctness property of the whole tool
# --------------------------------------------------------------------------------------


def test_faithful_rewording_passes():
    src = bullet(
        "a",
        "Developed a typo-tolerant search using RapidFuzz fuzzy matching, achieving 86% accuracy.",
        ["python", "fuzzy matching", "rapidfuzz"],
    )
    reworded = "Built typo-tolerant approximate matching with RapidFuzz, reaching 86% accuracy."
    assert check_fabrication(src, reworded) == []


def test_planted_technology_is_rejected():
    """The headline case: the model invents a framework the candidate never used."""
    src = bullet("a", "Built a search service in Python.", ["python", "search"])
    fabricated = "Built a search service in Python using Kubernetes and PyTorch."
    offenders = check_fabrication(src, fabricated)
    assert "Kubernetes" in offenders
    assert "PyTorch" in offenders


def test_invented_metric_is_rejected():
    src = bullet("a", "Reduced query latency through optimization.", ["optimization"])
    fabricated = "Reduced query latency by 99% through optimization."
    assert "99" in " ".join(check_fabrication(src, fabricated))


def test_tags_extend_the_permitted_vocabulary():
    """A technology named in tags but not in the text is legitimately available."""
    src = bullet("a", "Built a vector search backend.", ["chromadb", "search"])
    assert check_fabrication(src, "Built a ChromaDB vector search backend.") == []


def test_sentence_initial_capitals_are_not_false_positives():
    src = bullet("a", "designed and shipped an internal tool", ["python"])
    assert check_fabrication(src, "Designed and shipped an internal tool.") == []


def test_preserved_numbers_pass():
    src = bullet("a", "Indexed 55k+ documents with 92% accuracy.", ["search"], metric=True)
    assert check_fabrication(src, "Indexed 55k+ documents, 92% accuracy.") == []


@pytest.mark.parametrize("term", ["Elasticsearch", "GRPO", "GPT-4"])
def test_various_unsourced_terms_are_caught(term):
    src = bullet("a", "Trained a model on public data.", ["machine learning"])
    assert term in check_fabrication(src, f"Trained a model on public data with {term}.")


def test_slash_compound_of_permitted_terms_passes():
    """A live false positive: the guard rejected a real run over "Python/FastAPI".

    `_TOKEN` treats "/" as an internal separator, so a slash compound arrives as a single
    token whose lowercase form is absent from a vocabulary holding each half separately.
    Both halves are traceable, so the compound asserts nothing new.
    """
    src = bullet(
        "a",
        "FastAPI backend streaming graph events into a Next.js UI.",
        ["fastapi", "react", "typescript", "python"],
    )
    rewritten = "Shipped a Python/FastAPI backend streaming to a React/TypeScript frontend."
    assert check_fabrication(src, rewritten) == []


def test_slash_compound_is_still_caught_when_a_part_is_unsourced():
    """The permissive half of the rule must not become a hole: one bad part fails the whole."""
    src = bullet("a", "Built a backend in Python.", ["python"])
    offenders = check_fabrication(src, "Built a Python/Kubernetes backend.")
    assert "Python/Kubernetes" in offenders


def test_plural_of_a_permitted_term_passes():
    """A live false positive: a `gpu` tag rejected the rewrite's "GPUs"."""
    src = bullet("a", "Trained on four A30/L40S.", ["gpu", "fine-tuning"])
    assert check_fabrication(src, "Trained on four A30/L40S GPUs.") == []

    # And the reverse direction: source plural, rewrite singular.
    src = bullet("b", "Benchmarked several LLMs.", ["llm"])
    assert check_fabrication(src, "Benchmarked one LLM.") == []


def test_pluralisation_does_not_excuse_an_unsourced_term():
    src = bullet("a", "Built a search service in Python.", ["python", "search"])
    assert "TPUs" in check_fabrication(src, "Built a search service on TPUs.")


def test_compound_of_a_permitted_term_and_ordinary_words_passes():
    """A live false positive: an `llm` tag rejected the rewrite's "LLM-powered".

    "powered" carries no factual claim, so the compound asserts only what "LLM" asserts.
    """
    src = bullet("a", "Enabled conditional routing to generate SQL.", ["llm", "rag", "sql"])
    rewritten = "Enabled conditional routing in an LLM-powered RAG pipeline to generate SQL."
    assert check_fabrication(src, rewritten) == []


def test_compound_part_that_is_itself_a_compound_still_matches():
    """A live false positive: "Next.js/React" broke into Next+js+React before matching.

    "Next.js" is one token in the source vocabulary, so the split has to try "/" first and
    re-check each side whole rather than shattering the whole term at once.
    """
    src = bullet(
        "a",
        "FastAPI backend streaming graph events into a Next.js 15 UI.",
        ["fastapi", "nextjs", "react", "typescript"],
    )
    assert check_fabrication(src, "Streamed graph events into a Next.js/React UI.") == []


def test_component_of_a_source_compound_is_permitted_alone():
    """A live false positive: source "Recall@k/MRR" rejected a rewrite's bare "MRR".

    `_TOKEN` does not treat "@" as internal, so the source arrives as "Recall" + "k/MRR"
    and the whole-token vocabulary never contained "MRR" on its own.
    """
    src = bullet(
        "a",
        "Authored an evaluation suite (router F1, Recall@k/MRR, citation accuracy).",
        ["evaluation", "retrieval eval"],
    )
    assert check_fabrication(src, "Authored an evaluation suite: Recall@k, MRR, router F1.") == []


def test_source_numbers_are_not_decomposed_into_new_metrics():
    """Splitting "96.3" would invent a "3" the source never claimed."""
    src = bullet("a", "Lifted top-5 accuracy to 96.3% overall.", ["evaluation"], metric=True)
    offenders = check_fabrication(src, "Lifted accuracy 3% overall.")
    assert "3" in offenders


def test_initialism_of_a_source_phrase_passes():
    """A live false positive: a "computer science fundamentals" tag rejected "CS"."""
    src = bullet(
        "a",
        "Mentored students on core concepts across 18 topics.",
        ["teaching", "computer science fundamentals"],
    )
    assert check_fabrication(src, "Mentored students across 18 core CS topics.") == []


def test_unsourced_acronym_is_still_caught():
    """The initialism rule must not excuse an acronym with no phrase behind it."""
    src = bullet("a", "Built a search service in Python.", ["python", "search"])
    assert "GRPO" in check_fabrication(src, "Built a search service in Python with GRPO.")


def test_fabricated_version_is_caught_despite_compound_splitting():
    """Splitting parts must not launder a version bump the source never made.

    The source names GPT-4.1, which tokenises whole — "GPT" is not separately in the
    vocabulary, so a rewrite claiming a different model still fails.
    """
    src = bullet("a", "Benchmarked OpenAI GPT-4.1 Mini for cost.", ["llm", "openai"])
    assert "GPT-5" in check_fabrication(src, "Benchmarked OpenAI GPT-5 for cost.")


def test_thousands_separated_number_is_one_token():
    """"1,000" must not shatter into "1" + "000".

    It did, which put both fragments into the vocabulary as whole tokens and let a rewrite
    assert either one freely — a hole in the "numbers are checked whole" invariant. Found by
    a live run: a faithful rewrite of "over 1,000" was rejected over a phantom "000+".
    """
    src = bullet("a", "Reviewed over 1,000 daily conversations.", ["data analysis"])

    assert check_fabrication(src, "Reviewed 1,000 daily conversations.") == []
    # The hole: neither fragment is licensed on its own.
    assert check_fabrication(src, "Reviewed 000 daily conversations.") == ["000"]
    assert check_fabrication(src, "Handled 1 daily conversation.") == ["1"]


def test_fabricated_thousands_separated_number_is_caught():
    src = bullet("a", "Reviewed over 1,000 daily conversations.", ["data analysis"])
    assert check_fabrication(src, "Reviewed 2,500 daily conversations.") == ["2,500"]


def test_comma_splitting_does_not_license_a_new_figure():
    """Splitting on "," must not do what splitting on "." was already forbidden from doing."""
    src = bullet("a", "Cut latency to 96.3 ms across 1,200 requests.", ["performance"])
    offenders = check_fabrication(src, "Cut latency to 3 ms across 200 requests.")
    assert "3" in offenders and "200" in offenders


def test_fabricated_metric_is_unaffected_by_compound_splitting():
    """Numbers are single tokens with no separator, so splitting never reaches them."""
    src = bullet("a", "Reduced latency through caching.", ["optimization"])
    assert "99" in " ".join(check_fabrication(src, "Reduced latency 99% through caching."))


# --------------------------------------------------------------------------------------
# Widow detection and repair
#
# The failure this guards against is not dishonesty but arithmetic: a bullet two characters
# past a line boundary wraps onto a whole extra line holding one word. Every widow measured
# in output/ came back at 204-207 characters against a 202-character budget.
# --------------------------------------------------------------------------------------

CPL = config.CHARS_PER_LINE


def _text(n: int) -> str:
    """A bullet of exactly `n` characters."""
    return "x" * n


class _FakeRewriteMessages:
    def __init__(self, replies, calls):
        self._replies = replies
        self._calls = calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        if not self._replies:
            raise AssertionError("model called more times than the test supplied replies")
        return _FakeResponse(self._replies.pop(0))


class _FakeRewriteClient:
    """Returns each queued RewriteResult in turn, recording every call's kwargs.

    The queue is shared, not copied: `llm.client_for` is called once per stage call, so a
    per-client copy would silently replay the first reply to the widow-repair pass and make
    the repair look like a no-op.
    """

    def __init__(self, replies, calls):
        self.messages = _FakeRewriteMessages(replies, calls)


def _reply(**by_id) -> rewrite.RewriteResult:
    return rewrite.RewriteResult(
        bullets=[rewrite.RewrittenBullet(id=k, text=v) for k, v in by_id.items()]
    )


@pytest.fixture
def rewrite_calls(monkeypatch):
    """Queue model replies; yields the recorded call kwargs list."""
    calls: list[dict] = []

    def install(*replies):
        queue = list(replies)
        monkeypatch.setattr(
            rewrite.llm, "client_for", lambda purpose: _FakeRewriteClient(queue, calls)
        )
        return calls

    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    return install


# --- the arithmetic -------------------------------------------------------------------


def test_a_bullet_filling_whole_lines_is_not_a_widow():
    """An exact multiple fills its last line completely — the ideal, not the failure."""
    assert config.line_span(_text(2 * CPL)) == 2
    assert config.last_line_fill(_text(2 * CPL)) == CPL
    assert rewrite.widowed({"a": _text(2 * CPL)}) == {}


def test_two_characters_over_a_line_boundary_is_a_widow():
    """The measured failure: 204 characters against a 202 budget costs a whole line."""
    over = _text(2 * CPL + 2)
    assert config.line_span(over) == 3
    assert config.last_line_fill(over) == 2
    assert "a" in rewrite.widowed({"a": over})


def test_a_single_line_bullet_is_never_a_widow():
    """There is no earlier line to fall back onto; a short bullet is just short."""
    assert rewrite.widowed({"a": _text(5)}) == {}
    assert rewrite.widowed({"a": _text(CPL)}) == {}


def test_a_comfortably_filled_last_line_is_not_a_widow():
    assert rewrite.widowed({"a": _text(198)}) == {}


def test_the_ceiling_is_a_full_line_below_where_the_text_ends():
    """An explicit 'cut seven characters', not a vague 'shorten by 15%'."""
    assert rewrite.widowed({"a": _text(204)}) == {"a": 2 * CPL - config.WIDOW_SAFETY}


# --- the prompt -----------------------------------------------------------------------


def test_the_prompt_advertises_a_band_below_the_budget():
    """A ceiling alone is what let the model optimise right up to the cliff edge."""
    soft_min, hard_max = rewrite._length_band(202)
    assert hard_max < 202, "max must sit below the budget, not on it"
    assert soft_min < hard_max

    rendered = rewrite._format_bullets([bullet("a", "Built a service.", ["python"])], 202)
    assert f"max={hard_max}" in rendered
    assert f"{soft_min}-{hard_max}" in rendered


def test_the_system_prompt_states_which_way_to_err():
    assert "Err short, never long." in rewrite._SYSTEM


def test_the_system_prompt_forbids_moving_metrics_across_bullet_ids():
    """Regression pin for aeth_b3/zot_b3 cross-wiring of eval metrics."""
    assert "Never move a number or metric from one bullet id to another" in rewrite._SYSTEM


def test_the_system_prompt_encourages_leadership_and_drive_verbs_without_forcing_them():
    assert "a stretched \"led\"" in rewrite._SYSTEM
    assert "do not imply managing people, owning a decision" in rewrite._SYSTEM


def test_the_system_prompt_foregrounds_accomplishment_without_inventing_one():
    assert "Foreground the accomplishment." in rewrite._SYSTEM
    assert "never manufacture a result, number, or comparison" in rewrite._SYSTEM


# --- the repair pass ------------------------------------------------------------------


def _reqs():
    return requirements(("python", "must_have"))


def test_a_clean_draft_costs_exactly_one_call(rewrite_calls):
    """The cost guarantee: no widow, no follow-up."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    calls = rewrite_calls(_reply(a=_text(150)))

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert len(calls) == 1
    assert outcome.widows_repaired == 0
    assert outcome.widows_remaining == 0


def test_a_widow_triggers_exactly_one_follow_up_carrying_only_the_offender(rewrite_calls):
    src = [
        bullet("a", "Built a Python service.", ["python"]),
        bullet("b", "Shipped a Python tool.", ["python"]),
    ]
    calls = rewrite_calls(
        _reply(a=_text(204), b=_text(150)),  # only "a" widows
        _reply(a=_text(190)),
    )

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert len(calls) == 2
    follow_up = calls[1]["messages"][0]["content"]
    assert "'a'" in follow_up
    assert "'b'" not in follow_up, "a bullet that fits must not be re-sent"
    assert outcome.widows_repaired == 1
    assert outcome.widows_remaining == 0
    assert outcome.texts["a"] == _text(190)
    assert outcome.texts["b"] == _text(150)


def test_a_repair_that_is_still_widowed_is_discarded(rewrite_calls):
    """Non-regressive: the pass may improve a run, never worsen one."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    calls = rewrite_calls(_reply(a=_text(204)), _reply(a=_text(103)))  # still 2 lines, 2 chars

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert len(calls) == 2
    assert outcome.texts["a"] == _text(204), "original kept"
    assert outcome.widows_repaired == 0
    assert outcome.widows_remaining == 1


def test_a_repair_that_grew_is_discarded(rewrite_calls):
    src = [bullet("a", "Built a Python service.", ["python"])]
    rewrite_calls(_reply(a=_text(204)), _reply(a=_text(280)))

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert outcome.texts["a"] == _text(204)
    assert outcome.widows_repaired == 0


def test_a_repair_the_model_ignored_leaves_the_original(rewrite_calls):
    """A reply naming no known bullet must not lose the first draft."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    rewrite_calls(_reply(a=_text(204)), _reply(ghost=_text(150)))

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert outcome.texts["a"] == _text(204)
    assert outcome.widows_repaired == 0


def test_the_repair_pass_cannot_smuggle_in_a_fabrication(rewrite_calls):
    """Shortening under pressure is exactly when a model invents. The guard still binds."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    rewrite_calls(
        _reply(a="Built a Python service. " + _text(180)),
        _reply(a="Built a Kubernetes service in Python."),
    )

    with pytest.raises(rewrite.FabricationError, match="Kubernetes"):
        rewrite.rewrite_bullets(src, _reqs(), char_budget=202)


# --------------------------------------------------------------------------------------
# Fabrication retry (one pass, failing ids only)
# --------------------------------------------------------------------------------------


def test_fabrication_retry_accepts_a_clean_second_try(rewrite_calls):
    """A first-draft invention earns one retry; a clean reply replaces the draft."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    clean = "Built a Python service for internal tooling."
    calls = rewrite_calls(
        _reply(a="Built a Kubernetes service in Python."),
        _reply(a=clean),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    assert len(calls) == 2
    assert outcome.texts["a"] == clean


def test_fabrication_retry_is_scoped_to_offending_ids(rewrite_calls):
    """Clean bullets must not be re-sent; the retry prompt names the rejected terms."""
    src = [
        bullet("a", "Built a Python service.", ["python"]),
        bullet("b", "Shipped a Python tool.", ["python"]),
    ]
    calls = rewrite_calls(
        _reply(
            a="Built a Python service.",
            b="Built a Kubernetes tool in Python.",
        ),
        _reply(b="Shipped a Python tool for teams."),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    assert len(calls) == 2
    follow_up = calls[1]["messages"][0]["content"]
    assert "'b'" in follow_up
    assert "'a'" not in follow_up, "a clean bullet must not be re-sent"
    assert "Kubernetes" in follow_up
    assert outcome.texts["a"] == "Built a Python service."
    assert outcome.texts["b"] == "Shipped a Python tool for teams."


def test_fabrication_retry_still_fabricating_is_fatal(rewrite_calls):
    """One retry only — a second invention remains a hard failure."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    rewrite_calls(
        _reply(a="Built a Kubernetes service in Python."),
        _reply(a="Built a PyTorch service in Python."),
    )

    with pytest.raises(rewrite.FabricationError, match="PyTorch"):
        rewrite.rewrite_bullets(
            src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
        )


def test_fabrication_retry_missing_id_is_fatal(rewrite_calls):
    """Omitting the offender on retry must not silently pass the first draft."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    rewrite_calls(
        _reply(a="Built a Kubernetes service in Python."),
        _reply(ghost="Built a Python service."),
    )

    with pytest.raises(rewrite.FabricationError, match="Kubernetes"):
        rewrite.rewrite_bullets(
            src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
        )


def test_no_widow_repair_holds_the_run_to_one_call(rewrite_calls):
    """The control half of the A/B: isolates what the prompt band achieves alone."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    calls = rewrite_calls(_reply(a=_text(204)))

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    assert len(calls) == 1
    assert outcome.texts["a"] == _text(204)
    assert outcome.widows_remaining == 1


# --------------------------------------------------------------------------------------
# Opening-verb variety
# --------------------------------------------------------------------------------------


def test_opening_verb_ignores_non_word_openers():
    """Hyphenated or empty openers are not verbs and must not participate in collisions."""
    assert rewrite.opening_verb("Designed a pipeline.") == "designed"
    assert rewrite.opening_verb("Full-stack app") is None
    assert rewrite.opening_verb("") is None


def test_verb_collisions_flags_exact_duplicate_openers():
    """A second bullet opening with the same word is always an offender."""
    texts = {
        "a": "Designed a Python service.",
        "b": "Designed a retrieval pipeline.",
        "c": "Led a mentoring cohort.",
    }
    collisions = rewrite.verb_collisions(texts)
    assert set(collisions) == {"b"}
    assert "designed" in collisions["b"]


def test_verb_collisions_flags_family_over_concentration():
    """More than MAX_SAME_FAMILY_OPENERS near-synonyms must flag the extras."""
    texts = {
        "a": "Designed a Python service.",
        "b": "Engineered a retrieval pipeline.",
        "c": "Architected a SQL router.",
        "d": "Led a mentoring cohort.",
    }
    collisions = rewrite.verb_collisions(texts)
    # First two build-family openers keep their claim; the third is the offender.
    assert set(collisions) == {"c"}
    assert "designed" in collisions["c"]
    assert "engineered" in collisions["c"]


def test_verb_collisions_ignores_unknown_openers_for_family_rules():
    """An unlisted opener never participates in family over-concentration."""
    texts = {
        "a": "Photographed campus events.",
        "b": "Photographed lab demos.",
        "c": "Designed a Python service.",
        "d": "Engineered a retrieval pipeline.",
    }
    collisions = rewrite.verb_collisions(texts)
    # Exact duplicate of Photographed is still flagged; family rule does not invent one.
    assert set(collisions) == {"b"}
    assert "photographed" in collisions["b"]


def test_polish_swaps_a_colliding_opener(rewrite_calls):
    """One follow-up call replaces a repeated opener without rewriting the rest."""
    src = [
        bullet("a", "Designed a Python service for search.", ["python"]),
        bullet("b", "Designed a Python retrieval pipeline.", ["python"]),
    ]
    # First call: echo source (exact collision). Second: swap b's opener only.
    calls = rewrite_calls(
        _reply(
            a="Designed a Python service for search.",
            b="Designed a Python retrieval pipeline.",
        ),
        _reply(b="Built a Python retrieval pipeline."),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=True
    )

    assert len(calls) == 2
    assert "bullets_to_revoice" in calls[1]["messages"][0]["content"]
    assert outcome.texts["b"].startswith("Built ")
    assert outcome.verbs_diversified == 1
    assert outcome.verb_collisions_remaining == 0


def test_polish_discards_a_swap_that_still_collides(rewrite_calls):
    """Non-regressive: a reply that keeps a forbidden opener leaves the original."""
    src = [
        bullet("a", "Designed a Python service for search.", ["python"]),
        bullet("b", "Designed a Python retrieval pipeline.", ["python"]),
    ]
    rewrite_calls(
        _reply(
            a="Designed a Python service for search.",
            b="Designed a Python retrieval pipeline.",
        ),
        _reply(b="Designed a Python retrieval pipeline."),  # no change
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=True
    )

    assert outcome.texts["b"].startswith("Designed ")
    assert outcome.verbs_diversified == 0
    assert outcome.verb_collisions_remaining == 1


def test_polish_discards_a_fabricating_verb_swap(rewrite_calls):
    """A cosmetic pass must not kill the run; fabrication on a swap is discarded."""
    src = [
        bullet("a", "Designed a Python service for search.", ["python"]),
        bullet("b", "Designed a Python retrieval pipeline.", ["python"]),
    ]
    rewrite_calls(
        _reply(
            a="Designed a Python service for search.",
            b="Designed a Python retrieval pipeline.",
        ),
        _reply(b="Built a Kubernetes retrieval pipeline."),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=True
    )

    assert outcome.texts["b"].startswith("Designed ")
    assert outcome.verbs_diversified == 0


def test_no_verb_repair_holds_the_run_to_one_call(rewrite_calls):
    """The control half of the A/B for verb variety."""
    src = [
        bullet("a", "Designed a Python service for search.", ["python"]),
        bullet("b", "Designed a Python retrieval pipeline.", ["python"]),
    ]
    calls = rewrite_calls(
        _reply(
            a="Designed a Python service for search.",
            b="Designed a Python retrieval pipeline.",
        )
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    assert len(calls) == 1
    assert outcome.verb_collisions_remaining == 1


def test_widow_and_verb_defects_share_one_polish_call(rewrite_calls):
    """Both defect kinds ride in a single follow-up, preserving the five-call cap."""
    # a is widowed (204 chars starting with Designed); b collides on Designed but fits.
    widowed_text = "Designed " + ("x" * (204 - len("Designed ")))
    src = [
        bullet("a", "Designed a Python service.", ["python"]),
        bullet("b", "Designed a short Python tool.", ["python"]),
    ]
    shortened = "Designed " + ("x" * (190 - len("Designed ")))
    calls = rewrite_calls(
        _reply(a=widowed_text, b="Designed a short Python tool."),
        _reply(a=shortened, b="Built a short Python tool."),
    )

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert len(calls) == 2
    follow_up = calls[1]["messages"][0]["content"]
    assert "bullets_to_shorten" in follow_up
    # a was widowed so it is sent only as a widow; b is the verb-only offender.
    assert "bullets_to_revoice" in follow_up
    assert "'b'" in follow_up
    assert outcome.widows_repaired == 1
    assert outcome.verbs_diversified == 1
    assert outcome.verb_collisions_remaining == 0
