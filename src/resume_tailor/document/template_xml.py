"""Paragraph and run primitives for template building: create, delete, restyle, respace."""

from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from . import docx_text, template_bullets


# --------------------------------------------------------------------------------------
# Low-level XML helpers
# --------------------------------------------------------------------------------------
def make_para(text: str) -> OxmlElement:
    """Build a bare paragraph carrying a `{%p %}` control tag.

    The `p` suffix is load-bearing, not cosmetic. A plain `{% for %}` is substituted
    inline, so the loop body starts mid-paragraph and each iteration re-emits the
    surrounding `<w:p>` fragments — nesting a paragraph inside a paragraph. The result
    is well-formed XML that violates the OOXML schema, and Word refuses to open it with
    a generic "Word experienced an error trying to open the file". `{%p %}` makes
    docxtpl drop the whole enclosing paragraph instead, so loops span entire paragraphs.

    Deliberately style-less: these paragraphs are deleted at render time, so formatting
    on them would be wasted, and inheriting a list style would leave a stray bullet
    behind if a tag were ever mistyped.
    """
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    p.append(r)
    return p

def delete(paragraph: Paragraph) -> None:
    paragraph._p.getparent().remove(paragraph._p)

def strip_hyperlinks(paragraph: Paragraph) -> list[str]:
    """Remove `w:hyperlink` wrappers, returning the link texts that were dropped.

    Each project carries its own URL, so a hyperlink baked into the template would point
    every rendered project at the prototype's target. The link is reinstated at render
    time as a docxtpl `RichText`, which supplies the correct per-project URL.
    """
    dropped = []
    for link in paragraph._p.findall(qn("w:hyperlink")):
        dropped.append("".join(t.text or "" for t in link.iter(qn("w:t"))))
        paragraph._p.remove(link)
    return dropped

def has_tab_element(run) -> bool:
    """Whether the run's tab is a `<w:tab/>` element rather than a literal character.

    Word writes tab stops as elements, which `run.text` renders as "\\t". Treating that
    rendered form as if it were real text and rewriting it produced a duplicated tab —
    the element survived the rewrite and a literal tab was added alongside it.
    """
    return run._r.find(qn("w:tab")) is not None

_DRAWING_TAGS = ("w:drawing", "w:pict", "w:object")

def _has_drawing(run) -> bool:
    """True for a run holding an image, shape or embedded object (not text)."""
    return any(run._r.find(f".//{qn(tag)}") is not None for tag in _DRAWING_TAGS)

def _drop_run(run) -> None:
    """Remove a run, unless it holds a drawing: then only its text goes.

    An icon beside the name, a phone glyph in the contact line, a divider image: the
    build never edits them, so collapsing a paragraph to one tagged run keeps them in
    place (template-analyze reports them as the non-blocking `decorative_drawing`).
    """
    if _has_drawing(run):
        for t in run._r.findall(qn("w:t")):
            run._r.remove(t)
        return
    run._r.getparent().remove(run._r)

def collapse_runs(runs, tag: str) -> None:
    """Put ``tag`` in the first text run and drop the other runs, keeping drawings."""
    runs = list(runs)
    target = next((run for run in runs if not _has_drawing(run)), runs[0])
    set_run_text(target, tag)
    for extra in runs:
        if extra._r is not target._r:
            _drop_run(extra)

def set_run_text(run, text: str, *, keep_tabs: bool = False) -> None:
    """Replace a run's text, preserving significant whitespace.

    With `keep_tabs`, any `<w:tab/>` elements are left in place and `text` is appended
    after them — use it for the run that holds a header's alignment tab.
    """
    for t in run._r.findall(qn("w:t")):
        run._r.remove(t)
    if not keep_tabs:
        for tab in run._r.findall(qn("w:tab")):
            run._r.remove(tab)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run._r.append(t)

def clone_run_after(run, text: str) -> Run:
    """Duplicate a run (inheriting its formatting) with new text, placed just after it."""
    new_r = copy.deepcopy(run._r)
    run._r.addnext(new_r)
    cloned = Run(new_r, run._parent)
    set_run_text(cloned, text)
    return cloned

def strip_bold(run: Run) -> None:
    """Remove bold from a run's character properties."""
    rPr = run._r.find(qn("w:rPr"))
    if rPr is None:
        return
    for tag in ("w:b", "w:bCs"):
        el = rPr.find(qn(tag))
        if el is not None:
            rPr.remove(el)

def tab_run_index(paragraph: Paragraph) -> int:
    """Return the index of the run holding the header's date-alignment tab."""
    for i, run in enumerate(paragraph.runs):
        if "\t" in run.text or has_tab_element(run):
            return i
    return len(paragraph.runs) - 1

def set_num_id(paragraph: Paragraph, num_id: str) -> None:
    """Point a list paragraph at a different numbering definition instance."""
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        paragraph._p.insert(0, pPr)
    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        numPr = OxmlElement("w:numPr")
        pPr.insert(0, numPr)
    num_id_el = numPr.find(qn("w:numId"))
    if num_id_el is None:
        num_id_el = OxmlElement("w:numId")
        numPr.append(num_id_el)
    num_id_el.set(qn("w:val"), num_id)

def strip_right_indent(paragraph: Paragraph) -> None:
    """Drop a paragraph's right indent — it narrows the column and inflates line count."""
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        return
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        return
    if ind.get(qn("w:right")) is not None:
        del ind.attrib[qn("w:right")]

# Word single spacing under lineRule=auto is 240 (240ths of a line).
SINGLE_LINE = "240"

