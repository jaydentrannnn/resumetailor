"""Clean-up applied to an uploaded .docx before anything reads it (P3-D).

Every upload path (template analyze, template install, content import) runs `prepare`
first, so the analyzer, the builder and the installed baseline all see the same bytes
and paragraph ids stay aligned. The user's own file is never touched: this rewrites the
copy the server received.

- **Other formats** (.doc, .odt, .rtf) are converted to .docx with LibreOffice.
- **Tracked changes** are accepted: insertions kept, deletions dropped, formatting
  changes kept as they now look.
- **Comments** are removed (their anchors and reference runs).
- **Content controls** (`w:sdt`, the fill-in boxes of Word's resume templates) are
  unwrapped so their text is ordinary paragraphs and runs.
- **Typed bullets** ("•" + tab) become a real Word list, only when the user asks
  (`convert_bullets`): it can move the text slightly, so it is never automatic for a
  template.

All of it is deterministic: the same upload gives the same bytes, which is what lets
install re-check the hash the analyze step recorded. A file that needs none of it is
returned byte-for-byte unchanged.
"""

from __future__ import annotations

import io
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from . import convert
from .analysis_types import Issue

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_NUMBERING_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
_NUMBERING_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"

_DOCUMENT = "word/document.xml"
_NUMBERING = "word/numbering.xml"
_DOC_RELS = "word/_rels/document.xml.rels"
_CONTENT_TYPES = "[Content_Types].xml"

#: A typed bullet: a glyph, then a tab or spaces, at the start of the paragraph text.
_TYPED_BULLET_RE = re.compile("^\\s*([\u2022\u25cf\u25cb\u25aa\u25e6\u2013\u2014*-])[\\t ]+\\S")

_TRACK_REMOVE = ("del", "moveFrom")
_TRACK_UNWRAP = ("ins", "moveTo")
_TRACK_MARKERS = (
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
    "rPrChange",
    "pPrChange",
    "sectPrChange",
    "tblPrChange",
    "tblGridChange",
    "trPrChange",
    "tcPrChange",
    "numberingChange",
)


class UploadFormatError(ValueError):
    """The upload can't be used; the message is shown to the user as-is."""


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


@dataclass
class Prepared:
    raw: bytes
    filename: str
    notices: list[Issue] = field(default_factory=list)


@dataclass
class _Counts:
    tracked: int = 0
    comments: int = 0
    controls: int = 0
    bullets: int = 0

    def any(self) -> bool:
        return bool(self.tracked or self.comments or self.controls or self.bullets)


def _unwrap(element: etree._Element) -> None:
    parent = element.getparent()
    index = parent.index(element)
    for child in list(element):
        parent.insert(index, child)
        index += 1
    parent.remove(element)


def _accept_tracked_changes(root: etree._Element) -> int:
    count = 0
    for name in _TRACK_REMOVE:
        for el in list(root.iter(_w(name))):
            if el.getparent() is not None:
                el.getparent().remove(el)
                count += 1
    for name in _TRACK_UNWRAP:
        for el in list(root.iter(_w(name))):
            parent = el.getparent()
            if parent is None:
                continue
            # An empty w:ins inside rPr/trPr marks an inserted paragraph mark or row: a
            # marker, not content.
            if len(el) == 0 or etree.QName(parent).localname.endswith("Pr"):
                parent.remove(el)
            else:
                _unwrap(el)
            count += 1
    for name in _TRACK_MARKERS:
        for el in list(root.iter(_w(name))):
            if el.getparent() is not None:
                el.getparent().remove(el)
                count += 1
    return count


def _remove_comments(root: etree._Element) -> int:
    count = 0
    for name in ("commentRangeStart", "commentRangeEnd"):
        for el in list(root.iter(_w(name))):
            el.getparent().remove(el)
    for ref in list(root.iter(_w("commentReference"))):
        run = ref.getparent()
        if run is not None and run.getparent() is not None:
            run.getparent().remove(run)
            count += 1
    return count


def _unwrap_content_controls(root: etree._Element) -> int:
    count = 0
    # Deepest first, so a nested control is unwrapped before the one around it.
    for sdt in reversed(list(root.iter(_w("sdt")))):
        parent = sdt.getparent()
        if parent is None:
            continue
        content = sdt.find(_w("sdtContent"))
        index = parent.index(sdt)
        if content is not None:
            for child in list(content):
                parent.insert(index, child)
                index += 1
        parent.remove(sdt)
        count += 1
    return count


def _paragraph_text(p: etree._Element) -> str:
    parts = []
    for el in p.iter(_w("t"), _w("tab")):
        parts.append("\t" if etree.QName(el).localname == "tab" else (el.text or ""))
    return "".join(parts)


