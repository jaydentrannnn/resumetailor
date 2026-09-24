"""Application funnel state persisted in ``applications.json``."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args

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
    "awaiting_otp",
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

#: Statuses that close the funnel — must not revert to pre-ready states. The only
#: definition: `preparation.check` reports these as `terminal_application`, which is
#: what the SPA reads rather than keeping its own copy.
TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"submitted", "interview", "rejected", "ghosted", "skipped"}
)

#: Discovery/screen/tailor stages before a packet is ``ready``.
PRE_READY_STATUSES: frozenset[ApplicationStatus] = frozenset(
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

#: Filled applications waiting on the applicant: the Applications page's top table.
REVIEW_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"awaiting_review", "awaiting_otp", "fill_failed", "submit_unconfirmed"}
)

#: Pipeline order, for sorting by status (not alphabetical by internal name).
_STATUS_RANK: dict[str, int] = {status: rank for rank, status in enumerate(get_args(ApplicationStatus))}

SCHEMA_VERSION = 5


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
    uploads: list[dict[str, Any]] = Field(default_factory=list)
    required_empty: list[str] = Field(default_factory=list)
    ready_to_submit: bool = False
    submit_action: str = ""
    confirmation: str = ""
    screenshot_path: str | None = None
    error: str | None = None
    status: str = ""
    browser_target_id: str = ""
    browser_url: str = ""
    handoff_reason: str = ""
    final_step_reached: bool = False
    field_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    current_step_id: str = ""
    review_snapshot_id: str = ""
    review_fields: list[dict[str, Any]] = Field(default_factory=list)
    #: Questions recognised as a profile fact the profile leaves blank, one entry per
    #: key: {key, field_label, section, path, questions, answered}.
    missing_profile: list[dict[str, Any]] = Field(default_factory=list)


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
    otp_prompt: str | None = None
    archived_at: str | None = None


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


def _migrate_v2(apps: dict[str, Application]) -> tuple[dict[str, Application], bool]:
    """Re-key Workday rows whose canonical key has the wrong requisition id.

    Before the fix, `identity.canonical_key` matched the first letters-plus-year
    it found anywhere in the path (so ``…Intern-2027_R39474`` became
    ``workday:amfam:ERN-2027``); it now takes the id after the URL's final
    ``_``. Also backfills `Application.ats` for rows still at the "unknown"
    default, which happens for rows created by Find before their first fetch.
    Returns the (possibly unchanged) registry and whether anything changed.
    """
    from resume_tailor.apply import fetch_jd

    renamed: dict[str, str] = {}
    changed = False
    out = dict(apps)
    for key, app in list(out.items()):
        if not app.canonical_key.startswith("workday:"):
            continue
        url = app.final_url or app.posting_url
        if not url:
            continue
        new_key = identity.canonical_key(url)
        if new_key == key or new_key in out:
            continue
        app.canonical_key = new_key
        del out[key]
        out[new_key] = app
        renamed[key] = new_key
        changed = True

    if renamed:
        for app in out.values():
            if app.duplicate_of in renamed:
                app.duplicate_of = renamed[app.duplicate_of]

    for app in out.values():
        if app.ats == "unknown":
            url = app.final_url or app.posting_url
            if url:
                detected = fetch_jd.detect_ats(url)
                if detected != "unknown":
                    app.ats = detected
                    changed = True

    return out, changed


def load_all() -> dict[str, Application]:
    """Load every application keyed by ``canonical_key`` (or legacy id).

    Schema v1 files are migrated in memory to v2, then v2 registries are passed
    through `_migrate_v2` (Workday re-keying + ATS backfill), then v3 registries
    through `_migrate_v3` (one-time archive of submitted rows), then v4 registries
    through `_migrate_v4` (one-time archive of screened-out rows). Any upgrade that
    changes rows backs up the file once before rewriting it.
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
        out = _migrate_v1(apps_raw)
        backup = True
    else:
        out = {str(key): Application.model_validate(value) for key, value in apps_raw.items()}
        backup = False
    if version < 3:
        out, changed = _migrate_v2(out)
        backup = backup or changed
    if version < 4:
        out, changed = _migrate_v3(out)
        backup = backup or changed
    if version < 5:
        out, changed = _migrate_v4(out)
        backup = backup or changed
    if version < SCHEMA_VERSION:
        if backup:
            _backup(path)
        save_all(out)
    return out


def _migrate_v3(apps: dict[str, Application]) -> tuple[dict[str, Application], bool]:
    """Archive every submitted row once, matching the new submit-archives rule.

    Runs only on the v3→v4 upgrade, so a submitted row the user later restores
    stays restored. ``archived_at`` takes the submission's own timestamp when the
    history has one, so the archive table sorts by when each was actually sent.
    """
    changed = False
    for app in apps.values():
        if app.status != "submitted" or app.archived_at:
            continue
        submitted_at = next(
            (change.at for change in reversed(app.status_history) if change.status == "submitted"),
            None,
        )
        app.archived_at = submitted_at or _now_iso()
        changed = True
    return apps, changed


def _migrate_v4(apps: dict[str, Application]) -> tuple[dict[str, Application], bool]:
    """Archive existing screen-outs once; later manual restores remain restored."""
    changed = False
    for app in apps.values():
        if app.status != "screened_out" or app.archived_at:
            continue
        screened_at = next(
            (change.at for change in reversed(app.status_history) if change.status == "screened_out"),
            None,
        )
        app.archived_at = screened_at or _now_iso()
        changed = True
    return apps, changed


