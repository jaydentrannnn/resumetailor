"""Pairing incoming jobs and projects with the ones already in the master resume.

`plan_pairs` decides, per incoming entry, which existing entry it is the same as (or
that it is new) and says why; `union_bullets` folds a matched entry's bullets together
without losing one. Both are pure and deterministic: no LLM call, and no bullet text is
ever written here that the student did not write in one of the two resumes.
"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field

from ..content.data import Bullet, Experience, MasterResume, Project, Section
from . import import_merge_match

PairKind = Literal["experience", "project"]

#: Below this similarity two bullets are never folded into one. Folding also needs one
#: bullet to be the other with words added (`_bullet_overlap`), so a changed word or
#: number always keeps both: dropping a fact the student wrote is worse than showing
#: two alike lines.
_SAME_BULLET = 0.7

#: Why a pair was proposed, in the words the review list shows.
SAME_NAME = "same name"
SIMILAR_NAME_AND_DATES = "similar name and the same dates"
SAME_DATES_AND_TITLE = "same dates and a similar title"
CHOSEN = "your choice"


class MergePair(BaseModel):
    """One incoming job or project, and the existing entry it would be merged into."""

    #: `"<kind>:<incoming section index>:<incoming entry index>"`; the key a decision uses.
    key: str
    kind: PairKind
    name: str
    #: Title and dates (a job) or dates (a project), to tell two same-named entries apart.
    detail: str = ""
    #: The existing entry's id, or None for a new entry.
    match: str | None = None
    match_name: str = ""
    reason: str = ""
    #: An existing job with the same dates and a similar title but another employer's
    #: name: shown as a possibility, never merged unless the student picks it.
    suggested: str | None = None
    suggested_name: str = ""
    #: Incoming bullets the existing entry does not already have (all of them when new).
    new_bullets: int = 0


class MergeOption(BaseModel):
    """An existing entry the student may pick as "the same one" instead."""

    ref: str
    kind: PairKind
    label: str


class MergePlan(BaseModel):
    """What a merge would do to jobs and projects, for review before anything is saved."""

    pairs: list[MergePair] = Field(default_factory=list)
    options: list[MergeOption] = Field(default_factory=list)
    #: The saved resume this plan was made against (`resume_revision`); a merge that
    #: sends it back is refused when the resume changed in between.
    revision: str = ""
    #: The saved resume holds no entries, so there is nothing to merge into.
    existing_empty: bool = True


def resume_revision(resume: MasterResume) -> str:
    """A short fingerprint of a saved resume's content."""
    return hashlib.sha256(resume.model_dump_json(by_alias=True).encode("utf-8")).hexdigest()[:16]


def _name(entry: Experience | Project) -> str:
    return entry.company if isinstance(entry, Experience) else entry.name


def _detail(entry: Experience | Project) -> str:
    """The line under an entry's name in the review list."""
    dates = " – ".join(part for part in (entry.start, entry.end) if part)
    if isinstance(entry, Experience):
        return " · ".join(part for part in (entry.title, dates) if part)
    return dates or entry.date


def _norm(text: str) -> str:
    return import_merge_match._match_key(text)


#: Words that say nothing about a role, left out when titles are compared.
_TITLE_FILLER = {"of", "and", "the", "for", "in", "at", "to", "a", "an"}


def _similar_titles(a: str, b: str) -> bool:
    """Whether two job titles share at least half their words ("Undergraduate Research
    Assistant" / "Economic Research Assistant": research and assistant, 2 of 4). "Data
    Intern" / "Research Intern" share 1 of 3, so they stay two roles."""
    words_a = set(_norm(a).split("-")) - _TITLE_FILLER - {""}
    words_b = set(_norm(b).split("-")) - _TITLE_FILLER - {""}
    if not words_a or not words_b:
        return False
    return len(words_a & words_b) * 2 >= len(words_a | words_b)


