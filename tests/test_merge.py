"""Tests for the bullet merging feature.

The merge feature is composed of two deterministic parts:
1. `merge.propose` (pure proposal heuristics, no network)
2. `rewrite._merge_bullets` acceptance logic (guard + number preservation + widows)

The actual LLM rewrite itself is stubbed with fake clients, matching the existing
no-network rewrite tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from resume_tailor import config, merge, render, rewrite
from resume_tailor.data import Bullet, Contact, Experience, MasterResume
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor import fit as fit_mod, report


def bullet(bid: str, text: str, tags: list[str], metric: bool = False) -> Bullet:
    """Build a Bullet for tests with a stable id."""
    return Bullet(id=bid, text=text, tags=tags, metric=metric)


def requirements(*keywords: tuple[str, str]) -> JobRequirements:
    """Build JobRequirements from (canonical, importance) pairs."""
    return JobRequirements(
        title="Test Role",
        seniority="entry",
        keywords=[
            Keyword(phrase=kw[0], canonical=kw[0], importance=kw[1])  # type: ignore[arg-type]
            for kw in keywords
        ],
    )


def _text(n: int) -> str:
    """A string of exactly `n` characters."""
    return "x" * n


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, replies, calls):
        self._replies = replies
        self._calls = calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        if not self._replies:
            raise AssertionError("model called more times than the test supplied replies")
        return _FakeResponse(self._replies.pop(0))


class _FakeClient:
    def __init__(self, replies, calls):
        self.messages = _FakeMessages(replies, calls)


def _reply(**by_id) -> rewrite.RewriteResult:
    """Build a RewriteResult reply with one output per provided id."""
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
            rewrite.llm, "client_for", lambda purpose: _FakeClient(queue, calls)
        )
        monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
        return calls

    return install


def test_propose_respects_same_entry_constraint():
    b1 = bullet("a1", "Built python service.", ["python"])
    b2 = bullet("a2", "Shipped python API.", ["python"])
    c1 = bullet("b1", "Built react UI.", ["react"])
    c2 = bullet("b2", "Shipped react component.", ["react"])

    e1 = Experience(company="E1", title="t", start="2020-01", end="2020-02", bullets=[b1, b2])
    e2 = Experience(company="E2", title="t", start="2020-01", end="2020-02", bullets=[c1, c2])

    selected = [b1, b2, c1, c2]
    reqs = requirements(("python", "must_have"), ("react", "must_have"))

    groups = merge.propose(
        [e1, e2],
        selected,
        reqs,
        semantic={b1.id: 1.0, b2.id: 1.0, c1.id: 1.0, c2.id: 1.0},
        char_budget=2 * config.CHARS_PER_LINE,
        shorten_pct=0,
        attempt=0,
    )

    assert len(groups) <= config.MAX_MERGES_PER_RUN
    entry_by_id = {b1.id: "e1", b2.id: "e1", c1.id: "e2", c2.id: "e2"}
    for g in groups:
        assert entry_by_id[g.member_ids[0]] == entry_by_id[g.member_ids[1]]


def test_propose_chooses_earliest_member_as_survivor():
    b1 = bullet("a1", "Built python service.", ["python"])
    b2 = bullet("a2", "Shipped python API.", ["python"])
    b3 = bullet("a3", "Improved python tooling.", ["python"])
    e = Experience(company="E1", title="t", start="2020-01", end="2020-02", bullets=[b1, b2, b3])

    reqs = requirements(("python", "must_have"))
    selected = [b1, b2, b3]
    groups = merge.propose(
        [e],
        selected,
        reqs,
        semantic={b.id: 1.0 for b in selected},
        char_budget=2 * config.CHARS_PER_LINE,
        shorten_pct=0,
        attempt=1,  # allows 3-member groups
    )

    # If a 3-member group is proposed, the survivor must be the earliest bullet id.
    assert all(g.survivor_id == "a1" for g in groups)


def test_propose_rejects_when_source_is_too_long_for_hard_max():
    CPL = config.CHARS_PER_LINE
    hard_max = max(40, 2 * CPL - config.WIDOW_SAFETY)
    # 1.8 * hard_max is the max proposal sum; make the sum exceed it.
    too_long = int(config.MERGE_SOURCE_RATIO * hard_max) + 10
    b1 = bullet("a1", _text(too_long // 2), ["python"])
    b2 = bullet("a2", _text(too_long - len(b1.text)), ["python"])
    e = Experience(company="E1", title="t", start="2020-01", end="2020-02", bullets=[b1, b2])

    groups = merge.propose(
        [e],
        [b1, b2],
        requirements(("python", "must_have")),
        semantic={b1.id: 1.0, b2.id: 1.0},
        char_budget=2 * CPL,
        shorten_pct=0,
        attempt=0,
    )

    assert groups == []


def test_propose_allows_3_member_groups_only_after_first_overflow_rung():
    b1 = bullet("a1", "x" * 40, ["python"])
    b2 = bullet("a2", "x" * 40, ["python"])
    b3 = bullet("a3", "x" * 40, ["python"])
    e = Experience(company="E1", title="t", start="2020-01", end="2020-02", bullets=[b1, b2, b3])

    reqs = requirements(("python", "must_have"))
    semantic = {b1.id: 1.0, b2.id: 1.0, b3.id: 1.0}

    groups0 = merge.propose(
        [e],
        [b1, b2, b3],
        reqs,
        semantic=semantic,
        char_budget=2 * config.CHARS_PER_LINE,
        shorten_pct=0,
        attempt=0,
    )
    assert all(len(g.member_ids) == 2 for g in groups0)

    groups1 = merge.propose(
        [e],
        [b1, b2, b3],
        reqs,
        semantic=semantic,
        char_budget=2 * config.CHARS_PER_LINE,
        shorten_pct=0,
        attempt=1,
    )
    assert any(len(g.member_ids) == 3 for g in groups1)


def test_multi_source_guard_still_rejects_tokenisation_number_fragments():
    src96 = bullet("a", "Lifted top-5 accuracy to 96.3% overall.", ["evaluation"], metric=True)
    src_other = bullet("b", "Built a service in python.", ["python"])
    offenders = rewrite._check_fabrication([src96, src_other], "Lifted accuracy 3% overall.")
    assert "3" in offenders


def test_multi_source_guard_still_rejects_fabricated_percentage_numbers():
    src96 = bullet("a", "Reduced query latency to 96.3% overall.", ["evaluation"], metric=True)
    src_other = bullet("b", "Built a service in python.", ["python"])
    offenders = rewrite._check_fabrication([src96, src_other], "Reduced query latency to 99% overall.")
    assert "99" in offenders


def test_merge_acceptance_collapses_ids_but_keeps_entry_renderable(monkeypatch, rewrite_calls, tmp_path):
    """Accepted merge deletes absorbed ids from the rewritten bullets dict."""
    CPL = config.CHARS_PER_LINE
    char_budget = 2 * CPL
    _, hard_max = rewrite._length_band(char_budget)

    a = bullet("aol_b1", _text(hard_max), ["python"])
    b = bullet("aol_b2", _text(hard_max), ["python"])

    e = Experience(company="ACME", title="t", start="2020-01", end="2020-02", bullets=[a, b])
    resume = MasterResume(
        comment=None,
        contact=Contact(name="Test", email="test@example.com", phone=""),
        education=[],
        summary_variants=[],
        experience=[e],
        projects=[],
        skills=[],
    )

    groups = [
        merge.MergeGroup(
            survivor_id=a.id,
            member_ids=(a.id, b.id),
            affinity=1.0,
            reason="test",
        )
    ]

    # LLM call 1: rewrite each bullet -> keep text as-is.
    # LLM call 2: merge stage -> produce a shorter candidate that frees lines.
    candidate = _text(hard_max)  # still 2 lines; before_lines sums to 4 lines.
    calls = rewrite_calls(_reply(**{a.id: a.text, b.id: b.text}), _reply(**{a.id: candidate}))

    reqs = requirements(("python", "must_have"))
    outcome = rewrite.rewrite_bullets(
        [a, b],
        reqs,
        char_budget=char_budget,
        shorten_pct=0,
        repair_widows=False,
        merge_groups=groups,
    )

    assert outcome.merges == groups
    assert set(outcome.texts.keys()) == {a.id}

    class _DummyTpl:
        def build_url_id(self, url: str) -> str:  # pragma: no cover
            return url

    ctx = render.build_context(resume, tpl=_DummyTpl(), bullets=outcome.texts)
    assert len(ctx["experience"]) == 1
    assert ctx["experience"][0]["bullets"] == [candidate]


def test_merge_rejects_when_numbers_are_dropped(monkeypatch, rewrite_calls):
    """Even if the merged text is shorter, dropping any source number rejects the merge."""
    CPL = config.CHARS_PER_LINE
    char_budget = 2 * CPL
    _, hard_max = rewrite._length_band(char_budget)

    a = bullet("aol_b1", f"{_text(hard_max - 10)} 100", ["python"])
    b = bullet("aol_b2", f"{_text(hard_max - 20)} 200", ["python"])
    e = Experience(company="ACME", title="t", start="2020-01", end="2020-02", bullets=[a, b])
    resume = MasterResume(
        comment=None,
        contact=Contact(name="Test", email="test@example.com", phone=""),
        education=[],
        summary_variants=[],
        experience=[e],
        projects=[],
        skills=[],
    )

    groups = [
        merge.MergeGroup(
            survivor_id=a.id,
            member_ids=(a.id, b.id),
            affinity=1.0,
            reason="test",
        )
    ]

    # Candidate is shorter but contains no digits, so `numbers_dropped` must reject.
    candidate = _text(hard_max - 1)
    rewrite_calls(_reply(**{a.id: a.text, b.id: b.text}), _reply(**{a.id: candidate}))

    reqs = requirements(("python", "must_have"))
    outcome = rewrite.rewrite_bullets(
        [a, b],
        reqs,
        char_budget=char_budget,
        shorten_pct=0,
        repair_widows=False,
        merge_groups=groups,
    )

    assert outcome.merges == []
    assert set(outcome.texts.keys()) == {a.id, b.id}

    class _DummyTpl:
        def build_url_id(self, url: str) -> str:  # pragma: no cover
            return url

    ctx = render.build_context(resume, tpl=_DummyTpl(), bullets=outcome.texts)
    assert len(ctx["experience"]) == 1
    assert len(ctx["experience"][0]["bullets"]) == 2


def test_report_prints_merge_section_and_counts_absorbed_members_as_kept():
    """Merging should not be reported as dropping bullets entirely."""
    resume = MasterResume(
        comment=None,
        contact=Contact(name="Test", email="test@example.com", phone=""),
        education=[],
        summary_variants=[],
        experience=[
            Experience(
                company="ACME",
                title="t",
                start="2020-01",
                end="2020-02",
                bullets=[bullet("a1", "A", ["python"]), bullet("a2", "B", ["python"])],
            )
        ],
        projects=[],
        skills=[],
    )
    reqs = requirements(("python", "must_have"))

    groups = [
        merge.MergeGroup(
            survivor_id="a1",
            member_ids=("a1", "a2"),
            affinity=1.0,
            reason="test",
        )
    ]

    # Only the survivor renders after merge acceptance.
    fit_result = fit_mod.FitResult(
        out_path=config.OUTPUT_DIR / "out.docx",
        pages=1,
        pages_are_estimated=False,
        iterations=1,
        bullets_selected=2,
        bullets_total=2,
        bullets={"a1": "merged"},
        semantic_used=False,
        widows_repaired=0,
        widows_remaining=0,
        merges=groups,
        warnings=[],
    )

    text = report.format_report(resume, reqs, fit_result)
    assert "Merges: 1 accepted" in text
    assert "ACME: 2/2 bullets" in text

