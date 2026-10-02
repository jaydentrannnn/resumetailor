"""Profile-mode tagging of the fixed sections: name, contact, experience, education, etc."""

from __future__ import annotations

import copy

from docx.text.paragraph import Paragraph

from . import template_bullets, template_tagging, template_tags, template_xml
from .template_profile import OptionalSpan, TemplateProfile


def build_name_profile(doc, profile: TemplateProfile) -> None:
    """Tag the mapped name paragraph as ``{{ name }}`` (nothing when it is in the page
    header, which is kept as uploaded)."""
    if profile.name_in_header:
        return
    paragraph = template_tagging._para_by_id(doc, profile.name_paragraph_id)
    runs = paragraph.runs
    if not runs:
        raise RuntimeError("Name line has no runs to tag.")
    template_xml.collapse_runs(runs, template_tags.NAME_TAG)

def build_contact_profile(doc, profile: TemplateProfile) -> None:
    """Tag the mapped contact paragraph(s) as RichText placeholder(s).

    A table layout's `contact.slots` spreads the contact block across several
    paragraphs (name in one cell, address in another, email/phone in a third and
    fourth) — each slot gets its own `contact_slot_<i>` tag on its own paragraph,
    instead of collapsing everything onto one joined `{{r contact }}` line, which
    would discard the layout. Empty `slots` (every profile before this existed, and
    any single-paragraph contact block) keeps today's exact one-tag behaviour. A contact
    line in the page header (`contact is None`) is left as uploaded.
    """
    if profile.contact is None:
        return
    if profile.contact.slots:
        for i, slot in enumerate(profile.contact.slots):
            paragraph = template_tagging._para_by_id(doc, slot.paragraph_id)
            template_xml.strip_hyperlinks(paragraph)
            runs = paragraph.runs
            if not runs:
                raise RuntimeError(f"Contact slot {i} has no runs to tag.")
            template_xml.collapse_runs(runs, template_tags.CONTACT_SLOT_TAG_FMT % i)
        return

    paragraph = template_tagging._para_by_id(doc, profile.contact.paragraph_id)
    template_xml.strip_hyperlinks(paragraph)
    runs = paragraph.runs
    if not runs:
        raise RuntimeError("Contact line has no runs to tag.")
    template_xml.collapse_runs(runs, template_tags.CONTACT_TAG)

def _tag_mapped_header(
    doc,
    header_mapping,
    tag_for: dict[str, str],
    *,
    render_owned_separator_before: frozenset[str] = frozenset(),
) -> Paragraph:
    """Replace a header paragraph's mapped spans with tags, preserving runs and tabs.

    Spans are measured against the paragraph's text AS UPLOADED, including any baked-in
    hyperlink — callers must not strip hyperlinks before calling this. `retag_paragraph`
    removes them as a side effect of replacing every run, which is what keeps offsets
    valid (stripping first shortens the text the spans were measured against and slides
    every later span left — this is exactly how a project's date lost its tab stop).
    """
    paragraph = template_tagging._para_by_id(doc, header_mapping.header_paragraph_id)

    items: list[tuple[int, int, str, str]] = []
    for name, field in header_mapping.fields.items():
        if not field.present or field.span is None or name not in tag_for:
            continue
        if field.span.paragraph_id != header_mapping.header_paragraph_id:
            other = template_tagging._para_by_id(doc, field.span.paragraph_id)
            template_tagging.replace_span_with_tag(other, field.span, tag_for[name], field=name)
            continue
        items.append((field.span.start, field.span.end, tag_for[name], name))

    if not items:
        return paragraph

    template_tagging.retag_paragraph(
        paragraph, items, render_owned_separator_before=render_owned_separator_before
    )
    return paragraph

