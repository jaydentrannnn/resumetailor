"""Reading a PDF into styled lines (with its size limits and error) and cleaning page chrome."""

from __future__ import annotations

import io
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..document import entry_structure
from . import pdf_patterns, pdf_structure

#: Fewer extracted characters than this means an image-only (scanned) PDF.
MIN_TEXT_CHARS = 50

#: A resume longer than this is almost certainly the wrong file.
MAX_PAGES = 10

class PdfImportError(ValueError):
    """The PDF can't be imported; the message is shown to the user as-is."""

# --------------------------------------------------------------------------------------
# 1. Lines from the text layer
# --------------------------------------------------------------------------------------
@dataclass
class Line:
    """One logical line of text. Segments separated by a wide gap are joined by a tab."""

    text: str
    x0: float
    top: float
    size: float
    bold: bool = False
    italic: bool = False
    page: int = 0
    #: `top` as a fraction of the page height (header/footer detection).
    rel_top: float = 0.0
    bullet: bool = False
    #: Where the text starts after a bullet glyph (continuation lines align here).
    text_x0: float = 0.0
    #: `top` of the last physical line merged into this one.
    last_top: float = 0.0

@dataclass
class _Segment:
    chars: list[dict[str, Any]]

    @property
    def x0(self) -> float:
        return float(self.chars[0]["x0"])

    @property
    def x1(self) -> float:
        return float(self.chars[-1]["x1"])

