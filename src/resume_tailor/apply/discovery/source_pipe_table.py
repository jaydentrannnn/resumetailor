"""Parse pipe-table internship READMEs (``kind="pipe_table"``)."""

from __future__ import annotations

import re
from typing import Any

from . import source_headings, source_rows

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}

_MONTH_DAY_RE = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?$")

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

def parse_posted(text: str, *, today: Any = None) -> tuple[int | None, str]:
    """``(age_days, iso_date)`` for a README "posted" cell.

    Accepts an age token (``3d``, ``15m`` — no date), an ISO date (``2026-08-30``),
    or a month-day date (``Aug 01``, ``Sep 29``) read as its most recent past
    occurrence; a date up to two days ahead is taken as this year (time zones).
    Returns ``(None, "")`` when the cell does not parse.
    """
    from datetime import date, timedelta

    cleaned = re.sub(r"<[^>]+>|\*", "", text or "").strip()
    age = source_rows.parse_age(cleaned)
    if age is not None:
        return age, ""
    today = today or date.today()
    iso = _ISO_DATE_RE.match(cleaned)
    try:
        if iso:
            when = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        else:
            match = _MONTH_DAY_RE.match(cleaned)
            month = _MONTHS.get(match.group(1)[:3].lower()) if match else None
            if not match or not month:
                return None, ""
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else today.year
            when = date(year, month, day)
            if not match.group(3) and when > today + timedelta(days=2):
                when = date(year - 1, month, day)
    except ValueError:
        return None, ""
    return max(0, (today - when).days), when.isoformat()

def _pipe_cell_href(cell: str) -> str | None:
    """Extract the first href or markdown link URL from a pipe-table cell."""
    html_match = re.search(r'href=["\']([^"\']+)["\']', cell, re.I)
    if html_match:
        return html_match.group(1)
    md_match = re.search(r"\]\(([^)\s]+)\)", cell)
    if md_match:
        return md_match.group(1)
    return None

