"""Application funnel state, persisted in the workspace's SQLite database.

Storage. Rows live in the ``applications`` table of ``<DATA_DIR>/app.db``
(`resume_tailor.storage.db`), one JSON document per row plus indexed copies of the
columns the Apply page filters on. A pre-SQLite ``applications.json`` is imported once
on first open (`_import_json`): the original is copied to
``backup-pre-sqlite-<stamp>/``, migrated in memory through the old schema steps, and
renamed to ``applications.json.migrated`` (rename it back and delete ``app.db`` to
downgrade). Parsed rows are cached per process and re-read only when the table's
change counter moves, so a write from another process (the nightly CLI) is seen.

Concurrency model. Web routes, the operation worker threads, the nightly run and fill
all read and write this registry, and fill holds a row for minutes while it drives a
browser. Every read-modify-write therefore goes through `_LOCK`, and `upsert` is a
field-level three-way merge rather than a blind replace: a row returned by `get`,
`load_all` or `list_applications` remembers the stored version it was read from
(`Application._base`), and `upsert` writes back only the fields the caller changed
since then, on top of whatever is stored *now*. A user's archive, note or "mark
submitted" made while a fill was running therefore survives the fill's later write.
Conflicts (both sides changed one field) go to the caller, except that a status the
user moved to a terminal state is kept (`_merge_into`). After a write the caller's
object is refreshed in place to the merged row, so it never carries stale fields into
its next write. `update(key, mutate)` is the atomic form for new code.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, PrivateAttr

from resume_tailor import config
from resume_tailor.apply import identity
from resume_tailor.apply.screen import ScreenResult
from resume_tailor.storage import db

_log = logging.getLogger(__name__)

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
    #: Bumped on every write of this row; lets a client tell that a row changed.
    revision: int = 0

    #: The stored version this object was read from (never mutated), or None for a
    #: row built in memory. `upsert` diffs against it; see the module docstring.
    _base: Application | None = PrivateAttr(default=None)


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
    """Every application keyed by ``canonical_key`` (or legacy id), as private copies."""
    with _LOCK:
        return {key: _checkout(app) for key, app in _snapshot().items()}


class StaleApplication(RuntimeError):
    """`update` could not find the row it was asked to change."""


_LOCK = threading.RLock()
_TABLE = "applications"
_JSON_MARKER = "json_import:applications"

#: (database path, table generation, parsed rows) of the last read or write. The rows
#: are private: callers only ever get `_checkout` copies, so they are never mutated.
_cache: tuple[Path, int, dict[str, Application]] | None = None
#: Databases whose JSON import is settled, so `_db` can skip the check.
_imported: set[Path] = set()


def _db_file() -> Path:
    return db.db_path(_path().parent)


def _db() -> sqlite3.Connection:
    """This thread's connection to the active workspace's database, JSON imported."""
    db_file = _db_file()
    conn = db.connect(db_file)
    if db_file not in _imported:
        _import_json(conn, db_file)
    return conn


@contextmanager
def _txn() -> Iterator[sqlite3.Connection]:
    """`_LOCK` plus a database write transaction, for every read-modify-write."""
    with _LOCK, db.transaction(_db()) as conn:
        yield conn


def _snapshot() -> dict[str, Application]:
    """Current registry rows, shared and read-only. Hold `_LOCK` while using them.

    Re-parses only when the table's change counter moved since the last read or write,
    which turns `get()` on a large registry into one small query.
    """
    global _cache
    conn = _db()
    db_file = _db_file()
    gen = db.generation(conn, _TABLE)
    if _cache is not None and _cache[0] == db_file and _cache[1] == gen:
        return _cache[2]
    rows = {
        key: Application.model_validate_json(doc)
        for key, doc in conn.execute("SELECT key, doc FROM applications ORDER BY rowid")
    }
    _cache = (db_file, gen, rows)
    return rows


def _checkout(app: Application) -> Application:
    """A private, mutable copy of a stored row that remembers where it came from."""
    out = app.model_copy(deep=True)
    out._base = app
    return out


def _parse_json(raw_bytes: bytes) -> dict[str, Application]:
    """Rows of a legacy ``applications.json``, upgraded through every old schema step.

    Schema v1 files are migrated to v2, then v2 registries through `_migrate_v2`
    (Workday re-keying + ATS backfill), v3 through `_migrate_v3` (one-time archive of
    submitted rows), and v4 through `_migrate_v4` (one-time archive of screen-outs).
    """
    raw = json.loads(raw_bytes.decode("utf-8"))
    apps_raw = raw.get("applications", {}) if isinstance(raw, dict) else {}
    if not isinstance(apps_raw, dict):
        return {}
    version = int(raw.get("schema_version") or 1)
    if version < 2:
        out = _migrate_v1(apps_raw)
    else:
        out = {str(key): Application.model_validate(value) for key, value in apps_raw.items()}
    if version < 3:
        out, _ = _migrate_v2(out)
    if version < 4:
        out, _ = _migrate_v3(out)
    if version < 5:
        out, _ = _migrate_v4(out)
    return out


def _import_json(conn: sqlite3.Connection, db_file: Path) -> None:
    """Move a pre-SQLite ``applications.json`` into the database, once.

    Rows already in the database win over same-key rows in the file. A file that does
    not parse is kept aside as ``applications.json.corrupt-<stamp>`` and logged; the
    import is not retried, since retrying would fail the same way on every read.
    """
    path = _path()
    with _LOCK:
        if db.marker(conn, _JSON_MARKER):
            if path.is_file():
                _log.warning("ignoring %s: already imported into %s", path.name, db_file.name)
            _imported.add(db_file)
            return
        if not path.is_file():
            return  # checked again on the next open, in case the file appears
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        backup_dir = path.parent / f"backup-pre-sqlite-{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir / path.name)
        try:
            rows = _parse_json(path.read_bytes())
            suffix = ".migrated"
        except (ValueError, UnicodeDecodeError, TypeError) as exc:
            _log.error("could not import %s (%s); kept it in %s", path.name, exc, backup_dir.name)
            rows = {}
            suffix = f".corrupt-{stamp}"
        with db.transaction(conn):
            existing = {row[0] for row in conn.execute("SELECT key FROM applications")}
            for key, app in rows.items():
                if key not in existing:
                    _put(conn, key, app)
            db.set_marker(conn, _JSON_MARKER)
            db.bump(conn, _TABLE)
        _imported.add(db_file)
        try:
            path.replace(path.with_name(path.name + suffix))
        except OSError as exc:  # e.g. open in an editor on Windows; the marker is set
            _log.warning("imported %s but could not rename it: %s", path.name, exc)


def _put(conn: sqlite3.Connection, key: str, app: Application) -> None:
    conn.execute(
        """INSERT INTO applications(key, revision, status, company, role, location, ats,
               discovered_at, archived_at, group_key, job_id, doc)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET
               revision = excluded.revision, status = excluded.status,
               company = excluded.company, role = excluded.role,
               location = excluded.location, ats = excluded.ats,
               discovered_at = excluded.discovered_at, archived_at = excluded.archived_at,
               group_key = excluded.group_key, job_id = excluded.job_id, doc = excluded.doc""",
        (
            key, app.revision, app.status, app.company, app.role, app.location, app.ats,
            app.discovered_at, app.archived_at, app.group_key, app.job_id,
            app.model_dump_json(),
        ),
    )


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


def save_all(apps: dict[str, Application]) -> None:
    """Persist the full registry in one transaction: rows not in ``apps`` are deleted.

    A blind write of every row: use `upsert`/`update` to change rows other code may
    also be changing.
    """
    stored: dict[str, Application] = {}
    for key, app in apps.items():
        row = app.model_copy(deep=True)
        row._base = None
        stored[key] = row
    _write(stored)


def _write(rows: dict[str, Application]) -> None:
    """`save_all` for rows the store owns outright: cached as-is, not copied.

    Writes only the rows that are not the very objects already stored, so an `upsert`
    that took its dict from `_snapshot` rewrites one row, not the table.
    """
    global _cache
    with _txn() as conn:
        current = _snapshot()
        for key in current.keys() - rows.keys():
            conn.execute("DELETE FROM applications WHERE key = ?", (key,))
        for key, app in rows.items():
            if current.get(key) is not app:
                _put(conn, key, app)
        gen = db.bump(conn, _TABLE)
        _cache = (_db_file(), gen, rows)


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


def _locate(apps: dict[str, Application], key: str) -> str | None:
    """Registry key of the row ``key`` names: a registry key, canonical key or source id."""
    if key in apps:
        return key
    index = build_index(apps)
    if key in index.by_canonical:
        found = index.by_canonical[key]
        return next((k for k, app in apps.items() if app is found), None)
    for (_source, source_job_id), ckey in index.by_source_ref.items():
        if source_job_id == key:
            if ckey in apps:
                return ckey
            found = index.by_canonical.get(ckey)
            return next((k for k, app in apps.items() if app is found), None)
    return None


def get(key: str) -> Application | None:
    """Return one application by canonical key or any source_job_id."""
    with _LOCK:
        apps = _snapshot()
        found = _locate(apps, key)
        return _checkout(apps[found]) if found is not None else None


#: Fields `_merge_into` never copies from the caller: bookkeeping it computes itself.
_MERGE_SKIP = frozenset({"revision", "status_history", "source_refs"})


def _merge_into(stored: Application, app: Application, base: Application) -> Application:
    """Apply the fields ``app`` changed since ``base`` onto ``stored`` (the row as it is now).

    Returns a new row; none of the three inputs is modified. ``status_history`` and
    ``source_refs`` are append-only, so the caller's new entries are appended to the
    stored ones rather than replacing entries a concurrent writer added. When the
    caller changed ``status`` while someone else moved the row to a terminal status
    (the user marked it submitted, skipped, ...), the terminal status is kept and a
    note says what arrived late: a background fill must never un-submit a row.
    """
    merged = stored.model_copy(deep=True)
    merged._base = None
    keep_status = (
        app.status != base.status
        and stored.status != base.status
        and stored.status in TERMINAL_STATUSES
        and app.status != stored.status
    )
    for name in type(app).model_fields:
        if name in _MERGE_SKIP:
            continue
        mine = getattr(app, name)
        if mine == getattr(base, name):
            continue
        if keep_status and name in {"status", "archived_at"}:
            continue
        setattr(merged, name, copy.deepcopy(mine))

    base_history = base.status_history
    if app.status_history[: len(base_history)] == base_history:
        merged.status_history.extend(
            change.model_copy() for change in app.status_history[len(base_history):]
        )
    else:  # the caller rewrote history rather than appending: its version wins
        merged.status_history = [change.model_copy() for change in app.status_history]
    if keep_status:
        merged.status_history.append(
            StatusChange(
                status=stored.status,
                at=_now_iso(),
                note=f"{app.status} arrived after this was marked {stored.status}; status kept",
            )
        )

    known = {(ref.source, ref.source_job_id) for ref in merged.source_refs}
    for ref in app.source_refs:
        if (ref.source, ref.source_job_id) not in known:
            merged.source_refs.append(ref.model_copy())
            known.add((ref.source, ref.source_job_id))
    return merged


def _refresh(app: Application, row: Application) -> None:
    """Make the caller's ``app`` equal to the stored ``row`` it just wrote."""
    for name in type(app).model_fields:
        setattr(app, name, copy.deepcopy(getattr(row, name)))
    app._base = row


