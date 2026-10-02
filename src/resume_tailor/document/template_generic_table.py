"""Profile-mode tagging of generic sections laid out as table rows."""

from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from . import (
    template_bullets,
    template_generic,
    template_profile_build,
    template_tagging,
    template_tags,
    template_xml,
)
from .template_profile import TemplateProfile

_TR_TAG = qn("w:tr")

_TC_TAG = qn("w:tc")

def _row_of(paragraph: Paragraph):
    """The `<w:tr>` ancestor of `paragraph`, or `None` when it is body-level (not
    inside any table)."""
    el = paragraph._p.getparent()
    while el is not None and el.tag != _TR_TAG:
        el = el.getparent()
    return el

def _marker_row(text: str, grid_cols: int):
    """A disposable one-cell row carrying a `{%tr ... %}` row-level control tag.

    docxtpl's row pass (`DocxTemplate.patch_xml`, run for `y in ["tr","tc","p","r"]` —
    `tr` FIRST) replaces the ENTIRE `<w:tr>` containing a `{%tr %}` tag with the bare
    Jinja tag: the row is *consumed*, not repeated. Every row-level control tag
    therefore needs its own throwaway row — putting the tag inside a content row would
    delete that row's content along with it — and the rows meant to repeat sit between
    an open marker row and a matching close marker row.

    Must still be schema-valid OOXML on its own, since a user can open the tagged
    template in Word before it is ever rendered: at least one `<w:tc>`, with at least
    one `<w:p>`, spanning the table's declared column count so the grid isn't torn.
    """
    tr = OxmlElement("w:tr")
    tc = OxmlElement("w:tc")
    tcPr = OxmlElement("w:tcPr")
    grid_span = OxmlElement("w:gridSpan")
    grid_span.set(qn("w:val"), str(max(grid_cols, 1)))
    tcPr.append(grid_span)
    tc.append(tcPr)
    tc.append(template_xml.make_para(text))
    tr.append(tc)
    return tr

def _wrap_cell_loop(paragraph: Paragraph, open_tag: str, close_tag: str = "{%p endfor %}") -> None:
    """Put a `{%p for %}` / `{%p endfor %}` pair around `paragraph`, inside its own
    cell, and remove every paragraph AFTER it within that same cell.

    A table cell commonly stacks several repeatable items as separate paragraphs
    (three bullets, three skill groups' labels), and only the *first* of them becomes
    the loop's tagged prototype — `template_analyze`'s own convention:
    `bullet_paragraph_id` / `detail_paragraph_id` / a skills `label_span.paragraph_id`
    always name the first paragraph of its kind in the entry. Left untouched, a later
    sibling would be duplicated verbatim into every rendered entry, since the whole
    ROW gets cloned once as the loop's per-iteration template
    (`build_generic_table`) — never a problem in a paragraph layout, where each bullet
    is an independent body-level paragraph the surrounding victim-deletion sweeps up
    regardless of this function.

    Never removes a paragraph BEFORE `paragraph` in the same cell — that is fixed
    content (a school/degree line the education fallback's synthetic single-paragraph
    detail clone sits *after*), not a repeatable sibling, and must survive untouched.
    """
    open_el = template_xml.make_para(open_tag)
    close_el = template_xml.make_para(close_tag)
    paragraph._p.addprevious(open_el)
    paragraph._p.addnext(close_el)

    tc = paragraph._p.getparent()
    while tc is not None and tc.tag != _TC_TAG:
        tc = tc.getparent()
    if tc is None:
        return
    siblings = tc.findall(template_tags.W)
    idx = siblings.index(close_el)
    for extra in siblings[idx + 1 :]:
        tc.remove(extra)

def _section_body_rows(doc, heading_para: Paragraph, other_heading_paras: list[Paragraph]) -> list:
    """Rows after `heading_para`'s own row, up to (excluding) the next heading's row —
    the row-level analogue of `_section_body_paragraphs`, and for the same reason:
    matched by `<w:tr>` object identity, never by re-deriving an index or matching
    heading text, so an ordinary entry row is never mistaken for a heading row just
    because some paragraph inside it happens to equal another heading's text.
    """
    heading_row = _row_of(heading_para)
    if heading_row is None:
        raise RuntimeError(f"Heading paragraph {heading_para.text!r} is not inside a table row.")
    other_rows = {_row_of(p) for p in other_heading_paras}
    table_el = heading_row.getparent()
    rows = table_el.findall(_TR_TAG)
    start = rows.index(heading_row) + 1
    body: list = []
    for tr in rows[start:]:
        if tr in other_rows:
            break
        body.append(tr)
    return body

