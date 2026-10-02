"""Matching imported entries against the master resume and placing leftovers."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..content.data import (
    Bullet,
    Education,
    Section,
)
from . import import_common


# --------------------------------------------------------------------------------------
# Merging an imported draft into an existing master resume
# --------------------------------------------------------------------------------------
def _match_key(text: str) -> str:
    """Case/punctuation-insensitive identity key for merge matching.

    Deliberately not `config.slugify`: slugify caps its output at 40 characters, which
    is fine for minting a short id but wrong for an equality key — two distinct
    50-character company names sharing a 40-character prefix would slugify to the same
    string and one would silently overwrite the other on merge. This has no length cap.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

#: Below this, a `_match_key` is too short for a suffix match to be meaningful evidence
#: (a single short word could coincidentally be a prefix/suffix of an unrelated one).
_MIN_NEAR_MISS_KEY = 4

def _is_near_miss(a: str, b: str) -> bool:
    """True when two `_match_key`s differ only by a leading/trailing suffix at a hyphen
    boundary — `university-of-california-irvine` vs `university-of-california-irvine-
    paul-merage-school-of-business`. Boundary-anchored, not a bare substring test, so a
    mid-word coincidence (`art` inside `martin`) can never match.

    Scoped to education (`_merge_education`) only: an institution's name legitimately
    grows a school/college suffix across two exports of the same resume; a company's
    generally does not, so experience/project/skills/list matching stays exact.
    """
    ka, kb = _match_key(a), _match_key(b)
    if ka == kb:
        return False
    short, long_ = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(short) < _MIN_NEAR_MISS_KEY:
        return False
    return long_.startswith(short + "-") or long_.endswith("-" + short)

def _merge_education_entry(existing: Education, incoming: Education) -> Education:
    """Field-by-field, only overwriting where `incoming` actually has a value — same
    rule `_merge_contact` uses, for the same reason: replacing the entry wholesale
    would silently wipe a curated field (e.g. `gpa`/`show_gpa`) the incoming .docx
    simply has no way to express (GPA written as free text like "Cumulative GPA:
    3.9/4.0" is read as a detail line, not the `gpa` field — see `_GPA_RE`).

    `show_gpa` is a bool, so truthiness can't tell "not found" apart from a deliberate
    `False`; it is only adopted alongside a non-empty incoming `gpa`.
    """
    updates: dict[str, object] = {
        field_name: value
        for field_name in ("school", "degree", "dates", "location", "coursework", "details")
        if (value := getattr(incoming, field_name))
    }
    if incoming.gpa:
        updates["gpa"] = incoming.gpa
        updates["show_gpa"] = incoming.show_gpa
    return existing.model_copy(update=updates)

class MergeStats(BaseModel):
    """What `merge_into` actually did, named rather than just counted — the caller
    surfaces these names so a near-miss duplicate (two spellings of the same school,
    say) is visible immediately instead of buried in a total."""

    updated: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    added_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

def _remint_bullets(bullets: list[Bullet], entry_id: str) -> list[Bullet]:
    """Bullets carry the id of the entry that owns them. On a merge match, the
    incoming bullets were minted under the incoming entry's own id — which is
    discarded, since the existing entry's id is what survives the merge — so they must
    be re-numbered under that surviving id instead."""
    return [b.model_copy(update={"id": f"{entry_id}_b{i}"}) for i, b in enumerate(bullets, start=1)]

def _target_section_index(sections: list[Section], kind: str, title: str) -> int | None:
    """Which existing section (by index) unmatched incoming entries of `kind` should
    be appended to, or `None` if a brand-new section must be created. First rule that
    applies:

    1. An existing section of `kind` whose title matches `title` (via `_match_key`).
    2. Else an existing *empty* section of `kind` — adopted, so a fresh workspace's
       default-titled placeholder sections (see `workspace._STARTER_RESUME`) receive
       the import instead of a same-kind duplicate being created beside them. The
       caller is responsible for actually renaming it.
    3. Else, if exactly one section of `kind` exists, use it — avoids splitting content
       across an ambiguous second section (e.g. skills vs. "additional information")
       when there is no real conflict to resolve.
    4. Else `None` — the caller creates a new section.

    By the time rule 3 is reached, rule 2 has already ruled out every same-kind section
    being empty, so rule 3 never silently claims an empty section under a different
    name than the caller would have picked via rule 2.
    """
    same_kind = [(i, s) for i, s in enumerate(sections) if s.kind == kind]
    for i, s in same_kind:
        if _match_key(s.title) == _match_key(title):
            return i
    for i, s in same_kind:
        if not s.entries:
            return i
    if len(same_kind) == 1:
        return same_kind[0][0]
    return None

def _place_leftovers(
    sections: list[Section],
    kind: str,
    inc_title: str,
    taken_section_ids: set[str],
    stats: MergeStats,
    section_cls: type,
) -> int:
    """Resolve (creating if needed) the section leftover incoming entries of `kind`
    should be appended to, and return its index. Shared tail end of every per-kind
    merge function once it has a non-empty `leftovers` list."""
    target_idx = _target_section_index(sections, kind, inc_title)
    if target_idx is None:
        new_section = section_cls(
            id=import_common._fresh_id(inc_title, taken_section_ids), title=inc_title, entries=[]
        )
        sections.append(new_section)
        stats.added_sections.append(inc_title)
        return len(sections) - 1
    if not sections[target_idx].entries:
        sections[target_idx] = sections[target_idx].model_copy(update={"title": inc_title})
    return target_idx
