"""Merging an imported resume into the master resume, section by section."""

from __future__ import annotations

from ..content.data import (
    Contact,
    Education,
    EducationSection,
    Experience,
    ExperienceSection,
    ListItem,
    ListSection,
    MasterResume,
    Project,
    ProjectSection,
    Section,
    SkillGroup,
    SkillsSection,
)
from . import import_common, import_merge_match, import_merge_plan

#: The fields an incoming entry may refresh on its match, per kind. The name comes
#: first: it is adopted only on a same-name match (a different spelling the student
#: chose to pair keeps the name already in the resume).
_REFRESHED = {
    "experience": ("company", "title", "location", "start", "end"),
    "project": ("name", "tech", "start", "end", "date", "link", "url"),
}
_SECTION_CLASS = {"experience": ExperienceSection, "project": ProjectSection}


def _merge_paired(
    sections: list[Section],
    incoming_sections: list[Section],
    kind: import_merge_plan.PairKind,
    decisions: dict[str, str] | None,
    taken_entry_ids: set[str],
    taken_section_ids: set[str],
    stats: import_merge_match.MergeStats,
) -> None:
    """Merge every incoming job (or project) into its pair, or add it as new.

    A matched entry keeps its id, its bullets and their Extra skills; the incoming
    entry refreshes only the fields it has a value for and adds the bullets the entry
    does not already hold (`import_merge_plan.union_bullets`). Pairing is global, never
    by section; a new entry goes where `_place_leftovers` puts its section.
    """
    pairs = {
        pair.key: pair
        for pair in import_merge_plan.plan_pairs(sections, incoming_sections, kind, decisions)
    }
    name_field = _REFRESHED[kind][0]
    for isi, inc_sec in enumerate(incoming_sections):
        if inc_sec.kind != kind:
            continue
        leftovers: list[Experience | Project] = []
        for iei, inc in enumerate(inc_sec.entries):
            pair = pairs[f"{kind}:{isi}:{iei}"]
            if pair.match is None:
                leftovers.append(inc)
                continue
            si, ei = next(
                (si, ei)
                for si, sec in enumerate(sections)
                if sec.kind == kind
                for ei, entry in enumerate(sec.entries)
                if entry.id == pair.match
            )
            existing = sections[si].entries[ei]
            same_name = pair.reason == import_merge_plan.SAME_NAME
            updates: dict[str, object] = {
                field: value
                for field in _REFRESHED[kind]
                if (value := getattr(inc, field)) and (same_name or field != name_field)
            }
            updates["bullets"], _ = import_merge_plan.union_bullets(
                existing.bullets, inc.bullets, existing.id
            )
            sections[si].entries[ei] = existing.model_copy(update=updates)
            stats.updated.append(getattr(inc, name_field))
            if not same_name:
                stats.warnings.append(
                    f'"{getattr(inc, name_field)}" was merged into your existing '
                    f'"{getattr(existing, name_field)}" ({pair.reason}).'
                )

        if not leftovers:
            continue
        target_idx = import_merge_match._place_leftovers(
            sections, kind, inc_sec.title, taken_section_ids, stats, _SECTION_CLASS[kind]
        )
        for inc in leftovers:
            name = getattr(inc, name_field)
            entry_id = import_common._fresh_id(
                name or ("role" if kind == "experience" else "project"), taken_entry_ids
            )
            sections[target_idx].entries.append(
                inc.model_copy(
                    update={
                        "id": entry_id,
                        "bullets": import_merge_match._remint_bullets(inc.bullets, entry_id),
                    }
                )
            )
            stats.added.append(name)

