"""Tests for `propose.py`: the LLM vocabulary-proposal stage and its deterministic
post-filter.

The API call itself is stubbed throughout (the `llm.client_for` seam, matching
`test_jd.py`) — nothing here reaches the network or needs a key. `filter_proposals` is
pure and gets its own direct tests, separate from the call/cache plumbing.
"""

from __future__ import annotations

import pytest

from resume_tailor import config, libraries, propose
from resume_tailor.data import (
    Bullet,
    Contact,
    Experience,
    MasterResume,
)
from resume_tailor.jd import JobRequirements, Keyword


def _resume(*, bullet_text: str = "Did a thing.", bullet_tags: tuple[str, ...] = ("python",)) -> MasterResume:
    return MasterResume(
        contact=Contact(name="X", email="x@y.z"),
        experience=[
            Experience(
                company="Acme",
                title="Engineer",
                start="2020",
                end="2021",
                bullets=[Bullet(id="b1", text=bullet_text, tags=list(bullet_tags))],
            )
        ],
    )


def _requirements(phrase: str, canonical: str) -> JobRequirements:
    return JobRequirements(
        title="T",
        seniority="entry",
        keywords=[Keyword(phrase=phrase, canonical=canonical, importance="must_have")],
    )


# --------------------------------------------------------------------------------------
# Input gathering
# --------------------------------------------------------------------------------------


def test_near_miss_alias_candidates_finds_a_spelling_mismatch():
    resume = _resume(bullet_tags=("grpo",))
    reqs = _requirements("Group Relative Policy Optimization", "group relative policy optimization")

    pairs = propose.near_miss_alias_candidates(reqs, resume)

    assert pairs == [("Group Relative Policy Optimization", "grpo")]


def test_near_miss_alias_candidates_empty_when_nothing_is_close():
    resume = _resume(bullet_tags=("python",))
    reqs = _requirements("Nursing", "nursing")

    assert propose.near_miss_alias_candidates(reqs, resume) == []


def test_unclassified_opening_verbs_finds_an_unknown_opener():
    resume = _resume(bullet_text="Triaged 200 support tickets weekly.")

    assert propose.unclassified_opening_verbs(resume) == ["triaged"]


def test_unclassified_opening_verbs_excludes_a_known_opener():
    resume = _resume(bullet_text="Designed a caching layer.")

    assert propose.unclassified_opening_verbs(resume) == []


# --------------------------------------------------------------------------------------
# LLM call: prompt contents and cache key
# --------------------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, parsed, calls):
        self._parsed = parsed
        self._calls = calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return _FakeResponse(self._parsed)


class _FakeClient:
    def __init__(self, parsed, calls):
        self.messages = _FakeMessages(parsed, calls)


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """Stub the API and redirect the proposal cache into a temp directory."""
    recorded: list[dict] = []
    parsed = propose.VocabularyProposal(
        tag_aliases=[propose.AliasProposal(alias="pg", canonical="postgresql", rationale="r")],
        verb_families=[propose.VerbProposal(verb="triaged", family="analyse", rationale="r")],
    )
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(propose.llm, "client_for", lambda purpose: _FakeClient(parsed, recorded))
    return recorded


def test_no_call_when_nothing_to_propose_about(calls):
    result = propose.propose_vocabulary(
        known_tags=["python"], unmatched=[], unknown_verbs=[], families={}
    )
    assert result == propose.VocabularyProposal()
    assert calls == []


def test_known_tags_and_unmatched_and_verbs_reach_the_prompt(calls):
    propose.propose_vocabulary(
        known_tags=["python", "docker"],
        unmatched=[("Postgres", "postgresql")],
        unknown_verbs=["triaged"],
        families={"build": ("built", "designed")},
    )

    content = calls[0]["messages"][0]["content"]
    assert "<known_tags>" in content and "docker" in content and "python" in content
    assert "<unmatched_spellings>" in content and "Postgres" in content
    assert "<unclassified_verbs>" in content and "triaged" in content
    assert "<verb_families>" in content and "build:" in content


def test_jd_text_reaches_the_prompt_only_when_supplied(calls):
    propose.propose_vocabulary(
        known_tags=["python"],
        unmatched=[("Postgres", "postgresql")],
        unknown_verbs=[],
        families={},
    )
    assert "<job_description>" not in calls[0]["messages"][0]["content"]

    propose.propose_vocabulary(
        known_tags=["python"],
        unmatched=[("Postgres", "postgresql")],
        unknown_verbs=[],
        families={},
        jd_text="We need Postgres.",
        use_cache=False,
    )
    assert "<job_description>" in calls[1]["messages"][0]["content"]


def test_second_call_with_identical_inputs_hits_the_cache(calls):
    kwargs = dict(
        known_tags=["python"], unmatched=[("Postgres", "postgresql")], unknown_verbs=[], families={}
    )
    propose.propose_vocabulary(**kwargs)
    propose.propose_vocabulary(**kwargs)
    assert len(calls) == 1


