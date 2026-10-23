"""Evidence for the master resume: what the student added and what was proposed from it.

A workspace file, ``evidence.json`` beside the master resume. Pure, no network, no LLM.

Sources are GitHub repositories and documents (a syllabus, a reference letter, a project
write-up). Proposals read from them are only suggestions. Nothing here changes the
resume, and a pending proposal affects nothing. The student decides each one:

- ``added``: written into the resume through the resume route, as the student edited it
  (their own edit, trusted like typing in the editor);
- ``matching_only``: a skill kept in `Evidence.matching` (entry id → skills). Runs read
  it beside the inferred skills (`with_matching`), so it helps match a posting, and it
  never reaches `Bullet.tags`, `Project.tech`, the Skills section or the fabrication
  guard's whitelist;
- ``dismissed``: stays dismissed on a rescan, because a proposal's id is a hash of what
  it proposes (`proposal_id`).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.content.data import MasterResume
from resume_tailor.infra import atomic

SourceKind = Literal["github", "syllabus", "letter", "writeup", "other"]
#: Whose work a repository is: ``own`` at 80%+ of its commits, ``fork`` never proposed.
Attribution = Literal["own", "contributed", "fork", "unknown", ""]
ProposalKind = Literal["bullet", "project", "skill", "coursework"]
State = Literal["pending", "added", "matching_only", "dismissed"]

_LOCK = threading.RLock()


class EvidenceSource(BaseModel):
    id: str
    kind: SourceKind
    title: str
    url: str | None = None
    added_at: str = ""
    sha: str = ""
    text: str = ""
    #: What `posting_guard` flagged in it, in plain words.
    flags: list[str] = Field(default_factory=list)
    attribution: Attribution = ""
    #: The student's share of the repository's commits, 0..1, when GitHub reported it.
    commit_share: float | None = None
    languages: list[str] = Field(default_factory=list)
    #: When proposals were last read from it; "" until the student scans it.
    scanned_at: str = ""
    #: Proposals the guard rejected in the last scan.
    dropped: int = 0
    #: Why they were rejected, counted ("term not in excerpt": 2).
    drop_reasons: dict[str, int] = Field(default_factory=dict)
    model: str = ""


class NewProject(BaseModel):
    name: str
    tech: list[str] = Field(default_factory=list)
    url: str = ""
    start: str = ""
    end: str = ""


class Proposal(BaseModel):
    id: str
    source_id: str
    kind: ProposalKind
    #: The resume entry a bullet or skill belongs to; "" for a new project or a course.
    target_entry_id: str = ""
    new_project: NewProject | None = None
    #: The bullet text, the skill or the course name.
    text: str
    #: The source's own words that support it.
    excerpt: str
    basis: Literal["stated", "inferred"]
    #: What the student should answer before using an inferred item.
    question: str = ""
    state: State = "pending"
    decided_at: str = ""
    #: Where an added item went, e.g. "bullet acme_b4" or "skills Languages".
    added_to: str = ""


class Evidence(BaseModel):
    sources: list[EvidenceSource] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    #: Skills kept for matching only, by resume entry id.
    matching: dict[str, list[str]] = Field(default_factory=dict)


def path() -> Path:
    return config.MASTER_RESUME_PATH.parent / "evidence.json"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def short_id(prefix: str, *parts: str) -> str:
    """A short id that depends only on ``parts``."""
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:10]}"


def proposal_id(kind: str, target: str, text: str) -> str:
    """Stable across scans, so a dismissed item stays dismissed (as `propose._proposal_id`)."""
    return short_id("e", kind, target, " ".join(text.casefold().split()))


def load() -> Evidence:
    return atomic.read_cached(path(), Evidence) or Evidence()


def _save(evidence: Evidence) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(target, evidence.model_dump_json(indent=1) + "\n")


@contextmanager
def update() -> Iterator[Evidence]:
    """Load, let the caller change, save — one writer at a time. Nothing is saved when
    the block raises."""
    with _LOCK:
        evidence = load()
        yield evidence
        _save(evidence)


def source(evidence: Evidence, source_id: str) -> EvidenceSource | None:
    return next((s for s in evidence.sources if s.id == source_id), None)


def proposal(evidence: Evidence, pid: str) -> Proposal | None:
    return next((p for p in evidence.proposals if p.id == pid), None)


def put_source(evidence: Evidence, fresh: EvidenceSource) -> EvidenceSource:
    """Add ``fresh``, or refresh the stored source with the same id (its scan stays)."""
    old = source(evidence, fresh.id)
    if old is None:
        evidence.sources.append(fresh)
        return fresh
    keep = {"added_at": old.added_at or fresh.added_at}
    if old.sha == fresh.sha:
        keep |= {"scanned_at": old.scanned_at, "dropped": old.dropped, "model": old.model}
    merged = fresh.model_copy(update=keep)
    evidence.sources[evidence.sources.index(old)] = merged
    return merged


def remove_source(evidence: Evidence, source_id: str) -> bool:
    """Drop a source and its undecided proposals. Decided ones stay: an added bullet is
    in the resume, and a matching-only skill keeps working until it is removed."""
    if source(evidence, source_id) is None:
        return False
    evidence.sources = [s for s in evidence.sources if s.id != source_id]
    evidence.proposals = [
        p for p in evidence.proposals if p.source_id != source_id or p.state != "pending"
    ]
    return True


def merge_scan(evidence: Evidence, source_id: str, fresh: list[Proposal]) -> list[Proposal]:
    """Replace a source's pending proposals with ``fresh``. A proposal already decided
    keeps its state and is not offered again. Returns the source's pending proposals."""
    decided = {p.id for p in evidence.proposals if p.state != "pending"}
    evidence.proposals = [
        p for p in evidence.proposals if p.source_id != source_id or p.state != "pending"
    ]
    pending: list[Proposal] = []
    for item in fresh:
        if item.id in decided or any(p.id == item.id for p in pending):
            continue
        pending.append(item.model_copy(update={"source_id": source_id, "state": "pending"}))
    evidence.proposals.extend(pending)
    return pending


