"""Legacy section discovery and bullet numbering/marker normalisation for template building."""

from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from . import template_tags, template_xml

# --------------------------------------------------------------------------------------
# Document structure
# --------------------------------------------------------------------------------------
SECTIONS = ("EDUCATION", "WORK EXPERIENCES", "PROJECTS", "SKILLS")

def is_bullet(p: Paragraph) -> bool:
    """A real list paragraph, i.e. one carrying numbering properties."""
    return p._p.find(f".//{qn('w:numPr')}") is not None

def find_sections(doc) -> dict[str, tuple[int, int]]:
    """Map each section heading to the (start, end) paragraph range of its body."""
    heads: dict[str, int] = {}
    for i, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        if text in SECTIONS:
            heads[text] = i

    bounds: dict[str, tuple[int, int]] = {}
    ordered = sorted(heads.items(), key=lambda kv: kv[1])
    for n, (name, idx) in enumerate(ordered):
        end = ordered[n + 1][1] if n + 1 < len(ordered) else len(doc.paragraphs)
        bounds[name] = (idx + 1, end)
    return bounds

def _num_to_abstract(numbering_root) -> dict[str, str]:
    """Map numbering instance ids to their abstract definition ids."""
    mapping: dict[str, str] = {}
    for num in numbering_root.findall(qn("w:num")):
        nid = num.get(qn("w:numId"))
        abs_el = num.find(qn("w:abstractNumId"))
        if nid is not None and abs_el is not None:
            mapping[nid] = abs_el.get(qn("w:val"), "")
    return mapping

def _abstract_has_noto_marker(numbering_root, abstract_id: str) -> bool:
    """Return whether an abstract numbering definition pins Noto for its lvl0 bullet."""
    for anum in numbering_root.findall(qn("w:abstractNum")):
        if anum.get(qn("w:abstractNumId")) != abstract_id:
            continue
        for lvl in anum.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) != "0":
                continue
            num_fmt = lvl.find(qn("w:numFmt"))
            if num_fmt is None or num_fmt.get(qn("w:val")) != "bullet":
                continue
            rPr = lvl.find(qn("w:rPr"))
            rf = rPr.find(qn("w:rFonts")) if rPr is not None else None
            return rf is not None and rf.get(qn("w:ascii")) == template_tags.NOTO_MARKER_FONT
    return False

def discover_noto_num_id(doc) -> str | None:
    """Find a list instance id whose lvl0 bullet marker uses Noto Sans Symbols.

    Prefer an id used by education bullets so experience/projects match that section.
    """
    numbering = doc.part.numbering_part
    root = numbering.element
    num_to_abs = _num_to_abstract(root)

    bounds = find_sections(doc)
    candidates: list[str] = []
    if "EDUCATION" in bounds:
        start, end = bounds["EDUCATION"]
        for paragraph in doc.paragraphs[start:end]:
            if not is_bullet(paragraph):
                continue
            pPr = paragraph._p.find(qn("w:pPr"))
            numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
            if numPr is None:
                continue
            num_id_el = numPr.find(qn("w:numId"))
            if num_id_el is None:
                continue
            num_id = num_id_el.get(qn("w:val"))
            if num_id and _abstract_has_noto_marker(root, num_to_abs.get(num_id, "")):
                return num_id
            if num_id:
                candidates.append(num_id)

    for num_id, abstract_id in num_to_abs.items():
        if _abstract_has_noto_marker(root, abstract_id):
            return num_id
    return candidates[0] if candidates else None

#: Word stores its Symbol/Wingdings bullets as private-use code points that only those
#: fonts can draw (Word's default bullet is U+F0B7 in Symbol). Pinning another font on such a
#: marker renders a box or a stray glyph, so the marker is first swapped for the real
#: Unicode character it shows. A private-use marker not listed here keeps its own font.
_SYMBOL_FONT_GLYPHS = {
    "\uf0b7": "\u2022",  # Symbol bullet
    "\uf0a7": "\u25aa",  # Wingdings small square
    "\uf0d8": "\u27a2",  # Wingdings arrowhead
    "\uf076": "\u2756",  # Wingdings diamond
    "\uf0fc": "\u2713",  # Wingdings check
}