def _rows(chars: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group characters sharing a baseline, top to bottom."""
    rows: list[list[dict[str, Any]]] = []
    anchor = None
    for ch in sorted(chars, key=lambda c: (round(float(c["bottom"]), 1), float(c["x0"]))):
        bottom = float(ch["bottom"])
        tol = max(1.0, 0.45 * float(ch.get("size") or 10))
        if anchor is not None and abs(bottom - anchor) <= tol:
            rows[-1].append(ch)
        else:
            rows.append([ch])
            anchor = bottom
    return [sorted(r, key=lambda c: float(c["x0"])) for r in rows]

def _segments(row: list[dict[str, Any]]) -> list[_Segment]:
    """Split a row at gaps wider than two ems (tab stops, columns, right-aligned dates)."""
    segs: list[_Segment] = []
    prev_x1 = None
    for ch in row:
        if ch["text"].isspace():
            continue
        size = float(ch.get("size") or 10)
        if prev_x1 is None or float(ch["x0"]) - prev_x1 > 2.0 * size:
            segs.append(_Segment([ch]))
        else:
            segs[-1].chars.append(ch)
        prev_x1 = float(ch["x1"])
    return segs

def _segment_text(seg: _Segment, row: list[dict[str, Any]]) -> str:
    """Characters of `seg`, with a space wherever the source had one or a word gap."""
    out: list[str] = []
    members = {id(c) for c in seg.chars}
    prev = None
    pending_space = False
    for ch in row:
        if id(ch) not in members:
            if (
                prev is not None
                and ch["text"].isspace()
                and float(ch["x0"]) >= float(prev["x1"]) - 0.5
            ):
                pending_space = True
            continue
        if prev is not None:
            gap = float(ch["x0"]) - float(prev["x1"])
            if pending_space or gap > 0.3 * float(ch.get("size") or 10):
                out.append(" ")
        out.append(ch["text"])
        prev = ch
        pending_space = False
    return "".join(out)

def _gutter(segs: list[_Segment], width: float) -> float | None:
    """x of a persistent column gutter, or None for a single-column page.

    Two columns means: many segments start at the same x in the middle of the page,
    a fair share of segments end left of it, and almost nothing spans across it. A
    single-column resume with right-aligned dates fails the last test, because its
    bullets run across the whole width.
    """
    n = len(segs)
    if n < 8:
        return None
    starts = Counter(round(s.x0 / 3) for s in segs if 0.3 * width < s.x0 < 0.75 * width)
    for key, _count in starts.most_common(3):
        x = key * 3.0
        at = sum(1 for s in segs if abs(s.x0 - x) <= 4)
        across = sum(1 for s in segs if s.x0 < x - 4 and s.x1 > x + 2)
        left = sum(1 for s in segs if s.x1 <= x - 2)
        if at >= max(4, 0.2 * n) and across <= 0.15 * n and left >= 0.2 * n:
            return x - 4
    return None

def _style(chars: list[dict[str, Any]]) -> tuple[float, bool, bool]:
    letters = [c for c in chars if c["text"].strip()]
    if not letters:
        return 10.0, False, False
    size = statistics.median(float(c.get("size") or 10) for c in letters)
    bold = (
        sum(1 for c in letters if pdf_patterns._BOLD_RE.search(str(c.get("fontname", ""))))
        > len(letters) / 2
    )
    italic = (
        sum(1 for c in letters if pdf_patterns._ITALIC_RE.search(str(c.get("fontname", ""))))
        > len(letters) / 2
    )
    return round(size, 1), bold, italic

def _page_lines(page: Any, index: int) -> list[Line]:
    width, height = float(page.width), float(page.height)
    rows = _rows([c for c in page.chars if c.get("upright", True)])
    placed: list[tuple[list[dict[str, Any]], _Segment]] = [
        (row, seg) for row in rows for seg in _segments(row)
    ]
    gutter = _gutter([seg for _row, seg in placed], width)
    columns: list[list[tuple[list[dict[str, Any]], _Segment]]] = (
        [placed]
        if gutter is None
        else [
            [(r, s) for r, s in placed if s.x0 < gutter],
            [(r, s) for r, s in placed if s.x0 >= gutter],
        ]
    )
    lines: list[Line] = []
    for column in columns:
        by_row: dict[int, list[_Segment]] = {}
        row_of: dict[int, list[dict[str, Any]]] = {}
        for row, seg in column:
            by_row.setdefault(id(row), []).append(seg)
            row_of[id(row)] = row
        for key in sorted(by_row, key=lambda k: float(row_of[k][0]["bottom"])):
            row, segs = row_of[key], sorted(by_row[key], key=lambda s: s.x0)
            text = "\t".join(_segment_text(s, row) for s in segs)
            chars = [c for s in segs for c in s.chars]
            size, bold, italic = _style(chars)
            top = min(float(c["top"]) for c in chars)
            lines.append(
                Line(
                    text=text,
                    x0=segs[0].x0,
                    top=top,
                    size=size,
                    bold=bold,
                    italic=italic,
                    page=index,
                    rel_top=top / height if height else 0.0,
                    text_x0=_text_x0(segs[0]),
                    last_top=top,
                )
            )
    return lines

def _text_x0(seg: _Segment) -> float:
    """x of the first character after a leading bullet glyph (or the segment start)."""
    chars = seg.chars
    if chars and pdf_patterns._BULLET_RE.match(chars[0]["text"] + " ") and len(chars) > 1:
        return float(chars[1]["x0"])
    return seg.x0

def _unreadable(exc: BaseException) -> PdfImportError:
    """The user-facing error for a PDF the parser rejected. pdfplumber wraps pdfminer's
    exceptions, so the password case is found by walking the wrapped causes."""
    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect

    seen: BaseException | None = exc
    for _ in range(4):
        if seen is None:
            break
        if isinstance(seen, (PDFPasswordIncorrect, PDFEncryptionError)):
            return PdfImportError(
                "This PDF is password-protected. Save a copy without a password and upload that."
            )
        wrapped = next((a for a in seen.args if isinstance(a, BaseException)), None)
        seen = wrapped or seen.__cause__
    return PdfImportError(f"This file isn't a readable PDF ({exc or type(exc).__name__}).")

def extract_lines(raw: bytes) -> tuple[list[Line], list[str]]:
    """Physical lines of every page in reading order, plus the PDF's link targets."""
    import pdfplumber  # imported lazily: only PDF import needs it

    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as exc:
        raise _unreadable(exc) from exc
    try:
        if len(pdf.pages) > MAX_PAGES:
            raise PdfImportError(
                f"This PDF has {len(pdf.pages)} pages. Upload your resume only "
                f"(at most {MAX_PAGES} pages)."
            )
        lines: list[Line] = []
        links: list[str] = []
        for index, page in enumerate(pdf.pages):
            lines.extend(_page_lines(page, index))
            for link in page.hyperlinks or []:
                uri = str(link.get("uri") or "").strip()
                if uri and uri not in links:
                    links.append(uri)
    except PdfImportError:
        raise
    except Exception as exc:
        raise _unreadable(exc) from exc
    finally:
        pdf.close()
    if sum(len(ln.text.strip()) for ln in lines) < MIN_TEXT_CHARS:
        raise PdfImportError(
            "This PDF has no readable text; it is probably a scan or an image. Export it "
            "again as a PDF with text from the app you made it in, or upload the .docx."
        )
    return lines, links

# --------------------------------------------------------------------------------------
# 2. Clean-up and joining wrapped lines
# --------------------------------------------------------------------------------------
def _normalise(line: Line) -> Line | None:
    text = unicodedata.normalize("NFKC", line.text)
    match = pdf_patterns._BULLET_RE.match(text)
    if match:
        line.bullet = True
        text = text[match.end() :]
    else:
        line.text_x0 = line.x0
    text = pdf_patterns._PUA_RE.sub(" ", text)
    text = "\t".join(re.sub(r"\s+", " ", part).strip() for part in text.split("\t"))
    text = re.sub(r"\t+", "\t", text).strip("\t ")
    if not text or entry_structure._is_chrome(text):
        return None
    line.text = text
    return line

def _repeated_chrome(lines: list[Line]) -> set[int]:
    """Indices of running headers/footers (same text, same height, several pages) and
    page numbers in the top or bottom margin."""
    pages = {ln.page for ln in lines}
    drop: set[int] = set()
    if len(pages) > 1:
        seen: dict[tuple[str, int], set[int]] = {}
        for ln in lines:
            key = (re.sub(r"\d+", "#", ln.text.lower()), round(ln.top / 3))
            seen.setdefault(key, set()).add(ln.page)
        for i, ln in enumerate(lines):
            key = (re.sub(r"\d+", "#", ln.text.lower()), round(ln.top / 3))
            if len(seen[key]) > 1:
                drop.add(i)
    for i, ln in enumerate(lines):
        if (ln.rel_top < 0.08 or ln.rel_top > 0.92) and pdf_patterns._PAGE_NUMBER_RE.match(ln.text):
            drop.add(i)
    return drop

def _continues(prev: Line, cur: Line, first_on_page: bool) -> bool:
    """Whether `cur` is a wrapped continuation of `prev`."""
    if cur.bullet or "\t" in cur.text or "\t" in prev.text or pdf_structure._heading_text(cur.text):
        return False
    same_flow = cur.page == prev.page and 0 < cur.top - prev.last_top <= 1.9 * max(prev.size, 1)
    page_turn = first_on_page and cur.page == prev.page + 1
    if not (same_flow or page_turn) or abs(cur.size - prev.size) > 0.6:
        return False
    tol = max(3.0, 0.5 * cur.size)
    if prev.bullet:
        return abs(cur.x0 - prev.text_x0) <= tol and not pdf_patterns._DATE_FULL_RE.match(cur.text)
    if abs(cur.x0 - prev.x0) > tol or prev.bold != cur.bold:
        return False
    tail = prev.text.rstrip()
    return (
        tail.endswith((",", "-", "\u00ad", "&", ";", "/"))
        or tail.lower().endswith((" and", " of", " the", " with", " for", " in"))
        or cur.text[:1].islower()
    )

def _join(prev: str, cur: str) -> str:
    """Join a wrapped line. A soft hyphen disappears; a hard one stays and takes no
    space ("cross-" + "functional"), since a real compound is more common than an
    auto-hyphenated break and never invents a word."""
    if prev.endswith("\u00ad"):
        return prev[:-1] + cur
    if prev.endswith("-") and cur[:1].isalpha():
        return prev + cur
    return f"{prev} {cur}"

def clean_lines(lines: list[Line]) -> list[Line]:
    """Normalise, drop chrome, and join wrapped lines into logical lines."""
    drop = _repeated_chrome(lines)
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    normalised = [n for n in (_normalise(ln) for ln in kept) if n is not None]
    out: list[Line] = []
    last_page = -1
    for ln in normalised:
        first_on_page = ln.page != last_page
        last_page = ln.page
        if out and _continues(out[-1], ln, first_on_page):
            prev = out[-1]
            prev.text = _join(prev.text, ln.text)
            prev.last_top = ln.top
            if ln.page != prev.page:
                prev.page = ln.page
            continue
        out.append(ln)
    for ln in out:
        ln.text = ln.text.replace("\u00ad", "")
    return out
