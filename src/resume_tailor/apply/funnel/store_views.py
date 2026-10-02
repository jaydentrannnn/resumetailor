"""Read-only views over the registry: listing, counts, CSV export and the review summary."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from . import store, store_models


def list_applications(
    *,
    status: store_models.ApplicationStatus | None = None,
    limit: int | None = None,
    offset: int = 0,
    q: str = "",
    archive: Literal["active", "archived", "all"] = "all",
    sort: Literal["posted_at", "status_at", "discovered_at", "archived_at", "company", "role", "location", "status", "coverage", "salary", "ats", "sources"] = "discovered_at",
    direction: Literal["asc", "desc"] = "desc",
    group: Literal["review", "working"] | None = None,
    applications: list[store_models.Application] | None = None,
) -> list[store_models.Application]:
    """Return applications sorted over the whole filtered list, then paged.

    ``group="review"`` keeps only `REVIEW_STATUSES`; ``"working"`` drops them. Ties in
    the sort column fall back to newest-discovered, then company, so a coarse column
    (Platform, Status) still reads in a sensible order page after page.
    """
    apps = filtered_applications(q=q, archive=archive, applications=applications)
    if status is not None:
        apps = [row for row in apps if row.status == status]
    if group is not None:
        apps = [
            row
            for row in apps
            if (row.status in store_models.REVIEW_STATUSES) == (group == "review")
        ]
    apps.sort(key=lambda row: row.company.casefold())
    apps.sort(key=lambda row: row.discovered_at or "", reverse=True)
    def sort_value(row: store_models.Application) -> str | float | None:
        if sort == "posted_at":
            return store_models.posted_date(row)[0] or None
        if sort == "status_at":
            raw_at = store.status_at(row)
            if not raw_at:
                return None
            try:
                parsed = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=UTC).timestamp() if parsed.tzinfo is None else parsed.timestamp()
            except ValueError:
                return None
        if sort == "status":
            return store_models._STATUS_RANK.get(row.status, len(store_models._STATUS_RANK))
        if sort == "coverage":
            screen = row.screen
            total = screen.coverage_total if screen else 0
            return screen.coverage_matched / total if screen and total > 0 else None
        if sort == "sources":
            return ", ".join(sorted({ref.source for ref in row.source_refs})).casefold() if row.source_refs else row.source.casefold()
        raw = getattr(row, sort, None)
        return str(raw).strip().casefold() if raw else None
    values = {id(row): sort_value(row) for row in apps}
    apps.sort(key=lambda row: values[id(row)] if values[id(row)] is not None else (0.0 if sort in {"coverage", "status_at"} else ""), reverse=direction == "desc")
    apps.sort(key=lambda row: values[id(row)] is None)
    apps = apps[max(0, offset):]
    if limit is not None:
        apps = apps[: max(0, limit)]
    return apps

def filtered_applications(
    *,
    q: str = "",
    archive: Literal["active", "archived", "all"] = "all",
    applications: list[store_models.Application] | None = None,
) -> list[store_models.Application]:
    query = q.strip().casefold()
    return [
        app for app in (applications if applications is not None else store.load_all().values())
        if (archive == "all" or bool(app.archived_at) == (archive == "archived"))
        and (not query or query in app.company.casefold() or query in app.role.casefold() or query in app.location.casefold())
    ]

def status_counts() -> dict[str, int]:
    """Count applications grouped by ``status``."""
    counts: dict[str, int] = {}
    with store._LOCK:
        rows = list(store._snapshot().values())
    for app in rows:
        counts[app.status] = counts.get(app.status, 0) + 1
    return counts

_CSV_COLUMNS: tuple[str, ...] = (
    "source_job_id",
    "company",
    "role",
    "location",
    "status",
    "posting_url",
    "final_url",
    "ats",
    "sponsorship_ok",
    "citizenship_required",
    "discovered_at",
    "job_id",
    "reused_from_job_id",
    "notes",
    "error",
    "canonical_key",
    "group_key",
    "sources",
    "salary",
    "duplicate_of",
    "archived_at",
    "flags",
)

def export_csv() -> str:
    """Render the application tracker as CSV with a header row."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for app in list_applications():
        source_ids = (
            ";".join(ref.source for ref in app.source_refs)
            if app.source_refs
            else app.source
        )
        writer.writerow(
            [
                app.source_job_id,
                app.company,
                app.role,
                app.location,
                app.status,
                app.posting_url,
                app.final_url,
                app.ats,
                app.sponsorship_ok,
                app.citizenship_required,
                app.discovered_at,
                app.job_id or "",
                app.reused_from_job_id or "",
                app.notes,
                app.error or "",
                app.canonical_key,
                app.group_key,
                source_ids,
                app.salary,
                app.duplicate_of or "",
                app.archived_at or "",
                ";".join(app.eligibility_flags),
            ]
        )
    return buffer.getvalue()

#: Outcome states that need the applicant (mirrors the SPA's `reviewGroup` "attention").
_ATTENTION_STATES = frozenset({"manual_review", "ambiguous", "invalid_existing", "failed"})

_SIGN_IN_HANDOFF = re.compile(r"sign in|sign-in|password|account terms|create account", re.I)

_SUMMARY_LABEL_CHARS = 40

def _clean_label(label: str) -> str:
    """A field label fit for a table cell; '' for a bare element id."""
    text = " ".join(str(label or "").split()).rstrip("*").strip()
    if not text or text.startswith("#") or (" " not in text and "--" in text):
        return ""
    if len(text) <= _SUMMARY_LABEL_CHARS:
        return text
    return text[: _SUMMARY_LABEL_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,:;") + "…"

def review_summary(app: store_models.Application) -> str | None:
    """A short "what needs you" line for a row in `REVIEW_STATUSES`, else None.

    Names the first field waiting on the applicant ("Salary expectations +2"), or the
    kind of hand-off when no single field is to blame.
    """
    if app.status not in store_models.REVIEW_STATUSES:
        return None
    if app.status == "awaiting_otp":
        return "Verification code"
    if app.status == "submit_unconfirmed":
        return "Confirm submission"
    fill = (
        store_models.FillResult.model_validate(app.fill) if isinstance(app.fill, dict) else app.fill
    )
    if fill is None:
        return "Fill failed" if app.status == "fill_failed" else "Check the form"
    if fill.handoff_reason and _SIGN_IN_HANDOFF.search(fill.handoff_reason):
        return "Sign-in needed"
    labels: list[str] = []
    for outcome in fill.field_outcomes:
        state = outcome.get("state")
        if state in _ATTENTION_STATES or (state == "unanswered" and outcome.get("required") is True):
            labels.append(_clean_label(outcome.get("label") or ""))
    for item in fill.leftovers:
        if isinstance(item, dict) and (item.get("required") or item.get("reason") == "needs_review"):
            labels.append(_clean_label(item.get("label") or ""))
    labels.extend(_clean_label(entry) for entry in fill.required_empty)
    unique = list(dict.fromkeys(label for label in labels if label))
    if unique:
        return unique[0] if len(unique) == 1 else f"{unique[0]} +{len(unique) - 1}"
    if app.status == "fill_failed":
        return "Fill failed"
    if fill.ready_to_submit:
        return "Ready to submit"
    return "Check the form"
