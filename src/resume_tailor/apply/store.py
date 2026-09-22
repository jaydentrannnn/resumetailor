"""Application funnel state persisted in ``applications.json``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply import identity
from resume_tailor.apply.screen import ScreenResult

ApplicationStatus = Literal[
    "discovered",
    "jd_fetched",
    "needs_browser",
    "screened_out",
    "screened_in",
    "tailoring",
    "tailor_failed",
    "ready",
    "filling",
    "fill_failed",
    "awaiting_review",
    "submitted",
    "submit_unconfirmed",
    "interview",
    "rejected",
    "ghosted",
    "skipped",
]

AtsKind = Literal[
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "icims",
    "smartrecruiters",
    "other",
    "unknown",
]

#: Statuses that close the funnel — must not revert to pre-ready states.
_TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"submitted", "interview", "rejected", "ghosted", "skipped"}
)

#: Discovery/screen/tailor stages before a packet is ``ready``.
_PRE_READY_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        "discovered",
        "jd_fetched",
        "needs_browser",
        "screened_out",
        "screened_in",
        "tailoring",
        "tailor_failed",
    }
)

SCHEMA_VERSION = 2


class StatusChange(BaseModel):
    """One entry in an application's status timeline."""

    status: ApplicationStatus
    at: str
    note: str = ""


class FillResult(BaseModel):
    """Form-fill outcome persisted on ``Application.fill``."""

    filled: list[Any] = Field(default_factory=list)
    leftovers: list[Any] = Field(default_factory=list)
    long_text_answers: dict[str, str] = Field(default_factory=dict)
    required_empty: list[str] = Field(default_factory=list)
    ready_to_submit: bool = False
    submit_action: str = ""
    confirmation: str = ""
    screenshot_path: str | None = None
    error: str | None = None
    status: str = ""


class SourceRef(BaseModel):
    """One discovery sighting of a posting (Simplify UUID, speedyapply hash, …)."""

    source: str
    source_job_id: str
    url: str = ""
    first_seen: str = ""


class Application(BaseModel):
    """One tracked posting from discovery through submit."""

    source: str
    source_job_id: str
    company: str
    role: str
    location: str = ""
    posting_url: str = ""
    final_url: str = ""
    ats: AtsKind = "unknown"
    sponsorship_ok: str = "Unknown"
    citizenship_required: str = "No"
    notes: str = ""
    status: ApplicationStatus = "discovered"
    status_history: list[StatusChange] = Field(default_factory=list)
    discovered_at: str = ""
    jd_text_path: str | None = None
    screen: ScreenResult | None = None
    job_id: str | None = None
    reused_from_job_id: str | None = None
    fill: FillResult | dict[str, Any] | None = None
    error: str | None = None
    canonical_key: str = ""
    group_key: str = ""
    source_refs: list[SourceRef] = Field(default_factory=list)
    age_days: int | None = None
    salary: str = ""
    duplicate_of: str | None = None
    eligibility_flags: list[str] = Field(default_factory=list)


@dataclass
class Index:
    """In-memory lookup tables over the applications registry."""

    by_canonical: dict[str, Application] = field(default_factory=dict)
    by_source_ref: dict[tuple[str, str], str] = field(default_factory=dict)
    by_group: dict[str, list[str]] = field(default_factory=dict)


def _path() -> Path:
    """Active workspace's applications registry path."""
    return config.APPLICATIONS_PATH


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _registry_key(app: Application) -> str:
    """Primary dict key: canonical_key when set, else legacy source_job_id."""
    return app.canonical_key or app.source_job_id


def _migrate_v1(apps_raw: dict[str, Any]) -> dict[str, Application]:
    """Rekey a schema-v1 registry onto canonical keys and attach source_refs."""
    out: dict[str, Application] = {}
    for _key, value in apps_raw.items():
        app = Application.model_validate(value)
        url = app.final_url or app.posting_url
        if not app.canonical_key:
            app.canonical_key = identity.canonical_key(url) if url else f"legacy:{app.source_job_id}"
        if not app.group_key:
            app.group_key = identity.group_key(app.company, app.role)
        if not app.source_refs:
            app.source_refs = [
                SourceRef(
                    source=app.source,
                    source_job_id=app.source_job_id,
                    url=app.posting_url,
                    first_seen=app.discovered_at,
                )
            ]
        out[_registry_key(app)] = app
    return out


