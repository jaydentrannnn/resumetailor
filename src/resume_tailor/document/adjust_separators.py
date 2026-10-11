"""Quick adjustments' separators: the rows the panel offers, their current values, and
how each is changed.

Two separators are literal text in the layout file (between contact fields, and between
a project's name and its tools); they are rewritten there, and the read-back picks them
up as it would a Word edit. The rest are written by the renderer, so they change
`TemplateStyle.separators` instead. No LLM.
"""

from __future__ import annotations

from docx.oxml.ns import qn

from . import docx_text, skeleton_tokens
from .skeleton_tokens import TOKEN_RE
from .template_style import Separators, TemplateStyle

#: Panel rows in display order. "literal" rows live in the file, the rest in the style.
ROWS = ("contact", "project_tech", "tech_items", "project_link", "skills_items",
        "coursework", "dates")  # fmt: skip
_LITERAL = ("contact", "project_tech")
#: Characters a literal gap may hold for it to count as a separator (not words).
_GAP_CHARS = set(" |•·–—-,/;:●▪∙~")


def _tokens(paragraph):
    """(start, end, Token) for every known «token» in a paragraph, left to right."""
    found = []
    for match in TOKEN_RE.finditer(docx_text.paragraph_text(paragraph)):
        token = skeleton_tokens.lookup(match.group(1) or match.group(2))
        if isinstance(token, skeleton_tokens.Token):
            found.append((match.start(), match.end(), token))
    return found


def _is_separator(text: str) -> bool:
    return bool(text.strip()) and set(text) <= _GAP_CHARS


def _gaps(doc, row: str) -> list[tuple[object, int, int]]:
    """(paragraph, start, end) of every literal gap `row` names in the layout file."""
    out = []
    for paragraph, _loc in docx_text.iter_document_paragraphs(doc):
        text = docx_text.paragraph_text(paragraph)
        tokens = _tokens(paragraph)
        for (_s, end, left), (start, _e, right) in zip(tokens, tokens[1:]):
            gap = text[end:start]
            if not _is_separator(gap):
                continue
            if row == "contact" and left.kind == right.kind == "contact":
                out.append((paragraph, end, start))
            elif row == "project_tech" and (left.kind, left.field, right.field) == (
                "project", "name", "tech",
            ):
                out.append((paragraph, end, start))
    return out


def _set_gap(paragraph, start: int, end: int, value: str) -> None:
    """Replace text [start, end) with `value`, editing only plain text runs (a run that
    also holds a tab or a drawing is left alone, and with it the whole gap)."""
    slices = [s for s in docx_text.paragraph_run_slices(paragraph)
              if s.end > start and s.start < end]  # fmt: skip
    plain = {qn("w:rPr"), qn("w:t")}
    if not slices or any({child.tag for child in s.element} - plain for s in slices):
        return
    for i, piece in enumerate(slices):
        old = piece.element.findall(qn("w:t"))
        text = "".join(t.text or "" for t in old)
        before = text[: max(0, start - piece.start)]
        after = text[max(0, end - piece.start):]
        new = before + (value if i == 0 else "") + after
        for t in old[1:]:
            piece.element.remove(t)
        old[0].text = new
        old[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def rows(doc) -> set[str]:
    """The rows this template prints."""
    labels = {tok.label for p, _l in docx_text.iter_document_paragraphs(doc)
              for _s, _e, tok in _tokens(p)}  # fmt: skip
    found = {row for row in _LITERAL if _gaps(doc, row)}
    if "Project tools" in labels:
        found.add("tech_items")
    if "Project" in labels:
        found.add("project_link")
    if "Skills" in labels:
        found.add("skills_items")
    if "Education detail" in labels:
        found.add("coursework")
    if "Job dates" in labels:
        found.add("dates")
    return found


def current(doc, style: TemplateStyle, date_separator: str) -> dict[str, str]:
    """Each printed row's current separator."""
    present = rows(doc)
    values: dict[str, str] = {}
    for row in ROWS:
        if row not in present:
            continue
        if row in _LITERAL:
            paragraph, start, end = _gaps(doc, row)[0]
            values[row] = docx_text.paragraph_text(paragraph)[start:end]
        elif row == "dates":
            values[row] = style.separators.dates or date_separator
        else:
            values[row] = getattr(style.separators, row)
    return values


def apply(doc, chosen: dict[str, str]) -> None:
    """Rewrite the literal rows in the layout file."""
    for row in _LITERAL:
        value = chosen.get(row)
        if value is None:
            continue
        # Right to left, so an earlier gap's offsets survive a later one's edit.
        for paragraph, start, end in reversed(_gaps(doc, row)):
            _set_gap(paragraph, start, end, value)


def styled(style: TemplateStyle, chosen: dict[str, str]) -> TemplateStyle:
    """`style` with the renderer-written rows of `chosen` (validated)."""
    update = {row: v for row, v in chosen.items() if row not in _LITERAL and v is not None}
    if not update:
        return style
    merged = Separators.model_validate(style.separators.model_dump() | update)
    return style.model_copy(update={"separators": merged})
