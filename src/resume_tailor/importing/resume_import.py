"""Deterministic DOCX -> `MasterResume` importer.

An upload to the Template tab was, until now, a layout donor whose content was
discarded — a new user uploads their resume and then retypes every bullet by hand into
the editor. `template_analyze.analyze_docx` already locates every section, entry,
header field, date, and bullet in an uploaded document (Phase 4's move to reconciling
*every* entry via `_reconcile_header_fields`, not just a single prototype, is exactly
the prerequisite this needed); this module turns that same structural analysis into a
`MasterResume` draft instead of a template mapping.

No LLM call is required to produce a usable draft. Tags are seeded deterministically by
substring-matching each bullet's text against a known-tag vocabulary
(`_seed_tags`) — the same "cheap and free first" instinct the rest of the pipeline
follows (tag-overlap scoring before the semantic LLM blend, `TAG_ALIASES` before a
model call). A bullet nothing matched gets the sentinel tag `"untagged"` (required
since `Bullet.tags` has `min_length=1`) and is counted in `ImportedResume.
untagged_bullet_count`, surfaced to the user rather than silently guessed at.

An optional, explicitly opt-in LLM pass — `propose.propose_bullet_tags` — can suggest
real tags for whatever the deterministic pass left untagged. It is never part of this
module's own call graph; the caller (the web route) decides whether to run it, exactly
as `propose.py`'s existing vocabulary proposals are opt-in Settings-tab actions, never
pipeline stages.

Reuses `template_analyze`'s own private paragraph-level helpers (`_load_paras`,
`_split_entries`, `_header_fields_from_text`, `_skills_spans`) rather than re-deriving
entry/field detection a second time — two independent implementations of "where is the
company name on this line" would drift the moment either one's edge cases were fixed
only in one place. This mirrors how `template_verify.py` already shares
`template_build`'s tag constants instead of re-deriving them.
"""

from __future__ import annotations

from ..content.data import (
    EducationSection,
    ExperienceSection,
    ListSection,
    MasterResume,
    ProjectSection,
    Section,
    SkillsSection,
)
from ..document import (
    template_analyze,
)
from ..document.analysis_types import AnalyzeResult
from . import import_common, import_contact, import_entries, import_layout


def import_from_analysis(
    result: AnalyzeResult, doc, *, known_tags: set[str] | None = None
) -> import_common.ImportedResume:
    """Build a `MasterResume` draft from `result` (an already-run `analyze_docx` call)
    and the open `doc` it was computed from.

    `known_tags` seeds the deterministic tag matcher; defaults to the built-in alias
    table when the caller has no existing resume's vocabulary to union in (a brand new
    workspace's first import). Passing an existing resume's `tag_vocabulary` lets a
    re-import recognize that resume's own established tag spellings too.
    """
    warnings: list[str] = [i.message for i in result.issues if not i.blocking]
    paras = template_analyze._load_paras(doc)
    vocabulary = import_common._default_vocabulary() if known_tags is None else set(known_tags)

    first_heading_id = result.sections[0].heading_paragraph_id if result.sections else None
    contact = import_layout.header_contact(
        doc, import_contact._import_contact(paras, first_heading_id)
    )

    entry_ids: set[str] = set()
    section_ids: set[str] = set()
    sections: list[Section] = []

    for sec in result.sections:
        body = paras[sec.body_start : sec.body_end]
        section_id = import_common._fresh_id(sec.heading_text, section_ids)
        if sec.key == "experience":
            entries, warns = import_entries._import_experience_entries(body, vocabulary, entry_ids)
            warnings.extend(warns)
            sections.append(
                ExperienceSection(id=section_id, title=sec.heading_text, entries=entries)
            )
        elif sec.key == "projects":
            entries, warns = import_entries._import_project_entries(body, vocabulary, entry_ids)
            warnings.extend(warns)
            sections.append(
                ProjectSection(id=section_id, title=sec.heading_text, entries=entries)
            )
        elif sec.key == "education":
            edu_entries, warns = import_entries._import_education_entries(body)
            warnings.extend(warns)
            sections.append(
                EducationSection(id=section_id, title=sec.heading_text, entries=edu_entries)
            )
        elif sec.key == "skills":
            groups, warns = import_entries._import_skill_groups(body)
            warnings.extend(warns)
            sections.append(
                SkillsSection(id=section_id, title=sec.heading_text, entries=groups)
            )
        elif sec.key == "list":
            list_items = import_entries._import_list_items(body, vocabulary, entry_ids)
            sections.append(
                ListSection(id=section_id, title=sec.heading_text, entries=list_items)
            )

    resume = import_common.normalize_resume_dashes(MasterResume(contact=contact, sections=sections))
    used_tags = sorted(
        {t for b in resume.all_bullets() for t in b.tags if t != import_common.UNTAGGED}
    )
    resume = resume.model_copy(
        update={"tag_vocabulary": import_common.with_skill_terms(resume, used_tags)}
    )

    untagged = sum(1 for b in resume.all_bullets() for t in b.tags if t == import_common.UNTAGGED)
    if untagged:
        warnings.append(
            f"{untagged} bullet(s) could not be matched to a known tag and were "
            f'marked "{import_common.UNTAGGED}" — retag them before saving, or run the optional '
            "tag suggestion pass."
        )

    return import_common.ImportedResume(
        resume=resume, warnings=warnings, untagged_bullet_count=untagged
    )
