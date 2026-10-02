"""PDF -> `MasterResume` draft (content only; the layout still comes from a template).

A student's only copy of their resume is often a PDF (Canva, Google Docs, an old
export). This module reads its text layer and produces the same `ImportedResume` draft
the .docx importer does. The user reviews the draft before anything is saved, and a PDF
never becomes a template: tailoring still needs a .docx or a default template.

Pipeline:
1. `extract_lines`: characters from pdfplumber are grouped into rows by baseline, split
   into segments at wide gaps (a tab-aligned date becomes ``"\\t"``), and read column
   by column when the page has a persistent gutter (a two-column design).
2. `clean_lines`: NFKC (ligatures), bullet glyphs become a flag, private-use icon glyphs
   are stripped, repeated headers/footers and page numbers are dropped, and wrapped
   lines are joined back into logical lines.
3. Structuring, in one of two ways:
   - heuristic (always available): headings by text and shared style, entries by
     bullets and dates;
   - model-assisted (opt-in, `use_model=True`): the model is shown the numbered plain
     lines and answers with line numbers plus field strings. Every field string must be
     copied from the lines it cites (`_guard_field`); bullets are line numbers, so their
     text is always the PDF's own. Nothing the model writes reaches the draft unchecked.
4. `_build`: the same `data` models and tag seeding as `resume_import`.

The model call rides the ``extract`` purpose (like `propose.py`), keyed on its
fingerprint plus `_PROMPT_VERSION`.
"""

from __future__ import annotations

import hashlib
import io
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import config
from ..content.data import (
    Bullet,
    Contact,
    Education,
    EducationSection,
    Experience,
    ExperienceSection,
    ListItem,
    ListSection,
    MasterResume,
    Project,
    ProjectSection,
    Section,
    SkillGroup,
    SkillsSection,
    SummaryVariant,
)
from ..document import analysis_types, entry_structure
from ..document.render import parse_range
from .resume_import import UNTAGGED, ImportedResume, _default_vocabulary, _fresh_id, _seed_tags

_PROMPT_VERSION = 1

#: Fewer extracted characters than this means an image-only (scanned) PDF.
MIN_TEXT_CHARS = 50
#: A resume longer than this is almost certainly the wrong file.
MAX_PAGES = 10

_BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi", re.I)
_ITALIC_RE = re.compile(r"italic|oblique", re.I)
_PUA_RE = re.compile("[\ue000-\uf8ff]")
#: A bullet glyph at the start of a line. Hyphen, dash and asterisk count only when
#: followed by a space, so "-5% churn" or "*Expected" stay text.
_BULLET_RE = re.compile(
    "^\\s*(?:[\u2022\u25aa\u25e6\u25cf\u2023\u2043\u2219\u00b7\u25cb\u25a0\u25a1\u25ba"
    "\u25b6\u27a2\u27a4\u2713\u2714\u2756\u25c6\u25c7\ue000-\uf8ff]\\s*|[-\u2013\u2014*]\\s+)"
)
_PAGE_NUMBER_RE = re.compile(r"(?i)^(?:page\s*)?\d{1,3}(?:\s*(?:of|/)\s*\d{1,3})?$")
_SEPARATORS_RE = re.compile(r"\s+(?:\||\u2022|\u00b7|\u25aa)\s+")

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_SEASON = r"(?:spring|summer|fall|autumn|winter)"
_YEAR = r"(?:(?:19|20)\d{2}|['\u2019]\d{2})"
_POINT = rf"(?:(?:{_MONTH}|{_SEASON}),?\s+{_YEAR}|\d{{1,2}}/(?:19|20)?\d{{2}}|{_YEAR})"
_END = rf"(?:{_POINT}|present|current|now|ongoing)"
_DATE_SPAN = (
    rf"(?:(?:expected|anticipated|exp\.)\s+)?{_POINT}(?:\s*(?:-|\u2013|\u2014|to)\s*{_END})?"
    r"|present"
)
_DATE_FULL_RE = re.compile(rf"(?i)^\(?(?:{_DATE_SPAN})\)?$")
_DATE_TAIL_RE = re.compile(rf"(?i)[\s,|\u2013\u2014-]*\(?({_DATE_SPAN})\)?\s*$")
_LOCATION_RE = re.compile(
    r"^(?:remote|hybrid|[A-Z][A-Za-z.'\- ]{1,30},\s*(?:[A-Z]{2}|[A-Z][A-Za-z .'-]{2,30})"
    r"(?:\s+\d{5})?(?:\s*\((?:remote|hybrid)\))?)$",
    re.I,
)
_SCHOOL_RE = re.compile(r"(?i)\b(university|college|institute|school|academy|polytechnic)\b")
_GPA_RE = re.compile(r"(?i)[,|\s]*\(?\bGPA\b[:\s]*([0-9]\.[0-9]{1,2}(?:\s*/\s*[0-9.]+)?)\)?")
_COURSEWORK_RE = re.compile(r"(?i)^(?:relevant\s+)?course\s*work\s*:\s*(.+)$")
_LINK_RES = {
    "linkedin": re.compile(r"(?i)(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%.]+/?"),
    "github": re.compile(r"(?i)(?:https?://)?(?:www\.)?github\.com/[\w\-.]+/?"),
}
_URL_RE = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s|,]+|\b[\w-]+\.(?:com|io|dev|me|net|org)/[^\s|,]*"
)