def _tag_experience_prototype(
    doc, mapping, *, noto_num_id: str | None
) -> tuple[Paragraph, Paragraph, Paragraph]:
    """Tag one experience header/title/bullet prototype in place. Pure tagging — no loop
    insertion, no deletion — so both `build_experience_profile` (fixed mode) and
    `build_generic` (generic mode) can wrap the result in whichever loop shape they need.
    Returns `(header, title, bullet)`, still at their original document positions.
    """
    header = _tag_mapped_header(doc, mapping.header, template_tags.EXPERIENCE_HEADER_TAGS)
    if mapping.title.present and mapping.title.span is not None:
        title_para = template_tagging._para_by_id(doc, mapping.title.span.paragraph_id)
        template_tagging.replace_span_with_tag(
            title_para, mapping.title.span, template_tags.EXPERIENCE_TITLE_TAG
        )
    elif mapping.title_paragraph_id is not None:
        title_para = template_tagging._para_by_id(doc, mapping.title_paragraph_id)
        if title_para.runs:
            template_xml.collapse_runs(title_para.runs, template_tags.EXPERIENCE_TITLE_TAG)
    else:
        raise RuntimeError("Experience mapping is missing a job title.")

    title_para = (
        template_tagging._para_by_id(doc, mapping.title.span.paragraph_id)
        if mapping.title.present and mapping.title.span is not None
        else template_tagging._para_by_id(doc, mapping.title_paragraph_id)  # type: ignore[arg-type]
    )
    bullet = template_tagging._para_by_id(doc, mapping.bullet_paragraph_id)
    template_bullets.retarget_bullet(doc, bullet, noto_num_id)
    template_tagging.tag_bullet(bullet, template_tags.BULLET_TAG)
    return header, title_para, bullet

def build_experience_profile(
    doc, profile: TemplateProfile, *, noto_num_id: str | None, other_headings: list[Paragraph]
) -> None:
    """Loop-tag the experience section from the confirmed mapping."""
    mapping = profile.experience
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, other_headings)
    header, title_para, bullet = _tag_experience_prototype(doc, mapping, noto_num_id=noto_num_id)

    # Insert clones before the (still-present) prototype header, then drop originals.
    anchor = header
    anchor._p.addprevious(template_xml.make_para("{%p for job in experience %}"))
    anchor._p.addprevious(copy.deepcopy(header._p))
    anchor._p.addprevious(copy.deepcopy(title_para._p))
    anchor._p.addprevious(template_xml.make_para("{%p for bullet in job.bullets %}"))
    anchor._p.addprevious(copy.deepcopy(bullet._p))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))

    _delete_paragraphs(victims)

def _tag_education_prototype(
    doc, mapping, *, noto_num_id: str | None
) -> tuple[Paragraph, Paragraph, Paragraph]:
    """Tag one education header/degree/detail prototype in place. Pure tagging, same
    split as `_tag_experience_prototype`. Returns `(header, degree, detail)`."""
    header = _tag_mapped_header(doc, mapping.header, template_tags.EDUCATION_HEADER_TAGS)
    degree = template_tagging._para_by_id(doc, mapping.degree_paragraph_id)
    template_bullets.retarget_bullet(doc, degree, noto_num_id)
    template_tagging.tag_bullet(degree, template_tags.EDUCATION_DEGREE_TAG)

    if mapping.detail_paragraph_id is not None:
        detail = template_tagging._para_by_id(doc, mapping.detail_paragraph_id)
        if detail._p is degree._p:
            detail_p = copy.deepcopy(degree._p)
            degree._p.addnext(detail_p)
            detail = Paragraph(detail_p, degree._parent)
            template_tagging.tag_bullet(detail, template_tags.EDUCATION_DETAIL_TAG)
        else:
            template_bullets.retarget_bullet(doc, detail, noto_num_id)
            template_tagging.tag_bullet(detail, template_tags.EDUCATION_DETAIL_TAG)
    else:
        detail_p = copy.deepcopy(degree._p)
        degree._p.addnext(detail_p)
        detail = Paragraph(detail_p, degree._parent)
        template_tagging.tag_bullet(detail, template_tags.EDUCATION_DETAIL_TAG)
    return header, degree, detail

