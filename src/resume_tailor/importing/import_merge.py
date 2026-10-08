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
from . import import_common, import_merge_match


def _merge_experience(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_entry_ids: set[str],
    taken_section_ids: set[str],
    stats: import_merge_match.MergeStats,
) -> None:
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    for si, sec in enumerate(sections):
        if sec.kind != "experience":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(import_merge_match._match_key(e.company), []).append(
                (si, ei)
            )

    for inc_sec in incoming_sections:
        if inc_sec.kind != "experience":
            continue
        leftovers: list[Experience] = []
        for inc in inc_sec.entries:
            queue = existing_by_key.get(import_merge_match._match_key(inc.company))
            if queue:
                si, ei = queue.pop(0)
                existing = sections[si].entries[ei]
                sections[si].entries[ei] = existing.model_copy(
                    update={
                        "company": inc.company,
                        "title": inc.title,
                        "location": inc.location,
                        "start": inc.start,
                        "end": inc.end,
                        "bullets": import_merge_match._remint_bullets(inc.bullets, existing.id),
                    }
                )
                stats.updated.append(inc.company)
            else:
                leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = import_merge_match._place_leftovers(
            sections, "experience", inc_sec.title, taken_section_ids, stats, ExperienceSection
        )
        for inc in leftovers:
            entry_id = import_common._fresh_id(inc.company or "role", taken_entry_ids)
            sections[target_idx].entries.append(
                inc.model_copy(
                    update={
                        "id": entry_id,
                        "bullets": import_merge_match._remint_bullets(inc.bullets, entry_id),
                    }
                )
            )
            stats.added.append(inc.company)

def _merge_projects(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_entry_ids: set[str],
    taken_section_ids: set[str],
    stats: import_merge_match.MergeStats,
) -> None:
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    for si, sec in enumerate(sections):
        if sec.kind != "project":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(import_merge_match._match_key(e.name), []).append((si, ei))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "project":
            continue
        leftovers: list[Project] = []
        for inc in inc_sec.entries:
            queue = existing_by_key.get(import_merge_match._match_key(inc.name))
            if queue:
                si, ei = queue.pop(0)
                existing = sections[si].entries[ei]
                sections[si].entries[ei] = existing.model_copy(
                    update={
                        "name": inc.name,
                        "tech": inc.tech,
                        "start": inc.start,
                        "end": inc.end,
                        "date": inc.date,
                        "link": inc.link,
                        "url": inc.url,
                        "bullets": import_merge_match._remint_bullets(inc.bullets, existing.id),
                    }
                )
                stats.updated.append(inc.name)
            else:
                leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = import_merge_match._place_leftovers(
            sections, "project", inc_sec.title, taken_section_ids, stats, ProjectSection
        )
        for inc in leftovers:
            entry_id = import_common._fresh_id(inc.name or "project", taken_entry_ids)
            sections[target_idx].entries.append(
                inc.model_copy(
                    update={
                        "id": entry_id,
                        "bullets": import_merge_match._remint_bullets(inc.bullets, entry_id),
                    }
                )
            )
            stats.added.append(inc.name)

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
    existing: MasterResume, incoming: MasterResume
) -> tuple[MasterResume, import_merge_match.MergeStats]:
    """Fold `incoming` (typically the `.resume` of an `ImportedResume`) into `existing`
    by matching entries on company/project name, school, skills label, or exact list
    text — never by section. An incoming section whose title doesn't match an existing
    one (e.g. "LEADERSHIP" vs. an existing "LEADERSHIP EXPERIENCE") must not cause an
    entry that already lives in that differently-titled section to be duplicated.
    Education additionally matches on a boundary-anchored suffix (`_is_near_miss`) after
    exact matching fails, since one export commonly names a school's college/school where
    another doesn't — every other kind matches exactly only.

    A matched entry is updated *in place*, keeping its existing id (and, for
    experience/project, its bullets re-minted under that id) so nothing referencing it
    elsewhere breaks; education additionally only overwrites fields the incoming entry
    actually has a value for (`_merge_education_entry`), so a curated `gpa`/`show_gpa`
    the incoming .docx has no way to express survives. An unmatched incoming entry is
    added — see `_target_section_index` for where. Anything in `existing` with no
    counterpart in `incoming` is left completely untouched, including its id, bullets,
    and tags.

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

    _merge_experience(sections, incoming.sections, taken_entry_ids, taken_section_ids, stats)
    _merge_projects(sections, incoming.sections, taken_entry_ids, taken_section_ids, stats)
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