_SUMMARY_TITLES = {
    "summary",
    "professional summary",
    "profile",
    "professional profile",
    "objective",
    "career objective",
    "about me",
}
_LIST_TITLES = {
    "certifications",
    "certificates",
    "licenses & certifications",
    "licenses and certifications",
    "awards",
    "honors",
    "honors & awards",
    "honors and awards",
    "awards & honors",
    "awards and honors",
    "publications",
    "languages",
    "interests",
    "relevant coursework",
    "coursework",
}
#: Headings whose section kind depends on its body: entries with bullets read as
#: experience, one-line items as a list.
_SHAPED_TITLES = {
    "leadership",
    "activities",
    "involvement",
    "campus involvement",
    "extracurricular activities",
    "extracurriculars",
    "volunteering",
    "volunteer",
    "community service",
    "research",
    "leadership & activities",
    "leadership and activities",
}

SectionKind = Literal["experience", "project", "education", "skills", "list", "summary"]


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
    bold = sum(1 for c in letters if _BOLD_RE.search(str(c.get("fontname", "")))) > len(letters) / 2
    italic = (
        sum(1 for c in letters if _ITALIC_RE.search(str(c.get("fontname", "")))) > len(letters) / 2
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
    if chars and _BULLET_RE.match(chars[0]["text"] + " ") and len(chars) > 1:
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
    match = _BULLET_RE.match(text)
    if match:
        line.bullet = True
        text = text[match.end() :]
    else:
        line.text_x0 = line.x0
    text = _PUA_RE.sub(" ", text)
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
        if (ln.rel_top < 0.08 or ln.rel_top > 0.92) and _PAGE_NUMBER_RE.match(ln.text):
            drop.add(i)
    return drop


def _continues(prev: Line, cur: Line, first_on_page: bool) -> bool:
    """Whether `cur` is a wrapped continuation of `prev`."""
    if cur.bullet or "\t" in cur.text or "\t" in prev.text or _heading_text(cur.text):
        return False
    same_flow = cur.page == prev.page and 0 < cur.top - prev.last_top <= 1.9 * max(prev.size, 1)
    page_turn = first_on_page and cur.page == prev.page + 1
    if not (same_flow or page_turn) or abs(cur.size - prev.size) > 0.6:
        return False
    tol = max(3.0, 0.5 * cur.size)
    if prev.bullet:
        return abs(cur.x0 - prev.text_x0) <= tol and not _DATE_FULL_RE.match(cur.text)
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


# --------------------------------------------------------------------------------------
# 3a. Heuristic structure
# --------------------------------------------------------------------------------------


@dataclass
class _Entry:
    primary: str = ""
    secondary: str = ""
    location: str = ""
    dates: str = ""
    extra: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


@dataclass
class _Draft:
    kind: SectionKind
    title: str
    entries: list[_Entry] = field(default_factory=list)
    #: skills / list / summary: logical lines in order.
    lines: list[str] = field(default_factory=list)


def _title_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(":").strip()).lower()


