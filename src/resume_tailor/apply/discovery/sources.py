"""Fetch and parse SimplifyJobs-style internship README tables."""

from __future__ import annotations

import re
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup

from . import (
    source_company_table,
    source_headings,
    source_pipe_table,
    source_rows,
    source_watchlists,
)


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
) -> list[source_rows.SourceRow]:
    """Parse HTML table rows inside one README category chunk."""
    chunk = "".join(lines[start:end])
    soup = BeautifulSoup(chunk, "html.parser")
    out: list[source_rows.SourceRow] = []
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

        us_flag = (
            source_rows.US_CITIZEN_FLAG in raw_company or source_rows.US_CITIZEN_FLAG in raw_role
        )
        no_sponsor = (
            source_rows.NO_SPONSOR_FLAG in raw_company or source_rows.NO_SPONSOR_FLAG in raw_role
        )
        faang = source_rows.FAANG_FLAG in raw_company
        grad = source_rows.GRAD_FLAG in raw_role

        company = raw_company.replace(source_rows.FAANG_FLAG, "").strip()
        if company in ("↳", ""):
            company = last_company or ""
        else:
            last_company = company
        role = raw_role.replace(source_rows.GRAD_FLAG, "").strip()

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
            source_rows.SourceRow(
                company=company,
                role=role,
                location=location,
                age=age,
                age_days=source_rows.parse_age(age),
                job_id=job_id,
                application_link=app_link,
                sponsorship_ok="No" if no_sponsor else "Unknown",
                citizenship_required="Yes" if us_flag else "No",
                notes="; ".join(notes),
                advanced_degree=grad,
            )
        )
    return out


def parse_readme(text: str, categories: list[str]) -> list[source_rows.SourceRow]:
    """Parse requested category sections from a SimplifyJobs-style README (empty = all)."""
    lines = text.splitlines(keepends=True)
    if not categories:
        return _parse_section(lines, 0, len(lines))
    sections = _find_sections(lines)
    rows: list[source_rows.SourceRow] = []
    for category in categories:
        bounds = sections.get(category)
        if bounds is None:
            continue
        start, end = bounds
        rows.extend(_parse_section(lines, start, end))
    return rows


def filter_rows(
    rows: list[source_rows.SourceRow],
    *,
    max_age_days: int,
    exclude_advanced_degree: bool,
    exclude_citizenship: bool,
    exclude_no_sponsorship: bool,
    known_ids: set[str] | set[tuple[str, str]],
    eligibility: Any | None = None,
) -> source_rows.FilterResult:
    """Apply age, title, sponsorship, citizenship, degree, and dedupe filters.

    ``known_ids`` accepts legacy bare job-id strings or ``(source_id, job_id)``
    pairs. A row without ``job_id`` is never treated as new. ``eligibility`` is
    an optional ``EligibilitySettings``; when set, ``check_title`` drops hard
    rejects and stamps soft flags onto surviving rows.
    """
    from resume_tailor.apply.funnel import eligibility as eligibility_mod

    total_candidates = len(rows)
    age_filtered = [
        row for row in rows if row.age_days is not None and row.age_days <= max_age_days
    ]

    excluded_title = 0
    after_title: list[source_rows.SourceRow] = []
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

    def _is_known(row: source_rows.SourceRow) -> bool:
        """Return True when this row's identity is already in the store."""
        if row.job_id is None:
            return True
        if pair_mode:
            return (row.source_id, row.job_id) in known_ids  # type: ignore[operator]
        return row.job_id in known_ids  # type: ignore[operator]

    new_rows = [row for row in kept if row.job_id is not None and not _is_known(row)]
    already_known = len(kept) - len(new_rows)
    return source_rows.FilterResult(
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


# --- format detection and one-call fetch ------------------------------------------

ReadmeKind = Literal["simplify_html", "pipe_table", "company_link_table"]
README_KINDS: tuple[ReadmeKind, ...] = ("simplify_html", "pipe_table", "company_link_table")


def parse_source_text(kind: str, text: str, categories: list[str]) -> list[source_rows.SourceRow]:
    """Rows of a README body for a README ``kind`` (empty categories = everything)."""
    if kind == "simplify_html":
        return parse_readme(text, categories)
    if kind == "pipe_table":
        return source_pipe_table.parse_pipe_table_readme(text, categories)
    if kind == "company_link_table":
        return source_company_table.parse_company_link_table(text, categories)
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
            name
            for name in source_company_table.company_link_sections(text)
            if source_company_table.parse_company_link_table(text, [name])
        ]
    names = list(dict.fromkeys(name for _level, name in source_headings.list_sections(text)))
    return [name for name in names if parse_source_text(kind, text, [name])]


def _apply_source_filters(
    src: Any, rows: list[source_rows.SourceRow]
) -> list[source_rows.SourceRow]:
    """Keep README rows whose title and location satisfy the source's own filters.

    Watchlists and keyword searches apply the same three filters while they read; a job
    list reads whole sections, so the filters run here. No filters set keeps every row.
    """
    include, exclude, places = source_watchlists.source_keyword_filters(src)
    if not (include or exclude or places):
        return rows
    return [
        row
        for row in rows
        if source_watchlists.matches_filters(
            row.role, row.location, include=include, exclude=exclude, locations=places
        )
    ]


def fetch_source_rows(src: Any) -> tuple[list[source_rows.SourceRow], list[str]]:
    """Postings from one `SourceConfig` and its per-part errors, for every kind.

    README kinds fetch the body (ETag-cached) and parse ``categories``; watchlists and
    keyword searches report a failed board or phrase as an error and keep the rest.
    Rows are stamped with ``src.id``. Raises when the whole source fails (README
    unreachable, missing API keys, unknown kind).
    """
    errors: list[str] = []
    if src.kind == "ats_board":
        rows, errors = source_watchlists.board_rows(src)
    elif src.kind == "job_search":
        from resume_tailor.apply.discovery import job_apis

        rows, errors = job_apis.job_search_rows(src)
    elif src.kind in README_KINDS:
        rows = parse_source_text(src.kind, fetch_readme(src.url), src.categories)
        rows = _apply_source_filters(src, rows)
    else:
        raise ValueError(f"unknown source kind {src.kind!r}")
    for row in rows:
        row.source_id = src.id
    return rows, errors