def _same_dates(a: Experience | Project, b: Experience | Project) -> bool:
    """Both entries have a start and an end, and they are equal."""
    return (
        all((a.start, a.end, b.start, b.end))
        and _norm(a.start) == _norm(b.start)
        and _norm(a.end) == _norm(b.end)
    )


def _same_entry_reason(
    existing: Experience | Project, incoming: Experience | Project
) -> str | None:
    """Why two differently-named entries are the same one, or None when nothing says so.

    Both halves of the evidence are required: the same dates on both, and a name that
    only grew or lost words at one end ("Acme Corp" / "Acme Corp Consulting Division").
    A similar name alone is never enough (one employer over different years is two
    jobs), and neither is a similar title: two Research Assistant jobs over the same
    semester can be at two universities. That case is offered to the student as a
    possibility (`_possible_same_job`), never merged on its own.
    """
    if _same_dates(existing, incoming) and import_merge_match._is_near_miss(
        _name(existing), _name(incoming)
    ):
        return SIMILAR_NAME_AND_DATES
    return None


def _possible_same_job(existing: Experience | Project, incoming: Experience | Project) -> bool:
    """Two jobs over the same dates with a similar title (`_similar_titles`), under names
    that share nothing the app can check ("UCSD Economics Lab" / "UC San Diego
    Department of Economics"): maybe one job, but only the student knows."""
    return (
        isinstance(existing, Experience)
        and isinstance(incoming, Experience)
        and _same_dates(existing, incoming)
        and _similar_titles(existing.title, incoming.title)
    )


#: Words of a bullet for comparing two versions: numbers stay whole ("1.5" is one word,
#: so "$1M" -> "$1.5M" is a changed word, not an added one).
_BULLET_WORD = re.compile(r"\d+(?:[.,]\d+)*|[a-z]+")


def _is_subsequence(short: list[str], long_: list[str]) -> bool:
    remaining = iter(long_)
    return all(word in remaining for word in short)


def _bullet_overlap(old: str, new: str) -> Literal["same", "longer", "shorter"] | None:
    """How an incoming bullet relates to an existing one, when they are one line.

    ``same``: the same words (only case or punctuation differ). ``longer``: the incoming
    line is the existing one with words added; ``shorter``: with words left out. Nothing
    is lost either way, because the version kept holds every word of the other in
    order. Any changed, swapped or reordered word ("Canadian" / "Mexican", "20%" /
    "30%") returns None, and both lines are kept.
    """
    a, b = _BULLET_WORD.findall(old.lower()), _BULLET_WORD.findall(new.lower())
    if a == b:
        return "same"
    if SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() < _SAME_BULLET:
        return None
    if _is_subsequence(a, b):
        return "longer"
    if _is_subsequence(b, a):
        return "shorter"
    return None


def union_bullets(
    existing: list[Bullet], incoming: list[Bullet], entry_id: str
) -> tuple[list[Bullet], int]:
    """`existing` with `incoming` folded in, and how many incoming bullets were new.

    Every existing bullet stays, with its id and its Extra skills (`tags`). An incoming
    bullet that is an existing line with words added or left out (`_bullet_overlap`)
    is folded into it: the longer wording is kept, and the incoming Extra skills are
    added to the line's. Any other incoming bullet, including one where a word or number
    changed, is added at the end under a fresh id. Nothing is removed: a bullet missing
    from the uploaded file may simply not have been on that version.
    """
    merged = list(existing)
    used = {bullet.id for bullet in merged}
    added = 0
    for inc in incoming:
        twin, overlap = next(
            (
                (i, rel)
                for i, b in enumerate(merged)
                if (rel := _bullet_overlap(b.text, inc.text))
            ),
            (None, None),
        )
        if twin is not None:
            tags = merged[twin].tags + [t for t in inc.tags if t not in merged[twin].tags]
            update: dict[str, object] = {"tags": tags}
            if overlap == "longer":
                update["text"] = inc.text
                update["metric"] = inc.metric or merged[twin].metric
            merged[twin] = merged[twin].model_copy(update=update)
            continue
        number = len(merged) + 1
        while f"{entry_id}_b{number}" in used:
            number += 1
        bullet_id = f"{entry_id}_b{number}"
        used.add(bullet_id)
        merged.append(inc.model_copy(update={"id": bullet_id}))
        added += 1
    return merged, added