def _heading_text(text: str) -> SectionKind | Literal["shaped"] | None:
    """Section kind a heading's text names, or None when it isn't heading-shaped."""
    stripped = text.strip().rstrip(":").strip()
    if (
        not stripped
        or "\t" in text
        or len(stripped.split()) > 5
        or len(stripped) > 48
        or "@" in stripped
        or "," in stripped
        or (_DATE_TAIL_RE.search(stripped) and re.search(r"\d", stripped))
    ):
        return None
    key = _title_key(stripped)
    if key in _SUMMARY_TITLES:
        return "summary"
    if key in _LIST_TITLES:
        return "list"
    if key in _SHAPED_TITLES:
        return "shaped"
    kind, confidence, _alias = entry_structure._classify_heading(stripped)
    if kind is not None and confidence >= 0.55:
        return {"projects": "project"}.get(kind, kind)  # type: ignore[return-value]
    return None


def _signature(line: Line) -> tuple[float, bool, bool]:
    letters = [c for c in line.text if c.isalpha()]
    upper = bool(letters) and all(c.isupper() for c in letters)
    return round(line.size), line.bold, upper


def _find_headings(lines: list[Line]) -> dict[int, SectionKind | Literal["shaped"]]:
    """Heading line index -> kind. Known titles first; then any short line styled
    exactly like them (a custom title such as "LEADERSHIP & IMPACT")."""
    body_size = statistics.median(ln.size for ln in lines) if lines else 10
    found: dict[int, SectionKind | Literal["shaped"]] = {}
    for i, ln in enumerate(lines):
        kind = _heading_text(ln.text)
        if kind is None or ln.bullet:
            continue
        sig = _signature(ln)
        stands_out = sig[1] or sig[2] or ln.size >= body_size + 0.5 or ln.text.strip().endswith(":")
        if stands_out:
            found[i] = kind
    styles = {_signature(lines[i]) for i in found}
    for i, ln in enumerate(lines):
        if i in found or ln.bullet or "\t" in ln.text or i == 0:
            continue
        stripped = ln.text.strip().rstrip(":")
        sig = _signature(ln)
        if (
            sig in styles
            and (sig[1] or sig[2])
            and len(stripped.split()) <= 4
            and not re.search(r"\d|@|,", stripped)
        ):
            found[i] = "shaped"
    if not found:
        for i, ln in enumerate(lines):
            if i and not ln.bullet and entry_structure._looks_like_heading(ln.text):
                found[i] = "shaped"
    return found


def _split_segments(text: str) -> list[str]:
    parts: list[str] = []
    for chunk in text.split("\t"):
        parts.extend(p.strip() for p in _SEPARATORS_RE.split(chunk) if p.strip())
    return parts


def _parse_header(lines: list[Line], kind: SectionKind) -> _Entry:
    """Company/title/location/dates (or project name/tech/date, or school/degree) from
    an entry's header lines."""
    entry = _Entry()
    others: list[tuple[str, bool]] = []
    for ln in lines:
        for seg in _split_segments(ln.text):
            if not entry.dates and _DATE_FULL_RE.match(seg):
                entry.dates = seg.strip("()")
                continue
            if (
                not entry.location
                and _LOCATION_RE.match(seg)
                and kind != "project"
                and not _SCHOOL_RE.search(seg)
            ):
                entry.location = seg
                continue
            tail = _DATE_TAIL_RE.search(seg)
            if not entry.dates and tail and tail.start() > 0:
                entry.dates = tail.group(1)
                seg = seg[: tail.start()].strip()
            if seg:
                others.append((seg, ln.italic))
    if len(others) == 1 and kind in ("experience", "project"):
        dash = re.split(r"\s+[\u2013\u2014-]\s+", others[0][0], maxsplit=1)
        if len(dash) == 2:
            others = [(dash[0], others[0][1]), (dash[1], others[0][1])]
    if kind == "education":
        school_at = next((i for i, (s, _) in enumerate(others) if _SCHOOL_RE.search(s)), 0)
        if school_at and others:
            others.insert(0, others.pop(school_at))
    elif len(others) >= 2 and others[0][1] and not others[1][1]:
        others[0], others[1] = others[1], others[0]  # the italic line is the title
    if others:
        entry.primary = others[0][0]
    if len(others) > 1:
        entry.secondary = others[1][0]
    entry.extra = [s for s, _ in others[2:]]
    return entry


