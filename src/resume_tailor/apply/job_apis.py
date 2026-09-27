"""Job search source: keyword-based job search via public APIs (Adzuna + USAJobs).

Unlike company watchlists which query specific ATS boards for one company, job search
sources query job aggregators across any industry by keyword, location, and recency.
Postings are mapped to `SourceRow`s so screening, dedupe, and tailoring remain shared.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from resume_tailor import config
from resume_tailor.apply.sources import SourceRow, _age_days, _keyword_re, matches_filters

JobProvider = Literal["adzuna", "usajobs"]
JOB_PROVIDERS: tuple[JobProvider, ...] = ("adzuna", "usajobs")

#: Pause between pages to stay polite to the public APIs.
JOB_SEARCH_DELAY_SECONDS = 1.0
#: Stop after this many pages for any single source.
MAX_PAGES = 5

_sleep: Callable[[float], None] = time.sleep


def _redact(text: str, *secrets: str | None) -> str:
    """Mask credential values in text that reaches the daily log and run summary.

    Adzuna takes its keys as query parameters, so an HTTP error that echoes the
    request URL would otherwise carry them into `summary.errors`.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


class MissingCredentialsError(RuntimeError):
    """Raised when required credentials for a job search provider are not configured."""


class JobSearchError(RuntimeError):
    """Raised when a job search API fails (HTTP error, invalid JSON, etc.)."""


def _format_adzuna_salary(job: dict[str, Any]) -> str:
    s_min = job.get("salary_min")
    s_max = job.get("salary_max")
    if s_min is not None and s_max is not None:
        try:
            min_f = float(s_min)
            max_f = float(s_max)
            if min_f == max_f:
                return f"${min_f:,.0f}"
            return f"${min_f:,.0f} - ${max_f:,.0f}"
        except (ValueError, TypeError):
            return f"${s_min} - ${s_max}"
    if s_min is not None:
        try:
            return f"${float(s_min):,.0f}+"
        except (ValueError, TypeError):
            return f"${s_min}+"
    if s_max is not None:
        try:
            return f"Up to ${float(s_max):,.0f}"
        except (ValueError, TypeError):
            return f"${s_max}"
    return ""


def _format_usajobs_salary(desc: dict[str, Any]) -> str:
    remun = desc.get("PositionRemuneration")
    if not remun or not isinstance(remun, list):
        return ""
    r0 = remun[0]
    if not isinstance(r0, dict):
        return ""
    min_val = r0.get("MinimumRange")
    max_val = r0.get("MaximumRange")
    interval = r0.get("RateIntervalCode") or r0.get("Description") or ""
    if min_val and max_val:
        try:
            min_f = float(min_val)
            max_f = float(max_val)
            salary = f"${min_f:,.0f} - ${max_f:,.0f}"
        except (ValueError, TypeError):
            salary = f"${min_val} - ${max_val}"
    elif min_val:
        try:
            salary = f"${float(min_val):,.0f}"
        except (ValueError, TypeError):
            salary = f"${min_val}"
    elif max_val:
        try:
            salary = f"Up to ${float(max_val):,.0f}"
        except (ValueError, TypeError):
            salary = f"${max_val}"
    else:
        return ""
    if interval:
        salary = f"{salary} / {interval}"
    return salary


def _search_adzuna(
    source: Any,
    *,
    get: Callable[..., Any],
    now: datetime,
) -> tuple[list[SourceRow], list[str]]:
    app_id = config.credential("ADZUNA_APP_ID")
    app_key = config.credential("ADZUNA_APP_KEY")
    missing = []
    if not app_id:
        missing.append("ADZUNA_APP_ID")
    if not app_key:
        missing.append("ADZUNA_APP_KEY")
    if missing:
        raise MissingCredentialsError(
            f"Adzuna requires credentials: {', '.join(missing)}"
        )

    country = (source.country or "us").strip().lower()
    include = _keyword_re(source.include, whole=False)
    exclude = _keyword_re(source.exclude, whole=False)
    places = _keyword_re(source.locations, whole=True)

    rows: list[SourceRow] = []
    errors: list[str] = []

    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            _sleep(JOB_SEARCH_DELAY_SECONDS)
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params: dict[str, Any] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 50,
            "content-type": "application/json",
        }
        if source.query:
            params["what"] = source.query
        if source.location:
            params["where"] = source.location
        if source.max_age_days is not None:
            params["max_days_old"] = source.max_age_days

        try:
            response = get(url, params=params, follow_redirects=True, timeout=20.0)
        except httpx.HTTPError as exc:
            errors.append(
                _redact(f"could not reach api.adzuna.com: {exc}", app_id, app_key)
            )
            break
        if response.status_code != 200:
            errors.append(f"api.adzuna.com answered {response.status_code}")
            break
        try:
            data = response.json()
        except ValueError as exc:
            errors.append(f"api.adzuna.com sent invalid JSON: {exc}")
            break

        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            break

        for job in results:
            if not isinstance(job, dict) or not job.get("id"):
                continue
            title = str(job.get("title") or "").strip()
            company_info = job.get("company")
            company = (
                str(company_info.get("display_name") or "")
                if isinstance(company_info, dict)
                else ""
            )
            location_info = job.get("location")
            location = (
                str(location_info.get("display_name") or "")
                if isinstance(location_info, dict)
                else ""
            )

            if not matches_filters(
                title, location, include=include, exclude=exclude, locations=places
            ):
                continue

            created = str(job.get("created") or "")
            age = _age_days(created, now) if created else None
            salary = _format_adzuna_salary(job)
            flags = [] if age is not None else ["age_unknown"]

            rows.append(
                SourceRow(
                    company=company or source.query,
                    role=title,
                    location=location,
                    age=f"{age}d" if age is not None else "",
                    age_days=age if age is not None else 0,
                    job_id=f"adzuna:{job['id']}",
                    application_link=str(job.get("redirect_url") or ""),
                    source_id=source.id,
                    salary=salary,
                    flags=flags,
                )
            )

        total_count = data.get("count") if isinstance(data, dict) else None
        if isinstance(total_count, int) and page * 50 >= total_count:
            break
        if len(results) < 50:
            break

    return rows, errors


