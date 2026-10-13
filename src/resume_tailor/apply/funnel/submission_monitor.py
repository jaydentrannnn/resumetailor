"""Recognize a manual submission in its retained application tab; never click."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from resume_tailor import config
from resume_tailor.apply.discovery import identity
from resume_tailor.apply.funnel import store, store_models

ROWS_JS = "() => [...document.querySelectorAll('tr, [role=row]')].map(row => row.innerText || '')"
_SUBMITTED_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b",
    re.I,
)


def confirmation(
    posting_url: str, current_url: str, body: str, ats: str, rows: list[str] | None = None
) -> dict[str, str] | None:
    """Require an explicit confirmation and the matching posting or requisition."""
    original, current = urlsplit(posting_url), urlsplit(current_url)
    if original.hostname != current.hostname:
        return None
    key = identity.canonical_key(posting_url.rstrip("/").removesuffix("/apply"))
    requisition = key.rsplit(":", 1)[-1] if key else ""
    if not requisition:
        return None
    matching_url = identity.canonical_key(current_url.rstrip("/").removesuffix("/apply")) == key
    matching_body = bool(re.search(rf"(?<![\w-]){re.escape(requisition)}(?![\w-])", body, re.I))
    if not matching_url and not matching_body:
        return None
    date_signal = ""
    if ats == "workday" and rows is not None and not matching_url:
        matching_rows = [
            row
            for row in rows
            if re.search(rf"(?<![\w-]){re.escape(requisition)}(?![\w-])", row, re.I)
        ]
        if any(re.search(r"not (?:yet )?submitted|application (?:draft|not submitted)", row, re.I)
               for row in matching_rows):
            return None
        if not any(_SUBMITTED_DATE.search(row) for row in matching_rows):
            return None
        if re.search(r"date\s+submitted", body, re.I):
            date_signal = "Matching requisition has a Date Submitted"
    marker = re.search(
        r"application submitted|application (?:has been |was )?(?:successfully )?(?:submitted|received)"
        r"|thank you for (?:applying|your application)|you have successfully applied|you have already applied",
        body,
        re.I,
    )
    if marker is None and not date_signal:
        return None
    if ats == "workday" and not matching_body and not matching_url:
        return None
    return {
        "url": current_url,
        "requisition": requisition,
        "signal": marker[0] if marker else date_signal,
    }


def record(
    app: store_models.Application,
    evidence: dict[str, str],
    *,
    workspace_path: Path | None = None,
) -> store_models.FillResult | None:
    """Re-read atomically; a workspace switch or later terminal decision wins."""
    from resume_tailor.web import template_ops  # noqa: PLC0415

    result = None

    def confirm(current: store_models.Application) -> None:
        nonlocal result
        if current.status in store_models.TERMINAL_STATUSES or current.status == "screened_out":
            return
        prior = store_models.FillResult.model_validate(current.fill or {})
        result = prior.model_copy(
            update={
                "status": "submitted",
                "submit_action": "manual_submit",
                "confirmation": evidence["signal"],
                "confirmation_evidence": {**evidence, "at": store_models._now_iso()},
                "browser_url": evidence["url"],
                "handoff_reason": "",
                "error": None,
            }
        )
        current.fill, current.error = result, None
        store.set_status(
            current, "submitted", note="Manual submission confirmed in the recorded application tab"
        )

    with template_ops.LOCK:
        if workspace_path is not None and workspace_path != config.APPLICATIONS_PATH:
            return None
        saved = store.update(app.source_job_id, confirm)
        if result is not None:
            app.fill, app.status, app.error, app.archived_at = (
                saved.fill,
                saved.status,
                saved.error,
                saved.archived_at,
            )
    return result


async def inspect(
    app: store_models.Application, page: Any, *, workspace_path: Path | None = None
) -> bool:
    workspace_path = workspace_path or config.APPLICATIONS_PATH
    try:
        body = await page.locator("body").inner_text(timeout=4000)
        rows = await page.evaluate(ROWS_JS) if app.ats == "workday" else None
        evidence = confirmation(
            app.final_url or app.posting_url, str(page.url), body, app.ats, rows
        )
        if evidence:
            return record(app, evidence, workspace_path=workspace_path) is not None
    except Exception:  # noqa: BLE001 - a closed or busy tab is retried, never a confirmation
        pass
    return False