def set_single_spacing(paragraph: Paragraph, *, exact: bool = False) -> None:
    """Force Word single line spacing on a paragraph, preserving before/after gaps.

    `lineRule=auto` is Word's "Single". Bullets also get `exact` so a taller substitute
    bullet font (common under LibreOffice when Noto is missing) cannot inflate the
    auto line box past single — measured wraps were ~15.7pt for 10pt body text.
    """
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        paragraph._p.insert(0, pPr)
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:line"), SINGLE_LINE)
    # exact locks height in twips (240 = 12pt); auto is Word UI "Single".
    spacing.set(qn("w:lineRule"), "exact" if exact else "auto")

def pin_sub_single_to_exact(paragraph: Paragraph) -> bool:
    """Rewrite a sub-single `lineRule="auto"` paragraph to the equivalent `"exact"` height.

    Returns whether anything was changed.

    Proportional (`auto`) line spacing below 100% is **not portable**. Word honours it
    literally — `w:line="72"` is 30% of a line, ~3.5pt — while LibreOffice refuses to
    compress a line below its glyph height and floors the same paragraph at ~9.6pt, 2.8x
    taller. A source whose blank filler paragraphs are invisible in Word therefore grows a
    full blank line per filler once rendered through the container's LibreOffice.

    `exact` is honoured identically by both, and the twip number carries over directly:
    `w:line="72"` as `exact` is 72 twips = 3.6pt, within a rounding error of what Word
    already drew. This is the same reasoning that already pins bullets to `exact` in
    `set_single_spacing`.

    Only safe for paragraphs holding no text — an exact 3.6pt box would clip a 10pt glyph.
    Text paragraphs are normalised up to single instead; see `normalize_single_spacing`.
    """
    pPr = paragraph._p.find(qn("w:pPr"))
    spacing = pPr.find(qn("w:spacing")) if pPr is not None else None
    if spacing is None or spacing.get(qn("w:lineRule")) != "auto":
        return False
    line = spacing.get(qn("w:line"))
    if line is None:
        return False
    try:
        if int(line) >= int(SINGLE_LINE):
            return False
    except ValueError:
        return False
    spacing.set(qn("w:lineRule"), "exact")
    return True

def normalize_single_spacing(doc) -> None:
    """Make every body paragraph's line height renderer-independent.

    Google Docs exports can leave spacing unset (inherits a looser default) or carry
    Multiple > 1 on some paragraphs. Prototypes alone cannot fix education bullets or
    the name/contact lines, so this runs over the whole document after tagging.

    The governing rule is that a sub-100% `lineRule="auto"` value must never survive into
    a built template, because Word and LibreOffice disagree about it by ~3x (see
    `pin_sub_single_to_exact`). Two treatments, split on whether the paragraph holds text:

    - **Text** is normalised to single. Anything tighter only renders as the author
      intended in Word; under LibreOffice it floors out and merely looks cramped, or
      overlaps the line above.
    - **Chrome** (blank spacers, horizontal rules) keeps its authored height but is pinned
      to `exact`, so the thin gaps a source encodes as fractional filler paragraphs come
      out the same in both renderers instead of ballooning to a full blank line.
    """
    for paragraph, _location in docx_text.iter_document_paragraphs(doc):
        text = (paragraph.text or "").strip()
        # Control-tag paragraphs are dropped at render time; leave them bare.
        if text.startswith("{%p ") or text.startswith("{%tr "):
            continue
        if docx_text.is_chrome_text(text):
            pin_sub_single_to_exact(paragraph)
            continue
        set_single_spacing(paragraph, exact=template_bullets.is_bullet(paragraph))

def _section_text_width(doc) -> float | None:
    """Body text column width in twips, or `None` if the section geometry is missing.

    Deliberately reads `w:pgSz`/`w:pgMar` from the raw XML as `float` rather than using
    python-docx's typed `Section.page_width`/`.left_margin`/`.right_margin`: Google Docs
    exports non-integer twips (e.g. `w:left="1417.3228346456694"`), and those accessors
    raise `ValueError` on such a file.
    """
    body = doc.element.body
    sectPr = body.find(qn("w:sectPr"))
    if sectPr is None:
        return None
    pgSz = sectPr.find(qn("w:pgSz"))
    pgMar = sectPr.find(qn("w:pgMar"))
    if pgSz is None or pgMar is None:
        return None
    try:
        width = float(pgSz.get(qn("w:w")))
        left = float(pgMar.get(qn("w:left")))
        right = float(pgMar.get(qn("w:right")))
    except (TypeError, ValueError):
        return None
    return width - left - right

def clamp_tab_stops(doc) -> None:
    """Clamp every tab stop to its own paragraph's right edge, as Word silently does.

    A Google Docs export can carry a right tab stop (`w:tab/@w:pos`, measured from the
    left text margin) that overruns the paragraph's own right boundary — `text_width -
    w:ind/@w:right` — and even the page's text column. Word clamps such a stop back to the
    paragraph's right edge when it renders; LibreOffice honours it literally and lets the
    tab-aligned text hang past the margin. Baking Word's clamp into the XML makes both
    renderers agree, the same reasoning `pin_sub_single_to_exact` applies to line spacing.
    """
    text_width = _section_text_width(doc)
    if text_width is None:
        return
    for paragraph, _location in docx_text.iter_document_paragraphs(doc):
        pPr = paragraph._p.find(qn("w:pPr"))
        if pPr is None:
            continue
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            continue
        ind = pPr.find(qn("w:ind"))
        try:
            right_indent = float(ind.get(qn("w:right"))) if ind is not None else 0.0
        except (TypeError, ValueError):
            right_indent = 0.0
        limit = text_width - right_indent
        for tab in tabs.findall(qn("w:tab")):
            pos = tab.get(qn("w:pos"))
            if pos is None:
                continue
            try:
                pos_val = float(pos)
            except ValueError:
                continue
            if pos_val > limit:
                tab.set(qn("w:pos"), str(round(limit)))