def _entries(body: list[Line], kind: SectionKind) -> list[_Entry]:
    """Split a section body into entries: a header block of non-bullet lines, then its
    bullets. Education entries start at each school line instead."""
    groups: list[tuple[list[Line], list[Line]]] = []
    for ln in body:
        is_bullet = ln.bullet
        if kind == "education" and not is_bullet:
            starts = _SCHOOL_RE.search(ln.text) and not _COURSEWORK_RE.match(ln.text)
            header = groups[-1][0] if groups else []
            if not groups or (starts and header and _SCHOOL_RE.search(header[0].text)):
                groups.append(([ln], []))
            elif _DATE_FULL_RE.match(ln.text) or (
                len(header) < 2 and not groups[-1][1] and not _detail_line(ln.text)
            ):
                header.append(ln)
            else:
                groups[-1][1].append(ln)
            continue
        if is_bullet:
            if not groups:
                groups.append(([], []))
            groups[-1][1].append(ln)
        elif not groups or groups[-1][1]:
            groups.append(([ln], []))
        elif len(groups[-1][0]) >= 3 or (
            len(groups[-1][0]) >= 2 and len(ln.text) > 70 and not _DATE_TAIL_RE.search(ln.text)
        ):
            # A resume whose bullets lost their glyphs: long lines after the header.
            groups[-1][1].append(ln)
        else:
            groups[-1][0].append(ln)
    out: list[_Entry] = []
    for header, rest in groups:
        entry = _parse_header(header, kind)
        for ln in rest:
            if kind == "education":
                entry.details.append(ln.text)
            else:
                entry.bullets.append(ln.text.replace("\t", " "))
        out.append(entry)
    return out


def _detail_line(text: str) -> bool:
    return bool(_COURSEWORK_RE.match(text) or re.match(r"(?i)^\s*(gpa|honors|awards?)\b", text))


def _shape(body: list[Line]) -> SectionKind:
    has_bullets = any(ln.bullet for ln in body)
    has_headers = any(not ln.bullet for ln in body)
    return "experience" if has_bullets and has_headers else "list"


def _structure(lines: list[Line]) -> tuple[list[Line], list[_Draft]]:
    """(preamble lines before the first heading, section drafts)."""
    headings = _find_headings(lines)
    if not headings:
        return lines, []
    order = sorted(headings)
    drafts: list[_Draft] = []
    for n, start in enumerate(order):
        end = order[n + 1] if n + 1 < len(order) else len(lines)
        body = lines[start + 1 : end]
        title = lines[start].text.strip().rstrip(":").strip()
        found = headings[start]
        kind: SectionKind = _shape(body) if found == "shaped" else found
        if kind in ("experience", "project", "education"):
            drafts.append(_Draft(kind=kind, title=title, entries=_entries(body, kind)))
        else:
            drafts.append(_Draft(kind=kind, title=title, lines=[ln.text for ln in body]))
    return lines[: order[0]], drafts


# --------------------------------------------------------------------------------------
# 3b. Model-assisted structure (opt-in)
# --------------------------------------------------------------------------------------


class ImportEntryLLM(BaseModel):
    header_lines: list[int] = Field(default_factory=list)
    primary: str = ""
    secondary: str = ""
    location: str = ""
    dates: str = ""
    bullet_lines: list[int] = Field(default_factory=list)
    detail_lines: list[int] = Field(default_factory=list)


class ImportSectionLLM(BaseModel):
    heading_line: int
    kind: SectionKind
    entries: list[ImportEntryLLM] = Field(default_factory=list)


class ImportLLM(BaseModel):
    name_line: int = 0
    sections: list[ImportSectionLLM] = Field(default_factory=list)


