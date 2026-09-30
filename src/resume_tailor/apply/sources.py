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
    #: ISO date the posting was published, when the source states one ("" otherwise).
    posted_at: str = ""
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
    """Parse requested category sections from a SimplifyJobs-style README (empty = all)."""
    lines = text.splitlines(keepends=True)
    if not categories:
        return _parse_section(lines, 0, len(lines))
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
        row for row in rows if row.age_days is not None and row.age_days <= max_age_days
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

    excluded_citizenship = [row for row in after_title if row.citizenship_required == "Yes"]
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


_GITHUB_PAGE_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?"
    r"(?:/(blob|tree)/([^/\s]+)(/[^\s#?]*)?)?/?(?:[#?].*)?$"
)


def raw_readme_url(url: str) -> str:
    """The raw README behind a github.com repository or file link; ``url`` otherwise.

    People paste the page they see (``github.com/owner/repo``, or ``.../blob/dev/README.md``),
    and fetching that returns GitHub's HTML page, whose ``<table>`` markup the Simplify
    parser happily misreads. A bare repo maps to ``HEAD``, which raw.githubusercontent.com
    resolves to the default branch; a ``tree`` link means that branch's README.
    """
    match = _GITHUB_PAGE_RE.match(url.strip())
    if not match:
        return url
    owner, repo, view, ref, path = match.groups()
    if not path or view == "tree":
        path = (path or "").rstrip("/") + "/README.md"
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref or 'HEAD'}{path}"


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
    url = raw_readme_url(url)
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
        response = httpx.get(url, follow_redirects=True, timeout=30.0, headers=headers)
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


#: ``## Heading`` through ``#### Heading``.
_MD_HEADING_RE = re.compile(r"^(#{2,4})\s+(.*)$")
#: A collapsible section title, e.g. zapplyjobs'
#: ``<summary><h3>💻 <strong>SWE</strong></h3></summary>``.
_SUMMARY_HEADING_RE = re.compile(r"<summary>\s*<h([2-4])[^>]*>(.*?)</h\1>", re.IGNORECASE)


def _heading(line: str) -> tuple[int, str] | None:
    """``(level, cleaned_name)`` when ``line`` is a section heading, else None."""
    match = _MD_HEADING_RE.match(line)
    if match:
        level, raw = len(match.group(1)), match.group(2)
    else:
        match = _SUMMARY_HEADING_RE.search(line)
        if not match:
            return None
        level, raw = int(match.group(1)), re.sub(r"<[^>]+>", "", match.group(2))
    name = _normalize_heading_name(raw)
    return (level, name) if name else None


def list_sections(text: str) -> list[tuple[int, str]]:
    """Return ``(heading_level, cleaned_name)`` for every ``##``–``####`` header.

    A ``<summary><h3>…</h3></summary>`` title counts as a heading of that level.
    """
    return [found for line in text.splitlines() if (found := _heading(line))]


def _depth_sections(lines: list[str]) -> list[tuple[int, str, int, int]]:
    """Build ``(level, name, start, end)`` ranges for depth-aware headers."""
    headers: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        found = _heading(line)
        if found:
            headers.append((found[0], found[1], index))
    ranges: list[tuple[int, str, int, int]] = []
    for index, (level, name, start) in enumerate(headers):
        end = len(lines)
        for later_level, _later_name, later_start in headers[index + 1 :]:
            if later_level <= level:
                end = later_start
                break
        ranges.append((level, name, start, end))
    return ranges


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
    age = parse_age(cleaned)
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
    for flag in (GRAD_FLAG, US_CITIZEN_FLAG, NO_SPONSOR_FLAG, FAANG_FLAG):
        text = text.replace(flag, "")
    return re.sub(r"\s+", " ", text).strip()


