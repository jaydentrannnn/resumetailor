"""freehire.me keyword search (`provider="freehire"`): public, keyless, JSON.

An experiment (see `docs/notes/apply-funnel.md`): kept only if it finds postings the
other sources miss. Each hit's `url` is the employer's own ATS posting, so rows dedupe
against watchlist and README sightings by requisition (`identity.canonical_key`).

The endpoint and fields follow ai-job-search's `freehire-search/url-reference.md` (MIT,
© 2026 Mads Lorentzen); no code was ported. Reads only: `GET /api/v1/jobs/search` with
`q`, `countries`, `posted_within_days`, `limit` and `offset`; replies are
`{"data": [job, ...], "meta": {"total", "limit", "offset"}}`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from resume_tailor.apply.discovery.source_rows import SourceRow
from resume_tailor.apply.discovery.source_watchlists import (
    _age_days,
    iso_date,
    matches_filters,
    source_keyword_filters,
)

#: Override for a self-hosted instance.
URL_ENV = "RESUME_TAILOR_FREEHIRE_URL"
DEFAULT_URL = "https://freehire.me"
PAGE_SIZE = 50
_HEADERS = {"Accept": "application/json", "User-Agent": "ResumeTailor (job search)"}


def _base_url() -> str:
    return (os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")


def _salary(job: dict[str, Any]) -> str:
    extra = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
    low, high = extra.get("salary_min"), extra.get("salary_max")
    currency = str(extra.get("salary_currency") or "").upper()
    numbers = [f"{int(v):,}" for v in (low, high) if isinstance(v, (int, float)) and v > 0]
    if not numbers:
        return ""
    return f"{currency} {' - '.join(dict.fromkeys(numbers))}".strip()


def _row(job: dict[str, Any], source: Any, now: datetime) -> SourceRow:
    posted = str(job.get("posted_at") or job.get("created_at") or "")
    age = _age_days(posted, now) if posted else None
    return SourceRow(
        company=str(job.get("company") or "").strip(),
        role=str(job.get("title") or "").strip(),
        location=str(job.get("location") or "").strip(),
        age=f"{age}d" if age is not None else "",
        age_days=age if age is not None else 0,
        posted_at=iso_date(posted) if posted else "",
        job_id=f"freehire:{job['public_slug']}",
        application_link=str(job.get("url") or ""),
        source_id=source.id,
        salary=_salary(job),
        flags=[] if age is not None else ["age_unknown"],
    )


def search(
    source: Any,
    *,
    query: str,
    get: Callable[..., Any],
    now: datetime,
    max_pages: int,
    pause: Callable[[], None],
) -> tuple[list[SourceRow], list[str]]:
    """One phrase's postings, filtered like every keyword search, and any errors."""
    include, exclude, places = source_keyword_filters(source)
    url = f"{_base_url()}/api/v1/jobs/search"
    host = url.split("/")[2]
    rows: list[SourceRow] = []
    for page in range(max_pages):
        if page:
            pause()
        params: dict[str, Any] = {"q": query, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
        if source.country:
            params["countries"] = source.country.strip().lower()
        if source.max_age_days is not None:
            params["posted_within_days"] = source.max_age_days
        try:
            response = get(url, params=params, headers=_HEADERS, follow_redirects=True,
                           timeout=20.0)
        except httpx.HTTPError as exc:
            return rows, [f"could not reach {host}: {exc}"]
        if response.status_code != 200:
            return rows, [f"{host} answered HTTP {response.status_code}"]
        try:
            body = response.json()
        except ValueError as exc:
            return rows, [f"{host} sent invalid JSON: {exc}"]
        jobs = body.get("data") if isinstance(body, dict) else None
        if not isinstance(jobs, list) or not jobs:
            break
        for job in jobs:
            if not isinstance(job, dict) or not job.get("public_slug"):
                continue
            row = _row(job, source, now)
            if matches_filters(row.role, row.location, include=include, exclude=exclude,
                               locations=places):
                rows.append(row)
        meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        total = meta.get("total")
        if len(jobs) < PAGE_SIZE or (isinstance(total, int) and (page + 1) * PAGE_SIZE >= total):
            break
    return rows, []
