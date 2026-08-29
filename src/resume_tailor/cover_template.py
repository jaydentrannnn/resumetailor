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
from docx.oxml.ns import qn
from docx.shared import Emu, Inches, Pt
from docx.text.paragraph import Paragraph

from . import config, docx_text
from .template_build import (
    _para_by_id,
    build_contact_profile,
    build_name_profile,
    delete,
    make_para,
    set_run_text,
)
from .template_profile import TemplateProfile, load_profile

#: Bump when ``build_cover_template`` output changes so ``ensure_cover_template`` rebuilds.
_BUILDER_VERSION = 1

DATE_TAG = "{{ date }}"
SALUTATION_TAG = "{{ salutation }}"
CLOSING_TAG = "{{ closing }}"
SIGNATURE_TAG = "{{ signature }}"
INSIDE_OPEN = "{%p for line in inside_address %}"
INSIDE_BODY = "{{ line }}"
INSIDE_CLOSE = "{%p endfor %}"
BODY_OPEN = "{%p for para in paragraphs %}"
BODY_BODY = "{{ para }}"
BODY_CLOSE = "{%p endfor %}"


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
    fmt.left_indent = Emu(0)
    fmt.right_indent = Emu(0)
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
    if donor_bdr is None:
        return
    paragraph = _para_by_id(doc, profile.contact.paragraph_id)
    p_pr = paragraph._p.get_or_add_pPr()
    # ``w:pBdr`` must precede ``w:spacing`` and ``w:ind`` in ``w:pPr``.
    existing = p_pr.find(qn("w:pBdr"))
    if existing is not None:
        p_pr.remove(existing)
    p_pr.insert(0, copy.deepcopy(donor_bdr))


def _contact_paragraph_ids(profile: TemplateProfile) -> list[int]:
    """Return every paragraph id that belongs to the letterhead contact block."""
    ids = [profile.name_paragraph_id, profile.contact.paragraph_id]
    ids.extend(slot.paragraph_id for slot in profile.contact.slots)
    return sorted({i for i in ids if i is not None})


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
    """Delete every document paragraph with an id greater than ``last_keep_id``."""
    victims = [
        paragraph
        for para_id, (paragraph, _location) in enumerate(docx_text.iter_document_paragraphs(doc))
        if para_id > last_keep_id
    ]
    for paragraph in victims:
        delete(paragraph)


def _append_paragraph(doc: Document, element) -> None:
    """Append an OOXML paragraph element to the document body."""
    doc.element.body.append(element)


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

    margin = Inches(config.COVER_MARGIN_INCHES)
    section = doc.sections[0]
    section.left_margin = margin
    section.right_margin = margin
    section.top_margin = margin
    section.bottom_margin = margin

    if profile is not None:
        build_name_profile(doc, profile)
        build_contact_profile(doc, profile)
        _apply_letterhead_rule(doc, profile)
        last_keep_id = max(_contact_paragraph_ids(profile))
    else:
        last_keep_id = 1

    donor = _find_body_donor(doc, last_keep_id)
    _remove_paragraphs_after(doc, last_keep_id)

    # One blank line of the document's own body font between letter blocks. A bullet
    # donor has no space-after (resume bullets sit flush against each other), which would
    # otherwise render the whole letter as a single unbroken block of text.
    gap = _donor_font_size(donor)
    none = Pt(0)

    def letter_para(text: str, *, before: Pt = none, after: Pt = gap):
        """Clone the donor into one normalized letter paragraph element."""
        return _clone_donor_paragraph(donor, text, space_before=before, space_after=after)._p

    # Block spacing follows business-letter convention rather than being uniform: the
    # inside address is a tight stack, and so are the closing and signature, so the gap
    # before the salutation is carried by the salutation's own space-before instead of by
    # the address lines (which repeat in a loop and cannot space only their last one).
    sequence: list = [
        letter_para(DATE_TAG),
        make_para(INSIDE_OPEN),
        letter_para(INSIDE_BODY, after=none),
        make_para(INSIDE_CLOSE),
        letter_para(SALUTATION_TAG, before=gap),
        make_para(BODY_OPEN),
        letter_para(BODY_BODY),
        make_para(BODY_CLOSE),
        letter_para(CLOSING_TAG, after=none),
        letter_para(SIGNATURE_TAG, after=none),
    ]
    for element in sequence:
        _append_paragraph(doc, element)

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))


def _read_builder_version(meta_path: Path) -> int | None:
    """Return the recorded builder version, or ``None`` when the sidecar is absent."""
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return int(data.get("builder_version", 0))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _write_builder_version(meta_path: Path) -> None:
    """Persist ``_BUILDER_VERSION`` beside the generated cover template."""
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps({"builder_version": _BUILDER_VERSION}, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_cover_template(
    *,
    src: Path | None = None,
    dst: Path | None = None,
    profile: TemplateProfile | None = None,
    meta_path: Path | None = None,
) -> Path:
    """Build ``cover_template.docx`` when missing, stale, or on a builder version bump."""
    src = src or config.BASELINE_TEMPLATE_PATH
    dst = dst or config.COVER_TEMPLATE_PATH
    meta_path = meta_path or config.COVER_TEMPLATE_META_PATH
    profile = profile if profile is not None else load_profile()
    version_stale = _read_builder_version(meta_path) != _BUILDER_VERSION
    baseline_stale = not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime
    if dst.exists() and not version_stale and not baseline_stale:
        return dst
    build_cover_template(src, dst, profile=profile)
    _write_builder_version(meta_path)
    return dst