def upsert(app: Application) -> Application:
    """Insert ``app``, or write its changes onto the stored row, and persist.

    A row read from the store is merged (see `_merge_into`); a row built in memory
    replaces whatever is stored under its key. Either way ``app`` is refreshed in
    place to the stored result and returned.
    """
    with _txn():
        apps = dict(_snapshot())
        key = _registry_key(app)
        base = app._base
        stored_key: str | None = None
        if base is not None:
            stored_key = _locate(apps, _registry_key(base))
            if stored_key is None:
                stored_key = _locate(apps, base.source_job_id)
        if stored_key is not None and base is not None:
            row = _merge_into(apps[stored_key], app, base)
            if stored_key != key:
                del apps[stored_key]
            key = _registry_key(row)
        else:
            row = app.model_copy(deep=True)
            row._base = None
            previous = apps.get(key)
            row.revision = previous.revision if previous is not None else row.revision
        # Drop a stale legacy key if we are promoting to a canonical key.
        if row.canonical_key and row.source_job_id in apps and row.source_job_id != key:
            del apps[row.source_job_id]
        row.revision += 1
        apps[key] = row
        _write(apps)
        _refresh(app, row)
        return app


def update(key: str, mutate: Callable[[Application], None]) -> Application:
    """Atomically re-read the row ``key`` names, apply ``mutate`` to it, and save.

    Raises:
        StaleApplication: When no row matches ``key`` (deleted or re-keyed).
    """
    with _txn():
        app = get(key)
        if app is None:
            raise StaleApplication(f"application {key!r} not found")
        mutate(app)
        return upsert(app)