def test_cache_key_varies_with_the_effective_library(calls):
    kwargs = dict(
        known_tags=["python"], unmatched=[("Postgres", "postgresql")], unknown_verbs=[], families={}
    )
    propose.propose_vocabulary(**kwargs)

    libraries.write_pack(libraries.Pack(id="a", label="A", tag_aliases={"x": "y"}))
    libraries.write_workspace_state(
        libraries.WorkspaceLibraryState(enabled_packs=["core-tech", "a"])
    )

    propose.propose_vocabulary(**kwargs)
    assert len(calls) == 2


def test_cache_key_varies_with_prompt_version(calls, monkeypatch):
    kwargs = dict(
        known_tags=["python"], unmatched=[("Postgres", "postgresql")], unknown_verbs=[], families={}
    )
    propose.propose_vocabulary(**kwargs)
    monkeypatch.setattr(propose, "_PROMPT_VERSION", 999)
    propose.propose_vocabulary(**kwargs)
    assert len(calls) == 2


def test_llm_error_is_not_fatal_by_construction(calls, monkeypatch):
    """propose_vocabulary raises normally — non-fatal behaviour is the caller's job
    (the route and the jobs.py hook), asserted at that layer. This just pins that a
    parse failure surfaces as a normal exception, not a silent empty result."""

    def _raise(purpose):
        raise RuntimeError("boom")

    monkeypatch.setattr(propose.llm, "client_for", _raise)
    with pytest.raises(RuntimeError):
        propose.propose_vocabulary(
            known_tags=["python"], unmatched=[("Postgres", "postgresql")], unknown_verbs=[], families={}
        )


# --------------------------------------------------------------------------------------
# filter_proposals
# --------------------------------------------------------------------------------------


def _effective(**kw) -> libraries.EffectiveLibrary:
    defaults = dict(tag_aliases={}, verb_families={}, verb_index={}, diagnostics=[])
    defaults.update(kw)
    return libraries.EffectiveLibrary(**defaults)


def test_filters_a_target_not_in_known_tags():
    raw = propose.VocabularyProposal(
        tag_aliases=[propose.AliasProposal(alias="pg", canonical="postgresql")]
    )
    out = propose.filter_proposals(
        raw, known_tags=["python"], effective=_effective(), rejected=[]
    )
    assert out == []


def test_filters_an_alias_that_is_itself_a_known_tag():
    raw = propose.VocabularyProposal(
        tag_aliases=[propose.AliasProposal(alias="python", canonical="python")]
    )
    out = propose.filter_proposals(
        raw, known_tags=["python"], effective=_effective(), rejected=[]
    )
    assert out == []


def test_filters_an_alias_already_effective():
    raw = propose.VocabularyProposal(
        tag_aliases=[propose.AliasProposal(alias="pg", canonical="postgresql")]
    )
    out = propose.filter_proposals(
        raw,
        known_tags=["postgresql"],
        effective=_effective(tag_aliases={"pg": "postgresql"}),
        rejected=[],
    )
    assert out == []


def test_filters_a_previously_rejected_alias():
    raw = propose.VocabularyProposal(
        tag_aliases=[propose.AliasProposal(alias="pg", canonical="postgresql")]
    )
    out = propose.filter_proposals(
        raw,
        known_tags=["postgresql"],
        effective=_effective(),
        rejected=[libraries.RejectedEntry(kind="tag_alias", alias="pg", canonical="postgresql")],
    )
    assert out == []


def test_accepts_a_valid_alias_proposal():
    raw = propose.VocabularyProposal(
        tag_aliases=[propose.AliasProposal(alias="pg", canonical="postgresql", rationale="same db")]
    )
    out = propose.filter_proposals(
        raw, known_tags=["postgresql"], effective=_effective(), rejected=[]
    )
    assert len(out) == 1
    assert out[0].kind == "tag_alias"
    assert out[0].alias == "pg"
    assert out[0].canonical == "postgresql"


def test_filters_family_none():
    raw = propose.VocabularyProposal(
        verb_families=[propose.VerbProposal(verb="triaged", family="none")]
    )
    out = propose.filter_proposals(
        raw,
        known_tags=[],
        effective=_effective(verb_families={"analyse": ("assessed",)}),
        rejected=[],
    )
    assert out == []


def test_filters_a_family_that_does_not_exist():
    raw = propose.VocabularyProposal(
        verb_families=[propose.VerbProposal(verb="triaged", family="care")]
    )
    out = propose.filter_proposals(
        raw,
        known_tags=[],
        effective=_effective(verb_families={"analyse": ("assessed",)}),
        rejected=[],
    )
    assert out == []


def test_filters_a_verb_already_classified():
    raw = propose.VocabularyProposal(
        verb_families=[propose.VerbProposal(verb="assessed", family="analyse")]
    )
    out = propose.filter_proposals(
        raw,
        known_tags=[],
        effective=_effective(
            verb_families={"analyse": ("assessed",)}, verb_index={"assessed": "analyse"}
        ),
        rejected=[],
    )
    assert out == []


