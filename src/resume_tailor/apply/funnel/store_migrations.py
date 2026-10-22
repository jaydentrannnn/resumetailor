"""Schema migrations for stored applications (v1 through v4) and the legacy JSON import."""

from __future__ import annotations

from typing import Any

from resume_tailor.apply.discovery import identity

from . import store_models


def _migrate_v1(apps_raw: dict[str, Any]) -> dict[str, store_models.Application]:
    """Rekey a schema-v1 registry onto canonical keys and attach source_refs."""
    out: dict[str, store_models.Application] = {}
    for _key, value in apps_raw.items():
        app = store_models.Application.model_validate(value)
        url = app.final_url or app.posting_url
        if not app.canonical_key:
            app.canonical_key = identity.canonical_key(url) if url else f"legacy:{app.source_job_id}"
        if not app.group_key:
            app.group_key = identity.group_key(app.company, app.role)
        if not app.source_refs:
            app.source_refs = [
                store_models.SourceRef(
                    source=app.source,
                    source_job_id=app.source_job_id,
                    url=app.posting_url,
                    first_seen=app.discovered_at,
                )
            ]
        out[store_models._registry_key(app)] = app
    return out

def _migrate_v2(
    apps: dict[str, store_models.Application],
) -> tuple[dict[str, store_models.Application], bool]:
    """Re-key Workday rows whose canonical key has the wrong requisition id.

    Before the fix, `identity.canonical_key` matched the first letters-plus-year
    it found anywhere in the path (so ``…Intern-2027_R39474`` became
    ``workday:amfam:ERN-2027``); it now takes the id after the URL's final
    ``_``. Also backfills `Application.ats` for rows still at the "unknown"
    default, which happens for rows created by Find before their first fetch.
    Returns the (possibly unchanged) registry and whether anything changed.
    """
    from resume_tailor.apply.discovery import fetch_jd

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

def _migrate_v3(
    apps: dict[str, store_models.Application],
) -> tuple[dict[str, store_models.Application], bool]:
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
        app.archived_at = submitted_at or store_models._now_iso()
        changed = True
    return apps, changed

def _refs(app: store_models.Application) -> set[tuple[str, str]]:
    return {(ref.source, ref.source_job_id) for ref in app.source_refs} | {
        (app.source, app.source_job_id)
    }

def _fold_stranded_duplicates(
    apps: dict[str, store_models.Application],
) -> tuple[dict[str, store_models.Application], bool]:
    """Drop the untouched copy left behind when a posting's link began resolving.

    A posting saved under a placeholder key (an unresolved wrapper link) gets its real
    requisition key once the link reaches the ATS: `daily_row_run._RowRun._rekey` moves
    the row, but when another source already found that requisition the sighting merges
    into that row instead, and older versions always made a second row. Either way the
    placeholder row stays ``discovered`` with a source posting a real-keyed row also
    holds. It is folded into that one sibling only when it never got further (no tailor
    run, no fill); its source refs move across and any ``duplicate_of`` naming it is
    pointed at the sibling. Rows that change are copies, so ``apps`` is never mutated and
    an unchanged row is still the very object passed in.
    """
    by_ref: dict[tuple[str, str], list[str]] = {}
    for key, app in apps.items():
        for ref in _refs(app):
            by_ref.setdefault(ref, []).append(key)
    out = dict(apps)
    changed = False

    def editable(key: str) -> store_models.Application:
        if out[key] is apps[key]:
            out[key] = apps[key].model_copy(deep=True)
        return out[key]

    for key, app in apps.items():
        stranded = (
            app.status == "discovered"
            and identity.is_placeholder_key(key)
            and not app.job_id
            and app.fill is None
        )
        if not stranded:
            continue
        siblings = {
            other
            for ref in _refs(app)
            for other in by_ref[ref]
            if other != key and other in out and not identity.is_placeholder_key(other)
        }
        if len(siblings) != 1:
            continue
        real_key = siblings.pop()
        known = _refs(out[real_key])
        missing = [ref for ref in app.source_refs if (ref.source, ref.source_job_id) not in known]
        if missing:
            editable(real_key).source_refs.extend(ref.model_copy() for ref in missing)
        del out[key]
        for other_key in [k for k, other in out.items() if other.duplicate_of == key]:
            editable(other_key).duplicate_of = None if other_key == real_key else real_key
        changed = True
    return out, changed

def _migrate_v4(
    apps: dict[str, store_models.Application],
) -> tuple[dict[str, store_models.Application], bool]:
    """Archive existing screen-outs once; later manual restores remain restored."""
    changed = False
    for app in apps.values():
        if app.status != "screened_out" or app.archived_at:
            continue
        screened_at = next(
            (change.at for change in reversed(app.status_history) if change.status == "screened_out"),
            None,
        )
        app.archived_at = screened_at or store_models._now_iso()
        changed = True
    return apps, changed
