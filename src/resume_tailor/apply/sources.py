"""Fetch and parse SimplifyJobs-style internship README tables."""

from __future__ import annotations

import re
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

US_CITIZEN_FLAG = "🇺🇸"
NO_SPONSOR_FLAG = "🛂"
GRAD_FLAG = "🎓"
FAANG_FLAG = "🔥"

SponsorshipOk = Literal["Unknown", "No"]

#: Posted-age token: optional spaces between the number and unit.
_AGE_RE = re.compile(
    r"^(\d+)\s*(m|min|h|hr|d|w|mo)$",
    re.IGNORECASE,
)


class SourceRow(BaseModel):
    """One parsed posting row from a category section."""

    company: str
    role: str
    location: str
    age: str
    age_days: int | None = None
    job_id: str | None = None
    application_link: str | None = None
    sponsorship_ok: SponsorshipOk = "Unknown"
    citizenship_required: str = "No"
    notes: str = ""
    advanced_degree: bool = False
    source_id: str = ""
    salary: str = ""
    flags: list[str] = Field(default_factory=list)


class FilterResult(BaseModel):
    """Outcome of ``filter_rows`` with dedupe and exclusion counts."""

    new_rows: list[SourceRow] = Field(default_factory=list)
    total_candidates: int = 0
    age_filtered_count: int = 0
    excluded_citizenship: int = 0
    excluded_advanced_degree: int = 0
    excluded_no_sponsorship: int = 0
    excluded_title: int = 0
    already_known: int = 0


def parse_age(text: str) -> int | None:
    """Convert a README age token into whole days, or ``None`` when unparseable.

    Minutes and hours collapse to 0 (same calendar day). Weeks are 7 days;
    months are approximated as 30 days.
    """
    cleaned = text.strip().lower()
    if not cleaned:
        return None
    match = _AGE_RE.match(cleaned)
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit in {"m", "min", "h", "hr"}:
        return 0
    if unit == "d":
        return amount
    if unit == "w":
        return amount * 7
    if unit == "mo":
        return amount * 30
    return None


def _find_sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map each ``## `` header (emoji stripped) to its line range."""
    headers: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        if line.startswith("## "):
            name = re.sub(r"[^\w,&\s]", "", line[3:]).strip()
            headers.append((name, index))
    sections: dict[str, tuple[int, int]] = {}
    for index, (name, start) in enumerate(headers):
        end = headers[index + 1][1] if index + 1 < len(headers) else len(lines)
        sections[name] = (start, end)
    return sections


def _parse_section(
    lines: list[str],
    start: int,
    end: int,
) -> list[SourceRow]:
    """Parse HTML table rows inside one README category chunk."""
    chunk = "".join(lines[start:end])
    soup = BeautifulSoup(chunk, "html.parser")
    out: list[SourceRow] = []
    last_company: str | None = None
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        company_td, role_td, loc_td, app_td, age_td = tds[:5]
        raw_company = company_td.get_text(" ", strip=True)
        raw_role = role_td.get_text(" ", strip=True)
        location = loc_td.get_text(" | ", strip=True)
        age = age_td.get_text(strip=True)

        us_flag = US_CITIZEN_FLAG in raw_company or US_CITIZEN_FLAG in raw_role
        no_sponsor = NO_SPONSOR_FLAG in raw_company or NO_SPONSOR_FLAG in raw_role
        faang = FAANG_FLAG in raw_company
        grad = GRAD_FLAG in raw_role

        company = raw_company.replace(FAANG_FLAG, "").strip()
        if company in ("↳", ""):
            company = last_company or ""
        else:
            last_company = company
        role = raw_role.replace(GRAD_FLAG, "").strip()

        job_id: str | None = None
        app_link: str | None = None
        for anchor in app_td.find_all("a", href=True):
            href = anchor["href"]
            match = re.search(r"simplify\.jobs/p/([a-f0-9\-]+)", href)
            if match:
                job_id = match.group(1)
            elif not app_link:
                app_link = href.split("?")[0]

        notes: list[str] = []
        if faang:
            notes.append("FAANG+")

        out.append(
            SourceRow(
                company=company,
                role=role,
                location=location,
                age=age,
                age_days=parse_age(age),
                job_id=job_id,
                application_link=app_link,
                sponsorship_ok="No" if no_sponsor else "Unknown",
                citizenship_required="Yes" if us_flag else "No",
                notes="; ".join(notes),
                advanced_degree=grad,
            )
        )
    return out


def parse_readme(text: str, categories: list[str]) -> list[SourceRow]:
    """Parse requested category sections from a SimplifyJobs-style README."""
    lines = text.splitlines(keepends=True)
    sections = _find_sections(lines)
    rows: list[SourceRow] = []
    for category in categories:
        bounds = sections.get(category)
        if bounds is None:
            continue
        start, end = bounds
        rows.extend(_parse_section(lines, start, end))
    return rows


