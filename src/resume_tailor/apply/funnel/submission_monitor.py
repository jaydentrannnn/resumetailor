"""Recognize a manual submission in its retained application tab; never click.

Evidence is ``strong`` (the row becomes ``submitted``) or ``weak`` (``submit_unconfirmed``,
for the applicant to confirm; never archived, its tab never closed): a thank-you line on a
page that still shows the application form is weak (audit #6), and so is Workday's
completed-applications page (where a submit lands) when it does not show this requisition
as submitted (audit #36): a location variant shares its title, so a title is never enough.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from resume_tailor import config
from resume_tailor.apply.discovery import identity
from resume_tailor.apply.funnel import attempts, store, store_models

ROWS_JS = "() => [...document.querySelectorAll('tr, [role=row]')].map(row => row.innerText || '')"
#: Whether the page still shows an application form: a visible required field or a
#: Submit/Apply control. A thank-you line beside one is not a confirmation.
FORM_PROBE_JS = r"""() => {
  const shown = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const required = [...document.querySelectorAll(
    'input[required], textarea[required], select[required], [aria-required="true"]')]
    .some((el) => shown(el) && (el.type || '').toLowerCase() !== 'hidden');
  const submit = [...document.querySelectorAll('button, input[type="submit"], [role="button"]')]
    .some((el) => shown(el)
      && /^\s*(submit( (my )?application)?|apply( now)?|send application)\s*$/i
        .test(el.innerText || el.value || ''));
  return required || submit;
}"""
#: Status note when the evidence is not enough to record the application as sent.
LOOKS_SUBMITTED_NOTE = "Looks submitted — confirm?"
#: Workday's candidate home after a submit: the list of completed applications.
_WORKDAY_COMPLETED = re.compile(r"/jobTasks/completed(?:/|$)", re.I)
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


_NOT_SUBMITTED = re.compile(r"not (?:yet )?submitted|application (?:draft|not submitted)", re.I)


def confirmation(
    posting_url: str, current_url: str, body: str, ats: str, rows: list[str] | None = None,
    *, form_open: bool = False,
) -> dict[str, str] | None:
    """Require an explicit confirmation and the matching posting or requisition.

    ``form_open`` (`FORM_PROBE_JS`) says the page still shows an application form, so its
    thank-you text is weak evidence."""
    if _site(posting_url) != _site(current_url):
        return None
    key = identity.canonical_key(posting_url.rstrip("/").removesuffix("/apply"))
    requisitions = requisition_ids(key, ats)
    if not requisitions:
        return None
    evidence = _explicit(key, requisitions, current_url, body, ats, rows, form_open)
    if evidence or ats != "workday" or not _WORKDAY_COMPLETED.search(current_url):
        return evidence
    if any(_NOT_SUBMITTED.search(row) for row in rows or [] if mentions_any(requisitions, row)):
        return None  # this requisition is listed as a draft
    # Carrier (2026-10): the completed list said "noApplications" right after a submit.
    return {
        "url": current_url,
        "requisition": requisitions[0],
        "signal": "Workday's completed applications page opened",
        "strength": "weak",
    }


def _explicit(
    key: str, requisitions: list[str], current_url: str, body: str, ats: str,
    rows: list[str] | None, form_open: bool,
) -> dict[str, str] | None:
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
        if any(_NOT_SUBMITTED.search(row) for row in matching_rows):
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
        # A dated Workday row is a record, whatever else the page shows.
        "strength": "weak" if form_open and not date_signal else "strong",
    }


def strong(evidence: dict[str, str] | None) -> bool:
    """Evidence enough to record the application as sent (older records: yes)."""
    return bool(evidence) and evidence.get("strength", "strong") == "strong"


def record(
    app: store_models.Application,
    evidence: dict[str, str],
    *,
    workspace_path: Path | None = None,
) -> store_models.FillResult | None:
    """Re-read atomically; a workspace switch or later terminal decision wins. Weak
    evidence makes the row ``submit_unconfirmed`` once, for the applicant to confirm."""
    from resume_tailor.web import template_ops  # noqa: PLC0415

    result = None
    sent = strong(evidence)
    status = "submitted" if sent else "submit_unconfirmed"

    def confirm(current: store_models.Application) -> None:
        nonlocal result
        if current.status in store_models.TERMINAL_STATUSES or current.status == "screened_out":
            return
        if not sent and current.status == "submit_unconfirmed":
            return  # already waiting on the applicant's confirmation
        prior = store_models.FillResult.model_validate(current.fill or {})
        result = prior.model_copy(
            update={
                "status": status,
                "submit_action": "manual_submit",
                "confirmation": evidence["signal"] if sent else "",
                "confirmation_evidence": {**evidence, "at": store_models._now_iso()},
                "browser_url": evidence["url"],
                "handoff_reason": "" if sent else LOOKS_SUBMITTED_NOTE,
                "error": None,
            }
        )
        current.fill, current.error = result, None
        store.set_status(
            current, status, note=attempts.MONITOR_NOTE if sent else LOOKS_SUBMITTED_NOTE
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


def form_open(page: Any) -> bool:
    """`FORM_PROBE_JS` over every frame: an embedded application keeps its form in an
    iframe, below a thank-you line on the page around it. A frame that cannot be read
    counts as open."""
    for frame in page.frames:
        try:
            if frame.evaluate(FORM_PROBE_JS):
                return True
        except Exception:  # noqa: BLE001
            return True
    return False


async def form_open_async(page: Any) -> bool:
    """`form_open` for an async page."""
    for frame in page.frames:
        try:
            if await frame.evaluate(FORM_PROBE_JS):
                return True
        except Exception:  # noqa: BLE001
            return True
    return False


async def inspect(
    app: store_models.Application, page: Any, *, workspace_path: Path | None = None
) -> bool:
    """Record a submission seen in ``page``; True when it was recorded as sent (weak
    evidence is recorded too, but the tab is still read)."""
    workspace_path = workspace_path or config.APPLICATIONS_PATH
    try:
        body = await page.locator("body").inner_text(timeout=4000)
        rows = await page.evaluate(ROWS_JS) if app.ats == "workday" else None
        evidence = confirmation(
            app.final_url or app.posting_url, str(page.url), body, app.ats, rows,
            form_open=await form_open_async(page),
        )
        if evidence:
            recorded = record(app, evidence, workspace_path=workspace_path) is not None
            return recorded and strong(evidence)
    except Exception:  # noqa: BLE001 - a closed or busy tab is retried, never a confirmation
        pass
    return False