def _parse_pipe_rows(
    lines: list[str], start: int, end: int, *, today: Any = None
) -> list[SourceRow]:
    """Parse markdown pipe-table rows inside one section range.

    Each table's header row (the line above its ``|---|`` separator) maps that
    table's columns, so tables with different layouts can share a section. The apply
    link comes from the apply column, else from a link on the role (jobright-style).
    A ``↳`` company repeats the row above; Simplify's title flags (🛂 🇺🇸 🎓) count.
    """
    import hashlib

    out: list[SourceRow] = []
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
            SourceRow(
                company=_strip_title_flags(company),
                role=_strip_title_flags(_clean_pipe_text(raw_role)),
                location=_clean_pipe_location(_cell("location")),
                age=_clean_pipe_text(_cell("age")),
                age_days=age_days,
                posted_at=posted_at,
                job_id=hashlib.sha1(href.encode("utf-8")).hexdigest()[:16],
                application_link=href,
                salary=_clean_pipe_text(_cell("salary")),
                sponsorship_ok="No" if NO_SPONSOR_FLAG in raw_role else "Unknown",
                citizenship_required="Yes" if US_CITIZEN_FLAG in raw_role else "No",
                advanced_degree=GRAD_FLAG in raw_role,
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
) -> list[SourceRow]:
    """Parse requested categories from a speedyapply-style pipe-table README.

    Section ranges are depth-aware: a category matches by normalized name and
    ends at the next header of equal or higher level. Nested sections whose
    names contain ``International`` are skipped even when under a matched parent.
    Empty ``categories`` reads the whole README (still skipping International).
    """
    lines = text.splitlines(keepends=True)
    ranges = _depth_sections(lines)
    by_name = {name: (level, start, end) for level, name, start, end in ranges}
    if categories:
        targets = [by_name[c] for c in categories if c in by_name]
    else:
        targets = [(1, 0, len(lines))]
    rows: list[SourceRow] = []
    for level, start, end in targets:
        for seg_start, seg_end in _without_international(ranges, level, start, end):
            rows.extend(_parse_pipe_rows(lines, seg_start, seg_end, today=today))
    return rows


# --- per-company link tables (``kind="company_link_table"``) ----------------------

#: ``##`` headings in a company-link README that are not companies.
_NON_COMPANY_HEADINGS = {"contributing", "using this repository"}
#: Role abbreviations used by northwesternfintech's tables.
_ROLE_ABBREVIATIONS = {
    "qt": "Quant Trader",
    "qr": "Quant Researcher",
    "qd": "Quant Developer",
    "swe": "Software Engineer",
    "hw": "Hardware Engineer",
    "ml": "Machine Learning",
}


def _company_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """``(company, start, end)`` for every ``##`` company heading."""
    heads = [
        (index, _normalize_heading_name(line[3:]))
        for index, line in enumerate(lines)
        if line.startswith("## ")
    ]
    out: list[tuple[str, int, int]] = []
    for position, (start, name) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        if name and name.casefold() not in _NON_COMPANY_HEADINGS:
            out.append((name, start, end))
    return out


def company_link_sections(text: str) -> list[str]:
    """Company names (the ``##`` headings) of a company-link-table README."""
    return [name for name, _s, _e in _company_sections(text.splitlines(keepends=True))]


