"""Discovery source helpers for the Apply settings (plan P4-D).

- ``GET /api/apply/sources/sections?url=``: the categories a README source offers, so
  the settings show checkboxes instead of free text.
- ``POST /api/apply/boards/resolve``: turn a careers URL (or an ``ats``/``slug`` pair)
  into a checked board before it joins a watchlist. A wrong name answers 404 here,
  when the student can fix it, rather than failing silently every night.
- ``GET /api/apply/watchlists``: the suggested boards per field.
"""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from ipaddress import ip_address
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from resume_tailor.apply import boards, sources

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


def _embedded_board(url: str) -> tuple[boards.BoardAts, str]:
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise HTTPException(status_code=400, detail="Enter a careers page web address.")
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="Enter a public careers page web address.")
    try:
        if not ip_address(host).is_global:
            raise HTTPException(status_code=400, detail="Enter a public careers page web address.")
    except ValueError:
        pass
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
