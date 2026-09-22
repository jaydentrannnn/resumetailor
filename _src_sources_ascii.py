"""Fetch and parse SimplifyJobs-style internship README tables."""

from __future__ import annotations

import re
from typing import Literal

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

US_CITIZEN_FLAG = "??"
NO_SPONSOR_FLAG = "?"
GRAD_FLAG = "?"
FAANG_FLAG = "?"

SponsorshipOk = Literal["Unknown", "No"]


class SourceRow(BaseModel):
    """One parsed posting row from a category section."""

    company: str
    role: str
    location: str
    age: str
    job_id: str | None = None
    application_link: str | None = None
    sponsorship_ok: SponsorshipOk = "Unknown"
    citizenship_required: str = "No"
    notes: str = ""
    advanced_degree: bool = False


class FilterResult(BaseModel):
    """Outcome of ``filter_rows`` with dedupe and exclusion counts."""

    new_rows: list[SourceRow] = Field(default_factory=list)
    total_candidates: int = 0
    age_filtered_count: int = 0
    excluded_citizenship: int = 0
    excluded_advanced_degree: int = 0
    excluded_no_sponsorship: int = 0
    already_known: int = 0


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
        if company in ("?", ""):
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


def _allowed_ages(max_age_days: int) -> set[str]:
    """Build the posted-age tokens ``0d`` ? ``{max_age_days}d`` inclusive."""
    if max_age_days < 0:
        return set()
    return {f"{day}d" for day in range(max_age_days + 1)}


def filter_rows(
    rows: list[SourceRow],
    *,
    max_age_days: int,
    exclude_advanced_degree: bool,
    exclude_citizenship: bool,
    exclude_no_sponsorship: bool,
    known_ids: set[str],
) -> FilterResult:
    """Apply age, sponsorship, citizenship, degree, and dedupe filters."""
    total_candidates = len(rows)
    allowed = _allowed_ages(max_age_days)
    age_filtered = [row for row in rows if row.age in allowed]
    excluded_citizenship = [
        row for row in age_filtered if row.citizenship_required == "Yes"
    ]
    after_citizenship = (
        [row for row in age_filtered if row.citizenship_required != "Yes"]
        if exclude_citizenship
        else list(age_filtered)
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
    new_rows = [
        row
        for row in kept
        if row.job_id is not None and row.job_id not in known_ids
    ]
    already_known = len(kept) - len(new_rows)
    return FilterResult(
        new_rows=new_rows,
        total_candidates=total_candidates,
        age_filtered_count=len(age_filtered),
        excluded_citizenship=len(excluded_citizenship) if exclude_citizenship else 0,
        excluded_advanced_degree=len(excluded_grad),
        excluded_no_sponsorship=len(excluded_no_sponsor),
        already_known=already_known,
    )


def fetch_readme(url: str) -> str:
    """Download a README body from ``url`` via HTTP GET."""
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.text