_SYSTEM = """\
You organise the text of a resume that was extracted from a PDF. You are given its \
lines, numbered; bullet points start with "• ". Group the lines into sections and \
entries by line number.

Never rewrite, shorten or add text. Every field you return must be copied exactly from \
the lines you cite, and bullets and details are given only as line numbers.

- name_line: the line with the person's name.
- sections: one per section heading line. kind is one of: experience (jobs, \
internships, leadership, research, volunteering, activities with roles), project, \
education, skills, list (certifications, awards, languages, interests, anything that is \
one item per line), summary.
- For experience, project and education sections, one entry per job, project or \
school. header_lines are the lines that name it. primary is the company or \
organisation, the project name, or the school. secondary is the job title, the \
project's technologies, or the degree. location and dates exactly as printed, or empty. \
bullet_lines are its bullet points; detail_lines are its other lines (coursework, GPA, \
honors).
- For skills, list and summary sections, use one entry whose bullet_lines and \
detail_lines list the section's lines in order.
- Leave out only the contact line and page headers or footers."""


def _numbered(lines: list[Line]) -> str:
    return "\n".join(
        f"[{i}] {'• ' if ln.bullet else ''}{ln.text.replace(chr(9), '   ')}"
        for i, ln in enumerate(lines)
    )


def _cache_path(text: str):
    payload = "\n".join([str(_PROMPT_VERSION), config.fingerprint("extract"), text])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.pdfimport.json"