def parse_company_link_table(text: str, categories: list[str]) -> list[SourceRow]:
    """Parse a README of per-company ``|Role|Links|`` tables (northwesternfintech-style).

    The company is the ``##`` heading; each markdown link in a Links cell is its own
    row, its label (``C++``, ``PhD``) appended to the role. ``categories`` are company
    names; empty reads every company. These lists carry no dates and only list open
    postings, so rows are kept as new (``age_days=0``, flag ``age_unknown``), the way
    company watchlists treat an undated posting.
    """
    import hashlib

    lines = text.splitlines(keepends=True)
    wanted = {c.casefold() for c in categories}
    rows: list[SourceRow] = []
    for company, start, end in _company_sections(lines):
        if wanted and company.casefold() not in wanted:
            continue
        location = ""
        in_table = False
        for line in lines[start + 1 : end]:
            stripped = line.strip()
            loc = re.match(r"^\*\*Locations?\*\*:\s*(.*)$", stripped, re.I)
            if loc:
                location = _clean_pipe_text(loc.group(1))
                continue
            if not stripped.startswith("|"):
                continue
            cells = _split_pipe_row(stripped)
            if [c.lower() for c in cells[:2]] == ["role", "links"]:
                in_table = True
                continue
            if not in_table or _is_separator(stripped) or len(cells) < 2:
                continue
            raw_role = _clean_pipe_text(cells[0])
            role = _ROLE_ABBREVIATIONS.get(raw_role.casefold(), raw_role)
            for label, href in re.findall(r"\[([^\]]*)\]\(([^)\s]+)\)", cells[1]):
                label = re.sub(r"[^\w+#./\s-]", "", label).strip()
                link = _clean_apply_href(href)
                rows.append(
                    SourceRow(
                        company=company,
                        role=f"{role} ({label})" if label else role,
                        location=location,
                        age="",
                        age_days=0,
                        job_id=hashlib.sha1(link.encode("utf-8")).hexdigest()[:16],
                        application_link=link,
                        advanced_degree=bool(re.search(r"\bph\.?d\b", label, re.I)),
                        flags=["age_unknown"],
                    )
                )
    return rows


# --- format detection and one-call fetch ------------------------------------------

ReadmeKind = Literal["simplify_html", "pipe_table", "company_link_table"]
README_KINDS: tuple[ReadmeKind, ...] = ("simplify_html", "pipe_table", "company_link_table")


def parse_source_text(kind: str, text: str, categories: list[str]) -> list[SourceRow]:
    """Rows of a README body for a README ``kind`` (empty categories = everything)."""
    if kind == "simplify_html":
        return parse_readme(text, categories)
    if kind == "pipe_table":
        return parse_pipe_table_readme(text, categories)
    if kind == "company_link_table":
        return parse_company_link_table(text, categories)
    raise ValueError(f"unknown source kind {kind!r}")


def _format_signals(text: str) -> list[ReadmeKind]:
    """README kinds suggested by cheap text signals, most specific first."""
    signals: list[ReadmeKind] = []
    if re.search(r"<tr>\s*<td", text, re.I):
        signals.append("simplify_html")
    if re.search(r"^\|\s*Role\s*\|\s*Links\s*\|", text, re.I | re.M):
        signals.append("company_link_table")
    if re.search(r"^\|?\s*:?-{3,}:?\s*\|", text, re.M):
        signals.append("pipe_table")
    return signals


def detect_format(text: str) -> ReadmeKind | None:
    """The README kind whose parser reads rows from ``text``, or None when none does.

    Cheap signals are tried first (``<tr><td>`` rows, ``|Role|Links|`` tables, a
    ``|---|`` separator) and the first whose parser returns rows wins; otherwise every
    parser runs over the whole README and the one with the most rows wins.
    """
    signals = _format_signals(text)
    for kind in signals:
        if parse_source_text(kind, text, []):
            return kind
    counts = {
        kind: len(parse_source_text(kind, text, [])) for kind in README_KINDS if kind not in signals
    }
    best = max(counts, key=lambda k: counts[k], default=None)
    return best if best and counts[best] else None


def source_sections(kind: str, text: str) -> list[str]:
    """Category names a README offers for ``kind``: headings whose section has rows."""
    if kind == "company_link_table":
        return [
            name for name in company_link_sections(text) if parse_company_link_table(text, [name])
        ]
    names = list(dict.fromkeys(name for _level, name in list_sections(text)))
    return [name for name in names if parse_source_text(kind, text, [name])]


def source_keyword_filters(
    src: Any,
) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None, re.Pattern[str] | None]:
    """A source's (include, exclude, locations) patterns, as `matches_filters` takes them.

    The one place the three filters are derived, shared by watchlists, keyword searches and
    README lists so they cannot drift apart.
    """
    return (
        _keyword_re(src.include, whole=False),
        _keyword_re(src.exclude, whole=False),
        _keyword_re(src.locations, whole=True),
    )