def _unique_rows(rows: list) -> list:
    """Consecutive-duplicate-collapsed `rows`, preserving order.

    A table layout often puts a header field and the paragraph right after it (a
    degree line, a synthesized single-paragraph detail) in the very same physical
    row — cloning that row twice would duplicate its content, rather than merging
    naturally the way sibling paragraphs within one cell already do once the row
    itself is cloned once.
    """
    out: list = []
    for r in rows:
        if r is None or (out and out[-1] is r):
            continue
        out.append(r)
    return out

def build_generic_table(doc, profile: TemplateProfile) -> None:
    """Table-layout counterpart of `build_generic`: one shared block whose repeating
    unit is table ROWS, not paragraphs — a table used purely as an invisible
    single-column layout grid (see `TemplateProfile.layout`). Reuses the exact same
    per-kind `_tag_*_prototype` functions `build_generic` does (pure tagging, no loop
    insertion or deletion — see their own docstrings) since a table layout tags the
    same character spans; what differs is that a `{%p for/if %}` construct cannot
    repeat a table ROW, so `{%tr %}` marker rows wrap whichever rows an entry spans,
    and bullet/detail loops live inside a cell as `{%p for %}` while entry/skills-group
    repetition happens at the row level via `{%tr for %}`.

    `layout="table"` always implies `section_mode="generic"` (see that field's
    docstring), so `build_from_profile` calls this instead of `build_generic` — never
    both.
    """
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

    # Same bottom-up (later headings first) processing order `build_generic` uses, for
    # the same reason: `_tag_education_prototype` can insert a paragraph mid-build,
    # which must never invalidate an already-resolved heading id for a kind still
    # pending. Row insertion (below) happens only after every kind is fully tagged, so
    # that hazard never compounds with a second one.
    processing_order = sorted(
        (
            (mappings[kind].heading_paragraph_id, kind)
            for kind in template_generic._GENERIC_KIND_ORDER
            if mappings[kind] is not None and enabled[kind]
        ),
        reverse=True,
    )
    all_headings = {hid: template_tagging._para_by_id(doc, hid) for hid, _kind in processing_order}

    all_victim_rows: list = []
    heading_rows: list = []
    heading_ids: list[int] = []
    branches: dict[str, list] = {}  # kind -> ordered list of (row element | control-tag string)

    for _heading_id, kind in processing_order:
        mapping = mappings[kind]
        heading_para = template_tagging._para_by_id(doc, mapping.heading_paragraph_id)
        other_headings = [
            p for h, p in all_headings.items() if h != mapping.heading_paragraph_id
        ]
        all_victim_rows.extend(_section_body_rows(doc, heading_para, other_headings))
        heading_rows.append(_row_of(heading_para))
        heading_ids.append(mapping.heading_paragraph_id)

        if kind == "experience":
            header, _title_para, bullet = template_profile_build._tag_experience_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            header_row, bullet_row = _row_of(header), _row_of(bullet)
            if header_row is None or bullet_row is None:
                raise RuntimeError("Table-layout experience prototype must live inside table rows.")
            _wrap_cell_loop(bullet, "{%p for bullet in job.bullets %}")
            rows = _unique_rows([header_row, bullet_row])
            body: list = ["{%tr for job in section.entries %}", rows[0]]
            if len(rows) > 1:
                body += ["{%tr if job.bullets %}", rows[1], "{%tr endif %}"]
            body.append("{%tr endfor %}")
            branches[kind] = body
        elif kind == "project":
            header, bullet = template_profile_build._tag_project_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            header_row, bullet_row = _row_of(header), _row_of(bullet)
            if header_row is None or bullet_row is None:
                raise RuntimeError("Table-layout project prototype must live inside table rows.")
            _wrap_cell_loop(bullet, "{%p for bullet in proj.bullets %}")
            rows = _unique_rows([header_row, bullet_row])
            body = ["{%tr for proj in section.entries %}", rows[0]]
            if len(rows) > 1:
                body += ["{%tr if proj.bullets %}", rows[1], "{%tr endif %}"]
            body.append("{%tr endfor %}")
            branches[kind] = body
        elif kind == "list":
            bullet = template_profile_build._tag_list_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            bullet_row = _row_of(bullet)
            if bullet_row is None:
                raise RuntimeError("Table-layout list prototype must live inside a table row.")
            _wrap_cell_loop(bullet, "{%p for item in section.entries %}")
            branches[kind] = ["{%tr for item in section.entries %}", bullet_row, "{%tr endfor %}"]
        elif kind == "education":
            header, degree, detail = template_profile_build._tag_education_prototype(
                doc, mapping, noto_num_id=noto_num_id
            )
            header_row, degree_row, detail_row = _row_of(header), _row_of(degree), _row_of(detail)
            if header_row is None:
                raise RuntimeError("Table-layout education prototype must live inside table rows.")
            _wrap_cell_loop(detail, "{%p for detail in edu.details %}")
            rows = _unique_rows([header_row, degree_row, detail_row])
            body = ["{%tr for edu in section.entries %}", rows[0]]
            body.extend(rows[1:-1] if len(rows) > 2 else [])
            if len(rows) > 1:
                body += ["{%tr if edu.details %}", rows[-1], "{%tr endif %}"]
            body.append("{%tr endfor %}")
            branches[kind] = body
            # `_tag_education_prototype`'s degree/detail-share-one-paragraph fallback
            # clones `degree` in place (`addnext`) when there is no separate detail
            # bullet — unlike `build_generic`'s paragraph-level cloning, that synthetic
            # clone is already inside whichever row got captured above (it shares
            # `degree`'s own cell), so deleting the victim rows below removes it too.
            # No separate cleanup needed here.
        elif kind == "skills":
            label_para, body_para = template_profile_build._tag_skills_prototype(doc, mapping)
            label_row, body_row = _row_of(label_para), _row_of(body_para)
            if label_row is None:
                raise RuntimeError("Table-layout skills prototype must live inside a table row.")
            _wrap_cell_loop(label_para, "{%p for group in section.entries %}")
            if body_para._p is not label_para._p:
                _wrap_cell_loop(body_para, "{%p for group in section.entries %}")
            rows = _unique_rows([label_row, body_row])
            # This row's cells hold ONLY the loop (a label cell, a value cell) — an
            # empty `section.entries` would otherwise leave both with zero `<w:p>`,
            # invalid OOXML. Removing the whole row instead is both valid and visually
            # correct: no skills, no row.
            branches[kind] = ["{%tr if section.entries %}", *rows, "{%tr endif %}"]

    if not branches:
        raise RuntimeError("Generic table template build found no enabled sections to tag.")

    table_el = heading_rows[0].getparent()
    grid_cols = len(table_el.find(qn("w:tblGrid")).findall(qn("w:gridCol"))) or 1

    anchor_row = _row_of(template_tagging._para_by_id(doc, min(heading_ids)))
    if anchor_row is None:
        raise RuntimeError("Table-layout section heading is not inside a table row.")

    heading_source = template_tagging._para_by_id(doc, profile.heading_prototype.paragraph_id)
    heading_row_source = _row_of(heading_source)
    if heading_row_source is None:
        raise RuntimeError("Table-layout heading prototype must live inside a table row.")
    heading_row_clone = copy.deepcopy(heading_row_source)
    # Tag the first non-blank paragraph in the cloned row as {{ section.title }};
    # blank any OTHER paragraph's text WITHOUT removing it — a <w:tc> must never end up
    # with zero <w:p>.
    heading_tagged = False
    for tc in heading_row_clone.findall(_TC_TAG):
        for p_el in tc.findall(template_tags.W):
            p_obj = Paragraph(p_el, heading_source._parent)
            if not (p_obj.text or "").strip():
                continue
            if not heading_tagged:
                runs = p_obj.runs
                if runs:
                    template_xml.collapse_runs(runs, template_tags.SECTION_TITLE_TAG)
                heading_tagged = True
            else:
                for run in list(p_obj.runs):
                    template_xml._drop_run(run)
    if not heading_tagged:
        raise RuntimeError("Heading prototype row has no text to tag.")

    insertions: list = [
        _marker_row(template_tags.SECTION_LOOP_OPEN_TR, grid_cols),
        heading_row_clone,
    ]
    for kind in template_generic._GENERIC_KIND_ORDER:
        body = branches.get(kind)
        if body is None:
            continue
        insertions.append(_marker_row(f"{{%tr if section.kind == '{kind}' %}}", grid_cols))
        for item in body:
            insertions.append(
                _marker_row(item, grid_cols) if isinstance(item, str) else copy.deepcopy(item)
            )
        insertions.append(_marker_row("{%tr endif %}", grid_cols))
    insertions.append(_marker_row("{%tr endfor %}", grid_cols))

    for element in insertions:
        anchor_row.addprevious(element)

    for tr in all_victim_rows:
        if tr.getparent() is not None:
            tr.getparent().remove(tr)
    for tr in heading_rows:
        if tr.getparent() is not None:
            tr.getparent().remove(tr)