def plan_pairs(
    sections: list[Section],
    incoming_sections: list[Section],
    kind: PairKind,
    decisions: dict[str, str] | None = None,
) -> list[MergePair]:
    """Pair each incoming `kind` entry with an existing one, or mark it new.

    In order: what the student decided (`decisions`: pair key to an existing entry's
    id, or `"new"`); then entries with the same name, in document order; then a single
    unclaimed existing entry that `_same_entry_reason` vouches for. Two candidates is a
    guess, so that entry is added as new and left for the student to pair. An entry left
    new with exactly one `_possible_same_job` gets it as ``suggested``. Existing entries
    are named by id, so reordering the resume cannot point a decision elsewhere.
    """
    decisions = decisions or {}
    existing: dict[str, Experience | Project] = {
        entry.id: entry for sec in sections if sec.kind == kind for entry in sec.entries
    }
    unclaimed = list(existing)
    incoming = [
        (f"{kind}:{si}:{ei}", entry)
        for si, sec in enumerate(incoming_sections)
        if sec.kind == kind
        for ei, entry in enumerate(sec.entries)
    ]
    matches: dict[str, tuple[str | None, str]] = {}

    for key, _ in incoming:
        choice = decisions.get(key)
        if choice == "new":
            matches[key] = (None, "")
        elif choice in unclaimed:
            unclaimed.remove(choice)
            matches[key] = (choice, CHOSEN)
    for key, entry in incoming:
        if key in matches:
            continue
        ref = next((r for r in unclaimed if _norm(_name(existing[r])) == _norm(_name(entry))), None)
        if ref is not None:
            unclaimed.remove(ref)
            matches[key] = (ref, SAME_NAME)
    for key, entry in incoming:
        if key in matches:
            continue
        candidates = [
            (r, why) for r in unclaimed if (why := _same_entry_reason(existing[r], entry))
        ]
        if len(candidates) == 1:
            ref, why = candidates[0]
            unclaimed.remove(ref)
            matches[key] = (ref, why)
        else:
            matches[key] = (None, "")

    pairs: list[MergePair] = []
    for key, entry in incoming:
        ref, why = matches[key]
        target = existing[ref] if ref else None
        new_bullets = (
            union_bullets(target.bullets, entry.bullets, target.id)[1]
            if target
            else len(entry.bullets)
        )
        possible = (
            [r for r in unclaimed if _possible_same_job(existing[r], entry)] if not target else []
        )
        suggested = possible[0] if len(possible) == 1 else None
        pairs.append(
            MergePair(
                key=key,
                kind=kind,
                name=_name(entry),
                detail=_detail(entry),
                match=ref,
                match_name=_name(target) if target else "",
                reason=why,
                suggested=suggested,
                suggested_name=_name(existing[suggested]) if suggested else "",
                new_bullets=new_bullets,
            )
        )
    return pairs


def plan_merge(
    existing: MasterResume,
    incoming_sections: list[Section],
    decisions: dict[str, str] | None = None,
) -> MergePlan:
    """The pairs for jobs and projects, every existing entry offered as a choice, and the
    saved resume's revision and emptiness."""
    sections = existing.sections
    pairs = [
        pair
        for kind in ("experience", "project")
        for pair in plan_pairs(sections, incoming_sections, kind, decisions)
    ]
    options = [
        MergeOption(
            ref=entry.id,
            kind=sec.kind,
            label=" · ".join(part for part in (_name(entry), _detail(entry)) if part),
        )
        for sec in sections
        if sec.kind in ("experience", "project")
        for entry in sec.entries
    ]
    return MergePlan(
        pairs=pairs,
        options=options,
        revision=resume_revision(existing),
        existing_empty=not any(sec.entries for sec in sections),
    )