def _merge_education(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_section_ids: set[str],
    stats: import_merge_match.MergeStats,
) -> None:
    """Two matching passes, exact before near-miss, so a resume already holding both a
    short and a long spelling of one school (see `_is_near_miss`) resolves unambiguously:
    the incoming long spelling claims its exact twin first, leaving the short entry alone
    rather than both being fuzzily eligible for the same incoming entry.
    """
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    unclaimed: list[tuple[int, int]] = []
    for si, sec in enumerate(sections):
        if sec.kind != "education":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(import_merge_match._match_key(e.school), []).append((si, ei))
            unclaimed.append((si, ei))

    # Flattened across incoming sections (matching must be global — see `merge_into`'s
    # docstring), but each entry keeps its originating section so an unmatched leftover
    # is still placed via that section's own title, exactly as before this pass split.
    incoming_flat: list[tuple[Section, Education]] = [
        (inc_sec, inc)
        for inc_sec in incoming_sections
        if inc_sec.kind == "education"
        for inc in inc_sec.entries
    ]

    exact_leftovers: list[tuple[Section, Education]] = []
    for inc_sec, inc in incoming_flat:
        queue = existing_by_key.get(import_merge_match._match_key(inc.school))
        if queue:
            si, ei = queue.pop(0)
            unclaimed.remove((si, ei))
            sections[si].entries[ei] = import_merge_match._merge_education_entry(
                sections[si].entries[ei], inc
            )
            stats.updated.append(inc.school)
        else:
            exact_leftovers.append((inc_sec, inc))

    leftovers: list[tuple[Section, Education]] = []
    for inc_sec, inc in exact_leftovers:
        candidates = [
            (si, ei)
            for si, ei in unclaimed
            if import_merge_match._is_near_miss(sections[si].entries[ei].school, inc.school)
        ]
        if len(candidates) == 1:
            si, ei = candidates[0]
            unclaimed.remove((si, ei))
            existing_school = sections[si].entries[ei].school
            sections[si].entries[ei] = import_merge_match._merge_education_entry(
                sections[si].entries[ei], inc
            )
            stats.updated.append(inc.school)
            stats.warnings.append(
                f'Matched education entry "{existing_school}" to incoming '
                f'"{inc.school}" as a near-miss (school names differ by a suffix) — '
                "verify this is the entry you meant."
            )
        else:
            if len(candidates) > 1:
                stats.warnings.append(
                    f'Incoming education entry "{inc.school}" matched '
                    f"{len(candidates)} existing entries as a near-miss; added as new "
                    "rather than guessing which one to update — reconcile by hand."
                )
            leftovers.append((inc_sec, inc))

    if not leftovers:
        return

    # Regroup by originating incoming section (dict keyed by identity, since Section is
    # unhashable) so `_place_leftovers` still runs once per section, unchanged.
    by_section: dict[int, list[Education]] = {}
    section_order: list[Section] = []
    for inc_sec, inc in leftovers:
        key = id(inc_sec)
        if key not in by_section:
            by_section[key] = []
            section_order.append(inc_sec)
        by_section[key].append(inc)

    for inc_sec in section_order:
        target_idx = import_merge_match._place_leftovers(
            sections, "education", inc_sec.title, taken_section_ids, stats, EducationSection
        )
        for inc in by_section[id(inc_sec)]:
            sections[target_idx].entries.append(inc.model_copy())
            stats.added.append(inc.school)

def _merge_skills(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_section_ids: set[str],
    stats: import_merge_match.MergeStats,
) -> None:
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    for si, sec in enumerate(sections):
        if sec.kind != "skills":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(import_merge_match._match_key(e.label), []).append((si, ei))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "skills":
            continue
        leftovers: list[SkillGroup] = []
        for inc in inc_sec.entries:
            queue = existing_by_key.get(import_merge_match._match_key(inc.label))
            if queue:
                si, ei = queue.pop(0)
                existing = sections[si].entries[ei]
                # Keep the existing label's own casing/wording — its match key already
                # equals the incoming one, so only the items are actually "refreshed".
                sections[si].entries[ei] = existing.model_copy(update={"items": inc.items})
                stats.updated.append(existing.label)
            else:
                leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = import_merge_match._place_leftovers(
            sections, "skills", inc_sec.title, taken_section_ids, stats, SkillsSection
        )
        for inc in leftovers:
            sections[target_idx].entries.append(inc.model_copy())
            stats.added.append(inc.label)

