"""Build a cover-letter docxtpl template from the resume baseline export.

Derives ``cover_template.docx`` from ``original_export.docx`` so the letter's letterhead,
fonts, margins, and page setup match the resume exactly. Keeps the tagged name and contact
block, deletes every resume section body, and appends the fixed cover-letter placeholder
set on paragraphs cloned from a body donor with ``w:numPr`` stripped.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Inches, Pt
from docx.text.paragraph import Paragraph

from .. import config
from . import cover_own, cover_settings, docx_text, template_custom
from .cover_settings import CoverSettings
from .template_profile import TemplateProfile, load_profile
from .template_profile_build import build_contact_profile, build_name_profile
from .template_tagging import _para_by_id
from .template_xml import make_para, set_run_text

#: Bump when ``build_cover_template`` output changes so ``ensure_cover_template`` rebuilds.
_BUILDER_VERSION = 3

DATE_TAG = "{{ date }}"
SUBJECT_TAG = "{{ subject }}"
SALUTATION_TAG = "{{ salutation }}"
CLOSING_TAG = "{{ closing }}"
SIGNATURE_TAG = "{{ signature }}"
INSIDE_OPEN = "{%p for line in inside_address %}"
INSIDE_BODY = "{{ line }}"
INSIDE_CLOSE = "{%p endfor %}"
BODY_OPEN = "{%p for para in paragraphs %}"
BODY_BODY = "{{ para }}"
BODY_CLOSE = "{%p endfor %}"
#: Every block but the body prints behind one of these (`cover_settings.CoverBlocks`). A
#: subscript, not `blocks.date`: attribute-first lookup is the `items` gotcha.
BLOCK_IF_FMT = '{%%p if blocks["%s"] %%}'
ELSE = "{%p else %}"
ENDIF = "{%p endif %}"
#: The inside address cannot space its own last line (it repeats in a loop), so the block
#: after it carries the gap — but only when the address actually printed.
AFTER_RECIPIENT = 'blocks["recipient"] and inside_address'


def _strip_numbering(paragraph_element) -> None:
    """Remove bullet numbering from a cloned paragraph element."""
    p_pr = paragraph_element.find(qn("w:pPr"))
    if p_pr is None:
        return
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is not None:
        p_pr.remove(num_pr)


def _donor_font_size(donor: Paragraph) -> Pt:
    """Body font size of ``donor``, for deriving one blank line of block spacing.

    Checked on the first run, then on the paragraph mark (``w:pPr/w:rPr/w:sz``, where a
    Google Docs export puts direct formatting), then defaulted. ``w:sz`` is in
    half-points, hence the halving.
    """
    for run in donor.runs:
        if run.font.size is not None:
            return run.font.size
    p_pr = donor._p.find(qn("w:pPr"))
    if p_pr is not None:
        r_pr = p_pr.find(qn("w:rPr"))
        if r_pr is not None:
            sz = r_pr.find(qn("w:sz"))
            if sz is not None and sz.get(qn("w:val")):
                return Pt(float(sz.get(qn("w:val"))) / 2)
    return Pt(10)


def _clone_donor_paragraph(
    donor: Paragraph,
    text: str,
    *,
    space_before: Pt,
    space_after: Pt,
    inset: tuple[Emu, Emu] = (Emu(0), Emu(0)),
) -> Paragraph:
    """Deep-copy ``donor`` as a letter paragraph carrying ``text``.

    The donor is a resume bullet: bullets are the one paragraph kind guaranteed to carry
    body-weight prose formatting rather than a heading's bold or a header's tab stops. But
    a bullet also carries the hanging indent that positions its text beside the glyph, so
    dropping ``w:numPr`` alone leaves every letter line inset half an inch with a negative
    first line, and with no space between blocks. Both are reset here.
    """
    new_element = copy.deepcopy(donor._p)
    _strip_numbering(new_element)
    cloned = Paragraph(new_element, donor._parent)
    # `paragraph_format` setters go through python-docx's `get_or_add_*`, which insert
    # `w:ind`/`w:spacing` into `w:pPr` in OOXML schema order. Appending them by hand would
    # produce a file that parses but that Word rejects.
    fmt = cloned.paragraph_format
    # `inset` lines the letter up with a table letterhead's text (`_table_text_inset`).
    fmt.left_indent, fmt.right_indent = inset
    # 0 (not None) so a `w:hanging` on the donor is actively cleared, not just left to
    # whatever the underlying style says.
    fmt.first_line_indent = Emu(0)
    fmt.space_before = space_before
    fmt.space_after = space_after
    fmt.line_spacing = 1.15
    if cloned.runs:
        set_run_text(cloned.runs[0], text)
        for extra in cloned.runs[1:]:
            cloned._p.remove(extra._r)
    return cloned


def _find_rule_donor(doc: Document):
    """Return the first ``w:pBdr`` element whose bottom border is a visible rule line."""
    for paragraph, _location in docx_text.iter_document_paragraphs(doc):
        p_pr = paragraph._p.find(qn("w:pPr"))
        if p_pr is None:
            continue
        p_bdr = p_pr.find(qn("w:pBdr"))
        if p_bdr is None:
            continue
        bottom = p_bdr.find(qn("w:bottom"))
        if bottom is None:
            continue
        if bottom.get(qn("w:val")) in (None, "nil", "none"):
            continue
        return p_bdr
    return None


def _apply_letterhead_rule(doc: Document, profile: TemplateProfile) -> None:
    """Clone the resume's section-heading rule onto the letterhead contact line."""
    donor_bdr = _find_rule_donor(doc)
    if donor_bdr is None or profile.contact is None:
        return
    paragraph = _para_by_id(doc, profile.contact.paragraph_id)
    p_pr = paragraph._p.get_or_add_pPr()
    # ``w:pBdr`` must precede ``w:spacing`` and ``w:ind`` in ``w:pPr``.
    existing = p_pr.find(qn("w:pBdr"))
    if existing is not None:
        p_pr.remove(existing)
    p_pr.insert(0, copy.deepcopy(donor_bdr))