def _search_usajobs(
    source: Any,
    *,
    get: Callable[..., Any],
    now: datetime,
) -> tuple[list[SourceRow], list[str]]:
    api_key = config.credential("USAJOBS_API_KEY")
    email = config.credential("USAJOBS_EMAIL")
    missing = []
    if not api_key:
        missing.append("USAJOBS_API_KEY")
    if not email:
        missing.append("USAJOBS_EMAIL")
    if missing:
        raise MissingCredentialsError(
            f"USAJobs requires credentials: {', '.join(missing)}"
        )

    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": email,
        "Authorization-Key": api_key,
    }

    include = _keyword_re(source.include, whole=False)
    exclude = _keyword_re(source.exclude, whole=False)
    places = _keyword_re(source.locations, whole=True)

    rows: list[SourceRow] = []
    errors: list[str] = []

    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            _sleep(JOB_SEARCH_DELAY_SECONDS)
        url = "https://data.usajobs.gov/api/search"
        params: dict[str, Any] = {
            "ResultsPerPage": 100,
            "Page": page,
        }
        if source.query:
            params["Keyword"] = source.query
        if source.location:
            params["LocationName"] = source.location
        if source.max_age_days is not None:
            params["DatePosted"] = min(60, max(0, source.max_age_days))

        try:
            response = get(
                url,
                params=params,
                headers=headers,
                follow_redirects=True,
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            errors.append(
                _redact(f"could not reach data.usajobs.gov: {exc}", api_key, email)
            )
            break
        if response.status_code != 200:
            errors.append(f"data.usajobs.gov answered {response.status_code}")
            break
        try:
            data = response.json()
        except ValueError as exc:
            errors.append(f"data.usajobs.gov sent invalid JSON: {exc}")
            break

        search_result = data.get("SearchResult") if isinstance(data, dict) else None
        items = (
            search_result.get("SearchResultItems")
            if isinstance(search_result, dict)
            else None
        )
        if not items:
            break

        for item in items:
            if not isinstance(item, dict) or not item.get("MatchedObjectId"):
                continue
            desc = item.get("MatchedObjectDescriptor") or {}
            title = str(desc.get("PositionTitle") or "").strip()
            company = str(
                desc.get("OrganizationName")
                or desc.get("DepartmentName")
                or ""
            ).strip()
            location = str(desc.get("PositionLocationDisplay") or "").strip()
            if not location:
                loc_list = desc.get("PositionLocation") or []
                if isinstance(loc_list, list) and loc_list:
                    location = str(loc_list[0].get("LocationName") or "")

            if not matches_filters(
                title, location, include=include, exclude=exclude, locations=places
            ):
                continue

            apply_uris = desc.get("ApplyURI")
            if isinstance(apply_uris, list) and apply_uris:
                app_link = str(apply_uris[0])
            elif isinstance(apply_uris, str) and apply_uris:
                app_link = apply_uris
            else:
                app_link = str(desc.get("PositionURI") or "")

            pub_date = str(desc.get("PublicationStartDate") or "")
            age = _age_days(pub_date, now) if pub_date else None
            salary = _format_usajobs_salary(desc)
            flags = [] if age is not None else ["age_unknown"]

            rows.append(
                SourceRow(
                    company=company or source.query,
                    role=title,
                    location=location,
                    age=f"{age}d" if age is not None else "",
                    age_days=age if age is not None else 0,
                    job_id=f"usajobs:{item['MatchedObjectId']}",
                    application_link=app_link,
                    source_id=source.id,
                    salary=salary,
                    flags=flags,
                )
            )

        count_all = (
            search_result.get("SearchResultCountAll")
            if isinstance(search_result, dict)
            else None
        )
        if isinstance(count_all, int) and page * 100 >= count_all:
            break
        if len(items) < 100:
            break

    return rows, errors


def job_search_rows(
    source: Any,
    *,
    get: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> tuple[list[SourceRow], list[str]]:
    """Fetch postings for a kind='job_search' source, returning (rows, errors).

    Raises:
        MissingCredentialsError: provider API keys are not set.
        ValueError: unsupported provider.
    """
    getter = get or httpx.get
    current_time = now or datetime.now(UTC)

    provider = source.provider
    if provider == "adzuna":
        return _search_adzuna(source, get=getter, now=current_time)
    if provider == "usajobs":
        return _search_usajobs(source, get=getter, now=current_time)
    raise ValueError(f"unsupported job search provider {provider!r}")
