"""Profile-mode tagging of generic (user-named) sections laid out as paragraphs."""

from __future__ import annotations

import copy

from docx.text.paragraph import Paragraph

from . import (
    docx_text,
    template_bullets,
    template_profile_build,
    template_tagging,
    template_tags,
    template_xml,
)
from .template_profile import TemplateProfile

#: Order the generic block's `{%p if section.kind == '...' %}` branches are emitted in.
#: Rendering order does not depend on this (each branch fires only for its own kind), but
#: a fixed order keeps the generated XML deterministic and readable.
_GENERIC_KIND_ORDER = ("experience", "project", "list", "education", "skills")

#: Entry-shaped kinds a `between_entries` spacer applies to — skills groups and list
#: items are consecutive bullet lines with no blank between them in any observed source.
_ENTRY_SHAPED_KINDS = ("experience", "project", "education")

def _spacer_donors(doc, paragraph_ids: list[int]) -> list:
    """Resolve a spacing donor *run* up front, before any tagging that could shift
    paragraph indices — same hazard `build_generic`'s descending processing order exists
    to dodge, sidestepped entirely by cloning while indices are still pristine.

    Returns the donors' deep-copied `<w:p>` elements in order. Any id that is out of
    range or no longer chrome drops out, and an empty result means "no spacer here" —
    degrading rather than failing the build, matching
    `template_analyze.validate_profile_against_doc`'s non-blocking `spacer_donor_missing`.
    """
    donors = []
    for paragraph_id in paragraph_ids:
        try:
            para = template_tagging._para_by_id(doc, paragraph_id)
        except RuntimeError:
            continue
        if not docx_text.is_chrome_text(para.text):
            continue
        donors.append(copy.deepcopy(para._p))
    return donors

def _spacer_clones(donors: list) -> list:
    """Fresh copies of a resolved spacer run for one insertion point. Each physical spot
    in the tagged template needs its own elements — docxtpl's `{%p for %}` repeats
    paragraphs that appear once in the template, so this is called once per *position*
    (before-heading, after-heading, one per entry-shaped branch), never once per entry."""
    return [copy.deepcopy(el) for el in donors]

