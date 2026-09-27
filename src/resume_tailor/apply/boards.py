"""Company watchlist source: public ATS job boards (plan P4-D2).

Finance and consulting postings rarely reach the Simplify READMEs, but many firms
publish their whole job board through a public, unauthenticated API. A watchlist is a
list of ``(ats, slug)`` boards. `board_rows` turns their postings into the same
`SourceRow`s the README parsers produce, so screening, dedupe and tailoring are shared.

Supported boards and their endpoints:

- Greenhouse: ``boards-api.greenhouse.io/v1/boards/{slug}/jobs``
- Lever: ``api.lever.co/v0/postings/{slug}?mode=json``
- Ashby: ``api.ashbyhq.com/posting-api/job-board/{slug}``
- SmartRecruiters: ``api.smartrecruiters.com/v1/companies/{slug}/postings`` (paged)
- Workday: ``{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`` (paged POST)

Each posting's URL is the ATS's own job URL, so `identity.canonical_key` gives the same
key a Simplify row for the same job gets, and the two sightings merge.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import httpx

BoardAts = Literal["greenhouse", "lever", "ashby", "smartrecruiters", "workday"]
BOARD_ATS: tuple[BoardAts, ...] = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")

#: Pause between two boards, to stay polite to the public APIs.
BOARD_DELAY_SECONDS = 1.0
#: SmartRecruiters pages hold 100 postings; stop after this many pages.
_SMART_MAX_PAGES = 10
_WORKDAY_MAX_PAGES = 10
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_WORKDAY_SLUG_RE = re.compile(
    r"^(?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)/"
    r"(?P<tenant>[A-Za-z0-9_-]+)/(?P<site>[A-Za-z0-9_-]+)$"
)
_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_POSTED_AGO_RE = re.compile(r"^Posted (\d+)\+? (Day|Week|Month|Year)s? Ago$", re.I)

_sleep: Callable[[float], None] = time.sleep


class BoardNotFound(LookupError):
    """The ATS answered 404: the slug is wrong or the board was taken down."""


class BoardUnavailable(RuntimeError):
    """The board could not be read right now (network, rate limit, bad JSON)."""


@dataclass(frozen=True)
class BoardJob:
    id: str
    title: str
    location: str
    url: str
    #: ISO timestamp of the posting's last update (or publication); "" when unknown.
    updated_at: str
    company: str = ""


def valid_slug(slug: str, ats: str | None = None) -> bool:
    if ats == "workday":
        match = _WORKDAY_SLUG_RE.fullmatch(slug or "")
        return bool(
            match and len(slug) <= 100
            and match["host"].split(".")[0].lower() == match["tenant"].lower()
        )
    return bool(_SLUG_RE.fullmatch(slug or ""))


def board_url(ats: str, slug: str) -> str:
    """The public careers page for a board, for links in the UI."""
    if ats == "workday" and valid_slug(slug, ats):
        host, _tenant, site = slug.split("/")
        return f"https://{host}.myworkdayjobs.com/{site}"
    return {
        "greenhouse": f"https://boards.greenhouse.io/{slug}",
        "lever": f"https://jobs.lever.co/{slug}",
        "ashby": f"https://jobs.ashbyhq.com/{slug}",
        "smartrecruiters": f"https://jobs.smartrecruiters.com/{slug}",
    }.get(ats, "")


def parse_board_url(url: str) -> tuple[BoardAts, str] | None:
    """``(ats, slug)`` from a careers-page or job URL; None when it is not a board.

    Accepts ``boards.greenhouse.io/acme``, ``job-boards.greenhouse.io/acme/jobs/1``,
    ``boards.greenhouse.io/embed/job_board?for=acme``, ``jobs.lever.co/acme``,
    ``jobs.ashbyhq.com/acme``, ``jobs.smartrecruiters.com/Acme`` and
    ``careers.smartrecruiters.com/Acme``. Workday slugs are
    ``{host-prefix}/{tenant}/{site}``, e.g. ``acme.wd5/acme/External``;
    the host prefix excludes ``.myworkdayjobs.com``.
    """
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    slug = ""
    ats: BoardAts | None = None
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        ats = "greenhouse"
        query = parse_qs(parts.query)
        if segments[:1] == ["embed"] and query.get("for"):
            slug = query["for"][0]
        elif segments:
            slug = segments[0]
    elif host == "jobs.lever.co" and segments:
        ats, slug = "lever", segments[0]
    elif host == "jobs.ashbyhq.com" and segments:
        ats, slug = "ashby", segments[0]
    elif host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"} and segments:
        ats, slug = "smartrecruiters", segments[0]
    elif host.endswith(".myworkdayjobs.com") and segments:
        host_prefix = host.removesuffix(".myworkdayjobs.com")
        if _LOCALE_RE.fullmatch(segments[0]):
            segments = segments[1:]
        if segments:
            ats, slug = "workday", f"{host_prefix}/{host_prefix.split('.')[0]}/{segments[0]}"
    if ats is None or not valid_slug(slug, ats):
        return None
    return ats, slug


def _get(url: str, *, get: Callable[..., Any], payload: dict[str, Any] | None = None) -> Any:
    try:
        kwargs: dict[str, Any] = {"follow_redirects": True, "timeout": 20.0}
        if payload is not None:
            kwargs["json"] = payload
        response = get(url, **kwargs)
    except httpx.HTTPError as exc:
        raise BoardUnavailable(f"could not reach {urlsplit(url).hostname}: {exc}") from exc
    if response.status_code == 404:
        raise BoardNotFound(url)
    if response.status_code != 200:
        raise BoardUnavailable(f"{urlsplit(url).hostname} answered {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise BoardUnavailable(f"{urlsplit(url).hostname} sent something that is not JSON") from exc


def _iso_from_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _greenhouse(slug: str, get: Callable[..., Any]) -> list[BoardJob]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", get=get)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    out = []
    for job in jobs or []:
        if not isinstance(job, dict) or not job.get("id"):
            continue
        location = job.get("location") or {}
        out.append(
            BoardJob(
                id=str(job["id"]),
                title=str(job.get("title") or "").strip(),
                location=str(location.get("name") or "") if isinstance(location, dict) else "",
                url=f"https://boards.greenhouse.io/{slug}/jobs/{job['id']}",
                updated_at=str(job.get("updated_at") or job.get("first_published") or ""),
                company=str(job.get("company_name") or ""),
            )
        )
    return out


def _lever(slug: str, get: Callable[..., Any]) -> list[BoardJob]:
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json", get=get)
    out = []
    for job in data if isinstance(data, list) else []:
        if not isinstance(job, dict) or not job.get("id"):
            continue
        categories = job.get("categories") or {}
        location = categories.get("location") if isinstance(categories, dict) else ""
        out.append(
            BoardJob(
                id=str(job["id"]),
                title=str(job.get("text") or "").strip(),
                location=str(location or ""),
                url=str(job.get("hostedUrl") or f"https://jobs.lever.co/{slug}/{job['id']}"),
                updated_at=_iso_from_ms(job.get("updatedAt") or job.get("createdAt")),
            )
        )
    return out


def _ashby(slug: str, get: Callable[..., Any]) -> list[BoardJob]:
    from resume_tailor.apply import ats_api

    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", get=get)
    if isinstance(data, dict):
        # The JD fetch for these postings reads the same board; don't download it twice.
        ats_api._ASHBY_BOARD_CACHE[slug] = data  # noqa: SLF001
    jobs = data.get("jobs") if isinstance(data, dict) else None
    out = []
    for job in jobs or []:
        if not isinstance(job, dict) or not job.get("id") or job.get("isListed") is False:
            continue
        out.append(
            BoardJob(
                id=str(job["id"]),
                title=str(job.get("title") or "").strip(),
                location=str(job.get("location") or ""),
                url=str(job.get("jobUrl") or f"https://jobs.ashbyhq.com/{slug}/{job['id']}"),
                updated_at=str(job.get("updatedAt") or job.get("publishedAt") or ""),
            )
        )
    return out


def _smartrecruiters(slug: str, get: Callable[..., Any]) -> list[BoardJob]:
    out: list[BoardJob] = []
    for page in range(_SMART_MAX_PAGES):
        data = _get(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
            f"?limit=100&offset={page * 100}",
            get=get,
        )
        content = data.get("content") if isinstance(data, dict) else None
        if not content:
            break
        for job in content:
            if not isinstance(job, dict) or not job.get("id"):
                continue
            location = job.get("location") or {}
            place = ", ".join(
                str(location.get(key))
                for key in ("city", "region", "country")
                if isinstance(location, dict) and location.get(key)
            )
            if isinstance(location, dict) and location.get("remote"):
                place = f"{place} (Remote)".strip()
            company = job.get("company") or {}
            out.append(
                BoardJob(
                    id=str(job["id"]),
                    title=str(job.get("name") or "").strip(),
                    location=place,
                    url=f"https://jobs.smartrecruiters.com/{slug}/{job['id']}",
                    updated_at=str(job.get("releasedDate") or ""),
                    company=str(company.get("name") or "") if isinstance(company, dict) else "",
                )
            )
        total = data.get("totalFound") if isinstance(data, dict) else None
        if not isinstance(total, int) or (page + 1) * 100 >= total:
            break
    return out


def _workday_date(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.lower() == "posted today":
        return datetime.now(UTC).date().isoformat()
    if value.lower() == "posted yesterday":
        return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    match = _POSTED_AGO_RE.fullmatch(value)
    if match:
        unit_days = {"day": 1, "week": 7, "month": 30, "year": 365}
        days = int(match[1]) * unit_days[match[2].lower()]
        return (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return ""


def _workday(slug: str, post: Callable[..., Any]) -> list[BoardJob]:
    host, tenant, site = slug.split("/")
    root = f"https://{host}.myworkdayjobs.com"
    endpoint = f"{root}/wday/cxs/{tenant}/{site}/jobs"
    out: list[BoardJob] = []
    for page in range(_WORKDAY_MAX_PAGES):
        data = _get(endpoint, get=post, payload={
            "limit": 20, "offset": page * 20, "searchText": "", "appliedFacets": {},
        })
        postings = data.get("jobPostings") if isinstance(data, dict) else None
        if not isinstance(postings, list) or not postings:
            break
        for job in postings:
            if not isinstance(job, dict) or not job.get("externalPath"):
                continue
            path = str(job["externalPath"])
            if not path.startswith("/") or path.startswith("//"):
                continue
            posting_path = path if path.startswith(f"/{site}/") else f"/{site}{path}"
            out.append(BoardJob(
                id=posting_path.rsplit("/", 1)[-1],
                title=str(job.get("title") or "").strip(),
                location=str(job.get("locationsText") or ""),
                url=f"{root}{posting_path}",
                updated_at=_workday_date(job.get("postedOn")),
            ))
        total = data.get("total") if isinstance(data, dict) else None
        if not isinstance(total, int) or (page + 1) * 20 >= total:
            break
    return out


_LISTERS: dict[str, Callable[[str, Callable[..., Any]], list[BoardJob]]] = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "smartrecruiters": _smartrecruiters,
}


def list_board(
    ats: str, slug: str, *, get: Callable[..., Any] | None = None,
    post: Callable[..., Any] | None = None,
) -> list[BoardJob]:
    """Every open posting on one board.

    Raises:
        BoardNotFound: the ATS has no such board (404).
        BoardUnavailable: anything else that stopped the read.
        ValueError: an unsupported ATS or a malformed slug.
    """
    if ats not in BOARD_ATS:
        raise ValueError(f"unsupported board ATS {ats!r}")
    if not valid_slug(slug, ats):
        raise ValueError(f"not a board name: {slug!r}")
    if ats == "workday":
        return _workday(slug, post or httpx.post)
    return _LISTERS[ats](slug, get or httpx.get)


# --- starter watchlists -----------------------------------------------------------


def watchlists() -> dict[str, list[dict[str, str]]]:
    """Suggested boards per field, from ``apply/watchlists/*.json``.

    These are suggestions only: the app checks each board live before it joins a
    watchlist (``POST /api/apply/boards/resolve``), so a renamed board is never added
    silently.
    """
    folder = resources.files("resume_tailor.apply").joinpath("watchlists")
    out: dict[str, list[dict[str, str]]] = {}
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(".json"):
            continue
        raw = json.loads(entry.read_text(encoding="utf-8"))
        boards = [
            {"ats": str(b["ats"]), "slug": str(b["slug"]), "company": str(b.get("company") or "")}
            for b in raw.get("boards", [])
            if isinstance(b, dict) and b.get("ats") in BOARD_ATS
            and valid_slug(str(b.get("slug")), str(b.get("ats")))
        ]
        out[entry.name.removesuffix(".json")] = boards
    return out