def _contact_paragraph_ids(profile: TemplateProfile) -> list[int]:
    """Return every body paragraph id that belongs to the letterhead contact block
    (none of them when the name and contact live in the page header)."""
    ids = [] if profile.name_in_header else [profile.name_paragraph_id]
    if profile.contact is not None:
        ids.append(profile.contact.paragraph_id)
        ids.extend(slot.paragraph_id for slot in profile.contact.slots)
    return sorted({i for i in ids if i is not None})


#: Word's default left/right cell padding (0.075") when neither the table nor its style
#: sets one.
_DEFAULT_CELL_MARGIN_DXA = 108


def _letterhead_table(doc: Document, profile: TemplateProfile):
    """The ``w:tbl`` holding the letterhead, or None for a paragraph letterhead."""
    ids = set(_contact_paragraph_ids(profile))
    for para_id, (paragraph, _location) in enumerate(docx_text.iter_document_paragraphs(doc)):
        if para_id in ids:
            table = next(paragraph._p.iterancestors(qn("w:tbl")), None)
            if table is not None:
                return table
    return None


def _dxa(element, name: str) -> int | None:
    """``w:w`` of child ``name`` when it is a ``dxa`` measure."""
    child = element.find(qn(name)) if element is not None else None
    if child is None or child.get(qn("w:type"), "dxa") != "dxa":
        return None
    try:
        return int(child.get(qn("w:w")))
    except (TypeError, ValueError):
        return None


def _cell_margin(doc: Document, tbl_pr, side: str) -> int:
    """Left/right cell padding in dxa: the table's own, else its style's, else Word's."""
    names = ("w:left", "w:start") if side == "left" else ("w:right", "w:end")
    sources = [tbl_pr.find(qn("w:tblCellMar")) if tbl_pr is not None else None]
    style = tbl_pr.find(qn("w:tblStyle")) if tbl_pr is not None else None
    if style is not None:
        for st in doc.styles.element.findall(qn("w:style")):
            if st.get(qn("w:styleId")) == style.get(qn("w:val")):
                st_pr = st.find(qn("w:tblPr"))
                sources.append(st_pr.find(qn("w:tblCellMar")) if st_pr is not None else None)
    for mar in sources:
        for name in names:
            value = _dxa(mar, name)
            if value is not None:
                return value
    return _DEFAULT_CELL_MARGIN_DXA


def _table_text_inset(doc: Document, table) -> tuple[Emu, Emu]:
    """How far the letterhead table's text sits inside the page margins, left and right,
    so the letter body can line up with it. A table with no fixed width (percentage or
    auto) is taken to start at its indent and span the text width."""
    tbl_pr = table.find(qn("w:tblPr"))
    section = doc.sections[0]
    text_dxa = int((section.page_width - section.left_margin - section.right_margin) / 635)
    width = _dxa(tbl_pr, "w:tblW")
    if not width:
        left = (_dxa(tbl_pr, "w:tblInd") or 0) + _cell_margin(doc, tbl_pr, "left")
        return Emu(max(left, 0) * 635), Emu(_cell_margin(doc, tbl_pr, "right") * 635)
    jc = tbl_pr.find(qn("w:jc"))
    align = jc.get(qn("w:val")) if jc is not None else "left"
    if align == "center":
        left = (text_dxa - width) // 2
    elif align in ("right", "end"):
        left = text_dxa - width
    else:
        left = _dxa(tbl_pr, "w:tblInd") or 0
    right = text_dxa - width - left
    left += _cell_margin(doc, tbl_pr, "left")
    right += _cell_margin(doc, tbl_pr, "right")
    return Emu(max(left, 0) * 635), Emu(max(right, 0) * 635)


