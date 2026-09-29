"""Discovery source helpers for the Apply settings (plan P4-D).

- ``GET /api/apply/sources/sections?url=``: the categories a README source offers, so
  the settings show checkboxes instead of free text.
- ``POST /api/apply/boards/resolve``: turn a careers URL (or an ``ats``/``slug`` pair)
  into a checked board before it joins a watchlist. A wrong name answers 404 here,
  when the student can fix it, rather than failing silently every night.
- ``GET /api/apply/watchlists``: the suggested boards per field.
- ``GET /api/apply/catalog``: the curated source catalog (remote, cached, or bundled).
- ``POST /api/apply/sources/inspect``: fetch a README once and report its detected
  format, categories and row count.
- ``POST /api/apply/sources/test``: run one source once through the funnel's filters
  (nothing saved, no LLM) so the student sees what it would bring in.
"""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from resume_tailor import workspace
from resume_tailor.apply import boards, source_catalog, sources
from resume_tailor.web.schemas import JobSettings, SourceConfig

router = APIRouter()
_PAGE_LIMIT = 2 * 1024 * 1024
_NO_BOARD = (
    "No supported job board (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) "
    "was found on that page."
)


class _BoardLinks(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.candidates: Counter[tuple[boards.BoardAts, str]] = Counter()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attribute = {"iframe": "src", "script": "src", "a": "href"}.get(tag)
        if attribute is None:
            return
        link = dict(attrs).get(attribute)
        if link:
            parsed = boards.parse_board_url(urljoin(self.base_url, link))
            if parsed:
                self.candidates[parsed] += 1


def _fetch_career_page(url: str) -> str:
    """Fetch one bounded HTML page for board links; never scrape its job listings."""
    try:
        with httpx.stream(
            "GET", url, follow_redirects=True, timeout=8.0,
            headers={
                "User-Agent": "ResumeTailor/1.0 (career board discovery)",
                "Accept": "text/html",
            },
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > _PAGE_LIMIT:
                    raise ValueError("The careers page is too large to inspect.")
            return content.decode(response.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise ValueError(f"Could not read the careers page: {exc}") from exc


def _require_public_url(url: str, *, what: str = "careers page") -> str:
    """``url`` with a scheme, or 400 when it is not a public http(s) address."""
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise HTTPException(status_code=400, detail=f"Enter a {what} web address.")
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise HTTPException(status_code=400, detail=f"Enter a public {what} web address.")
    try:
        if not ip_address(host).is_global:
            raise HTTPException(status_code=400, detail=f"Enter a public {what} web address.")
    except ValueError:
        pass
    return url


def _embedded_board(url: str) -> tuple[boards.BoardAts, str]:
    url = _require_public_url(url)
    try:
        html = _fetch_career_page(url)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    links = _BoardLinks(url)
    links.feed(html)
    if not links.candidates:
        raise HTTPException(status_code=404, detail=_NO_BOARD)
    most_common = links.candidates.most_common()
    top_count = most_common[0][1]
    tied = [board for board, count in most_common if count == top_count]
    if len(tied) > 1:
        choices = ", ".join(boards.board_url(ats, slug) for ats, slug in tied)
        raise HTTPException(status_code=409, detail=f"Several job boards were found: {choices}")
    return most_common[0][0]


class SectionsResponse(BaseModel):
    sections: list[str]


class BoardResolveRequest(BaseModel):
    url: str = ""
    ats: str = ""
    slug: str = ""
    company: str = ""


class BoardResolved(BaseModel):
    ats: str
    slug: str
    company: str
    jobs: int
    url: str


class WatchlistBoard(BaseModel):
    ats: str
    slug: str
    company: str


class WatchlistsResponse(BaseModel):
    fields: dict[str, list[WatchlistBoard]]


@router.get("/api/apply/sources/sections", response_model=SectionsResponse)
def source_sections(url: str = Query(min_length=8, max_length=2000)) -> SectionsResponse:
    if not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Enter the README's web address.")
    try:
        readme = sources.fetch_readme(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read the list: {exc}") from exc
    names = [name for _level, name in sources.list_sections(readme)]
    return SectionsResponse(sections=list(dict.fromkeys(names)))


@router.post("/api/apply/boards/resolve", response_model=BoardResolved)
def resolve_board(body: BoardResolveRequest) -> BoardResolved:
    if body.url.strip():
        parsed = boards.parse_board_url(body.url)
        if parsed is None:
            parsed = _embedded_board(body.url.strip())
        ats, slug = parsed
    else:
        ats, slug = body.ats.strip().lower(), body.slug.strip()
        if ats not in boards.BOARD_ATS or not boards.valid_slug(slug, ats):
            raise HTTPException(status_code=400, detail="Give a job board link.")
    try:
        jobs = boards.list_board(ats, slug)
    except boards.BoardNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"No {ats} job board is named {slug!r}."
        ) from exc
    except boards.BoardUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"Could not check the board: {exc}") from exc
    company = (
        body.company.strip() or next((j.company for j in jobs if j.company), "")
        or (slug.split("/")[1] if ats == "workday" else slug)
    )
    return BoardResolved(
        ats=ats, slug=slug, company=company, jobs=len(jobs), url=boards.board_url(ats, slug)
    )


@router.get("/api/apply/watchlists", response_model=WatchlistsResponse)
def list_watchlists() -> WatchlistsResponse:
    return WatchlistsResponse(
        fields={
            name: [WatchlistBoard(**board) for board in entries]
            for name, entries in boards.watchlists().items()
        }
    )


# --- source catalog, inspect, test (Sources tab) ------------------------------------

#: Rows shown in a Test result.
_TEST_SAMPLE = 5


class SourceInspectRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class SourceInspection(BaseModel):
    kind: Literal["simplify_html", "pipe_table", "company_link_table"] | None
    sections: list[str]
    row_count: int


class SourceTestRequest(BaseModel):
    source: SourceConfig


class SourceTestRow(BaseModel):
    company: str
    role: str
    location: str
    age: str
    posted_at: str
    application_link: str | None


class SourceTestResult(BaseModel):
    rows_total: int
    rows_kept: int
    sample: list[SourceTestRow]
    errors: list[str]


@router.get("/api/apply/catalog", response_model=source_catalog.CatalogResponse)
def get_catalog() -> source_catalog.CatalogResponse:
    return source_catalog.load_catalog()


@router.post("/api/apply/sources/inspect", response_model=SourceInspection)
def inspect_source(body: SourceInspectRequest) -> SourceInspection:
    url = _require_public_url(body.url.strip(), what="README")
    try:
        readme = sources.fetch_readme(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read the list: {exc}") from exc
    kind = sources.detect_format(readme)
    if kind is None:
        return SourceInspection(kind=None, sections=[], row_count=0)
    return SourceInspection(
        kind=kind,
        sections=sources.source_sections(kind, readme),
        row_count=len(sources.parse_source_text(kind, readme, [])),
    )


@router.post("/api/apply/sources/test", response_model=SourceTestResult)
def test_source(body: SourceTestRequest) -> SourceTestResult:
    src = body.source
    if src.kind in sources.README_KINDS:
        _require_public_url(src.url.strip(), what="README")
    try:
        rows, errors = sources.fetch_source_rows(src)
    except Exception as exc:  # noqa: BLE001 - a failed source is a result, not a 500
        return SourceTestResult(rows_total=0, rows_kept=0, sample=[], errors=[str(exc)])
    settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
    filtered = sources.filter_rows(
        rows,
        max_age_days=(
            max(src.max_age_days, settings.max_age_days)
            if src.max_age_days is not None
            else settings.max_age_days
        ),
        exclude_advanced_degree=settings.exclude_advanced_degree,
        exclude_citizenship=settings.exclude_citizenship_required,
        exclude_no_sponsorship=settings.exclude_no_sponsorship,
        known_ids=set(),
        eligibility=settings.eligibility,
    )
    return SourceTestResult(
        rows_total=len(rows),
        rows_kept=len(filtered.new_rows),
        sample=[
            SourceTestRow(**row.model_dump(include=set(SourceTestRow.model_fields)))
            for row in filtered.new_rows[:_TEST_SAMPLE]
        ],
        errors=errors,
    )