def keep_for_matching(evidence: Evidence, entry_id: str, skill: str) -> None:
    skills = evidence.matching.setdefault(entry_id, [])
    if skill.casefold() not in {s.casefold() for s in skills}:
        skills.append(skill)


def drop_from_matching(evidence: Evidence, entry_id: str, skill: str) -> None:
    kept = [s for s in evidence.matching.get(entry_id, []) if s.casefold() != skill.casefold()]
    if kept:
        evidence.matching[entry_id] = kept
    else:
        evidence.matching.pop(entry_id, None)


def matching_by_bullet(
    resume: MasterResume, evidence: Evidence | None = None
) -> dict[str, list[str]]:
    """Bullet id → matching-only skills, from its entry. Entries that no longer exist
    contribute nothing."""
    matching = (evidence or load()).matching
    out: dict[str, list[str]] = {}
    for section in resume.entry_sections:
        for entry in section.entries:
            skills = matching.get(entry.id)
            if skills:
                for bullet in entry.bullets:
                    out[bullet.id] = list(skills)
    return out


def with_matching(
    resume: MasterResume, inferred: Mapping[str, list[str]]
) -> dict[str, list[str]]:
    """``inferred`` (bullet text → skills) plus each entry's matching-only skills on that
    entry's current bullets. A copy; ``inferred`` and the inference cache are untouched."""
    merged = {text: list(skills) for text, skills in inferred.items()}
    try:
        extra = matching_by_bullet(resume)
    except (OSError, ValueError):  # an unreadable evidence file never stops a run
        return merged
    for bullet in resume.all_bullets():
        for skill in extra.get(bullet.id, ()):
            have = merged.setdefault(bullet.text, [])
            if skill.casefold() not in {s.casefold() for s in have}:
                have.append(skill)
    return merged