def _backup(path: Path) -> None:
    """Copy the registry file aside before a migration rewrites it in place."""
    if not path.is_file():
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{stamp}")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)


def save_all(apps: dict[str, Application]) -> None:
    """Persist the full registry atomically under ``SCHEMA_VERSION``."""
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


def set_archived(application_ids: list[str], archived: bool) -> tuple[list[str], dict[str, str]]:
    """Change archive state in one registry write, accepting canonical or source IDs."""
    apps = load_all()
    index = build_index(apps)
    updated: list[str] = []
    errors: dict[str, str] = {}
    changed = False
    for requested_id in dict.fromkeys(application_ids):
        app = apps.get(requested_id) or index.by_canonical.get(requested_id)
        if app is None:
            key = next((key for (source, sid), key in index.by_source_ref.items() if sid == requested_id), None)
            app = apps.get(key) if key else None
        if app is None:
            errors[requested_id] = "Application not found"
            continue
        if archived and not app.archived_at:
            app.archived_at = _now_iso()
            changed = True
        elif not archived and app.archived_at:
            app.archived_at = None
            changed = True
        updated.append(requested_id)
    if changed:
        save_all(apps)
    return updated, errors


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
    offset: int = 0,
    q: str = "",
    archive: Literal["active", "archived", "all"] = "all",
    sort: Literal["discovered_at", "archived_at", "company", "role", "location", "status", "coverage", "salary", "ats", "sources"] = "discovered_at",
    direction: Literal["asc", "desc"] = "desc",
    group: Literal["review", "working"] | None = None,
    applications: list[Application] | None = None,
) -> list[Application]:
    """Return applications sorted over the whole filtered list, then paged.

    ``group="review"`` keeps only `REVIEW_STATUSES`; ``"working"`` drops them. Ties in
    the sort column fall back to newest-discovered, then company, so a coarse column
    (Platform, Status) still reads in a sensible order page after page.
    """
    apps = filtered_applications(q=q, archive=archive, applications=applications)
    if status is not None:
        apps = [row for row in apps if row.status == status]
    if group is not None:
        apps = [row for row in apps if (row.status in REVIEW_STATUSES) == (group == "review")]
    apps.sort(key=lambda row: row.company.casefold())
    apps.sort(key=lambda row: row.discovered_at or "", reverse=True)
    def sort_value(row: Application) -> str | float | None:
        if sort == "status":
            return _STATUS_RANK.get(row.status, len(_STATUS_RANK))
        if sort == "coverage":
            screen = row.screen
            total = screen.coverage_total if screen else 0
            return screen.coverage_matched / total if screen and total > 0 else None
        if sort == "sources":
            return ", ".join(sorted({ref.source for ref in row.source_refs})).casefold() if row.source_refs else row.source.casefold()
        raw = getattr(row, sort, None)
        return str(raw).strip().casefold() if raw else None
    values = {id(row): sort_value(row) for row in apps}
    apps.sort(key=lambda row: values[id(row)] if values[id(row)] is not None else (0.0 if sort == "coverage" else ""), reverse=direction == "desc")
    apps.sort(key=lambda row: values[id(row)] is None)
    apps = apps[max(0, offset):]
    if limit is not None:
        apps = apps[: max(0, limit)]
    return apps


def filtered_applications(*, q: str = "", archive: Literal["active", "archived", "all"] = "all", applications: list[Application] | None = None) -> list[Application]:
    query = q.strip().casefold()
    return [
        app for app in (applications if applications is not None else load_all().values())
        if (archive == "all" or bool(app.archived_at) == (archive == "archived"))
        and (not query or query in app.company.casefold() or query in app.role.casefold() or query in app.location.casefold())
    ]


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


def set_status(
    app: Application,
    new_status: ApplicationStatus,
    note: str = "",
) -> Application:
    """Append a status change and enforce terminal-state guards.

    Raises:
        ValueError: When ``app.status`` is terminal and ``new_status`` is pre-ready.
    """
    if app.status in TERMINAL_STATUSES and new_status in PRE_READY_STATUSES:
        raise ValueError(
            f"cannot move from terminal status {app.status!r} to pre-ready {new_status!r}"
        )
    if app.status == new_status and not note:
        return app
    at = _now_iso()
    # A submitted application is done with the working queue. Only the transition
    # archives it: a submitted row the user restores stays restored.
    if new_status == "submitted" and app.status != "submitted" and not app.archived_at:
        app.archived_at = at
    # A failed recheck can set screened_out on a restored screened_out row again.
    if new_status == "screened_out" and not app.archived_at:
        app.archived_at = at
    app.status = new_status
    app.status_history.append(
        StatusChange(status=new_status, at=at, note=note)
    )
    return app


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


def review_summary(app: Application) -> str | None:
    """A short "what needs you" line for a row in `REVIEW_STATUSES`, else None.

    Names the first field waiting on the applicant ("Salary expectations +2"), or the
    kind of hand-off when no single field is to blame.
    """
    if app.status not in REVIEW_STATUSES:
        return None
    if app.status == "awaiting_otp":
        return "Verification code"
    if app.status == "submit_unconfirmed":
        return "Confirm submission"
    fill = FillResult.model_validate(app.fill) if isinstance(app.fill, dict) else app.fill
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