def _letterhead_custom(profile: TemplateProfile, last_keep_id: int) -> TemplateProfile:
    """`profile` restricted to the custom/dropped lines inside the kept letterhead —
    every later line is deleted with the resume body, so tagging it would be wasted."""
    return profile.model_copy(
        update={
            "custom_fields": [f for f in profile.custom_fields if f.paragraph_id <= last_keep_id],
            "dropped_paragraph_ids": [
                pid for pid in profile.dropped_paragraph_ids if pid <= last_keep_id
            ],
        }
    )


def _find_body_donor(doc: Document, after_id: int) -> Paragraph:
    """Return the first numbered paragraph after the letterhead, for body formatting."""
    for para_id, (paragraph, _location) in enumerate(docx_text.iter_document_paragraphs(doc)):
        if para_id <= after_id:
            continue
        p_pr = paragraph._p.find(qn("w:pPr"))
        if p_pr is not None and p_pr.find(qn("w:numPr")) is not None:
            return paragraph
    # Fallback: any paragraph after the letterhead, or the last letterhead line itself.
    last: Paragraph | None = None
    for para_id, (paragraph, _location) in enumerate(docx_text.iter_document_paragraphs(doc)):
        if para_id <= after_id:
            last = paragraph
    if last is None:
        raise RuntimeError("Could not find a paragraph donor for the cover-letter body.")
    return last


def _remove_paragraphs_after(doc: Document, last_keep_id: int) -> None:
    """Delete every document paragraph with an id greater than ``last_keep_id``.

    A table-layout resume keeps its letterhead and its sections in one table, so deleting
    paragraphs alone would leave rows of empty cells — and a ``w:tc`` with no ``w:p`` is
    a file Word refuses to open. Rows left with nothing kept go whole, then tables with
    no rows; any cell still emptied gets a blank paragraph back.
    """
    victims = [
        paragraph._p
        for para_id, (paragraph, _location) in enumerate(docx_text.iter_document_paragraphs(doc))
        if para_id > last_keep_id
    ]
    victim_set = set(victims)
    body = doc.element.body
    for row in list(body.iter(qn("w:tr"))):
        if not _attached(row, body):
            continue  # inside a row already removed
        paras = list(row.iter(qn("w:p")))
        if paras and all(p in victim_set for p in paras):
            row.getparent().remove(row)
    for p in victims:
        if _attached(p, body):
            p.getparent().remove(p)
    for table in list(body.iter(qn("w:tbl"))):
        if _attached(table, body) and table.find(qn("w:tr")) is None:
            table.getparent().remove(table)
    for cell in body.iter(qn("w:tc")):
        if cell.find(qn("w:p")) is None:
            cell.append(OxmlElement("w:p"))


def _attached(element, body) -> bool:
    """Whether ``element`` is still inside ``body`` (not under a removed row)."""
    node = element.getparent()
    while node is not None and node is not body:
        node = node.getparent()
    return node is body


def _append_paragraph(doc: Document, element) -> None:
    """Append an OOXML paragraph element to the end of the document body — before the
    body's ``w:sectPr``, which must stay its last child."""
    body = doc.element.body
    sect_pr = body.find(qn("w:sectPr"))
    if sect_pr is not None:
        sect_pr.addprevious(element)
    else:
        body.append(element)