def _ask_model(lines: list[Line], *, use_cache: bool = True) -> ImportLLM:
    from ..infra import llm

    text = _numbered(lines)
    path = _cache_path(text)
    if use_cache and path.exists():
        return ImportLLM.model_validate_json(path.read_text(encoding="utf-8"))
    client = llm.client_for("extract")
    response = client.messages.parse(
        model=config.model_for("extract"),
        max_tokens=config.max_tokens_for("extract"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"<lines>\n{text}\n</lines>"}],
        output_format=ImportLLM,
        output_config={"effort": config.effort_for("extract")},
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(
            f"Model did not return a parseable structure (stop_reason={response.stop_reason!r})."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(parsed.model_dump_json(indent=2), encoding="utf-8")
    return parsed


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _guard_field(value: str, source: str) -> str | None:
    """`value` if it is copied from `source` (whitespace/case aside, or a near-exact
    match of one of its segments), else None. This is the import's fabrication guard."""
    value = value.strip()
    if not value:
        return ""
    if _squash(value) in _squash(source):
        return value
    for seg in _split_segments(source):
        if SequenceMatcher(None, _squash(value), _squash(seg)).ratio() >= 0.9:
            return seg
    return None


def _from_model(
    lines: list[Line], answer: ImportLLM, warnings: list[str]
) -> tuple[int, list[_Draft]]:
    """(index of the first heading, drafts) from the model's answer, every string checked."""
    used: set[int] = set()

    def take(indices: list[int]) -> list[Line]:
        out = []
        for i in indices:
            if 0 <= i < len(lines) and i not in used:
                used.add(i)
                out.append(lines[i])
        return out

    drafts: list[_Draft] = []
    sections = sorted(
        (s for s in answer.sections if 0 <= s.heading_line < len(lines)),
        key=lambda s: s.heading_line,
    )
    for sec in sections:
        if sec.heading_line in used:
            continue
        used.add(sec.heading_line)
        title = lines[sec.heading_line].text.strip().rstrip(":").strip()
        draft = _Draft(kind=sec.kind, title=title)
        for raw in sec.entries:
            if sec.kind in ("skills", "list", "summary"):
                picked = take(sorted([*raw.bullet_lines, *raw.detail_lines]))
                draft.lines.extend(ln.text for ln in picked)
                continue
            header = take(raw.header_lines)
            source = "\t".join(ln.text for ln in header)
            entry = _Entry()
            for name in ("primary", "secondary", "location", "dates"):
                value = getattr(raw, name)
                checked = _guard_field(value, source)
                if checked is None:
                    warnings.append(
                        f"{title}: dropped {value!r}, which isn't in the PDF's text for that entry."
                    )
                    checked = ""
                setattr(entry, name, checked)
            if not entry.primary and header:
                entry = _parse_header(header, sec.kind)
            entry.bullets = [ln.text.replace("\t", " ") for ln in take(raw.bullet_lines)]
            entry.details = [ln.text for ln in take(raw.detail_lines)]
            if sec.kind == "education":
                entry.details = [*entry.bullets, *entry.details]
                entry.bullets = []
            draft.entries.append(entry)
        drafts.append(draft)
    first = sections[0].heading_line if sections else len(lines)
    unplaced = [
        lines[i].text for i in range(first, len(lines)) if i not in used and lines[i].text.strip()
    ]
    if unplaced:
        shown = "; ".join(repr(t[:60]) for t in unplaced[:5])
        more = f" and {len(unplaced) - 5} more" if len(unplaced) > 5 else ""
        warnings.append(f"{len(unplaced)} line(s) weren't placed in any section: {shown}{more}.")
    return first, drafts


# --------------------------------------------------------------------------------------
# 4. Build the MasterResume
# --------------------------------------------------------------------------------------


def _contact(preamble: list[Line], links: list[str], warnings: list[str]) -> tuple[Contact, str]:
    """(contact, leftover preamble text that reads as a summary)."""
    if not preamble:
        warnings.append("No name or contact line was found at the top of the PDF.")
        return Contact(name="", email=""), ""
    name_line = max(preamble[:3], key=lambda ln: ln.size)
    rest = [ln for ln in preamble if ln is not name_line]
    text = " | ".join(ln.text.replace("\t", " | ") for ln in rest)
    email_m = analysis_types._EMAIL_RE.search(text)
    phone = ""
    phone_m = analysis_types._PHONE_RE.search(text)
    if phone_m and not analysis_types._DATE_RE.search(phone_m.group(0)):
        phone = phone_m.group(0)
        if phone_m.start() > 0 and text[phone_m.start() - 1] == "(":
            phone = "(" + phone
    found = {key: "" for key in _LINK_RES}
    others: list[str] = []
    for uri in links:
        low = uri.lower()
        if low.startswith("mailto:"):
            continue
        key = next((k for k in _LINK_RES if f"{k}.com" in low), None)
        if key and not found[key]:
            found[key] = uri
        elif not key and uri not in others:
            others.append(uri)
    for key, pattern in _LINK_RES.items():
        m = pattern.search(text)
        if m and not found[key]:
            found[key] = m.group(0)
    location = ""
    summary: list[str] = []
    for ln in rest:
        segments = _split_segments(ln.text)
        contact_like = False
        for seg in segments:
            if (
                "@" in seg
                or analysis_types._PHONE_RE.fullmatch(seg.strip("() "))
                or _URL_RE.search(seg)
                or any(p.search(seg) for p in _LINK_RES.values())
                or seg.lower() in ("linkedin", "github", "portfolio")
            ):
                contact_like = True
            elif not location and _LOCATION_RE.match(seg):
                location = seg
                contact_like = True
        if not contact_like and len(ln.text) > 40:
            summary.append(ln.text)
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".")
        is_profile = any(p.search(url) for p in _LINK_RES.values())
        if not is_profile and "@" not in url and url not in others:
            others.append(url)
    email = email_m.group(0) if email_m else ""
    if not email:
        warnings.append("No email address was found; add it in the editor.")
    contact = Contact(
        name=name_line.text.replace("\t", " ").strip(),
        email=email,
        phone=phone,
        location=location,
        linkedin=found["linkedin"],
        github=found["github"],
        links=others[:5],
    )
    return contact, " ".join(summary)


def _bullets(texts: list[str], entry_id: str, vocabulary: set[str]) -> list[Bullet]:
    return [
        Bullet(
            id=f"{entry_id}_b{i}",
            text=text,
            tags=_seed_tags(text, vocabulary) or [UNTAGGED],
            metric=bool(re.search(r"\d", text)),
        )
        for i, text in enumerate((t.strip() for t in texts), start=1)
        if text
    ]