def patch(key: str, **fields: Any) -> Application:
    """`update` that assigns ``fields``: ``patch(key, notes="...")``."""

    def _assign(app: Application) -> None:
        for name, value in fields.items():
            setattr(app, name, value)

    return update(key, _assign)


def restore(previous: Application) -> Application:
    """Put back an earlier copy of a row, e.g. after a failed Prepare refresh.

    Unlike `upsert`, every field returns to ``previous`` except what the user owns:
    the stored ``notes``, and a terminal status set since (kept, with a note).
    """
    with _txn():
        apps = _snapshot()
        found = _locate(apps, _registry_key(previous))
        if found is None:
            found = _locate(apps, previous.source_job_id)
        row = previous.model_copy(deep=True)
        row._base = None
        if found is not None:
            stored = apps[found]
            row.notes = stored.notes
            if stored.status in TERMINAL_STATUSES and stored.status != previous.status:
                row.status = stored.status
                row.archived_at = stored.archived_at
                row.status_history = [change.model_copy() for change in stored.status_history]
                row.status_history.append(
                    StatusChange(
                        status=stored.status,
                        at=_now_iso(),
                        note=f"restore skipped: already marked {stored.status}",
                    )
                )
            row.revision = stored.revision
            if found != _registry_key(row):
                apps = dict(apps)
                del apps[found]
                _write(apps)
        return upsert(row)


def set_archived(application_ids: list[str], archived: bool) -> tuple[list[str], dict[str, str]]:
    """Change archive state in one registry write, accepting canonical or source IDs."""
    with _txn():
        apps = load_all()
        updated: list[str] = []
        errors: dict[str, str] = {}
        changed = False
        for requested_id in dict.fromkeys(application_ids):
            found = _locate(apps, requested_id)
            if found is None:
                errors[requested_id] = "Application not found"
                continue
            app = apps[found]
            if archived and not app.archived_at:
                app.archived_at = _now_iso()
                app.revision += 1
                changed = True
            elif not archived and app.archived_at:
                app.archived_at = None
                app.revision += 1
                changed = True
            updated.append(requested_id)
        if changed:
            save_all(apps)
        return updated, errors


def all_ids() -> set[tuple[str, str]]:
    """Return every ``(source, source_job_id)`` currently on disk."""
    refs: set[tuple[str, str]] = set()
    with _LOCK:
        rows = list(_snapshot().values())
    for app in rows:
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
    with _LOCK:
        rows = list(_snapshot().values())
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