def _clean_pipe_text(cell: str) -> str:
    """Plain text of a pipe-table cell: markdown links keep their label, tags go."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", text).strip()

def _clean_pipe_company(cell: str) -> str:
    """Strip HTML / markdown emphasis and links from a company cell."""
    return _clean_pipe_text(cell)

def _clean_pipe_location(cell: str) -> str:
    """A location cell as ``A | B``: ``<br>`` separates places, "N locations" goes."""
    text = re.sub(r"<summary>.*?</summary>", "", cell, flags=re.I | re.S)
    text = re.sub(r"<\s*/?\s*br\s*/?\s*>", " | ", text, flags=re.I)
    parts = [_clean_pipe_text(part) for part in text.split(" | ")]
    return " | ".join(part for part in parts if part)

#: Header text (lowercased, markup stripped) -> column role. Other columns
#: ("Work Model", "Visa", …) are ignored.
_PIPE_HEADER_ALIASES: dict[str, str] = {
    "company": "company",
    "employer": "company",
    "role": "role",
    "position": "role",
    "job title": "role",
    "title": "role",
    "location": "location",
    "locations": "location",
    "salary": "salary",
    "posting": "apply",
    "apply": "apply",
    "application": "apply",
    "application/link": "apply",
    "link": "apply",
    "apply link": "apply",
    "age": "age",
    "posted": "age",
    "date posted": "age",
    "added": "age",
    "date added": "age",
    "date": "age",
}

#: Query parameters that only track the click; dropped so ids stay stable.
_TRACKING_PARAMS = re.compile(
    r"^(utm_\w+|ref|source|src|s|gh_src|lever-source|lever-origin|trk)$", re.I
)

def _map_pipe_headers(cells: list[str]) -> dict[str, int]:
    """Map canonical column roles to indices from a header row (first match wins)."""
    mapping: dict[str, int] = {}
    for index, cell in enumerate(cells):
        role = _PIPE_HEADER_ALIASES.get(_clean_pipe_text(cell).lower())
        if role and role not in mapping:
            mapping[role] = index
    return mapping

def _split_pipe_row(line: str) -> list[str]:
    """Cells of one ``| a | b |`` line."""
    return [c.strip() for c in line.strip().strip("|").split("|")]

def _is_separator(line: str) -> bool:
    """True for a ``|---|:---:|`` table separator line."""
    cells = [c for c in _split_pipe_row(line) if c]
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)

def _clean_apply_href(href: str) -> str:
    """Drop tracking query parameters; a ``gh_jid`` link is kept whole (stable ids)."""
    if "gh_jid=" in href or "?" not in href:
        return href
    base, _, query = href.partition("?")
    kept = [
        part
        for part in query.split("&")
        if part and not _TRACKING_PARAMS.match(part.split("=", 1)[0])
    ]
    return f"{base}?{'&'.join(kept)}" if kept else base

def _strip_title_flags(text: str) -> str:
    """A role without the Simplify-style emoji flags."""
    for flag in (
        source_rows.GRAD_FLAG,
        source_rows.US_CITIZEN_FLAG,
        source_rows.NO_SPONSOR_FLAG,
        source_rows.FAANG_FLAG,
    ):
        text = text.replace(flag, "")
    return re.sub(r"\s+", " ", text).strip()

def _parse_pipe_rows(
    lines: list[str], start: int, end: int, *, today: Any = None
) -> list[source_rows.SourceRow]:
    """Parse markdown pipe-table rows inside one section range.

    Each table's header row (the line above its ``|---|`` separator) maps that
    table's columns, so tables with different layouts can share a section. The apply
    link comes from the apply column, else from a link on the role (jobright-style).
    A ``↳`` company repeats the row above; Simplify's title flags (🛂 🇺🇸 🎓) count.
    """
    import hashlib

    out: list[source_rows.SourceRow] = []
    col: dict[str, int] | None = None
    last_company = ""
    chunk = lines[start:end]
    for index, line in enumerate(chunk):
        if not line.strip().startswith("|") or _is_separator(line):
            continue
        if index + 1 < len(chunk) and _is_separator(chunk[index + 1]):
            mapped = _map_pipe_headers(_split_pipe_row(line))
            usable = "company" in mapped and ("apply" in mapped or "role" in mapped)
            col = mapped if usable else None
            last_company = ""
            continue
        if col is None:
            continue
        cells = _split_pipe_row(line)
        columns = col

        def _cell(name: str, cells: list[str] = cells, columns: dict[str, int] = columns) -> str:
            """Return the cell for a mapped column name, or empty."""
            idx = columns.get(name)
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx]

        raw_role = _cell("role")
        company = _clean_pipe_company(_cell("company"))
        if company in ("↳", ""):
            company = last_company
        else:
            last_company = company
        href = _pipe_cell_href(_cell("apply")) if "apply" in col else None
        if not href:
            href = _pipe_cell_href(raw_role)
        if not href or not company:
            continue
        href = _clean_apply_href(href)
        age_days, posted_at = parse_posted(_cell("age"), today=today)
        out.append(
            source_rows.SourceRow(
                company=_strip_title_flags(company),
                role=_strip_title_flags(_clean_pipe_text(raw_role)),
                location=_clean_pipe_location(_cell("location")),
                age=_clean_pipe_text(_cell("age")),
                age_days=age_days,
                posted_at=posted_at,
                job_id=hashlib.sha1(href.encode("utf-8")).hexdigest()[:16],
                application_link=href,
                salary=_clean_pipe_text(_cell("salary")),
                sponsorship_ok="No" if source_rows.NO_SPONSOR_FLAG in raw_role else "Unknown",
                citizenship_required="Yes" if source_rows.US_CITIZEN_FLAG in raw_role else "No",
                advanced_degree=source_rows.GRAD_FLAG in raw_role,
            )
        )
    return out

def _without_international(
    ranges: list[tuple[int, str, int, int]], level: int, start: int, end: int
) -> list[tuple[int, int]]:
    """``(start, end)`` segments of a range with nested International sections cut out."""
    skip_ranges = [
        (s, e)
        for lvl, name, s, e in ranges
        if s > start and e <= end and lvl > level and "international" in name.casefold()
    ]
    keep_segments: list[tuple[int, int]] = [(start, end)]
    for skip_start, skip_end in sorted(skip_ranges):
        next_segments: list[tuple[int, int]] = []
        for seg_start, seg_end in keep_segments:
            if skip_end <= seg_start or skip_start >= seg_end:
                next_segments.append((seg_start, seg_end))
                continue
            if seg_start < skip_start:
                next_segments.append((seg_start, skip_start))
            if skip_end < seg_end:
                next_segments.append((skip_end, seg_end))
        keep_segments = next_segments
    return keep_segments

def parse_pipe_table_readme(
    text: str, categories: list[str], *, today: Any = None
) -> list[source_rows.SourceRow]:
    """Parse requested categories from a speedyapply-style pipe-table README.

    Section ranges are depth-aware: a category matches by normalized name and
    ends at the next header of equal or higher level. Nested sections whose
    names contain ``International`` are skipped even when under a matched parent.
    Empty ``categories`` reads the whole README (still skipping International).
    """
    lines = text.splitlines(keepends=True)
    ranges = source_headings._depth_sections(lines)
    by_name = {name: (level, start, end) for level, name, start, end in ranges}
    if categories:
        targets = [by_name[c] for c in categories if c in by_name]
    else:
        targets = [(1, 0, len(lines))]
    rows: list[source_rows.SourceRow] = []
    for level, start, end in targets:
        for seg_start, seg_end in _without_international(ranges, level, start, end):
            rows.extend(_parse_pipe_rows(lines, seg_start, seg_end, today=today))
    return rows
