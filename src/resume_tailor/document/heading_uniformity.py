"""Which section headings a generic-mode build will not reproduce exactly.

Generic mode renders every section heading from one donor paragraph
(`TemplateProfile.heading_prototype`). A heading whose own paragraph or text formatting
differs from the donor's therefore changes appearance in the tailored output; this module
names each such heading so the difference is a visible warning rather than a surprise.
Read-only, no LLM.
"""

from __future__ import annotations

import copy

from docx.oxml.ns import qn
from lxml import etree

from . import analysis_types, template_tagging


def _normalized(element) -> bytes:
    """`element` serialised without what differs between identically-rendered paragraphs:
    revision-tracking ids, the paragraph's numbering and paragraph-mark run properties,
    and explicit "off" toggles (`<w:pageBreakBefore w:val="0"/>` renders like no toggle)."""
    if element is None:
        return b""
    clone = copy.deepcopy(element)
    for node in clone.iter():
        for attr in [a for a in node.attrib if a.startswith(qn("w:rsid"))]:
            del node.attrib[attr]
    for tag in ("w:numPr", "w:rPr"):
        for node in clone.findall(qn(tag)):
            clone.remove(node)
    for node in list(clone):
        if node.get(qn("w:val")) in ("0", "false") and len(node) == 0 and len(node.attrib) == 1:
            clone.remove(node)
    return etree.tostring(clone, method="c14n")


def _signature(paragraph) -> tuple[bytes, bytes]:
    """(paragraph properties, first run's properties) — what a heading looks like."""
    runs = paragraph.runs
    r_pr = runs[0]._r.rPr if runs else None
    return _normalized(paragraph._p.pPr), _normalized(r_pr)


def heading_differences(
    doc, prototype_id: int, candidates: list[analysis_types.SectionCandidate]
) -> list[str]:
    """One warning per section heading whose formatting differs from paragraph
    `prototype_id`'s, in document order."""
    donor = template_tagging._para_by_id(doc, prototype_id)
    donor_text = donor.text.strip()
    donor_p, donor_r = _signature(donor)
    messages: list[str] = []
    for cand in candidates:
        if cand.heading_paragraph_id == prototype_id:
            continue
        p_sig, r_sig = _signature(template_tagging._para_by_id(doc, cand.heading_paragraph_id))
        parts = []
        if p_sig != donor_p:
            parts.append("paragraph formatting (spacing, borders, alignment)")
        if r_sig != donor_r:
            parts.append("text formatting (font, size, weight)")
        if parts:
            messages.append(
                f"Heading {cand.heading_text!r} has different {' and '.join(parts)} than "
                f"{donor_text!r}; with movable sections it takes {donor_text!r}'s formatting."
            )
    return messages