def _strip_glyph(p: etree._Element) -> etree._Element | None:
    """Remove the leading glyph and the whitespace/tab after it; return the glyph's run."""
    glyph_run = None
    stripping = False
    for el in list(p.iter(_w("t"), _w("tab"))):
        if etree.QName(el).localname == "tab":
            if stripping:
                el.getparent().remove(el)
                continue
            if glyph_run is None:
                continue
            break
        text = el.text or ""
        if glyph_run is None:
            stripped = text.lstrip()
            if not stripped:
                el.text = ""
                continue
            glyph_run = el.getparent()
            text = stripped[1:]
            stripping = True
        if stripping:
            rest = text.lstrip(" \t")
            el.text = rest
            if rest:
                if rest != text:
                    el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                break
    return glyph_run


def _numbering_root(parts: dict[str, bytes]) -> etree._Element:
    if _NUMBERING in parts:
        return etree.fromstring(parts[_NUMBERING])
    root = etree.Element(_w("numbering"), nsmap={"w": W})
    rels = etree.fromstring(parts[_DOC_RELS])
    ids = {r.get("Id") for r in rels}
    rid = next(f"rId{n}" for n in range(1, 10_000) if f"rId{n}" not in ids)
    etree.SubElement(
        rels, f"{{{_REL_NS}}}Relationship", Id=rid, Type=_NUMBERING_REL, Target="numbering.xml"
    )
    parts[_DOC_RELS] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    types = etree.fromstring(parts[_CONTENT_TYPES])
    etree.SubElement(
        types, f"{{{_CT_NS}}}Override", PartName="/word/numbering.xml", ContentType=_NUMBERING_CT
    )
    parts[_CONTENT_TYPES] = etree.tostring(
        types, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return root


def _add_bullet_list(numbering: etree._Element, glyph: str, font: str | None) -> str:
    """Append a one-level bullet list definition; return its numId."""
    abstract_ids = [int(a.get(_w("abstractNumId"))) for a in numbering.iter(_w("abstractNum"))]
    num_ids = [int(n.get(_w("numId"))) for n in numbering.iter(_w("num"))]
    abstract_id = str(max(abstract_ids, default=-1) + 1)
    num_id = str(max(num_ids, default=0) + 1)

    abstract = etree.Element(_w("abstractNum"))
    abstract.set(_w("abstractNumId"), abstract_id)
    etree.SubElement(abstract, _w("multiLevelType")).set(_w("val"), "singleLevel")
    lvl = etree.SubElement(abstract, _w("lvl"))
    lvl.set(_w("ilvl"), "0")
    etree.SubElement(lvl, _w("start")).set(_w("val"), "1")
    etree.SubElement(lvl, _w("numFmt")).set(_w("val"), "bullet")
    etree.SubElement(lvl, _w("lvlText")).set(_w("val"), glyph)
    etree.SubElement(lvl, _w("lvlJc")).set(_w("val"), "left")
    ind = etree.SubElement(etree.SubElement(lvl, _w("pPr")), _w("ind"))
    ind.set(_w("left"), "360")
    ind.set(_w("hanging"), "360")
    if font:
        fonts = etree.SubElement(etree.SubElement(lvl, _w("rPr")), _w("rFonts"))
        for attr in ("ascii", "hAnsi", "cs"):
            fonts.set(_w(attr), font)

    # Schema order: every abstractNum before the first num.
    existing = list(numbering.iter(_w("abstractNum")))
    if existing:
        existing[-1].addnext(abstract)
    else:
        first_num = numbering.find(_w("num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            numbering.append(abstract)
    num = etree.SubElement(numbering, _w("num"))
    num.set(_w("numId"), num_id)
    etree.SubElement(num, _w("abstractNumId")).set(_w("val"), abstract_id)
    return num_id


def _convert_typed_bullets(root: etree._Element, parts: dict[str, bytes]) -> int:
    targets = []
    for p in root.iter(_w("p")):
        ppr = p.find(_w("pPr"))
        if ppr is not None and ppr.find(_w("numPr")) is not None:
            continue
        match = _TYPED_BULLET_RE.match(_paragraph_text(p))
        if match:
            targets.append((p, match.group(1)))
    if not targets:
        return 0
    numbering = _numbering_root(parts)
    glyph = targets[0][1] if targets[0][1] not in "-*" else "\u2022"
    first_run = None
    for p, _glyph in targets:
        run = _strip_glyph(p)
        first_run = first_run if first_run is not None else run
    font = None
    if first_run is not None:
        fonts = first_run.find(f"{_w('rPr')}/{_w('rFonts')}")
        if fonts is not None:
            font = fonts.get(_w("ascii"))
    num_id = _add_bullet_list(numbering, glyph, font)
    for p, _glyph in targets:
        ppr = p.find(_w("pPr"))
        if ppr is None:
            ppr = etree.Element(_w("pPr"))
            p.insert(0, ppr)
        num_pr = etree.Element(_w("numPr"))
        etree.SubElement(num_pr, _w("ilvl")).set(_w("val"), "0")
        etree.SubElement(num_pr, _w("numId")).set(_w("val"), num_id)
        # numPr follows pStyle/keepNext/…; after pStyle is always a valid spot.
        style = ppr.find(_w("pStyle"))
        if style is not None:
            style.addnext(num_pr)
        else:
            ppr.insert(0, num_pr)
    parts[_NUMBERING] = etree.tostring(
        numbering, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return len(targets)


def normalize(raw: bytes, *, convert_bullets: bool = False) -> tuple[bytes, _Counts]:
    """The cleaned .docx bytes (unchanged when nothing needed cleaning) and what changed."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            parts = {info.filename: archive.read(info.filename) for info in infos}
    except zipfile.BadZipFile:
        return raw, _Counts()  # the caller's own validation reports an unreadable file
    if _DOCUMENT not in parts:
        return raw, _Counts()
    root = etree.fromstring(parts[_DOCUMENT])
    counts = _Counts(
        tracked=_accept_tracked_changes(root),
        comments=_remove_comments(root),
        controls=_unwrap_content_controls(root),
    )
    if convert_bullets:
        counts.bullets = _convert_typed_bullets(root, parts)
    if not counts.any():
        return raw, counts
    parts[_DOCUMENT] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        names = [info.filename for info in infos]
        for info in infos:
            archive.writestr(info, parts[info.filename], compress_type=info.compress_type)
        for name in sorted(set(parts) - set(names)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, parts[name], compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue(), counts


def _notices(counts: _Counts) -> list[Issue]:
    notices = []
    if counts.tracked:
        notices.append(
            Issue(
                code="tracked_changes_accepted",
                message=(
                    f"Accepted {counts.tracked} tracked change(s) in a copy; your own "
                    "file is unchanged."
                ),
            )
        )
    if counts.comments:
        notices.append(
            Issue(
                code="comments_removed",
                message=f"Removed {counts.comments} comment(s) from the copy used here.",
            )
        )
    if counts.controls:
        notices.append(
            Issue(
                code="content_controls_unwrapped",
                message=(
                    f"Unwrapped {counts.controls} content control(s) (fill-in boxes from "
                    "a Word template) so their text can be read."
                ),
            )
        )
    if counts.bullets:
        notices.append(
            Issue(
                code="typed_bullets_converted",
                message=(
                    f"Turned {counts.bullets} typed bullet(s) into a real Word list. "
                    "Check the preview: indentation can shift slightly."
                ),
            )
        )
    return notices


def prepare(raw: bytes, filename: str, *, convert_bullets: bool = False) -> Prepared:
    """Convert (if needed) and clean an upload. Raises `UploadFormatError`."""
    name = Path(filename or "upload.docx").name
    suffix = Path(name).suffix.lower()
    notices: list[Issue] = []
    if suffix == ".pages":
        raise UploadFormatError(
            "Pages files can't be read. In Pages, choose File → Export To → Word, then "
            "upload the .docx."
        )
    if suffix in convert.CONVERTIBLE_SUFFIXES:
        if not raw:
            raise UploadFormatError("Upload is empty.")
        with tempfile.TemporaryDirectory(prefix="rt_convert_") as tmp:
            src = Path(tmp) / f"upload{suffix}"
            src.write_bytes(raw)
            try:
                produced = convert.to_docx(src, Path(tmp) / "out")
            except RuntimeError as exc:
                raise UploadFormatError(
                    f"Couldn't convert this {suffix} file ({exc}). Save it as .docx in "
                    "Word or LibreOffice and upload that instead."
                ) from exc
            raw = produced.read_bytes()
        name = f"{Path(name).stem}.docx"
        notices.append(
            Issue(
                code="converted_to_docx",
                message=(
                    f"Converted from {suffix} to .docx with LibreOffice. Check the "
                    "preview: some formatting may have changed."
                ),
            )
        )
    cleaned, counts = normalize(raw, convert_bullets=convert_bullets)
    return Prepared(raw=cleaned, filename=name, notices=[*notices, *_notices(counts)])