def build_education_profile(
    doc, profile: TemplateProfile, *, noto_num_id: str | None, other_headings: list[Paragraph]
) -> None:
    """Loop-tag the education section from the confirmed mapping."""
    mapping = profile.education
    assert mapping is not None
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, other_headings)
    header, degree, detail = _tag_education_prototype(doc, mapping, noto_num_id=noto_num_id)

    anchor = header
    anchor._p.addprevious(template_xml.make_para("{%p for edu in education %}"))
    anchor._p.addprevious(copy.deepcopy(header._p))
    anchor._p.addprevious(copy.deepcopy(degree._p))
    anchor._p.addprevious(template_xml.make_para("{%p for detail in edu.details %}"))
    anchor._p.addprevious(copy.deepcopy(detail._p))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))

    _delete_paragraphs(victims)
    if detail._p.getparent() is not None and detail not in victims:
        # Drop a temporary degree clone that was inserted beside the source bullet.
        template_xml.delete(detail)

def _tag_project_prototype(doc, mapping, *, noto_num_id: str | None) -> tuple[Paragraph, Paragraph]:
    """Tag one project header/bullet prototype in place. Pure tagging, same split as
    `_tag_experience_prototype`. Returns `(header, bullet)`."""
    tag_for = dict(template_tags.PROJECT_HEADER_TAGS)
    fields = dict(mapping.header.fields)
    if mapping.link.present and mapping.link.span is not None:
        fields["link"] = OptionalSpan(present=True, span=mapping.link.span)
        tag_for["link"] = template_tags.PROJECT_LINK_TAG
    header_mapping = mapping.header.model_copy(update={"fields": fields})
    # The baked-in hyperlink, if any, is removed by `_tag_mapped_header`'s rebuild — not
    # stripped here first. `mapping.link.span` was measured against the paragraph WITH
    # the hyperlink still present; stripping it first would shorten the text and shift
    # every later offset left, which used to swallow the date's tab into the link tag.
    # `render_owned_separator_before` drops the literal " | " before the link tag,
    # because `render.py` supplies that separator itself, only when a link is present.
    header_para = _tag_mapped_header(
        doc, header_mapping, tag_for, render_owned_separator_before=frozenset({"link"})
    )

    bullet = template_tagging._para_by_id(doc, mapping.bullet_paragraph_id)
    template_bullets.retarget_bullet(doc, bullet, noto_num_id)
    template_tagging.tag_bullet(bullet, template_tags.PROJECT_BULLET_TAG)
    return header_para, bullet

def build_projects_profile(
    doc, profile: TemplateProfile, *, noto_num_id: str | None, other_headings: list[Paragraph]
) -> None:
    """Loop-tag the projects section from the confirmed mapping."""
    mapping = profile.projects
    assert mapping is not None
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, other_headings)
    header_para, bullet = _tag_project_prototype(doc, mapping, noto_num_id=noto_num_id)

    anchor = header_para
    anchor._p.addprevious(template_xml.make_para("{%p for proj in projects %}"))
    anchor._p.addprevious(copy.deepcopy(header_para._p))
    anchor._p.addprevious(template_xml.make_para("{%p for bullet in proj.bullets %}"))
    anchor._p.addprevious(copy.deepcopy(bullet._p))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))

    _delete_paragraphs(victims)