def load_all() -> dict[str, Application]:
    """Load every application keyed by ``canonical_key`` (or legacy id).

    Schema v1 files are migrated in memory and rewritten once as v2.
    """
    path = _path()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    apps_raw = raw.get("applications", {})
    if not isinstance(apps_raw, dict):
        return {}
    version = int(raw.get("schema_version") or 1)
    if version < 2:
        migrated = _migrate_v1(apps_raw)
        save_all(migrated)
        return migrated
    out: dict[str, Application] = {}
    for key, value in apps_raw.items():
        app = Application.model_validate(value)
        out[str(key)] = app
    return out


def save_all(apps: dict[str, Application]) -> None:
    """Persist the full registry atomically under schema version 2."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "applications": {key: app.model_dump() for key, app in apps.items()},
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def build_index(apps: dict[str, Application] | None = None) -> Index:
    """Build canonical / source-ref / group lookup tables."""
    if apps is None:
        apps = load_all()
    index = Index()
    for key, app in apps.items():
        ckey = app.canonical_key or key
        index.by_canonical[ckey] = app
        refs = app.source_refs or [
            SourceRef(source=app.source, source_job_id=app.source_job_id)
        ]
        for ref in refs:
            index.by_source_ref[(ref.source, ref.source_job_id)] = ckey
        # Always index the mirrored primary source_job_id too.
        index.by_source_ref[(app.source, app.source_job_id)] = ckey
        if app.group_key:
            index.by_group.setdefault(app.group_key, []).append(ckey)
    return index


def get(key: str) -> Application | None:
    """Return one application by canonical key or any source_job_id."""
    apps = load_all()
    if key in apps:
        return apps[key]
    index = build_index(apps)
    if key in index.by_canonical:
        return index.by_canonical[key]
    for (_source, source_job_id), ckey in index.by_source_ref.items():
        if source_job_id == key:
            return index.by_canonical.get(ckey) or apps.get(ckey)
    return None


def upsert(app: Application) -> Application:
    """Insert or replace one application and persist the registry."""
    apps = load_all()
    key = _registry_key(app)
    # Drop a stale legacy key if we are promoting to a canonical key.
    if app.canonical_key and app.source_job_id in apps and app.source_job_id != key:
        del apps[app.source_job_id]
    apps[key] = app
    save_all(apps)
    return app


def all_ids() -> set[tuple[str, str]]:
    """Return every ``(source, source_job_id)`` currently on disk."""
    refs: set[tuple[str, str]] = set()
    for app in load_all().values():
        if app.source_refs:
            for ref in app.source_refs:
                refs.add((ref.source, ref.source_job_id))
        else:
            refs.add((app.source, app.source_job_id))
    return refs


def add_source_ref(app: Application, ref: SourceRef) -> Application:
    """Append ``ref`` when its ``(source, source_job_id)`` is not already present."""
    existing = {(r.source, r.source_job_id) for r in app.source_refs}
    if (ref.source, ref.source_job_id) not in existing:
        app.source_refs.append(ref)
    return app


def list_applications(
    *,
    status: ApplicationStatus | None = None,
    limit: int | None = None,
) -> list[Application]:
    """Return applications newest-first, optionally filtered by status."""
    apps = list(load_all().values())
    apps.sort(key=lambda row: row.discovered_at or "", reverse=True)
    if status is not None:
        apps = [row for row in apps if row.status == status]
    if limit is not None:
        apps = apps[: max(0, limit)]
    return apps


def status_counts() -> dict[str, int]:
    """Count applications grouped by ``status``."""
    counts: dict[str, int] = {}
    for app in load_all().values():
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
                ";".join(app.eligibility_flags),
            ]
        )
    return buffer.getvalue()


def set_status(
    app: Application,
    new_status: ApplicationStatus,
    note: str = "",
) -> Application:
    """Append a status change and enforce terminal-state guards.

    Raises:
        ValueError: When ``app.status`` is terminal and ``new_status`` is pre-ready.
    """
    if app.status in _TERMINAL_STATUSES and new_status in _PRE_READY_STATUSES:
        raise ValueError(
            f"cannot move from terminal status {app.status!r} to pre-ready {new_status!r}"
        )
    if app.status == new_status and not note:
        return app
    app.status = new_status
    app.status_history.append(
        StatusChange(status=new_status, at=_now_iso(), note=note)
    )
    return app