def _apply_source_filters(src: Any, rows: list[SourceRow]) -> list[SourceRow]:
    """Keep README rows whose title and location satisfy the source's own filters.

    Watchlists and keyword searches apply the same three filters while they read; a job
    list reads whole sections, so the filters run here. No filters set keeps every row.
    """
    include, exclude, places = source_keyword_filters(src)
    if not (include or exclude or places):
        return rows
    return [
        row
        for row in rows
        if matches_filters(
            row.role, row.location, include=include, exclude=exclude, locations=places
        )
    ]


def fetch_source_rows(src: Any) -> tuple[list[SourceRow], list[str]]:
    """Postings from one `SourceConfig` and its per-part errors, for every kind.

    README kinds fetch the body (ETag-cached) and parse ``categories``; watchlists and
    keyword searches report a failed board or phrase as an error and keep the rest.
    Rows are stamped with ``src.id``. Raises when the whole source fails (README
    unreachable, missing API keys, unknown kind).
    """
    errors: list[str] = []
    if src.kind == "ats_board":
        rows, errors = board_rows(src)
    elif src.kind == "job_search":
        from resume_tailor.apply import job_apis

        rows, errors = job_apis.job_search_rows(src)
    elif src.kind in README_KINDS:
        rows = parse_source_text(src.kind, fetch_readme(src.url), src.categories)
        rows = _apply_source_filters(src, rows)
    else:
        raise ValueError(f"unknown source kind {src.kind!r}")
    for row in rows:
        row.source_id = src.id
    return rows, errors


# --- company watchlists (``kind="ats_board"``, plan P4-D2) -------------------------


def _keyword_re(words: list[str], *, whole: bool) -> re.Pattern[str] | None:
    """One case-insensitive pattern for ``words``; None when there are none.

    Keywords match at a word start, so "intern" also finds "Internship" and "consult"
    finds "Consulting". Locations match whole words, so "NY" does not match "Albany".
    """
    cleaned = [w.strip() for w in words if w and w.strip()]
    if not cleaned:
        return None
    tail = r"(?!\w)" if whole else ""
    alternatives = "|".join(re.escape(w) for w in cleaned)
    return re.compile(rf"(?<!\w)(?:{alternatives}){tail}", re.IGNORECASE)