def _is_private_use(text: str) -> bool:
    return any(0xF000 <= ord(c) <= 0xF0FF for c in text)


def _canonical_glyph(text: str | None) -> str | None:
    """`text` as it reads on the page: a Symbol/Wingdings code point as its Unicode twin."""
    if text is None:
        return None
    return "".join(_SYMBOL_FONT_GLYPHS.get(c, c) for c in text)


def _bullet_lvl0s(root):
    """Every abstract definition's lvl0 `w:lvl` element that draws a bullet."""
    for anum in root.findall(qn("w:abstractNum")):
        for lvl in anum.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) != "0":
                continue
            num_fmt = lvl.find(qn("w:numFmt"))
            if num_fmt is not None and num_fmt.get(qn("w:val")) == "bullet":
                yield lvl


def normalize_bullet_numbering(doc) -> None:
    """Pin Noto Sans Symbols on every lvl0 bullet marker in numbering.xml.

    A Symbol/Wingdings private-use marker is rewritten to its Unicode character first
    (`_SYMBOL_FONT_GLYPHS`); one with no known equivalent keeps its own font, since Noto
    would draw it as a box."""
    numbering = doc.part.numbering_part
    root = numbering.element

    ref_rfonts = None
    for lvl in _bullet_lvl0s(root):
        rPr = lvl.find(qn("w:rPr"))
        rf = rPr.find(qn("w:rFonts")) if rPr is not None else None
        if rf is not None and rf.get(qn("w:ascii")) == template_tags.NOTO_MARKER_FONT:
            ref_rfonts = copy.deepcopy(rf)
            break

    if ref_rfonts is None:
        ref_rfonts = OxmlElement("w:rFonts")
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            ref_rfonts.set(qn(f"w:{attr}"), template_tags.NOTO_MARKER_FONT)

    for lvl in _bullet_lvl0s(root):
        text_el = lvl.find(qn("w:lvlText"))
        text = text_el.get(qn("w:val"), "") if text_el is not None else ""
        if _is_private_use(text):
            canonical = "".join(_SYMBOL_FONT_GLYPHS.get(c, c) for c in text)
            if _is_private_use(canonical):
                continue
            text_el.set(qn("w:val"), canonical)
        rPr = lvl.find(qn("w:rPr"))
        if rPr is None:
            rPr = OxmlElement("w:rPr")
            lvl.append(rPr)
        old_rf = rPr.find(qn("w:rFonts"))
        if old_rf is not None:
            rPr.remove(old_rf)
        rPr.insert(0, copy.deepcopy(ref_rfonts))

#: Most fonts (Times New Roman included) draw U+25CF "●" as a near-full-em disc, not
#: the small list dot a dedicated symbol font would give it. Pinning a symbol font at the
#: numbering level does not help: the paragraph mark's own direct rFonts (written by every
#: Google Docs export, on every bullet paragraph) takes precedence over the numbering
#: level's rPr, so the marker always renders in the body font regardless. Shrinking the
#: paragraph mark's own size sidesteps that precedence fight entirely, and works in
#: whatever font actually wins.
BULLET_MARKER_SIZE_RATIO = 0.8 * (2 / 3)  # ~0.53; a further 2/3 pass on top of the first cut

_MIN_MARKER_HALF_POINTS = 8  # 4pt floor so a tiny body font can't shrink the dot to nothing

#: Large geometric glyphs that render as a near-full-em disc/square in most fonts — the
#: shape `BULLET_MARKER_SIZE_RATIO` was tuned against. A hyphen, en-dash, small bullet
#: (U+2022, already text-sized), or asterisk is left alone: shrinking one of those by the
#: same ~53% that tames a "●" renders it as a near-invisible hairline, not a smaller dot.
_SHRINKABLE_MARKERS = frozenset("●⬤○◉■□◆◇")