def filter_rows(
    rows: list[SourceRow],
    *,
    max_age_days: int,
    exclude_advanced_degree: bool,
    exclude_citizenship: bool,
    exclude_no_sponsorship: bool,
    known_ids: set[str] | set[tuple[str, str]],
    eligibility: Any | None = None,
) -> FilterResult:
    """Apply age, title, sponsorship, citizenship, degree, and dedupe filters.

    ``known_ids`` accepts legacy bare job-id strings or ``(source_id, job_id)``
    pairs. A row without ``job_id`` is never treated as new. ``eligibility`` is
    an optional ``EligibilitySettings``; when set, ``check_title`` drops hard
    rejects and stamps soft flags onto surviving rows.
    """
    from resume_tailor.apply import eligibility as eligibility_mod

    total_candidates = len(rows)
    age_filtered = [
        row
        for row in rows
        if row.age_days is not None and row.age_days <= max_age_days
    ]

    excluded_title = 0
    after_title: list[SourceRow] = []
    settings = eligibility or eligibility_mod.EligibilitySettings()
    for row in age_filtered:
        result = eligibility_mod.check_title(row.role, settings)
        if not result.passed:
            excluded_title += 1
            continue
        if result.flags:
            row.flags = list(dict.fromkeys([*row.flags, *result.flags]))
        after_title.append(row)

    excluded_citizenship = [
        row for row in after_title if row.citizenship_required == "Yes"
    ]
    after_citizenship = (
        [row for row in after_title if row.citizenship_required != "Yes"]
        if exclude_citizenship
        else list(after_title)
    )
    if exclude_advanced_degree:
        excluded_grad = [row for row in after_citizenship if row.advanced_degree]
        kept = [row for row in after_citizenship if not row.advanced_degree]
    else:
        excluded_grad = []
        kept = list(after_citizenship)
    if exclude_no_sponsorship:
        excluded_no_sponsor = [row for row in kept if row.sponsorship_ok == "No"]
        kept = [row for row in kept if row.sponsorship_ok != "No"]
    else:
        excluded_no_sponsor = []

    sample = next(iter(known_ids), None) if known_ids else None
    pair_mode = isinstance(sample, tuple)

    def _is_known(row: SourceRow) -> bool:
        """Return True when this row's identity is already in the store."""
        if row.job_id is None:
            return True
        if pair_mode:
            return (row.source_id, row.job_id) in known_ids  # type: ignore[operator]
        return row.job_id in known_ids  # type: ignore[operator]

    new_rows = [row for row in kept if row.job_id is not None and not _is_known(row)]
    already_known = len(kept) - len(new_rows)
    return FilterResult(
        new_rows=new_rows,
        total_candidates=total_candidates,
        age_filtered_count=len(age_filtered),
        excluded_citizenship=len(excluded_citizenship) if exclude_citizenship else 0,
        excluded_advanced_degree=len(excluded_grad),
        excluded_no_sponsorship=len(excluded_no_sponsor),
        excluded_title=excluded_title,
        already_known=already_known,
    )


def fetch_readme(url: str) -> str:
    """Download a README body from ``url``, using an ETag cache when possible.

    Cache files live under ``APPLICATIONS_OUTPUT_DIR / readme_cache /``. A 304
    returns the cached body; a network error with a warm cache falls back to it.
    """
    import hashlib
    import json
    import logging

    from resume_tailor import config

    log = logging.getLogger(__name__)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    cache_dir = config.APPLICATIONS_OUTPUT_DIR / "readme_cache"
    cache_path = cache_dir / f"{digest}.json"
    cached: dict[str, str] | None = None
    if cache_path.is_file():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "body" in raw:
                cached = {"etag": str(raw.get("etag") or ""), "body": str(raw["body"])}
        except (OSError, json.JSONDecodeError):
            cached = None

    headers: dict[str, str] = {}
    if cached and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]

    try:
        response = httpx.get(
            url, follow_redirects=True, timeout=30.0, headers=headers
        )
        if response.status_code == 304 and cached is not None:
            return cached["body"]
        response.raise_for_status()
        body = response.text
        etag = response.headers.get("ETag") or response.headers.get("etag") or ""
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"etag": etag, "body": body}, ensure_ascii=False),
            encoding="utf-8",
        )
        return body
    except Exception:
        if cached is not None:
            log.warning("fetch_readme failed for %s; using cached body", url)
            return cached["body"]
        raise


def _normalize_heading_name(raw: str) -> str:
    """Strip emoji / shortcodes and keep word characters for section matching."""
    cleaned = re.sub(r":[a-z_]+:", "", raw)
    return re.sub(r"[^\w,&\s]", "", cleaned).strip()


