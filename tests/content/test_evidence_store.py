"""Evidence proposals, their decisions and the matching-only layer (`content/evidence_store.py`)."""

from __future__ import annotations

from fixtures import synthetic_resume

from resume_tailor.content import bullet_tags, evidence_store
from resume_tailor.content.evidence_store import Evidence, EvidenceSource, Proposal
from resume_tailor.pipeline import tag_infer


def _proposal(text: str, *, source_id: str = "s1", kind: str = "skill",
              target: str = "example-corp") -> Proposal:
    return Proposal(
        id=evidence_store.proposal_id(kind, target, text), source_id=source_id, kind=kind,
        target_entry_id=target, text=text, excerpt=f"Used {text} daily.", basis="stated",
    )


def test_a_proposal_id_ignores_case_and_spacing_so_a_rescan_finds_the_same_item():
    assert evidence_store.proposal_id("skill", "a", "Docker  Compose") == \
        evidence_store.proposal_id("skill", "a", "docker compose")
    assert evidence_store.proposal_id("skill", "a", "Docker") != \
        evidence_store.proposal_id("skill", "b", "Docker")


def test_a_rescan_replaces_pending_items_and_never_offers_a_decided_one_again():
    evidence = Evidence()
    evidence_store.merge_scan(evidence, "s1", [_proposal("Docker"), _proposal("Redis")])
    evidence.proposals[0].state = "dismissed"

    pending = evidence_store.merge_scan(evidence, "s1", [_proposal("Docker"), _proposal("Kafka")])

    assert [p.text for p in pending] == ["Kafka"]
    assert {(p.text, p.state) for p in evidence.proposals} == {
        ("Docker", "dismissed"), ("Kafka", "pending"),
    }


def test_removing_a_source_keeps_what_was_already_decided():
    evidence = Evidence(sources=[EvidenceSource(id="s1", kind="other", title="Notes")])
    evidence_store.merge_scan(evidence, "s1", [_proposal("Docker"), _proposal("Redis")])
    evidence.proposals[1].state = "matching_only"

    assert evidence_store.remove_source(evidence, "s1")
    assert evidence.sources == []
    assert [p.text for p in evidence.proposals] == ["Redis"]
    assert not evidence_store.remove_source(evidence, "s1")


def test_a_refreshed_source_keeps_its_scan_only_while_its_text_is_unchanged():
    evidence = Evidence()
    evidence_store.put_source(evidence, EvidenceSource(
        id="s1", kind="github", title="a/b", sha="x", added_at="2026-01-01", scanned_at="2026-01-02",
    ))
    same = evidence_store.put_source(evidence, EvidenceSource(id="s1", kind="github", title="a/b", sha="x"))
    assert (same.added_at, same.scanned_at) == ("2026-01-01", "2026-01-02")
    changed = evidence_store.put_source(evidence, EvidenceSource(id="s1", kind="github", title="a/b", sha="y"))
    assert (changed.added_at, changed.scanned_at) == ("2026-01-01", "")
    assert len(evidence.sources) == 1


def test_matching_only_skills_join_inferred_skills_for_the_entry_and_nothing_else():
    resume = synthetic_resume()
    with evidence_store.update() as stored:
        evidence_store.keep_for_matching(stored, "example-corp", "Kubernetes")
        evidence_store.keep_for_matching(stored, "example-corp", "kubernetes")
        evidence_store.keep_for_matching(stored, "gone-entry", "Rust")
    inferred = {"Indexed research notes with embeddings.": ["vector search"]}

    merged = evidence_store.with_matching(resume, inferred)

    text = resume.bullet_by_id("exp_b1").text
    assert merged[text] == ["Kubernetes"]
    assert merged["Indexed research notes with embeddings."] == ["vector search"]
    assert inferred == {"Indexed research notes with embeddings.": ["vector search"]}
    assert evidence_store.matching_by_bullet(resume) == {"exp_b1": ["Kubernetes"]}


def test_a_run_matches_on_the_kept_skill_but_the_resume_never_carries_it(monkeypatch):
    resume = synthetic_resume()
    with evidence_store.update() as stored:
        evidence_store.keep_for_matching(stored, "example-corp", "Kubernetes")
    monkeypatch.setattr(tag_infer, "cached", lambda _r: tag_infer.Inference(skills={}))

    tag_infer.annotate_cached(resume)

    bullet = resume.bullet_by_id("exp_b1")
    assert "kubernetes" in bullet_tags.match_tags(bullet)
    assert "kubernetes" not in bullet_tags.match_tags(bullet, inferred=False)
    assert bullet.tags == ["python"]


def test_dropping_the_last_kept_skill_forgets_the_entry():
    evidence = Evidence()
    evidence_store.keep_for_matching(evidence, "a", "Docker")
    evidence_store.drop_from_matching(evidence, "a", "docker")
    assert evidence.matching == {}
