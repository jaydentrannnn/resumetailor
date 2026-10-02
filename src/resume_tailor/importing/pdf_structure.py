"""Finding headings and entries in cleaned PDF lines (deterministic, no LLM)."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Literal

from ..document import entry_structure
from . import pdf_lines, pdf_patterns


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
    kind: pdf_patterns.SectionKind
    title: str
    entries: list[_Entry] = field(default_factory=list)
    #: skills / list / summary: logical lines in order.
    lines: list[str] = field(default_factory=list)

def _title_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(":").strip()).lower()

def _heading_text(text: str) -> pdf_patterns.SectionKind | Literal["shaped"] | None:
    """Section kind a heading's text names, or None when it isn't heading-shaped."""
    stripped = text.strip().rstrip(":").strip()
    if (
        not stripped
        or "\t" in text
        or len(stripped.split()) > 5
        or len(stripped) > 48
        or "@" in stripped
        or "," in stripped
        or (pdf_patterns._DATE_TAIL_RE.search(stripped) and re.search(r"\d", stripped))
    ):
        return None
    key = _title_key(stripped)
    if key in pdf_patterns._SUMMARY_TITLES:
        return "summary"
    if key in pdf_patterns._LIST_TITLES:
        return "list"
    if key in pdf_patterns._SHAPED_TITLES:
        return "shaped"
    kind, confidence, _alias = entry_structure._classify_heading(stripped)
    if kind is not None and confidence >= 0.55:
        return {"projects": "project"}.get(kind, kind)  # type: ignore[return-value]
    return None

def _signature(line: pdf_lines.Line) -> tuple[float, bool, bool]:
    letters = [c for c in line.text if c.isalpha()]
    upper = bool(letters) and all(c.isupper() for c in letters)
    return round(line.size), line.bold, upper

def _find_headings(
    lines: list[pdf_lines.Line],
) -> dict[int, pdf_patterns.SectionKind | Literal["shaped"]]:
    """Heading line index -> kind. Known titles first; then any short line styled
    exactly like them (a custom title such as "LEADERSHIP & IMPACT")."""
    body_size = statistics.median(ln.size for ln in lines) if lines else 10
    found: dict[int, pdf_patterns.SectionKind | Literal["shaped"]] = {}
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
        parts.extend(p.strip() for p in pdf_patterns._SEPARATORS_RE.split(chunk) if p.strip())
    return parts

def _parse_header(lines: list[pdf_lines.Line], kind: pdf_patterns.SectionKind) -> _Entry:
    """Company/title/location/dates (or project name/tech/date, or school/degree) from
    an entry's header lines."""
    entry = _Entry()
    others: list[tuple[str, bool]] = []
    for ln in lines:
        for seg in _split_segments(ln.text):
            if not entry.dates and pdf_patterns._DATE_FULL_RE.match(seg):
                entry.dates = seg.strip("()")
                continue
            if (
                not entry.location
                and pdf_patterns._LOCATION_RE.match(seg)
                and kind != "project"
                and not pdf_patterns._SCHOOL_RE.search(seg)
            ):
                entry.location = seg
                continue
            tail = pdf_patterns._DATE_TAIL_RE.search(seg)
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
        school_at = next(
            (i for i, (s, _) in enumerate(others) if pdf_patterns._SCHOOL_RE.search(s)), 0
        )
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

def _entries(body: list[pdf_lines.Line], kind: pdf_patterns.SectionKind) -> list[_Entry]:
    """Split a section body into entries: a header block of non-bullet lines, then its
    bullets. Education entries start at each school line instead."""
    groups: list[tuple[list[pdf_lines.Line], list[pdf_lines.Line]]] = []
    for ln in body:
        is_bullet = ln.bullet
        if kind == "education" and not is_bullet:
            starts = pdf_patterns._SCHOOL_RE.search(
                ln.text
            ) and not pdf_patterns._COURSEWORK_RE.match(ln.text)
            header = groups[-1][0] if groups else []
            if not groups or (starts and header and pdf_patterns._SCHOOL_RE.search(header[0].text)):
                groups.append(([ln], []))
            elif pdf_patterns._DATE_FULL_RE.match(ln.text) or (
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
            len(groups[-1][0]) >= 2
            and len(ln.text) > 70
            and not pdf_patterns._DATE_TAIL_RE.search(ln.text)
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
    return bool(
        pdf_patterns._COURSEWORK_RE.match(text) or re.match(r"(?i)^\s*(gpa|honors|awards?)\b", text)
    )

def _shape(body: list[pdf_lines.Line]) -> pdf_patterns.SectionKind:
    has_bullets = any(ln.bullet for ln in body)
    has_headers = any(not ln.bullet for ln in body)
    return "experience" if has_bullets and has_headers else "list"

def _structure(lines: list[pdf_lines.Line]) -> tuple[list[pdf_lines.Line], list[_Draft]]:
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
        kind: pdf_patterns.SectionKind = _shape(body) if found == "shaped" else found
        if kind in ("experience", "project", "education"):
            drafts.append(_Draft(kind=kind, title=title, entries=_entries(body, kind)))
        else:
            drafts.append(_Draft(kind=kind, title=title, lines=[ln.text for ln in body]))
    return lines[: order[0]], drafts