def test_filters_a_non_alphabetic_verb():
    raw = propose.VocabularyProposal(
        verb_families=[propose.VerbProposal(verb="re-factored", family="build")]
    )
    out = propose.filter_proposals(
        raw, known_tags=[], effective=_effective(verb_families={"build": ("built",)}), rejected=[]
    )
    assert out == []


def test_filters_a_previously_rejected_verb():
    raw = propose.VocabularyProposal(
        verb_families=[propose.VerbProposal(verb="triaged", family="analyse")]
    )
    out = propose.filter_proposals(
        raw,
        known_tags=[],
        effective=_effective(verb_families={"analyse": ("assessed",)}),
        rejected=[libraries.RejectedEntry(kind="verb_family", verb="triaged", family="analyse")],
    )
    assert out == []


def test_accepts_a_valid_verb_proposal():
    raw = propose.VocabularyProposal(
        verb_families=[propose.VerbProposal(verb="triaged", family="analyse", rationale="r")]
    )
    out = propose.filter_proposals(
        raw, known_tags=[], effective=_effective(verb_families={"analyse": ("assessed",)}), rejected=[]
    )
    assert len(out) == 1
    assert out[0].kind == "verb_family"
    assert out[0].verb == "triaged"
    assert out[0].family == "analyse"


def test_caps_at_max_proposals():
    raw = propose.VocabularyProposal(
        tag_aliases=[
            propose.AliasProposal(alias=f"alias{i}", canonical="python") for i in range(30)
        ]
    )
    out = propose.filter_proposals(
        raw, known_tags=["python"], effective=_effective(), rejected=[]
    )
    assert len(out) == propose._MAX_PROPOSALS


def test_proposal_ids_are_stable_across_calls():
    raw = propose.VocabularyProposal(
        tag_aliases=[propose.AliasProposal(alias="pg", canonical="postgresql")]
    )
    first = propose.filter_proposals(
        raw, known_tags=["postgresql"], effective=_effective(), rejected=[]
    )
    second = propose.filter_proposals(
        raw, known_tags=["postgresql"], effective=_effective(), rejected=[]
    )
    assert first[0].id == second[0].id


# --------------------------------------------------------------------------------------
# propose_bullet_tags
# --------------------------------------------------------------------------------------


@pytest.fixture
def tag_calls(monkeypatch):
    """Stub the API for propose_bullet_tags; no cache seam to redirect (unlike
    propose_vocabulary, this pass is not cached — see its own docstring)."""
    recorded: list[dict] = []
    parsed = propose._BulletTagProposals(
        proposals=[
            propose._BulletTagProposal(bullet_index=0, tags=["python", "not-a-real-tag"]),
            propose._BulletTagProposal(bullet_index=1, tags=[]),
            propose._BulletTagProposal(bullet_index=99, tags=["python"]),
        ]
    )
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(propose.llm, "client_for", lambda purpose: _FakeClient(parsed, recorded))
    return recorded


def test_no_call_when_nothing_to_tag(tag_calls):
    assert propose.propose_bullet_tags([], ["python"]) == {}
    assert propose.propose_bullet_tags(["Built a thing."], []) == {}
    assert tag_calls == []


def test_bullets_and_known_tags_reach_the_prompt(tag_calls):
    propose.propose_bullet_tags(["Built a Python service.", "Led a team."], ["python", "sql"])
    content = tag_calls[0]["messages"][0]["content"]
    assert "<known_tags>" in content and "python" in content and "sql" in content
    assert "<bullets>" in content and "Built a Python service." in content


def test_drops_a_tag_outside_known_tags(tag_calls):
    """The model proposed "not-a-real-tag" alongside "python" for bullet 0 — only the
    known one survives, mirroring `filter_proposals`'s own "model selects, code
    enforces" contract for vocabulary proposals."""
    result = propose.propose_bullet_tags(
        ["Built a Python service.", "Led a team."], ["python", "sql"]
    )
    assert result == {0: ["python"]}


def test_empty_tag_list_is_a_valid_answer_not_included(tag_calls):
    """Bullet 1 got an explicit empty list back (a real 'no known tag applies'
    answer) — it must not appear in the result at all, same as never being proposed."""
    result = propose.propose_bullet_tags(
        ["Built a Python service.", "Led a team."], ["python", "sql"]
    )
    assert 1 not in result


def test_out_of_range_bullet_index_is_ignored(tag_calls):
    """Bullet index 99 does not exist in a two-bullet request; it must not crash or
    leak into the result."""
    result = propose.propose_bullet_tags(
        ["Built a Python service.", "Led a team."], ["python", "sql"]
    )
    assert 99 not in result


def test_llm_error_is_not_fatal_by_construction_for_tags(monkeypatch):
    def _raise(purpose):
        raise RuntimeError("boom")

    monkeypatch.setattr(propose.llm, "client_for", _raise)
    with pytest.raises(RuntimeError):
        propose.propose_bullet_tags(["Built a thing."], ["python"])