# --------------------------------------------------------------------------------------
# The same job or project twice inside one resume
# --------------------------------------------------------------------------------------
class DuplicatePair(BaseModel):
    """Two entries of one resume that look like the same job or project."""

    kind: PairKind
    #: Entry ids: `keep` is the first in the resume, and the one a merge keeps.
    keep: str
    drop: str
    keep_label: str
    drop_label: str
    reason: str


def _duplicate_reason(a: Experience | Project, b: Experience | Project) -> str | None:
    """Why two entries of one resume are the same one. The same dates are required even
    for the same name: one employer twice with different dates is a promotion or a
    return, not a duplicate."""
    if _norm(_name(a)) == _norm(_name(b)):
        dated = all((a.start, a.end, b.start, b.end))
        same = dated and _norm(a.start) == _norm(b.start) and _norm(a.end) == _norm(b.end)
        return "same name and dates" if same else None
    return _same_entry_reason(a, b)


def find_duplicates(sections: list[Section]) -> list[DuplicatePair]:
    """Pairs of jobs (or projects) that look like one entry entered twice, in resume
    order. Each entry appears in at most one pair, so merging the list top to bottom
    never touches an entry twice."""
    pairs: list[DuplicatePair] = []
    for kind in ("experience", "project"):
        entries = [entry for sec in sections if sec.kind == kind for entry in sec.entries]
        used: set[str] = set()
        for i, a in enumerate(entries):
            if a.id in used:
                continue
            for b in entries[i + 1 :]:
                if b.id in used or not (why := _duplicate_reason(a, b)):
                    continue
                used.update((a.id, b.id))
                pairs.append(
                    DuplicatePair(
                        kind=kind,
                        keep=a.id,
                        drop=b.id,
                        keep_label=" · ".join(p for p in (_name(a), _detail(a)) if p),
                        drop_label=" · ".join(p for p in (_name(b), _detail(b)) if p),
                        reason=why,
                    )
                )
                break
    return pairs


def merge_duplicate(resume: MasterResume, keep_id: str, drop_id: str) -> MasterResume:
    """`resume` with entry `drop_id` folded into `keep_id` and removed.

    The kept entry keeps its id, name and bullets; it gains the other entry's bullets it
    does not already have (`union_bullets`) and any field it has empty. Raises
    ValueError unless both ids name different entries of one kind.
    """
    found: dict[str, tuple[int, int]] = {
        entry.id: (si, ei)
        for si, sec in enumerate(resume.sections)
        if sec.kind in ("experience", "project")
        for ei, entry in enumerate(sec.entries)
    }
    if keep_id == drop_id or keep_id not in found or drop_id not in found:
        raise ValueError("Those two entries are no longer in your resume.")
    (ks, ke), (ds, de) = found[keep_id], found[drop_id]
    if resume.sections[ks].kind != resume.sections[ds].kind:
        raise ValueError("A job can only be merged with a job, and a project with a project.")
    sections = [sec.model_copy(deep=True) for sec in resume.sections]
    keep, drop = sections[ks].entries[ke], sections[ds].entries[de]
    fields = ("title", "location", "start", "end") if isinstance(keep, Experience) else (
        "tech", "start", "end", "date", "link", "url"
    )
    updates: dict[str, object] = {
        field: getattr(drop, field)
        for field in fields
        if not getattr(keep, field) and getattr(drop, field)
    }
    updates["bullets"], _ = union_bullets(keep.bullets, drop.bullets, keep.id)
    sections[ks].entries[ke] = keep.model_copy(update=updates)
    del sections[ds].entries[de]
    # Validated again, not just copied: the resume's own checks (unique bullet ids,
    # entry order) must hold for what is saved.
    updated = resume.model_copy(update={"sections": sections})
    return MasterResume.model_validate(updated.model_dump(by_alias=True))
