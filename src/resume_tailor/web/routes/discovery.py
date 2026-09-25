"""Discovery source helpers for the Apply settings (plan P4-D).

- ``GET /api/apply/sources/sections?url=``: the categories a README source offers, so
  the settings show checkboxes instead of free text.
- ``POST /api/apply/boards/resolve``: turn a careers URL (or an ``ats``/``slug`` pair)
  into a checked board before it joins a watchlist. A wrong name answers 404 here,
  when the student can fix it, rather than failing silently every night.
- ``GET /api/apply/watchlists``: the suggested boards per field.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from resume_tailor.apply import boards, sources

router = APIRouter()


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
            raise HTTPException(
                status_code=400,
                detail=(
                    "That is not a Greenhouse, Lever, Ashby or SmartRecruiters job board "
                    "link. Open the company's careers page, click a job, and paste that "
                    "address."
                ),
            )
        ats, slug = parsed
    else:
        ats, slug = body.ats.strip().lower(), body.slug.strip()
        if ats not in boards.BOARD_ATS or not boards.valid_slug(slug):
            raise HTTPException(status_code=400, detail="Give a job board link.")
    try:
        jobs = boards.list_board(ats, slug)
    except boards.BoardNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"No {ats} job board is named {slug!r}."
        ) from exc
    except boards.BoardUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"Could not check the board: {exc}") from exc
    company = body.company.strip() or next((j.company for j in jobs if j.company), "") or slug
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
