"""Tests for the pure, deterministic half of the pipeline.

The LLM calls are not tested here — they cost money and are non-deterministic. What is
tested is everything that guards them: scoring, selection, and the fabrication check that
decides whether a rewrite is allowed to ship.
"""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.content.data import Bullet, Contact, Experience, MasterResume, Project
from resume_tailor.pipeline import (
    bullet_checks,
    bullet_merge,
    fabrication,
    followups,
    relevance,
    rewrite,
    rewrite_prompts,
    selection,
)
from resume_tailor.pipeline.bullet_checks import (
    delegated_authorship,
    guard_offenders,
    rebound_numbers,
)
from resume_tailor.pipeline.fabrication import check_fabrication
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from resume_tailor.pipeline.relevance import BulletScore, ScoreTable
from resume_tailor.pipeline.selection import (
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


def _rich_resume() -> MasterResume:
    """A resume with enough entries and bullets per entry to exercise entry-ranking and
    budget-allocation meaningfully: 4 experience entries and 3 projects (so a `limit=3`/
    `limit=2` selection is a genuine subset, not "everything there is"), each carrying 2
    python-tagged bullets (so budgets up to `len(entries) + 2` and flat-pool limits up to
    10 have enough real supply to draw from, not just enough to pad the count).
    """
    return MasterResume(
        contact=Contact(name="X", email="x@y.z"),
        experience=[
            Experience(
                company=name, title="Engineer", start="2020-01", end="2020-06",
                bullets=[
                    bullet(f"{name.lower()}_b1", f"Did {name} thing one.", ["python"]),
                    bullet(f"{name.lower()}_b2", f"Did {name} thing two.", ["python"]),
                ],
            )
            for name in ("Alpha", "Beta", "Gamma", "Delta")
        ],
        projects=[
            Project(
                id=name.lower().replace(" ", "-"), name=name,
                bullets=[
                    bullet(f"{name.lower().replace(' ', '_')}_b1", f"Built {name} one.", ["python"]),
                    bullet(f"{name.lower().replace(' ', '_')}_b2", f"Built {name} two.", ["python"]),
                ],
            )
            for name in ("Proj One", "Proj Two", "Proj Three")
        ],
    )


def test_select_entries_ranks_sections_independently():
    """The point of separate ranking: strong projects must not evict a relevant job."""
    reqs = requirements(("python", "must_have"))
    resume = _rich_resume()

    jobs = select_entries(resume.experience, reqs, limit=3)
    projects = select_entries(resume.projects, reqs, limit=2)

    assert len(jobs) == 3
    assert len(projects) == 2
    # Nothing from one section can appear in the other's results.
    assert {j.company for j in jobs}.isdisjoint({p.name for p in projects})


def test_select_entries_preserves_document_order():
    reqs = requirements(("python", "must_have"))
    resume = _rich_resume()

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
    resume = _rich_resume()
    entries = select_entries(resume.experience, reqs, limit=3)

    # A limit below the entry count must still leave every entry represented.
    picked = select_within_entries(entries, reqs, limit=1)
    covered = {e.company for e in entries for b in e.bullets if b in picked}
    assert covered == {e.company for e in entries}


def test_extra_budget_goes_to_the_strongest_bullets():
    reqs = requirements(("python", "must_have"))
    resume = _rich_resume()
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
    resume = _rich_resume()
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

    result = relevance.score_table(bullets, requirements(("python", "must_have")))

    assert result == {"a": 10.0, "b": 0.0}


def test_score_table_is_empty_without_bullets():
    assert relevance.score_table([], requirements(("python", "must_have"))) == {}


def test_score_cache_key_covers_bullet_text():
    """Editing a bullet must not silently reuse the score computed for its old wording."""
    reqs = requirements(("python", "must_have"))
    before = relevance._score_cache_path([bullet("a", "Original text.", ["python"])], reqs)
    after = relevance._score_cache_path([bullet("a", "Edited text.", ["python"])], reqs)
    assert before != after


def test_score_cache_key_covers_the_posting():
    b = [bullet("a", "x", ["python"])]
    one = relevance._score_cache_path(b, requirements(("python", "must_have")))
    two = relevance._score_cache_path(b, requirements(("sql", "must_have")))
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


def test_magnitude_suffix_does_not_license_bare_digits():
    """A source `50k` must not license a bare `50` — magnitude folding stays whole-token."""
    src = bullet("a", "Supported 50k monthly users.", ["support"], metric=True)
    assert "50" in check_fabrication(src, "Supported 50 monthly users.")


def test_rebound_numbers_flags_reattached_metric():
    """'40 engineers' in the source must not license '40 hours' in the rewrite."""
    src = bullet(
        "a",
        "Spent 8 years supporting 40 engineers on the platform.",
        ["support"],
        metric=True,
    )
    assert rebound_numbers([src], "Spent 8 years logging 40 hours on the platform.") == [
        "40 hours"
    ]
    assert any(
        o.startswith("rebound:")
        for o in guard_offenders(
            [src], "Spent 8 years logging 40 hours on the platform."
        )
    )


def test_rebound_numbers_passes_faithful_restatement():
    """Extra modifiers around the same number-noun binding are fine."""
    src = bullet(
        "a",
        "Spent 8 years supporting 40 engineers on the platform.",
        ["support"],
        metric=True,
    )
    assert (
        rebound_numbers(
            [src], "Spent 8 years supporting 40 remote engineers across the platform."
        )
        == []
    )


def test_rebound_numbers_accepts_an_aliased_noun(monkeypatch):
    """A vocabulary-pack alias makes two spellings of one subject the same binding."""
    src = bullet("a", "Tutored 130 students.", ["teaching"], metric=True)
    assert rebound_numbers([src], "Tutored 130 undergraduates.") == ["130 undergraduates"]

    monkeypatch.setitem(config.TAG_ALIASES, "undergraduate", "student")
    assert rebound_numbers([src], "Tutored 130 undergraduates.") == []


def test_rebound_numbers_reports_one_claim_per_number():
    """A rebinding names the nearest noun only — not every adjective in the window."""
    src = bullet("a", "Tutored 130 students.", ["teaching"], metric=True)
    assert rebound_numbers([src], "Logged 130 hours clarifying Python semantics.") == [
        "130 hours"
    ]


def test_rebound_numbers_silent_when_source_never_binds_noun():
    """If the source mentions a number with no noun neighbour, the guard cannot judge."""
    src = bullet("a", "Improved latency by 40.", ["latency"], metric=True)
    assert rebound_numbers([src], "Improved latency by 40 hours.") == []


def test_delegated_authorship_flags_escalation():
    """Coordinating a vendor must not become 'built the ingestion layer'."""
    src = bullet(
        "a",
        "Coordinated a vendor to deliver the ingestion layer for the billing pipeline.",
        ["ingestion"],
    )
    rewrite = "Built the ingestion layer for the billing pipeline."
    claims = delegated_authorship([src], rewrite)
    assert claims and "built" in claims[0]
    assert any(o.startswith("authorship:") for o in guard_offenders([src], rewrite))


def test_delegated_authorship_silent_without_delegation_verb():
    src = bullet("a", "Reviewed a vendor proposal for the ingestion layer.", ["ingestion"])
    assert (
        delegated_authorship([src], "Built the ingestion layer for billing.") == []
    )


def test_delegated_authorship_silent_without_external_party():
    """'Led a team that built X' — an internal team is not an external party."""
    src = bullet(
        "a",
        "Led a team that delivered the ingestion layer for billing.",
        ["ingestion"],
    )
    assert (
        delegated_authorship([src], "Built the ingestion layer for billing.") == []
    )


def test_delegated_authorship_silent_when_source_also_claims_direct():
    """Whole-bullet: 'managed a vendor and wrote the loader' already asserts authorship."""
    src = bullet(
        "a",
        "Managed a vendor and wrote the loader for the billing pipeline.",
        ["ingestion"],
    )
    assert (
        delegated_authorship([src], "Built the loader for the billing pipeline.") == []
    )


def test_delegated_authorship_silent_when_rewrite_keeps_external_party():
    src = bullet(
        "a",
        "Coordinated a vendor to deliver the ingestion layer.",
        ["ingestion"],
    )
    assert (
        delegated_authorship(
            [src], "Built the ingestion layer with the vendor for billing."
        )
        == []
    )


def test_delegated_authorship_silent_without_shared_tokens():
    src = bullet(
        "a",
        "Coordinated a vendor to deliver the ingestion layer.",
        ["ingestion"],
    )
    # Rewrite invents unrelated work — fabrication guard catches new terms; authorship
    # stays silent because shared significant tokens < 2.
    assert delegated_authorship([src], "Built a mobile app for consumers.") == []


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


def test_lower_bound_plus_requires_exact_number_and_lower_bound_source():
    src = bullet(
        "a",
        "Fine-tuned models on at least 9,000 data points from Spider.",
        ["fine-tuning", "llm"],
    )
    assert check_fabrication(src, "Fine-tuned on 9,000 Spider points.") == []
    assert check_fabrication(src, "Fine-tuned on 9,000+ Spider points.") == []
    assert check_fabrication(src, "Fine-tuned on 2,000+ Spider points.") == ["2,000+"]
    assert check_fabrication(bullet("b", "Reviewed 1,000 conversations.", ["review"]),
                             "Reviewed 1,000+ conversations.") == ["1,000+"]
    assert check_fabrication(bullet("c", "Reviewed under 1,000 conversations.", ["review"]),
                             "Reviewed 1,000+ conversations.") == ["1,000+"]


def test_logged_lower_bound_rewrites_pass_guard_and_preserve_number():
    cases = [
        ("Reviewed over 1,000 daily conversations.", "Reviewed 1,000+ daily conversations."),
        ("Supported over 130 students/week.", "Supported 130+ students/week."),
        ("Trained over 30 staff on IT practices.", "Trained 30+ staff on IT practices."),
    ]
    for source, rewritten in cases:
        src = bullet("a", source, ["support"], metric=True)
        assert guard_offenders([src], rewritten) == []
        assert fabrication.numbers_dropped([src], rewritten) == []


def test_lower_bound_equivalence_preserves_rebound_detection():
    src = bullet("a", "Trained over 30 staff.", ["support"], metric=True)
    assert rebound_numbers([src], "Saved 30+ hours.") == ["30 hours"]
    plus = bullet("b", "Trained 30+ staff.", ["support"], metric=True)
    assert guard_offenders([plus], "Trained over 30 staff.") == []
    assert fabrication.numbers_dropped([plus], "Trained more than 30 staff.") == []
    assert check_fabrication(plus, "Trained 30 staff.") == ["30"]
    bare = bullet("c", "Trained 30 staff.", ["support"], metric=True)
    assert check_fabrication(bare, "Trained over 30 staff.") == ["30"]


@pytest.mark.parametrize("bound", ["over 1,000", "more than 1,000", "at least 1,000",
                                   "1,000 or more", "1,000+"])
def test_all_source_lower_bound_forms_license_the_same_plus_token(bound):
    src = bullet("a", f"Reviewed {bound} conversations.", ["review"], metric=True)
    assert guard_offenders([src], "Reviewed 1,000+ conversations.") == []


def test_numeric_plus_equivalence_does_not_strip_a_technology_suffix():
    src = bullet("a", "Used GPT-4+.", ["language models"])
    assert "GPT-4" in check_fabrication(src, "Used GPT-4.")


def test_percentage_outcome_is_bound_before_the_number():
    src = bullet(
        "a", "Cut student troubleshooting time by 50-66% by providing step-by-step "
        "debugging guides and example solutions for common programming errors.",
        ["support"], metric=True,
    )
    candidate = "Cut student troubleshooting time by 50-66% by authoring debugging guides."
    assert guard_offenders([src], candidate) == []
    assert rebound_numbers([src], "Cut office costs by 50-66% by authoring guides.")


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


def _reply(**by_id) -> rewrite_prompts.RewriteResult:
    return rewrite_prompts.RewriteResult(
        bullets=[rewrite_prompts.RewrittenBullet(id=k, text=v) for k, v in by_id.items()]
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
    assert bullet_checks.widowed({"a": _text(2 * CPL)}) == {}


def test_two_characters_over_a_line_boundary_is_a_widow():
    """The measured failure: 204 characters against a 202 budget costs a whole line."""
    over = _text(2 * CPL + 2)
    assert config.line_span(over) == 3
    assert config.last_line_fill(over) == 2
    assert "a" in bullet_checks.widowed({"a": over})


def test_a_single_line_bullet_is_never_a_widow():
    """There is no earlier line to fall back onto; a short bullet is just short."""
    assert bullet_checks.widowed({"a": _text(5)}) == {}
    assert bullet_checks.widowed({"a": _text(CPL)}) == {}


def test_a_comfortably_filled_last_line_is_not_a_widow():
    assert bullet_checks.widowed({"a": _text(198)}) == {}


def test_the_ceiling_is_a_full_line_below_where_the_text_ends():
    """An explicit 'cut seven characters', not a vague 'shorten by 15%'."""
    assert bullet_checks.widowed({"a": _text(204)}) == {"a": 2 * CPL - config.WIDOW_SAFETY}


# --- the prompt -----------------------------------------------------------------------


def test_the_prompt_advertises_a_band_below_the_budget():
    """A ceiling alone is what let the model optimise right up to the cliff edge."""
    soft_min, hard_max = rewrite_prompts._length_band(202)
    assert hard_max < 202, "max must sit below the budget, not on it"
    assert soft_min < hard_max

    rendered = rewrite_prompts._format_bullets([bullet("a", "Built a service.", ["python"])], 202)
    assert f"max={hard_max}" in rendered
    assert f"{soft_min}-{hard_max}" in rendered


def test_the_system_prompt_states_which_way_to_err():
    assert "Err short, never long." in rewrite_prompts._system()


def test_the_system_prompt_forbids_moving_metrics_across_bullet_ids():
    """Regression pin for aeth_b3/zot_b3 cross-wiring of eval metrics."""
    assert "Never move a number or metric from one bullet id to another" in rewrite_prompts._system()


def test_the_system_prompt_encourages_leadership_and_drive_verbs_without_forcing_them():
    assert "a stretched \"led\"" in rewrite_prompts._system()
    assert "do not imply managing people, owning a decision" in rewrite_prompts._system()


def test_the_system_prompt_foregrounds_accomplishment_without_inventing_one():
    assert "Foreground the accomplishment." in rewrite_prompts._system()
    assert "never manufacture a result, number, or comparison" in rewrite_prompts._system()


def test_default_rewrite_system_prompt_is_byte_identical_to_the_legacy_string():
    """Splitting core/style must not change output when no override is active."""
    from resume_tailor.content import style as style_mod

    style_mod.activate(rewrite=None, expand=None)
    assert rewrite_prompts._system() == rewrite_prompts._SYSTEM


def test_a_custom_rewrite_style_reaches_the_llm_system_prompt(rewrite_calls):
    """User overrides replace the editable block but keep locked core rules."""
    from resume_tailor.content import style as style_mod

    style_mod.activate(rewrite="- Write every bullet in ALL CAPS for emphasis.", expand=None)
    calls = rewrite_calls(_reply(a="Built a Python service."))
    rewrite.rewrite_bullets(
        [bullet("a", "Built a Python service.", ["python"])],
        _reqs(),
        char_budget=202,
    )
    system = calls[0]["system"]
    assert "Write every bullet in ALL CAPS for emphasis." in system
    assert "NEVER introduce a skill, tool, technology, metric" in system
    assert "Never move a number or metric from one bullet id to another" in system


def test_a_custom_rewrite_style_cannot_drop_locked_core_rules(rewrite_calls):
    """Fabrication guard rules stay in the system prompt even when the style omits them."""
    from resume_tailor.content import style as style_mod

    style_mod.activate(rewrite="- Be concise.", expand=None)
    system = rewrite_prompts._system()
    assert "NEVER introduce a skill, tool, technology, metric" in system
    assert "Never bend a bullet toward a keyword to work it in" in system


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


def test_rewrite_defers_widow_repair_until_layout_is_measured(rewrite_calls):
    src = [
        bullet("a", "Built a Python service.", ["python"]),
        bullet("b", "Shipped a Python tool.", ["python"]),
    ]
    calls = rewrite_calls(
        _reply(a=_text(204), b=_text(150)),  # only "a" widows
        _reply(a=_text(190)),
    )

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert len(calls) == 1
    assert outcome.widows_repaired == 0
    assert outcome.widows_remaining == 1
    assert outcome.texts["a"] == _text(204)
    assert outcome.texts["b"] == _text(150)


def test_a_repair_that_is_still_widowed_is_discarded(rewrite_calls):
    """Non-regressive: the pass may improve a run, never worsen one."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    calls = rewrite_calls(_reply(a=_text(204)), _reply(a=_text(103)))  # still 2 lines, 2 chars

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert len(calls) == 1
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


def test_a_fabricating_widow_repair_is_discarded_not_fatal(rewrite_calls):
    """Shortening under pressure is when a model invents; the guard discards, not aborts."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    widowed_draft = "Built a Python service. " + _text(180)
    rewrite_calls(
        _reply(a=widowed_draft),
        _reply(a="Built a Kubernetes service in Python."),
    )

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert outcome.texts["a"] == widowed_draft
    assert outcome.widows_repaired == 0
    assert outcome.widows_remaining == 1
    assert outcome.widow_repairs_rejected == {}


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


def test_fabrication_retry_still_fabricating_falls_back_to_source(rewrite_calls):
    """One retry only — a second invention keeps the original text and warns instead."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    rewrite_calls(
        _reply(a="Built a Kubernetes service in Python."),
        _reply(a="Built a PyTorch service in Python."),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    assert outcome.texts["a"] == "Built a Python service."
    assert "a" in outcome.fabrications_rejected
    assert any("PyTorch" in t for t in outcome.fabrications_rejected["a"])


def test_fabrication_retry_missing_id_falls_back_to_source(rewrite_calls):
    """Omitting the offender on retry must not silently pass the first draft."""
    src = [bullet("a", "Built a Python service.", ["python"])]
    rewrite_calls(
        _reply(a="Built a Kubernetes service in Python."),
        _reply(ghost="Built a Python service."),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    assert outcome.texts["a"] == "Built a Python service."
    assert "a" in outcome.fabrications_rejected
    assert any("Kubernetes" in t for t in outcome.fabrications_rejected["a"])


def test_rebound_falls_back_to_source_after_one_retry(rewrite_calls):
    """A number rebinding is a fabrication: one retry, then fall back and warn."""
    src = [
        bullet(
            "a",
            "Spent 8 years supporting 40 engineers on the platform.",
            ["support"],
            metric=True,
        )
    ]
    rewrite_calls(
        _reply(a="Spent 8 years logging 40 hours on the platform."),
        _reply(a="Spent 8 years logging 40 hours on support work."),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    assert outcome.texts["a"] == "Spent 8 years supporting 40 engineers on the platform."
    assert "a" in outcome.fabrications_rejected
    assert any("rebound" in t for t in outcome.fabrications_rejected["a"])


def test_rebound_retry_prompt_names_rebound_claims(rewrite_calls):
    """The retry prompt must distinguish a rebound from a fabricated term."""
    src = [
        bullet(
            "a",
            "Spent 8 years supporting 40 engineers on the platform.",
            ["support"],
            metric=True,
        )
    ]
    calls = rewrite_calls(
        _reply(a="Spent 8 years logging 40 hours on the platform."),
        _reply(a="Spent 8 years supporting 40 engineers on the platform."),
    )

    outcome = rewrite.rewrite_bullets(
        src, _reqs(), char_budget=202, repair_widows=False, repair_verbs=False
    )

    follow_up = calls[1]["messages"][0]["content"]
    assert "rebound_claims=" in follow_up
    assert "40 hours" in follow_up
    assert outcome.texts["a"] == "Spent 8 years supporting 40 engineers on the platform."


def test_rebounding_widow_repair_is_discarded_not_fatal(rewrite_calls):
    """A polish pass that rebinds a number is discarded as a warning, not raised."""
    src = [
        bullet(
            "a",
            "Spent 8 years supporting 40 engineers.",
            ["support"],
            metric=True,
        )
    ]
    # Same widowing pattern as test_a_fabricating_widow_repair_is_discarded_not_fatal.
    widowed_draft = "Spent 8 years supporting 40 engineers. " + _text(180)
    rewrite_calls(
        _reply(a=widowed_draft),
        _reply(a="Spent 8 years logging 40 hours."),
    )

    outcome = rewrite.rewrite_bullets(src, _reqs(), char_budget=202)

    assert outcome.texts["a"] == widowed_draft
    assert outcome.widows_repaired == 0
    assert outcome.widow_repairs_rejected == {}


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
    assert bullet_checks.opening_verb("Designed a pipeline.") == "designed"
    assert bullet_checks.opening_verb("Full-stack app") is None
    assert bullet_checks.opening_verb("") is None


def test_verb_collisions_flags_exact_duplicate_openers():
    """A second bullet opening with the same word is always an offender."""
    texts = {
        "a": "Designed a Python service.",
        "b": "Designed a retrieval pipeline.",
        "c": "Led a mentoring cohort.",
    }
    collisions = bullet_checks.verb_collisions(texts)
    assert set(collisions) == {"b"}
    assert "designed" in collisions["b"]


def test_verb_collisions_flags_weak_openers_without_a_neighbour():
    """A vague opener is an offender on its own and never claims its word."""
    texts = {
        "a": "Assisted the deal team with a pitch book.",
        "b": "Modeled a three-statement forecast.",
        "c": "Helped reconcile 40 vendor accounts.",
    }
    collisions = bullet_checks.verb_collisions(texts)
    assert set(collisions) == {"a", "c"}
    assert {"assisted", "helped"} <= set(collisions["a"])
    assert "modeled" in collisions["a"]


def test_verb_collisions_leaves_strong_trade_verbs_alone():
    texts = {"a": "Performed due diligence on 12 targets.", "b": "Served 200 retail clients."}
    assert bullet_checks.verb_collisions(texts) == {}


def test_verb_collisions_flags_family_over_concentration():
    """More than MAX_SAME_FAMILY_OPENERS near-synonyms must flag the extras."""
    texts = {
        "a": "Designed a Python service.",
        "b": "Engineered a retrieval pipeline.",
        "c": "Architected a SQL router.",
        "d": "Led a mentoring cohort.",
    }
    collisions = bullet_checks.verb_collisions(texts)
    # First two build-family openers keep their claim; the third is the offender.
    assert set(collisions) == {"c"}
    assert "designed" in collisions["c"]
    assert "engineered" in collisions["c"]


def test_verb_collisions_family_cap_scales_with_page_length():
    """A 15-bullet page may carry three build-family openers; the fourth is flagged."""
    build = ["Designed", "Engineered", "Architected", "Built"]
    # Openers outside every verb family, so only the build family can concentrate.
    others = ["Photographed", "Sketched", "Painted", "Filmed", "Baked", "Gardened",
              "Sailed", "Knitted", "Juggled", "Hiked", "Surfed", "Skated"]
    texts = {f"o{i}": f"{verb} a thing." for i, verb in enumerate(others)}
    three = {**texts, **{f"b{i}": f"{v} a service." for i, v in enumerate(build[:3])}}
    four = {**three, "b3": "Built a service."}
    del four["o11"]

    assert len(three) == 15 and len(four) == 15
    assert config.family_opener_cap(15) == 3
    assert bullet_checks.verb_collisions(three) == {}
    assert set(bullet_checks.verb_collisions(four)) == {"b3"}


def test_verb_collisions_ignores_unknown_openers_for_family_rules():
    """An unlisted opener never participates in family over-concentration."""
    texts = {
        "a": "Photographed campus events.",
        "b": "Photographed lab demos.",
        "c": "Designed a Python service.",
        "d": "Engineered a retrieval pipeline.",
    }
    collisions = bullet_checks.verb_collisions(texts)
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
    assert "bullets_to_shorten" not in follow_up
    # The physical line repair runs in fit; this call only handles the verb.
    assert "bullets_to_revoice" in follow_up
    assert "'b'" in follow_up
    assert outcome.widows_repaired == 0
    assert outcome.verbs_diversified == 1
    assert outcome.verb_collisions_remaining == 0


# --- fit-loop pull-back ---------------------------------------------------------------


def test_widowed_max_fill_widens_the_net_without_changing_the_default():
    width = config.CHARS_PER_LINE
    # 38% of a last line: not a widow by default, but inside a 40% pull-back net.
    texts = {"a": "x" * (width + int(width * 0.38))}

    assert bullet_checks.widowed(texts) == {}
    assert bullet_checks.widowed(texts, max_fill=0.40) == {"a": width - config.WIDOW_SAFETY}


def test_pull_back_accepts_only_a_reply_that_saves_a_line(rewrite_calls):
    width = config.CHARS_PER_LINE
    long_text = "x" * (width + int(width * 0.38))
    src = {
        "a": bullet("a", "Built a Python service.", ["python"]),
        "b": bullet("b", "Shipped a Python tool.", ["python"]),
    }
    texts = {"a": long_text, "b": long_text}
    ceiling = width - config.WIDOW_SAFETY
    # "a" comes back under one line; "b" is shorter but still wraps, so it frees nothing.
    calls = rewrite_calls(_reply(a="y" * (ceiling - 1), b="y" * (width + 5)))

    out, pulled, rejected = bullet_merge.pull_back(
        texts, src, _reqs(), {"a": ceiling, "b": ceiling}
    )

    assert len(calls) == 1
    assert pulled == 1 and rejected == {}
    assert out["a"] == "y" * (ceiling - 1)
    assert out["b"] == long_text, "a cut that keeps the line count is discarded"


def test_pull_back_sends_only_the_requested_bullets(rewrite_calls):
    width = config.CHARS_PER_LINE
    src = {
        "a": bullet("a", "Built a Python service.", ["python"]),
        "b": bullet("b", "Shipped a Python tool.", ["python"]),
    }
    texts = {"a": "x" * (width + 10), "b": "x" * (width + 10)}
    calls = rewrite_calls(_reply(a="y" * 50))

    bullet_merge.pull_back(texts, src, _reqs(), {"a": width - config.WIDOW_SAFETY})

    sent = calls[0]["messages"][0]["content"]
    assert "'a'" in sent and "'b'" not in sent


def test_pull_back_with_no_targets_makes_no_call(rewrite_calls):
    calls = rewrite_calls()
    out, pulled, rejected = bullet_merge.pull_back({"a": "x"}, {}, _reqs(), {})
    assert calls == [] and pulled == 0 and out == {"a": "x"}


def test_measured_target_window_accepts_only_guard_clean_numeric_preserving_reply(rewrite_calls):
    src = {"a": bullet("a", "Trained over 30 staff on IT practices.", ["support"], metric=True)}
    current = {"a": "Trained over 30 staff on IT practices and common tools."}
    calls = rewrite_calls(_reply(a="Trained 30+ staff on IT practices."))
    out, fixed, _, rejected = followups._polish(
        current, src, _reqs(), repair_widows=False, repair_verbs=False,
        targets={"a": (30, 40)},
    )
    assert out["a"] == "Trained 30+ staff on IT practices."
    assert fixed == 1 and rejected == {}
    assert "<repair_prompt_version>7" in calls[0]["messages"][0]["content"]

    rewrite_calls(_reply(a="Trained 30+ staff."))
    out, fixed, _, _ = followups._polish(
        current, src, _reqs(), repair_widows=False, repair_verbs=False,
        targets={"a": (30, 40)},
    )
    assert out == current and fixed == 0


def test_measured_repair_gets_one_fabrication_retry(rewrite_calls):
    src = {"a": bullet("a", "Built a Python service.", ["python"])}
    calls = rewrite_calls(
        _reply(a="Built a Kubernetes service."),
        _reply(a="Built a Python service."),
    )
    out, fixed, _, rejected = followups._polish(
        {"a": "Built a Python service with several extra words."},
        src, _reqs(), repair_widows=False, repair_verbs=False,
        targets={"a": (20, 30)},
    )
    assert len(calls) == 2
    assert out["a"] == "Built a Python service."
    assert fixed == 1 and rejected == {}


# --------------------------------------------------------------------------------------
# Slash-compound number bindings
# --------------------------------------------------------------------------------------

_TA_SOURCE = Bullet(
    id="uci_b1",
    text=(
        "Facilitated three weekly labs in a team of three, clarifying Python and algorithm "
        "concepts for over 130 students/week to improve assignment completion and "
        "debugging skills."
    ),
    tags=["python"],
)


@pytest.mark.parametrize(
    "rewritten",
    [
        "Facilitated weekly labs for over 130 students, clarifying Python and algorithm "
        "concepts.",
        "Facilitated weekly labs for 130+ students each week, clarifying Python concepts.",
        "Led labs for over 130 students/week on Python and algorithms.",
    ],
)
def test_a_slash_compound_source_noun_licenses_its_parts(rewritten):
    assert bullet_checks.rebound_numbers([_TA_SOURCE], rewritten) == []


@pytest.mark.parametrize(
    ("rewritten", "claim"),
    [
        ("Led labs for over 130 teachers on Python.", "130 teachers"),
        ("Taught 130 courses in Python.", "130 courses"),
        # The rewrite's own compound must still match whole: the rate changed.
        ("Led labs for 130 students/semester on Python.", "130 students/semester"),
    ],
)
def test_a_slash_compound_source_still_rejects_a_rebound(rewritten, claim):
    assert bullet_checks.rebound_numbers([_TA_SOURCE], rewritten) == [claim]


# --------------------------------------------------------------------------------------
# Recency weight
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025-06", (2025, 6)),
        ("Apr 2026 - May 2026", (2026, 5)),
        ("June 2024", (2024, 6)),
        ("Aug 2025", (2025, 8)),
        ("2019 - 2023", (2023, 12)),
        ("sometime", None),
        ("", None),
    ],
)
def test_end_month_reads_the_last_date_named(text, expected):
    assert selection._end_month(text) == expected


def _job(end: str, *, bullets: list[Bullet] | None = None) -> Experience:
    return Experience(
        company=f"Co {end}", title="Engineer", start="2020-01", end=end,
        bullets=bullets or [Bullet(id=f"b{end}", text="Built things.", tags=["python"])],
    )


def test_entry_recency_decays_by_half_life_and_is_neutral_without_a_date(monkeypatch):
    monkeypatch.setattr(config, "RECENCY_WEIGHT", 0.2)
    monkeypatch.setattr(config, "RECENCY_HALF_LIFE_MONTHS", 24)
    today = (2026, 9)
    assert selection.entry_recency(_job("Present"), today=today) == pytest.approx(1.2)
    assert selection.entry_recency(_job("2026-09"), today=today) == pytest.approx(1.2)
    assert selection.entry_recency(_job("2024-09"), today=today) == pytest.approx(1.1)
    project = Project(id="p", name="P", date="", bullets=[])
    assert selection.entry_recency(project, today=today) == 1.0
    garbled = Project(id="q", name="Q", date="someday", bullets=[])
    assert selection.entry_recency(garbled, today=today) == 1.0
    ongoing = Project(id="r", name="R", date="Jul 2026 - Present", bullets=[])
    assert selection.entry_recency(ongoing, today=today) == pytest.approx(1.2)


def test_entry_recency_is_off_at_zero_weight(monkeypatch):
    monkeypatch.setattr(config, "RECENCY_WEIGHT", 0.0)
    assert selection.entry_recency(_job("Present")) == 1.0


def test_recency_breaks_a_tie_toward_the_recent_entry():
    requirements = JobRequirements(
        title="Engineer", seniority="mid",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )
    old, recent = _job("2019-06"), _job("2026-06")
    chosen = selection.select_entries([old, recent], requirements, limit=1)
    assert chosen == [recent]


def test_a_much_more_relevant_older_entry_still_wins():
    requirements = JobRequirements(
        title="Engineer", seniority="mid",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )
    relevant = [
        Bullet(id=f"old{i}", text="Built Python services.", tags=["python"]) for i in range(3)
    ]
    old = _job("2021-06", bullets=relevant)
    recent = _job(
        "2026-06", bullets=[Bullet(id="new1", text="Organised events.", tags=["events"])]
    )
    chosen = selection.select_entries([old, recent], requirements, limit=1)
    assert chosen == [old]


def _replies(*pairs) -> rewrite_prompts.RewriteResult:
    return rewrite_prompts.RewriteResult(
        bullets=[rewrite_prompts.RewrittenBullet(id=k, text=v) for k, v in pairs]
    )


def test_fit_target_keeps_the_longest_clean_version_inside_the_window(rewrite_calls):
    src = {"a": bullet("a", "Trained over 30 staff on IT practices and common tools.",
                       ["support"], metric=True)}
    current = {"a": "Trained over 30 staff on IT practices and common tools today."}
    calls = rewrite_calls(_replies(
        ("a", "Trained 30+ staff."),                       # too short
        ("a", "Trained 30+ staff on IT practices."),       # 34, in window
        ("a", "Trained over 30 staff on IT practices."),   # 38, in window, longest
    ))
    out, fixed, _, rejected = followups._polish(
        current, src, _reqs(), repair_widows=False, repair_verbs=False,
        targets={"a": (30, 40)},
    )
    assert out["a"] == "Trained over 30 staff on IT practices."
    assert fixed == 1 and rejected == {} and len(calls) == 1
    assert "THREE versions" in calls[0]["messages"][0]["content"]


def test_fit_target_accepts_a_line_saving_version_when_no_version_lands_in_the_window(
    rewrite_calls,
):
    src = {"a": bullet("a", "Trained over 30 staff on IT practices and common tools.",
                       ["support"], metric=True)}
    current = {"a": "Trained over 30 staff on IT practices."}
    rewrite_calls(_replies(("a", "Trained 30+ staff."), ("a", "x" * 90)))
    out, fixed, _, _ = followups._polish(
        current, src, _reqs(), repair_widows=False, repair_verbs=False,
        targets={"a": (45, 60)}, line_ceilings={"a": 20},
    )
    assert out["a"] == "Trained 30+ staff." and fixed == 1