def _skill_groups(lines: list[str], title: str, warnings: list[str]) -> list[SkillGroup]:
    """One group per "Label: items" line. Lines with no label (a sidebar listing one
    skill per line) are gathered into a single group named after the heading."""
    groups: list[SkillGroup] = []
    unlabelled: list[str] = []
    for text in lines:
        flat = text.replace("\t", " ")
        label, sep, items = flat.partition(":")
        if not sep:
            items = flat
        values = [i.strip() for i in re.split(r"[,;]| \u2022 | \| ", items) if i.strip()]
        if not sep:
            unlabelled.extend(values)
        elif label.strip() and values:
            groups.append(SkillGroup(label=label.strip(), items=values))
    if unlabelled:
        name = title.strip().title() or "Skills"
        groups.append(SkillGroup(label=name, items=unlabelled))
        warnings.append(f"Skills without a label were grouped as {name!r}; rename it if needed.")
    return groups


def _education(entry: _Entry) -> Education:
    degree = entry.secondary
    gpa = ""
    details: list[str] = []
    coursework: list[str] = []
    for text in [degree, *entry.extra, *entry.details]:
        m = _GPA_RE.search(text)
        if m and not gpa:
            gpa = m.group(1).strip()
            if text is degree:
                degree = (degree[: m.start()] + degree[m.end() :]).strip(" ,|")
                continue
            rest = (text[: m.start()] + text[m.end() :]).strip(" ,|")
            if rest:
                details.append(rest)
            continue
        if text is degree:
            continue
        cw = _COURSEWORK_RE.match(text)
        if cw and not coursework:
            coursework = [c.strip() for c in re.split(r"[,;]", cw.group(1)) if c.strip()]
        elif text:
            details.append(text.replace("\t", " "))
    return Education(
        school=entry.primary,
        degree=degree,
        dates=entry.dates,
        location=entry.location,
        coursework=coursework,
        gpa=gpa,
        show_gpa=bool(gpa),
        details=details,
    )


def _build(
    contact: Contact,
    summary: str,
    drafts: list[_Draft],
    vocabulary: set[str],
    warnings: list[str],
) -> MasterResume:
    entry_ids: set[str] = set()
    section_ids: set[str] = set()
    sections: list[Section] = []
    summaries: list[SummaryVariant] = []
    if summary:
        summaries.append(SummaryVariant(id="summary", text=summary))
    for draft in drafts:
        sid = _fresh_id(draft.title, section_ids)
        if draft.kind == "summary":
            text = " ".join(t.replace("\t", " ") for t in draft.lines).strip()
            if text:
                summaries.append(SummaryVariant(id=_fresh_id("summary", section_ids), text=text))
            continue
        if draft.kind == "experience":
            jobs = []
            for e in draft.entries:
                start, end = parse_range(e.dates) if e.dates else ("", "")
                eid = _fresh_id(e.primary or "entry", entry_ids)
                label = e.primary or draft.title
                if not e.primary:
                    warnings.append(f"{draft.title}: an entry has no company or organisation.")
                if not e.dates:
                    warnings.append(f"{label}: no dates found.")
                if e.extra:
                    warnings.append(f"{label}: header text not used: {', '.join(e.extra)}.")
                jobs.append(
                    Experience(
                        id=eid,
                        company=e.primary,
                        title=e.secondary,
                        location=e.location,
                        start=start,
                        end=end,
                        bullets=_bullets(e.bullets, eid, vocabulary),
                    )
                )
            sections.append(ExperienceSection(id=sid, title=draft.title, entries=jobs))
        elif draft.kind == "project":
            projects = []
            for e in draft.entries:
                tech_text = next((s for s in [e.secondary, *e.extra] if "," in s), e.secondary)
                tech_text = re.sub(r"(?i)^(tech(nologies)?|tools|stack)\s*:\s*", "", tech_text)
                pid = _fresh_id(e.primary or "project", entry_ids)
                if not e.bullets:
                    warnings.append(f"{e.primary or draft.title}: no bullets found.")
                projects.append(
                    Project(
                        id=pid,
                        name=e.primary,
                        tech=[t.strip() for t in re.split(r"[,;]", tech_text) if t.strip()],
                        date=e.dates,
                        bullets=_bullets(e.bullets, pid, vocabulary),
                    )
                )
            sections.append(ProjectSection(id=sid, title=draft.title, entries=projects))
        elif draft.kind == "education":
            schools = [_education(e) for e in draft.entries]
            for school in schools:
                if not school.degree:
                    warnings.append(f"{school.school or draft.title}: no degree line found.")
            sections.append(EducationSection(id=sid, title=draft.title, entries=schools))
        elif draft.kind == "skills":
            groups = _skill_groups(draft.lines, draft.title, warnings)
            sections.append(SkillsSection(id=sid, title=draft.title, entries=groups))
        else:
            items = [
                ListItem(
                    id=_fresh_id(t, entry_ids),
                    text=t.replace("\t", " ").strip(),
                    tags=_seed_tags(t, vocabulary),
                )
                for t in draft.lines
                if t.strip()
            ]
            sections.append(ListSection(id=sid, title=draft.title, entries=items))
    resume = MasterResume(contact=contact, summary_variants=summaries, sections=sections)
    used = sorted({t for b in resume.all_bullets() for t in b.tags if t != UNTAGGED})
    return resume.model_copy(update={"tag_vocabulary": used})


