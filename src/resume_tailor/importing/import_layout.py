"""Layout checks and raw line extraction for a .docx whose structure cannot be mapped."""

from __future__ import annotations

import re

from ..content.data import (
    Contact,
)
from ..document import (
    analysis_types,
    docx_text,
    entry_structure,
)
from . import import_common

# --------------------------------------------------------------------------------------
# Page-header contact details and content-only import (P3-D3, P3-D5)
# --------------------------------------------------------------------------------------

#: Analyzer codes for layouts that can't become a template. Their words can still be
#: imported, read in reading order by `import_content_only`.
LAYOUT_BLOCKERS = frozenset(
    {
        "nested_tables",
        "multiple_tables",
        "table_vertical_merge",
        "table_parallel_columns",
        "table_sidebar_bullets",
        "table_sidebar_headings",
        "table_no_headings",
        "textboxes",
    }
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"

def header_contact(doc, contact: Contact) -> Contact:
    """Fill the gaps in `contact` from the page header, where many Word templates put
    the name and contact line. Fields the body already supplied win."""
    text = entry_structure.header_identity_text(doc)
    if not text.strip():
        return contact
    updates: dict[str, str] = {}
    if not contact.email:
        m = analysis_types._EMAIL_RE.search(text)
        if m:
            updates["email"] = m.group(0)
    if not contact.phone:
        m = analysis_types._PHONE_RE.search(text)
        if m and not analysis_types._DATE_RE.search(m.group(0)):
            phone = m.group(0)
            if m.start() > 0 and text[m.start() - 1] == "(":
                phone = "(" + phone
            updates["phone"] = phone
    for key, pattern in (
        ("linkedin", r"(?i)(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%.]+/?"),
        ("github", r"(?i)(?:https?://)?(?:www\.)?github\.com/[\w\-.]+/?"),
    ):
        m = re.search(pattern, text)
        if m and not getattr(contact, key):
            updates[key] = m.group(0)
    if not contact.name.strip():
        for line in text.splitlines():
            stripped = line.strip()
            if (
                stripped
                and "@" not in stripped
                and not re.search(r"\d", stripped)
                and len(stripped.split()) <= 5
            ):
                updates["name"] = stripped
                break
    return contact.model_copy(update=updates) if updates else contact

def _local(el) -> str:
    tag = el.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def _owning_paragraph(el):
    node = el.getparent()
    while node is not None and _local(node) != "p":
        node = node.getparent()
    return node

def _in_fallback(el) -> bool:
    node = el.getparent()
    while node is not None:
        if node.tag == _MC_FALLBACK:
            return True
        node = node.getparent()
    return False

def _box_position(box) -> tuple[int, int]:
    """(horizontal, vertical) offset of a text box's anchor; inline boxes sort first."""
    node = box.getparent()
    while node is not None and node.tag != f"{{{_WP_NS}}}anchor":
        node = node.getparent()
    if node is None:
        return 0, 0

    def offset(axis: str) -> int:
        el = node.find(f"{{{_WP_NS}}}position{axis}/{{{_WP_NS}}}posOffset")
        try:
            return int(el.text) if el is not None and el.text else 0
        except ValueError:
            return 0

    return offset("H"), offset("V")

def docx_lines(doc):
    """Every paragraph's text in reading order, as `pdf_lines.Line`s.

    Unlike `docx_text.iter_document_paragraphs` this also reads text boxes (sorted by
    their anchor position, left column first) and walks layout tables column by column,
    so a sidebar design reads as "sidebar, then main column" instead of interleaved.
    """
    from docx.text.paragraph import Paragraph

    from .pdf_lines import Line

    parent = doc._body
    out: list[Line] = []

    def emit(p_el) -> None:
        paragraph = Paragraph(p_el, parent)
        text = docx_text.paragraph_text(paragraph)
        runs = [r for r in paragraph.runs if (r.text or "").strip()]
        style_font = paragraph.style.font if paragraph.style is not None else None

        def share(attr: str) -> bool:
            """Whether most of the text is bold/italic (a run's own setting, else the
            paragraph style's)."""
            inherited = bool(style_font is not None and getattr(style_font, attr))

            def on(run) -> bool:
                value = getattr(run, attr)
                return inherited if value is None else bool(value)

            chars = sum(len(r.text) for r in runs)
            return bool(chars) and sum(len(r.text) for r in runs if on(r)) * 2 > chars

        size = next((r.font.size.pt for r in runs if r.font.size is not None), None)
        if size is None and style_font is not None and style_font.size is not None:
            size = style_font.size.pt
        indent = paragraph.paragraph_format.left_indent
        x0 = float(indent.pt) if indent is not None else 0.0
        top = float(len(out) * 100)  # never "the next line", so nothing re-joins
        if text.strip():
            out.append(
                Line(
                    text=text,
                    x0=x0,
                    top=top,
                    size=float(size or 11),
                    bold=share("bold"),
                    italic=share("italic"),
                    rel_top=0.5,
                    bullet=analysis_types.is_bullet(paragraph),
                    text_x0=x0,
                    last_top=top,
                )
            )
        boxes = [
            box
            for box in p_el.iter(f"{{{_W_NS}}}txbxContent")
            if _owning_paragraph(box) is p_el and not _in_fallback(box)
        ]
        for box in sorted(boxes, key=_box_position):
            walk(box)

    def table(tbl) -> None:
        rows = [[tc for tc in tr.findall(f"{{{_W_NS}}}tc")] for tr in tbl.findall(f"{{{_W_NS}}}tr")]
        for column in range(max((len(r) for r in rows), default=0)):
            for row in rows:
                if column < len(row):
                    walk(row[column])

    def walk(container) -> None:
        for child in container:
            name = _local(child)
            if name == "p":
                emit(child)
            elif name == "tbl":
                table(child)
            elif name == "sdt":
                content = child.find(f"{{{_W_NS}}}sdtContent")
                if content is not None:
                    walk(content)

    header = entry_structure.header_identity_text(doc)
    for n, text in enumerate(line for line in header.splitlines() if line.strip()):
        out.append(Line(text=text, x0=0.0, top=float(n * 100), size=11.0, rel_top=0.5))
    walk(doc.element.body)
    return out

def import_content_only(doc, *, known_tags: set[str] | None = None) -> import_common.ImportedResume:
    """The words of a document whose layout can't become a template (text boxes, a
    sidebar table): read in reading order and structured like a PDF import."""
    from .pdf_lines import clean_lines
    from .resume_import_pdf import import_lines

    imported = import_lines(clean_lines(docx_lines(doc)), [], known_tags=known_tags)
    imported.warnings.insert(
        0,
        "This layout can't be used as a template, so only its words were imported. "
        "Check the sections below, then pick a template on the Template page.",
    )
    return imported
