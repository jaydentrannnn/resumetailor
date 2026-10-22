"""The Apply page's progress banner: when applications went out and how far postings got.

Read-only over the registry. Times stay ISO strings so the browser buckets them by the
applicant's own days and weeks; only the counts are worked out here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from pydantic import BaseModel

from . import outcomes, store, store_models

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


#: Days an application has had to hear back before it counts toward reply rates.
COHORT_DAYS = 21


class OutcomeCohort(BaseModel):
    """What happened to applications sent at least ``window_days`` ago. Every rate is
    a count over ``sent``; silence (``no_reply``) is kept apart from rejection."""

    window_days: int = COHORT_DAYS
    sent: int = 0
    responded: int = 0
    #: Reached an interview or further, whatever happened next.
    interviewed: int = 0
    offers: int = 0
    rejected: int = 0
    no_reply: int = 0


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
    outcomes: OutcomeCohort = OutcomeCohort()


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


def outcome_cohort(
    apps: Iterable[store_models.Application], *, today: date | None = None
) -> OutcomeCohort:
    cutoff = ((today or date.today()) - timedelta(days=COHORT_DAYS)).isoformat()
    cohort = OutcomeCohort()
    for app in apps:
        sent = outcomes.sent_on(app)
        if not sent or sent > cutoff:
            continue
        progress = outcomes.hiring_progress(app)
        rank = outcomes.STAGES.index(progress.stage or "applied")
        cohort.sent += 1
        cohort.responded += progress.responded
        cohort.interviewed += rank >= outcomes.STAGES.index("interview")
        cohort.offers += rank >= outcomes.STAGES.index("offer")
        cohort.rejected += progress.closed == "rejected"
        cohort.no_reply += not progress.responded
    return cohort


def progress_stats(
    apps: Iterable[store_models.Application], *, today: date | None = None
) -> ProgressStats:
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
        outcomes=outcome_cohort(rows, today=today),
    )
