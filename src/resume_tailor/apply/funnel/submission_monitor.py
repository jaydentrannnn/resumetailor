"""Recognize a manual submission in its retained application tab; never click."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from resume_tailor import config
from resume_tailor.apply.discovery import identity
from resume_tailor.apply.funnel import attempts, store, store_models

ROWS_JS = "() => [...document.querySelectorAll('tr, [role=row]')].map(row => row.innerText || '')"
_SUBMITTED_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b",
    re.I,
)
#: Hosts that serve one board: a posting saved on ``boards.`` is applied to on ``job-boards.``.
_SAME_SITE = {
    "boards.greenhouse.io": "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io": "job-boards.eu.greenhouse.io",
}
#: A Workday location variant: the URL's ``R5054820-2`` is requisition ``R5054820`` on the page.
_WORKDAY_VARIANT = re.compile(r"^(?P<base>.*\d.*)-\d{1,2}$")


def _site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return _SAME_SITE.get(host, host)


def requisition_ids(key: str, ats: str) -> list[str]:
    """The key's requisition, then (Workday) the bare id its location variant shows."""
    requisition = key.rsplit(":", 1)[-1] if key else ""
    if not requisition:
        return []
    variant = _WORKDAY_VARIANT.match(requisition) if ats == "workday" else None
    return [requisition, variant["base"]] if variant else [requisition]


def mentions_any(requisitions: list[str], text: str) -> bool:
    return any(
        re.search(rf"(?<![\w-]){re.escape(requisition)}(?![\w-])", text, re.I)
        for requisition in requisitions
    )


def confirmation(
    posting_url: str, current_url: str, body: str, ats: str, rows: list[str] | None = None
) -> dict[str, str] | None:
    """Require an explicit confirmation and the matching posting or requisition."""
    if _site(posting_url) != _site(current_url):
        return None
    key = identity.canonical_key(posting_url.rstrip("/").removesuffix("/apply"))
    requisitions = requisition_ids(key, ats)
    if not requisitions:
        return None
    requisition = requisitions[0]
    current_key = identity.canonical_key(current_url.rstrip("/").removesuffix("/apply"))
    matching_url = current_key == key or (
        len(requisitions) > 1 and current_key == key.removesuffix(requisition) + requisitions[1]
    )
    matching_body = mentions_any(requisitions, body)
    if not matching_url and not matching_body:
        return None
    date_signal = ""
    if ats == "workday" and rows is not None and not matching_url:
        matching_rows = [row for row in rows if mentions_any(requisitions, row)]
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
        store.set_status(current, "submitted", note=attempts.MONITOR_NOTE)

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
