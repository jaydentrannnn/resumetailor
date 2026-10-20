"""The Apply page's progress banner: when applications went out and how far postings got.

Read-only over the registry. Times stay ISO strings so the browser buckets them by the
applicant's own days and weeks; only the counts are worked out here.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from . import store, store_models

#: An outcome after sending implies the application was sent, even when the timeline
#: has no ``submitted`` entry (marked by hand straight to Interview, say).
_SENT_STATUSES: frozenset[str] = frozenset({"submitted", "interview", "rejected", "ghosted"})

#: Pipeline stages in order: (key, the statuses that mean a posting got that far).
_STAGES: tuple[tuple[str, frozenset[str]], ...] = (
    ("screened_in", frozenset({"screened_in"})),
    ("tailored", frozenset({"ready"})),
    ("autofilled", frozenset({"filling"})),
    ("sent", _SENT_STATUSES),
)


class SentApplication(BaseModel):
    at: str
    company: str


class PostingTimes(BaseModel):
    """When one posting was found and first reached each later stage (None: never)."""

    company: str
    found_at: str | None
    screened_in_at: str | None
    tailored_at: str | None
    autofilled_at: str | None
    sent_at: str | None


class ProgressStats(BaseModel):
    #: Every sent application, oldest first, archived ones included.
    sent: list[SentApplication]
    #: Every posting with its stage times, so the banner can count any stage over any
    #: dates in the applicant's own time zone (archived ones included).
    postings: list[PostingTimes] = []
    #: Postings ever found, then how many reached each stage (archived ones included).
    found: int
    screened_in: int
    tailored: int
    autofilled: int
    sent_total: int
    #: Live rows only: waiting on the applicant, ready to fill, not screened yet.
    needs_you: int
    ready: int
    unscreened: int


def _reached(app: store_models.Application, statuses: frozenset[str]) -> bool:
    return app.status in statuses or any(c.status in statuses for c in app.status_history)


def _reached_at(app: store_models.Application, statuses: frozenset[str]) -> str | None:
    """When ``app`` first reached one of ``statuses``: its first such timeline entry,
    else its status time (`store.status_at`: discovery, for a row with no timeline)."""
    for change in app.status_history:
        if change.status in statuses:
            return change.at
    if app.status in statuses:
        return store.status_at(app) or None
    return None


def _sent_at(app: store_models.Application) -> str | None:
    """When ``app`` went out."""
    return _reached_at(app, _SENT_STATUSES)


def _posting_times(app: store_models.Application) -> PostingTimes:
    times = {f"{key}_at": _reached_at(app, statuses) for key, statuses in _STAGES}
    return PostingTimes(company=app.company, found_at=app.discovered_at or None, **times)


def progress_stats(apps: Iterable[store_models.Application]) -> ProgressStats:
    """Count the registry for the progress banner."""
    rows = list(apps)
    stages = {key: sum(_reached(app, statuses) for app in rows) for key, statuses in _STAGES}
    sent = [
        SentApplication(at=at, company=app.company)
        for app in rows
        if (at := _sent_at(app)) is not None
    ]
    sent.sort(key=lambda item: item.at)
    live = [app for app in rows if not app.archived_at]
    return ProgressStats(
        sent=sent,
        postings=[_posting_times(app) for app in rows],
        found=len(rows),
        screened_in=stages["screened_in"],
        tailored=stages["tailored"],
        autofilled=stages["autofilled"],
        sent_total=stages["sent"],
        needs_you=sum(store_models.list_group(app) == "review" for app in live),
        ready=sum(app.status == "ready" for app in live),
        unscreened=sum(app.status in ("discovered", "jd_fetched") for app in live),
    )