def list_sections(text: str) -> list[tuple[int, str]]:
    """Return ``(heading_level, cleaned_name)`` for every ``##``–``####`` header."""
    out: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = re.match(r"^(#{2,4})\s+(.*)$", line)
        if not match:
            continue
        level = len(match.group(1))
        name = _normalize_heading_name(match.group(2))
        if name:
            out.append((level, name))
    return out


def _depth_sections(lines: list[str]) -> list[tuple[int, str, int, int]]:
    """Build ``(level, name, start, end)`` ranges for depth-aware headers."""
    headers: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,4})\s+(.*)$", line)
        if not match:
            continue
        level = len(match.group(1))
        name = _normalize_heading_name(match.group(2))
        if name:
            headers.append((level, name, index))
    ranges: list[tuple[int, str, int, int]] = []
    for index, (level, name, start) in enumerate(headers):
        end = len(lines)
        for later_level, _later_name, later_start in headers[index + 1 :]:
            if later_level <= level:
                end = later_start
                break
        ranges.append((level, name, start, end))
    return ranges


def _pipe_cell_href(cell: str) -> str | None:
    """Extract the first href or markdown link URL from a pipe-table cell."""
    html_match = re.search(r'href=["\']([^"\']+)["\']', cell, re.I)
    if html_match:
        return html_match.group(1)
    md_match = re.search(r"\]\(([^)]+)\)", cell)
    if md_match:
        return md_match.group(1)
    return None


def _clean_pipe_company(cell: str) -> str:
    """Strip HTML / markdown emphasis from a company cell."""
    text = re.sub(r"<[^>]+>", "", cell)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def _map_pipe_headers(cells: list[str]) -> dict[str, int]:
    """Map canonical column roles to indices from a header row."""
    mapping: dict[str, int] = {}
    for index, cell in enumerate(cells):
        key = cell.strip().lower()
        if key in {"company"}:
            mapping["company"] = index
        elif key in {"position", "role"}:
            mapping["role"] = index
        elif key in {"location"}:
            mapping["location"] = index
        elif key in {"salary"}:
            mapping["salary"] = index
        elif key in {"posting", "apply", "application", "link"}:
            mapping["apply"] = index
        elif key in {"age", "posted"}:
            mapping["age"] = index
    return mapping


def _parse_pipe_rows(lines: list[str], start: int, end: int) -> list[SourceRow]:
    """Parse markdown pipe-table rows inside one section range."""
    import hashlib

    table_lines = [
        line for line in lines[start:end] if line.strip().startswith("|")
    ]
    if len(table_lines) < 2:
        return []
    header_cells = [c.strip() for c in table_lines[0].strip("|").split("|")]
    col = _map_pipe_headers(header_cells)
    if "company" not in col or "apply" not in col:
        return []
    out: list[SourceRow] = []
    for line in table_lines[1:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r"[:\-]+", c or "") for c in cells):
            continue
        if len(cells) < len(header_cells):
            cells.extend([""] * (len(header_cells) - len(cells)))

        def _cell(name: str) -> str:
            """Return the cell for a mapped column name, or empty."""
            idx = col.get(name)
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx]

        company = _clean_pipe_company(_cell("company"))
        role = _cell("role")
        location = _cell("location")
        salary = _cell("salary")
        age = _cell("age")
        apply_cell = _cell("apply")
        href = _pipe_cell_href(apply_cell)
        if not href:
            continue
        # Keep gh_jid; otherwise drop the query string.
        if "gh_jid=" not in href and "?" in href:
            href = href.split("?", 1)[0]
        job_id = hashlib.sha1(href.encode("utf-8")).hexdigest()[:16]
        out.append(
            SourceRow(
                company=company,
                role=role,
                location=location,
                age=age,
                age_days=parse_age(age),
                job_id=job_id,
                application_link=href,
                salary=salary,
                advanced_degree=False,
            )
        )
    return out


def parse_pipe_table_readme(text: str, categories: list[str]) -> list[SourceRow]:
    """Parse requested categories from a speedyapply-style pipe-table README.

    Section ranges are depth-aware: a category matches by normalized name and
    ends at the next header of equal or higher level. Nested sections whose
    names contain ``International`` are skipped even when under a matched parent.
    """
    lines = text.splitlines(keepends=True)
    ranges = _depth_sections(lines)
    by_name = {name: (level, start, end) for level, name, start, end in ranges}
    rows: list[SourceRow] = []
    for category in categories:
        bounds = by_name.get(category)
        if bounds is None:
            continue
        level, start, end = bounds
        # Collect child International ranges to skip.
        skip_ranges = [
            (s, e)
            for lvl, name, s, e in ranges
            if s > start
            and e <= end
            and lvl > level
            and "international" in name.casefold()
        ]
        # Parse the parent chunk but also walk non-International children
        # individually when the parent itself is requested — rows under an
        # International child are excluded by splicing those ranges out.
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
        for seg_start, seg_end in keep_segments:
            rows.extend(_parse_pipe_rows(lines, seg_start, seg_end))
    return rows