def import_pdf(
    raw: bytes,
    *,
    known_tags: set[str] | None = None,
    use_model: bool = False,
    ask: Callable[[list[Line]], ImportLLM] | None = None,
) -> ImportedResume:
    """A reviewed-before-saving draft from a PDF's text. Raises `PdfImportError`.

    `use_model` adds the model-assisted structuring pass; any failure there falls back
    to the heuristic draft with a warning, so an unreachable model never blocks import.
    `ask` replaces the model call (tests).
    """
    physical, links = extract_lines(raw)
    return import_lines(
        clean_lines(physical), links, known_tags=known_tags, use_model=use_model, ask=ask
    )


def import_lines(
    lines: list[Line],
    links: list[str],
    *,
    known_tags: set[str] | None = None,
    use_model: bool = False,
    ask: Callable[[list[Line]], ImportLLM] | None = None,
) -> ImportedResume:
    """Structure already-cleaned logical lines into a draft. Shared by the PDF import
    and the .docx content-only import (`resume_import.import_content_only`)."""
    warnings: list[str] = []
    vocabulary = _default_vocabulary() if known_tags is None else set(known_tags)

    preamble, drafts = _structure(lines)
    if use_model:
        try:
            answer = (ask or _ask_model)(lines)
            model_warnings: list[str] = []
            first, model_drafts = _from_model(lines, answer, model_warnings)
            if model_drafts:
                preamble, drafts = lines[:first], model_drafts
                warnings.extend(model_warnings)
            else:
                warnings.append("The model found no sections; used the built-in reader instead.")
        except Exception as exc:  # the heuristic draft is always a valid answer
            warnings.append(f"Model-assisted import failed ({exc}); used the built-in reader.")

    if not drafts:
        warnings.append(
            "No section headings (Experience, Education…) were recognised; everything "
            "below your name was kept as one list for you to sort in the editor."
        )
        body = preamble[1:]
        preamble = preamble[:1] + [ln for ln in body if _is_contact_line(ln)]
        drafts = [
            _Draft(
                kind="list",
                title="Imported",
                lines=[ln.text for ln in body if not _is_contact_line(ln)],
            )
        ]

    contact, summary = _contact(preamble, links, warnings)
    resume = _build(contact, summary, drafts, vocabulary, warnings)
    untagged = sum(1 for b in resume.all_bullets() if b.tags == [UNTAGGED])
    if untagged:
        warnings.append(
            f"{untagged} bullet(s) could not be matched to a known tag and were marked "
            f'"{UNTAGGED}"; retag them before saving.'
        )
    return ImportedResume(resume=resume, warnings=warnings, untagged_bullet_count=untagged)


def _is_contact_line(line: Line) -> bool:
    return bool(
        analysis_types._EMAIL_RE.search(line.text)
        or any(p.search(line.text) for p in _LINK_RES.values())
    )