def build_generic(doc, profile: TemplateProfile) -> None:
    """Tag `doc` for `section_mode="generic"`: one shared block driven by the `sections`
    render-context key, so adding, renaming, or reordering a resume section never needs a
    template rebuild — see `data.MasterResume.sections` and `render.build_context`.

    Each enabled kind's prototype is tagged exactly the way `build_from_profile`'s
    per-kind builders already do (same helpers, same tag strings, same loop-variable
    names — `job`/`proj`/`edu`/`group`/`bullet`/`detail`, plus `item` for the new `list`
    kind), so a resume with exactly today's four sections renders identically to a
    fixed-mode build. What differs is the outer shape: one `{%p for section in sections %}`
    loop wraps a cloned, `{{ section.title }}`-tagged heading and one `{%p if
    section.kind == '<kind>' %}` branch per enabled kind, each with its own `{%p for
    <var> in section.entries %}` loop — so any number of sections of any kind, in any
    order, under any title, all render from the same tagged template.

    Deliberately independent `{%p if %}` blocks rather than an `elif` ladder: each kind's
    branch is then a self-contained unit that can be entirely omitted when that kind has
    no prototype, with no ladder ordering or dangling-`elif` bookkeeping to get right.
    """
    # Resolve spacer donors first, before any tagging — `_tag_education_prototype` can
    # insert a paragraph mid-build (see the descending-order comment below), which would
    # invalidate a donor id resolved afterward.
    before_heading_donors = _spacer_donors(doc, profile.spacing.before_heading)
    after_heading_donors = _spacer_donors(doc, profile.spacing.after_heading)
    between_entries_donors = _spacer_donors(doc, profile.spacing.between_entries)

    noto_num_id = (
        template_bullets.discover_noto_num_id(doc)
        if profile.normalization.normalize_bullet_font
        else None
    )

    template_profile_build.build_name_profile(doc, profile)
    template_profile_build.build_contact_profile(doc, profile)

    mappings = {
        "experience": profile.experience,
        "project": profile.projects,
        "list": profile.list_section,
        "education": profile.education,
        "skills": profile.skills,
    }
    enabled = {
        "experience": profile.enabled.experience,
        "project": profile.enabled.projects,
        "list": profile.enabled.list_section,
        "education": profile.enabled.education,
        "skills": profile.enabled.skills,
    }

    all_victims: list[Paragraph] = []
    heading_paragraphs: list[Paragraph] = []
    heading_ids: list[int] = []
    # kind -> ordered list of (paragraph-to-clone | literal control-tag string)
    branches: dict[str, list[Paragraph | str]] = {}

    # Process bottom-up (later headings first), same reasoning as `build_from_profile`'s
    # fixed-mode dispatch: `_tag_education_prototype` can INSERT a paragraph (cloning the
    # degree line when degree and detail share one paragraph — the common case for a
    # single-line education entry), which shifts every later paragraph's index. Tagging
    # a lower (later-in-document) kind first means that insertion can only affect
    # positions below kinds not yet processed, never above them, so an
    # already-resolved `heading_paragraph_id` for a still-pending kind never goes stale.
    processing_order = sorted(
        (
            (mappings[kind].heading_paragraph_id, kind)
            for kind in _GENERIC_KIND_ORDER
            if mappings[kind] is not None and enabled[kind]
        ),
        reverse=True,
    )

    # Resolve every enabled kind's heading paragraph *object* once, up front, before
    # any section's body is touched — same reasoning as `build_from_profile`'s
    # fixed-mode dispatch: `_section_body_paragraphs` stops on object identity, which
    # stays valid across the whole build, rather than re-deriving an index (which an
    # earlier insertion could shift) or matching heading text (which an ordinary entry
    # line could coincidentally equal).
    all_headings = {hid: template_tagging._para_by_id(doc, hid) for hid, _kind in processing_order}

    for _heading_id, kind in processing_order:
        mapping = mappings[kind]
        other_headings = [
            p for h, p in all_headings.items() if h != mapping.heading_paragraph_id
        ]
        all_victims.extend(
            template_profile_build._section_body_paragraphs(
                doc, mapping.heading_paragraph_id, other_headings
            )
        )
        heading_paragraphs.append(template_tagging._para_by_id(doc, mapping.heading_paragraph_id))
        heading_ids.append(mapping.heading_paragraph_id)

        if kind == "experience":
            header, title_para, bullet = template_profile_build._tag_experience_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            branches[kind] = [
                "{%p for job in section.entries %}",
                header,
                title_para,
                "{%p for bullet in job.bullets %}",
                bullet,
                "{%p endfor %}",
                "{%p endfor %}",
            ]
        elif kind == "project":
            header, bullet = template_profile_build._tag_project_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            branches[kind] = [
                "{%p for proj in section.entries %}",
                header,
                "{%p for bullet in proj.bullets %}",
                bullet,
                "{%p endfor %}",
                "{%p endfor %}",
            ]
        elif kind == "list":
            bullet = template_profile_build._tag_list_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            branches[kind] = ["{%p for item in section.entries %}", bullet, "{%p endfor %}"]
        elif kind == "education":
            header, degree, detail = template_profile_build._tag_education_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            branches[kind] = [
                "{%p for edu in section.entries %}",
                header,
                degree,
                "{%p for detail in edu.details %}",
                detail,
                "{%p endfor %}",
                "{%p endfor %}",
            ]
            # `_tag_education_prototype` clones the degree paragraph in place
            # (`addnext`) when degree/detail share one paragraph — the common
            # single-line-entry case. `branches[kind]` above already captured its own
            # independent copy for insertion, so the clone left sitting at its original
            # document position is now a duplicate; `_section_body_paragraphs` was
            # called (into `all_victims`) before this clone existed, so nothing else
            # will ever delete it. Same cleanup `build_education_profile` (fixed mode)
            # already does after its own call to this same tagging helper.
            if detail._p.getparent() is not None and detail not in all_victims:
                template_xml.delete(detail)
        elif kind == "skills":
            group, _body_para = template_profile_build._tag_skills_prototype(doc, mapping)
            branches[kind] = ["{%p for group in section.entries %}", group, "{%p endfor %}"]

    if not branches:
        raise RuntimeError("Generic template build found no enabled sections to tag.")

    # Anchor the whole block at the topmost enabled heading; every other enabled heading
    # is deleted too (folded into `all_victims` below), since one shared block now covers
    # all of them. Compared by `heading_paragraph_id`, not `doc.paragraphs.index(...)` —
    # `Paragraph.__eq__` is identity, and `doc.paragraphs` builds fresh wrapper objects on
    # every access, so no paragraph fetched earlier is ever found in a freshly-built list.
    anchor = template_tagging._para_by_id(doc, min(heading_ids))

    heading_source = template_tagging._para_by_id(doc, profile.heading_prototype.paragraph_id)
    heading_clone_el = copy.deepcopy(heading_source._p)
    heading_clone = Paragraph(heading_clone_el, heading_source._parent)
    heading_runs = heading_clone.runs
    if not heading_runs:
        raise RuntimeError("Heading prototype paragraph has no runs to tag.")
    template_xml.collapse_runs(heading_runs, template_tags.SECTION_TITLE_TAG)

    insertions: list = [template_xml.make_para(template_tags.SECTION_LOOP_OPEN)]
    if before_heading_donors:
        # `loop` here is the outer `for section in sections` loop — the only one open at
        # this point in the document — so `loop.first` means "first section", which is
        # what makes the gap precede every heading except the very first.
        insertions.append(template_xml.make_para("{%p if not loop.first %}"))
        insertions.extend(_spacer_clones(before_heading_donors))
        insertions.append(template_xml.make_para("{%p endif %}"))
    insertions.append(heading_clone_el)
    insertions.extend(_spacer_clones(after_heading_donors))
    for kind in _GENERIC_KIND_ORDER:
        body = branches.get(kind)
        if body is None:
            continue
        insertions.append(template_xml.make_para(f"{{%p if section.kind == '{kind}' %}}"))
        for idx, item in enumerate(body):
            insertions.append(
                template_xml.make_para(item) if isinstance(item, str) else copy.deepcopy(item._p)
            )
            # `item` at index 0 of an entry-shaped branch is always its opening
            # `{%p for <var> in section.entries %}` tag (see the per-kind blocks above).
            # Inserting the spacer right after it, guarded on `loop.first` of that
            # now-innermost loop, means "first entry" — skipping the gap before the
            # first entry and placing it only between entries.
            if idx == 0 and between_entries_donors and kind in _ENTRY_SHAPED_KINDS:
                insertions.append(template_xml.make_para("{%p if not loop.first %}"))
                insertions.extend(_spacer_clones(between_entries_donors))
                insertions.append(template_xml.make_para("{%p endif %}"))
        insertions.append(template_xml.make_para("{%p endif %}"))
    insertions.append(template_xml.make_para("{%p endfor %}"))

    for element in insertions:
        anchor._p.addprevious(element)

    template_profile_build._delete_paragraphs(all_victims)
    for heading in heading_paragraphs:
        template_xml.delete(heading)
