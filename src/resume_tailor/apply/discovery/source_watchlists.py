"""Company watchlist rows and keyword filters (``kind="ats_board"``)."""

from __future__ import annotations

import re
from typing import Any

from . import source_rows


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
) -> tuple[list[source_rows.SourceRow], list[str]]:
    """Postings from every board on a watchlist source, and one error per failed board.

    ``source`` is a `SourceConfig` with ``kind="ats_board"``. A board that fails
    (wrong name, unreachable) is reported and skipped; the others still count.
    A posting with no date is kept as new (``age_days=0``, flag ``age_unknown``):
    boards only list open postings.
    """
    from datetime import UTC, datetime

    from resume_tailor.apply.discovery import boards, identity

    list_board = list_board or boards.list_board
    now = now or datetime.now(UTC)
    include, exclude, places = source_keyword_filters(source)
    rows: list[source_rows.SourceRow] = []
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
                source_rows.SourceRow(
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