def _paragraph_num_id(paragraph: Paragraph) -> str | None:
    pPr = paragraph._p.find(qn("w:pPr"))
    numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
    num_id_el = numPr.find(qn("w:numId")) if numPr is not None else None
    return num_id_el.get(qn("w:val")) if num_id_el is not None else None


def _list_glyph(doc, num_id: str | None) -> str | None:
    """The literal lvl0 bullet character of list instance `num_id`."""
    if num_id is None:
        return None
    root = doc.part.numbering_part.element
    abstract_id = _num_to_abstract(root).get(num_id)
    if abstract_id is None:
        return None
    for anum in root.findall(qn("w:abstractNum")):
        if anum.get(qn("w:abstractNumId")) != abstract_id:
            continue
        for lvl in anum.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) != "0":
                continue
            text = lvl.find(qn("w:lvlText"))
            return text.get(qn("w:val")) if text is not None else None
    return None


def _marker_glyph(doc, paragraph: Paragraph) -> str | None:
    """The literal lvl0 bullet character governing `paragraph`'s numbering marker."""
    return _list_glyph(doc, _paragraph_num_id(paragraph))

def _body_run_size(paragraph: Paragraph) -> int | None:
    """Font size in half-points of the paragraph's first run that sets one explicitly."""
    for run in paragraph.runs:
        rPr = run._r.find(qn("w:rPr"))
        sz = rPr.find(qn("w:sz")) if rPr is not None else None
        if sz is not None and sz.get(qn("w:val")):
            return int(sz.get(qn("w:val")))
    return None

def shrink_bullet_marker(doc, paragraph: Paragraph) -> None:
    """Scale down the paragraph-mark font size that governs the bullet glyph.

    The paragraph mark's `rPr` (inside `pPr`, not the visible runs) formats only the
    numbering symbol, so this changes the dot's size without touching the bullet's own
    text size. Only applies to `_SHRINKABLE_MARKERS` glyphs — see that constant.

    Idempotent: the target size is derived from the paragraph's own body-run size (via
    `_body_run_size`) when one is set, not from the marker's current size, so calling
    this twice does not halve an already-shrunk marker.
    """
    if _marker_glyph(doc, paragraph) not in _SHRINKABLE_MARKERS:
        return
    pPr = paragraph._p.find(qn("w:pPr"))
    rPr = pPr.find(qn("w:rPr")) if pPr is not None else None
    sz = rPr.find(qn("w:sz")) if rPr is not None else None
    if sz is None or not sz.get(qn("w:val")):
        return
    body_size = _body_run_size(paragraph) or int(sz.get(qn("w:val")))
    marker_size = str(max(_MIN_MARKER_HALF_POINTS, round(body_size * BULLET_MARKER_SIZE_RATIO)))
    sz.set(qn("w:val"), marker_size)
    sz_cs = rPr.find(qn("w:szCs"))
    if sz_cs is not None:
        sz_cs.set(qn("w:val"), marker_size)

def retarget_bullet(doc, paragraph: Paragraph, num_id: str | None) -> None:
    """Move `paragraph` onto the canonical small-marker list `num_id` and drop any
    right-indent inflation.

    Only when that list draws the same marker the paragraph already shows (or the
    paragraph has no list yet): merging near-duplicate lists of one glyph is what this is
    for, and moving a "•" section onto an education list of "-" would change the page.
    """
    own = _paragraph_num_id(paragraph)
    if num_id is not None and (
        own is None
        or _canonical_glyph(_list_glyph(doc, own)) == _canonical_glyph(_list_glyph(doc, num_id))
    ):
        template_xml.set_num_id(paragraph, num_id)
    template_xml.strip_right_indent(paragraph)
    shrink_bullet_marker(doc, paragraph)
