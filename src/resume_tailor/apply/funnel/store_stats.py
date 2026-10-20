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


class ProgressStats(BaseModel):
    #: Every sent application, oldest first, archived ones included.
    sent: list[SentApplication]
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


def _sent_at(app: store_models.Application) -> str | None:
    """When ``app`` went out: its first sent-like timeline entry, else its status time
    (`store.status_at`: discovery, for a row with no timeline)."""
    for change in app.status_history:
        if change.status in _SENT_STATUSES:
            return change.at
    if app.status in _SENT_STATUSES:
        return store.status_at(app) or None
    return None


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
        found=len(rows),
        screened_in=stages["screened_in"],
        tailored=stages["tailored"],
        autofilled=stages["autofilled"],
        sent_total=stages["sent"],
        needs_you=sum(store_models.list_group(app) == "review" for app in live),
        ready=sum(app.status == "ready" for app in live),
        unscreened=sum(app.status in ("discovered", "jd_fetched") for app in live),
    )