def iso_date(value: str) -> str:
    """The ISO date (YYYY-MM-DD) of a timestamp string, or "" when it does not parse."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def _age_days(updated_at: str, now: Any) -> int | None:
    from datetime import UTC, datetime

    try:
        when = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, (now - when).days)


def matches_filters(
    title: str,
    location: str,
    *,
    include: re.Pattern[str] | None = None,
    exclude: re.Pattern[str] | None = None,
    locations: re.Pattern[str] | None = None,
) -> bool:
    """Check if title and location satisfy include, exclude, and locations filter patterns."""
    if not title:
        return False
    if include and not include.search(title):
        return False
    if exclude and exclude.search(title):
        return False
    return not (locations and location) or bool(locations.search(location))


def board_rows(
    source: Any,
    *,
    list_board: Any = None,
    now: Any = None,
) -> tuple[list[SourceRow], list[str]]:
    """Postings from every board on a watchlist source, and one error per failed board.

    ``source`` is a `SourceConfig` with ``kind="ats_board"``. A board that fails
    (wrong name, unreachable) is reported and skipped; the others still count.
    A posting with no date is kept as new (``age_days=0``, flag ``age_unknown``):
    boards only list open postings.
    """
    from datetime import UTC, datetime

    from resume_tailor.apply import boards, identity

    list_board = list_board or boards.list_board
    now = now or datetime.now(UTC)
    include, exclude, places = source_keyword_filters(source)
    rows: list[SourceRow] = []
    errors: list[str] = []
    for position, board in enumerate(source.boards):
        if position:
            boards._sleep(boards.BOARD_DELAY_SECONDS)  # noqa: SLF001
        name = board.company or board.slug
        try:
            jobs = list_board(board.ats, board.slug)
        except boards.BoardNotFound:
            errors.append(f"{name}: no {board.ats} board named {board.slug!r}")
            continue
        except Exception as exc:  # noqa: BLE001 - one board must not sink the source
            errors.append(f"{name}: {exc}")
            continue
        for job in jobs:
            if not matches_filters(
                job.title,
                job.location,
                include=include,
                exclude=exclude,
                locations=places,
            ):
                continue
            age = _age_days(job.updated_at, now) if job.updated_at else None
            flags = [] if age is not None else ["age_unknown"]
            rows.append(
                SourceRow(
                    company=board.company or job.company or board.slug,
                    role=job.title,
                    location=job.location,
                    age=f"{age}d" if age is not None else "",
                    age_days=age if age is not None else 0,
                    posted_at=iso_date(job.posted_at) if job.posted_at else "",
                    job_id=identity.canonical_key(job.url),
                    application_link=job.url,
                    source_id=source.id,
                    flags=flags,
                )
            )
    return rows, errors


# --- per-source run health (`source_status.json`) ---------------------------------------

_STATUS_ERROR_LIMIT = 200
_STATUS_WRITE_ATTEMPTS = 5


def short_reason(text: str) -> str:
    """One line of an error, capped so the Sources tab can show it inline."""
    line = " ".join(str(text).split())
    if len(line) > _STATUS_ERROR_LIMIT:
        line = line[: _STATUS_ERROR_LIMIT - 1].rstrip() + "…"
    return line


def load_source_status() -> dict[str, Any]:
    """The latest per-source run results: ``{"sources": {id: entry}, "last_run_at": str|None}``.

    A missing or unreadable file, or entries of the wrong shape, read as "never run" —
    health is advisory and must never break the page.
    """
    import json

    from resume_tailor import config

    empty: dict[str, Any] = {"sources": {}, "last_run_at": None}
    try:
        raw = json.loads(config.SOURCE_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        return empty
    entries = {
        str(sid): {
            "found": entry["found"],
            "kept": entry["kept"],
            "error": entry.get("error") if isinstance(entry.get("error"), str) else None,
            "at": entry["at"],
        }
        for sid, entry in raw["sources"].items()
        if isinstance(entry, dict)
        and isinstance(entry.get("found"), int)
        and isinstance(entry.get("kept"), int)
        and isinstance(entry.get("at"), str)
    }
    last = raw.get("last_run_at")
    return {"sources": entries, "last_run_at": last if isinstance(last, str) else None}


def record_source_status(entries: dict[str, dict[str, Any]], run_at: str) -> None:
    """Merge this run's per-source results into ``source_status.json`` (atomic).

    Sources absent from ``entries`` (disabled, or not in this run) keep their previous
    entry. Never raises: a failed write is logged and the run carries on.
    """
    import json
    import logging
    import os
    import time

    from resume_tailor import config

    try:
        merged = load_source_status()
        merged["sources"].update(entries)
        merged["last_run_at"] = run_at
        path = config.SOURCE_STATUS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        for attempt in range(_STATUS_WRITE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: a reader holds the file open for a moment
                if attempt == _STATUS_WRITE_ATTEMPTS - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except Exception:  # noqa: BLE001 - health is advisory
        logging.getLogger(__name__).warning("could not write source status", exc_info=True)


def failure_reason(exc: Exception) -> str:
    """A short human reason for a whole-source failure (credentials, network, HTTP)."""
    from urllib.parse import urlsplit

    if isinstance(exc, httpx.HTTPStatusError):
        host = urlsplit(str(exc.request.url)).netloc
        return short_reason(f"HTTP {exc.response.status_code} from {host}")
    if isinstance(exc, httpx.RequestError):
        try:
            host = urlsplit(str(exc.request.url)).netloc
        except RuntimeError:  # httpx raises when the error carries no request
            host = ""
        return short_reason(
            f"could not reach {host}" if host else f"could not reach the source: {exc}"
        )
    return short_reason(str(exc) or type(exc).__name__)