def _tag_skills_prototype(doc, mapping) -> tuple[Paragraph, Paragraph]:
    """Tag one skills label/entries prototype in place. Pure tagging. Returns
    `(label_paragraph, body_paragraph)` — the same paragraph twice when both spans
    share one paragraph (paragraph layout, today's exact behaviour), two different
    paragraphs when a table layout puts the label and its value in different cells
    (see `field_candidates._skills_pair_across_cells`) — mirrors how
    `_tag_mapped_header` already handles a cross-paragraph header field.
    """
    if mapping.label_span.paragraph_id == mapping.body_span.paragraph_id:
        prototype = template_tagging._para_by_id(doc, mapping.label_span.paragraph_id)
        # A separate run per tag — rather than collapsing the whole line into one, as
        # the prior implementation did — is what keeps the label's bold and the
        # entries' plain formatting from the upload. Same tradeoff legacy
        # `build_skills` documents.
        items = sorted(
            [
                (
                    mapping.label_span.start,
                    mapping.label_span.end,
                    template_tags.SKILLS_LABEL_TAG,
                    "skills_label",
                ),
                (
                    mapping.body_span.start,
                    mapping.body_span.end,
                    template_tags.SKILLS_BODY_TAG,
                    "skills_body",
                ),
            ],
            key=lambda it: it[0],
        )
        template_tagging.retag_paragraph(prototype, items)
        template_bullets.shrink_bullet_marker(doc, prototype)
        return prototype, prototype

    label_para = template_tagging._para_by_id(doc, mapping.label_span.paragraph_id)
    body_para = template_tagging._para_by_id(doc, mapping.body_span.paragraph_id)
    template_tagging.replace_span_with_tag(
        label_para, mapping.label_span, template_tags.SKILLS_LABEL_TAG, field="skills_label"
    )
    template_tagging.replace_span_with_tag(
        body_para, mapping.body_span, template_tags.SKILLS_BODY_TAG, field="skills_body"
    )
    template_bullets.shrink_bullet_marker(doc, label_para)
    return label_para, body_para

def build_skills_profile(
    doc, profile: TemplateProfile, *, other_headings: list[Paragraph]
) -> None:
    """Loop-tag the skills section from the confirmed mapping."""
    mapping = profile.skills
    assert mapping is not None
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, other_headings)
    # Fixed mode is paragraph-layout only (a table layout always forces generic mode —
    # see `TemplateProfile.layout`), so label and body always share one paragraph here.
    prototype, _body_para = _tag_skills_prototype(doc, mapping)

    anchor = prototype
    anchor._p.addprevious(template_xml.make_para("{%p for group in skills %}"))
    anchor._p.addprevious(copy.deepcopy(prototype._p))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))

    _delete_paragraphs(victims)

def _tag_list_prototype(doc, mapping, *, noto_num_id: str | None) -> Paragraph:
    """Tag one plain-list bullet prototype in place. The simplest of the five kinds — no
    header, no entry structure, just a bullet loop. Returns the tagged bullet paragraph."""
    bullet = template_tagging._para_by_id(doc, mapping.bullet_paragraph_id)
    template_bullets.retarget_bullet(doc, bullet, noto_num_id)
    template_tagging.tag_bullet(bullet, template_tags.LIST_ITEM_TAG)
    return bullet

def _section_body_paragraphs(
    doc, heading_id: int, other_headings: list[Paragraph]
) -> list[Paragraph]:
    """Return current body paragraphs of a section (after heading, before next heading).

    Stops at the first *paragraph object* in `other_headings` — every other enabled
    kind's own heading, resolved by the caller once via `_para_by_id` before any
    section's body is touched, so the reference stays valid regardless of what gets
    inserted or deleted elsewhere in the document afterward (headings themselves are
    never moved or deleted mid-build; only the space between them is).

    Identity, not text: comparing walked-paragraph *text* against other headings' text
    (the previous approach) means an ordinary entry line that happens to read exactly
    "SKILLS" or "PROJECTS" — a bolded label inside a bullet, for instance — is
    indistinguishable from the real heading and silently truncates the body early.
    """
    heading = template_tagging._para_by_id(doc, heading_id)
    other_elements = {p._p for p in other_headings}

    seen_heading = False
    body: list[Paragraph] = []
    for para in list(doc.paragraphs):
        if para._p is heading._p:
            seen_heading = True
            continue
        if not seen_heading:
            continue
        if para._p in other_elements:
            break
        body.append(para)
    return body

def _delete_paragraphs(paragraphs: list[Paragraph]) -> None:
    """Delete the given paragraph objects from the document."""
    for para in paragraphs:
        if para._p.getparent() is not None:
            template_xml.delete(para)