def build_cover_template(
    src: Path,
    dst: Path,
    profile: TemplateProfile | None = None,
) -> None:
    """Derive a cover-letter template from the resume baseline export.

    ``src`` is normally ``config.BASELINE_TEMPLATE_PATH``. When a ``TemplateProfile`` is
    available, the name and contact paragraphs are tagged the same way as the resume
    template; otherwise the first two body paragraphs are kept as-is.
    """
    profile = profile if profile is not None else load_profile()
    doc = Document(str(src))

    # A table letterhead keeps the resume's own side margins: its column widths are
    # fixed to the resume's text width, so wider margins would push it past the letter
    # body on both sides.
    table = _letterhead_table(doc, profile) if profile is not None else None
    in_table = table is not None
    margin = Inches(config.COVER_MARGIN_INCHES)
    section = doc.sections[0]
    if not in_table:
        section.left_margin = margin
        section.right_margin = margin
    section.top_margin = margin
    section.bottom_margin = margin

    custom = None
    if profile is not None:
        build_name_profile(doc, profile)
        build_contact_profile(doc, profile)
        _apply_letterhead_rule(doc, profile)
        last_keep_id = max(_contact_paragraph_ids(profile), default=-1)
        custom = template_custom.tag(doc, _letterhead_custom(profile, last_keep_id))
    else:
        last_keep_id = 1

    donor = _find_body_donor(doc, last_keep_id)
    _remove_paragraphs_after(doc, last_keep_id)
    if custom is not None:
        template_custom.finish(custom)

    # One blank line of the document's own body font between letter blocks. A bullet
    # donor has no space-after (resume bullets sit flush against each other), which would
    # otherwise render the whole letter as a single unbroken block of text.
    gap = _donor_font_size(donor)
    none = Pt(0)
    inset = _table_text_inset(doc, table) if in_table else (Emu(0), Emu(0))

    def letter_para(text: str, *, before: Pt = none, after: Pt = gap):
        """Clone the donor into one normalized letter paragraph element."""
        return _clone_donor_paragraph(
            donor, text, space_before=before, space_after=after, inset=inset
        )._p

    # Block spacing follows business-letter convention rather than being uniform: the
    # inside address is a tight stack, and so are the closing and signature, so the gap
    # before the next block is carried by that block's own space-before instead of by the
    # address lines (which repeat in a loop and cannot space only their last one). A
    # block that may or may not follow the address comes in two spacings, chosen at
    # render time.
    def guarded(name: str, *elements) -> list:
        return [make_para(BLOCK_IF_FMT % name), *elements, make_para(ENDIF)]

    def after_address(text: str, cond: str, *, after: Pt = gap) -> list:
        return [
            make_para(f"{{%p if {cond} %}}"),
            letter_para(text, before=gap, after=after),
            make_para(ELSE),
            letter_para(text, after=after),
            make_para(ENDIF),
        ]

    sequence: list = [
        # A table letterhead has no space under it (a paragraph contact line carries
        # the rule and its spacing), so the letter starts one blank line lower.
        *([letter_para("", after=none)] if in_table else []),
        *guarded("date", letter_para(DATE_TAG)),
        *guarded(
            "recipient",
            make_para(INSIDE_OPEN),
            letter_para(INSIDE_BODY, after=none),
            make_para(INSIDE_CLOSE),
        ),
        *guarded("subject", *after_address(SUBJECT_TAG, AFTER_RECIPIENT)),
        *guarded(
            "salutation",
            *after_address(SALUTATION_TAG, f'{AFTER_RECIPIENT} and not blocks["subject"]'),
        ),
        make_para(BODY_OPEN),
        letter_para(BODY_BODY),
        make_para(BODY_CLOSE),
        *guarded("closing", letter_para(CLOSING_TAG, after=none)),
        *guarded("signature", letter_para(SIGNATURE_TAG, after=none)),
    ]
    for element in sequence:
        _append_paragraph(doc, element)

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))


def _read_meta(meta_path: Path) -> dict:
    """The sidecar beside the generated cover template ({} when absent or unreadable)."""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_meta(meta_path: Path, design: str) -> None:
    """Persist ``_BUILDER_VERSION`` and the letter design beside the cover template."""
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"builder_version": _BUILDER_VERSION, "design": design}
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def ensure_cover_template(
    *,
    src: Path | None = None,
    dst: Path | None = None,
    profile: TemplateProfile | None = None,
    meta_path: Path | None = None,
    settings: CoverSettings | None = None,
) -> Path:
    """Build ``cover_template.docx`` when missing, stale, or on a builder version bump.

    With ``settings.design == "own"`` and an uploaded letter at ``config.COVER_OWN_PATH``
    the template is built from that letter (`cover_own.build`); otherwise from the resume
    baseline. Switching design rebuilds."""
    src = src or config.BASELINE_TEMPLATE_PATH
    dst = dst or config.COVER_TEMPLATE_PATH
    meta_path = meta_path or config.COVER_TEMPLATE_META_PATH
    profile = profile if profile is not None else load_profile()
    settings = settings if settings is not None else cover_settings.load()
    own = config.COVER_OWN_PATH
    design = "own" if settings.design == "own" and own.exists() else "generated"
    source = own if design == "own" else src
    meta = _read_meta(meta_path)
    stale = (
        not dst.exists()
        or meta.get("builder_version") != _BUILDER_VERSION
        or meta.get("design", "generated") != design
        or dst.stat().st_mtime < source.stat().st_mtime
    )
    if not stale:
        return dst
    if design == "own":
        keys = {
            (slot.label or slot.key).casefold(): slot.key
            for slot in (profile.custom_fields if profile is not None else [])
        }
        cover_own.build(own, dst, custom_keys=keys)
    else:
        build_cover_template(src, dst, profile=profile)
    _write_meta(meta_path, design)
    return dst