def _merge_list_items(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_entry_ids: set[str],
    taken_section_ids: set[str],
    stats: import_merge_match.MergeStats,
) -> None:
    existing_keys: set[str] = set()
    for sec in sections:
        if sec.kind != "list":
            continue
        for e in sec.entries:
            existing_keys.add(import_merge_match._match_key(e.text))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "list":
            continue
        leftovers: list[ListItem] = []
        for inc in inc_sec.entries:
            key = import_merge_match._match_key(inc.text)
            if key in existing_keys:
                continue
            existing_keys.add(key)  # a repeat within this same incoming batch is still a dup
            leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = import_merge_match._place_leftovers(
            sections, "list", inc_sec.title, taken_section_ids, stats, ListSection
        )
        for inc in leftovers:
            entry_id = import_common._fresh_id(inc.text, taken_entry_ids)
            sections[target_idx].entries.append(inc.model_copy(update={"id": entry_id}))
            stats.added.append(inc.text)

def _merge_contact(existing: Contact, incoming: Contact) -> Contact:
    """Field-by-field merge, only overwriting where `incoming` actually has a value.

    A blanket overwrite would blank a manually-curated LinkedIn URL the moment an
    export loses its hyperlink (a documented gotcha in this codebase) even though
    nothing about that field genuinely changed.
    """
    updates = {
        field_name: value
        for field_name in ("name", "email", "phone", "location", "linkedin", "github", "links")
        if (value := getattr(incoming, field_name))
    }
    return existing.model_copy(update=updates)

def merge_into(
    existing: MasterResume,
    incoming: MasterResume,
    decisions: dict[str, str] | None = None,
) -> tuple[MasterResume, import_merge_match.MergeStats]:
    """Fold `incoming` (typically the `.resume` of an `ImportedResume`) into `existing`
    by matching entries on company/project name, school, skills label, or exact list
    text — never by section. An incoming section whose title doesn't match an existing
    one (e.g. "LEADERSHIP" vs. an existing "LEADERSHIP EXPERIENCE") must not cause an
    entry that already lives in that differently-titled section to be duplicated.
    Education additionally matches on a boundary-anchored suffix (`_is_near_miss`) after
    exact matching fails, since one export commonly names a school's college/school where
    another doesn't. Jobs and projects pair on the same name, then on a similar name or
    (jobs) the same title over the same dates; `decisions` overrides any of those pairs
    (`import_merge_plan.plan_pairs`). Skills and plain lists match exactly only.

    A matched entry is updated *in place*, keeping its existing id so nothing
    referencing it elsewhere breaks, and only the fields the incoming entry actually has
    a value for are overwritten (so a curated `gpa`/`show_gpa`, or a location the upload
    lacks, survives). A matched job or project keeps every bullet it had, with its tags,
    and gains the incoming bullets it did not have (`import_merge_plan.union_bullets`):
    nothing is dropped. An unmatched incoming entry is added — see
    `_target_section_index` for where. Anything in `existing` with no counterpart in
    `incoming` is left completely untouched, including its id, bullets, and tags.

    Pure: no I/O, no LLM call. `MasterResume.tag_vocabulary` is the union of both
    sides; `summary_variants` and `_comment` are carried over from `existing` verbatim,
    since `incoming` (an import) never produces them.
    """
    sections: list[Section] = [s.model_copy(deep=True) for s in existing.sections]
    stats = import_merge_match.MergeStats()

    taken_entry_ids: set[str] = {
        e.id for s in sections if s.kind in ("experience", "project", "list") for e in s.entries
    }
    taken_section_ids: set[str] = {s.id for s in sections}

    for kind in ("experience", "project"):
        _merge_paired(
            sections, incoming.sections, kind, decisions, taken_entry_ids, taken_section_ids, stats
        )
    _merge_education(sections, incoming.sections, taken_section_ids, stats)
    _merge_skills(sections, incoming.sections, taken_section_ids, stats)
    _merge_list_items(sections, incoming.sections, taken_entry_ids, taken_section_ids, stats)

    merged = MasterResume(
        comment=existing.comment,
        contact=_merge_contact(existing.contact, incoming.contact),
        summary_variants=existing.summary_variants,
        sections=sections,
        tag_vocabulary=sorted(set(existing.tag_vocabulary) | set(incoming.tag_vocabulary)),
    )
    return merged, stats
