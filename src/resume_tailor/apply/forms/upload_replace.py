"""Telling the app's own earlier upload from the applicant's, and replacing it once stale.

A Continue fill finds files already attached. One the app uploaded itself (its record
says ``uploaded_by_app`` under that filename) is replaced when the prepared document has
changed since (``artifact_sha256``); anything else is the applicant's and is kept. A file
the applicant attached in the tab (`answer_harvest`'s listener) is theirs even under the
app's file name, and one whose version the record cannot tell is left for them to check.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from resume_tailor.apply.driver import clicks

#: Upload record reason when a stale earlier upload was swapped for the current document.
REPLACED_NOTE = "Replaced the earlier upload with the current version"
#: Upload record error when the stale earlier upload could not be removed.
NOT_REPLACED_NOTE = "An earlier version is attached and could not be replaced"
#: Upload record error when the stale earlier upload shows only away from its upload step.
EARLIER_STEP_NOTE = "An earlier version is attached; replace it on the upload step"
#: Upload record reason when a file under the app's name has no version on record.
AMBIGUOUS_NOTE = "A file with this name was already attached; check it is the current version"


def artifact_sha256(path: Any) -> str:
    """The prepared document's digest, or "" when there is no such file."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else ""
    except OSError:
        return ""


def attached_by_app(
    prior_uploads: Iterable[dict[str, Any]], purpose: str, shown: str, current_sha: str,
    touched: Iterable[str] = (),
) -> Literal["current", "stale", "theirs", "ambiguous"]:
    """Whose file ``shown`` is: the app's and up to date, the app's but outdated, not the
    app's (no record of uploading it, which includes records from before the app kept
    one, or the applicant attached it in the tab: ``touched``), or the app's name with no
    version on record to compare (``ambiguous``: kept, for the applicant to check)."""
    if shown in set(touched):
        return "theirs"
    prior = _ours(prior_uploads, purpose, shown)
    if prior is None:
        return "theirs"
    recorded = str(prior.get("artifact_sha256") or "")
    if not recorded or not current_sha:
        return "ambiguous"
    return "stale" if recorded != current_sha else "current"


def _ours(
    prior_uploads: Iterable[dict[str, Any]], purpose: str, shown: str
) -> dict[str, Any] | None:
    return next((
        item for item in prior_uploads
        if item.get("purpose") == purpose and item.get("uploaded_by_app")
        and item.get("filename") == shown
    ), None)


def pinned_copy(
    prior_uploads: Iterable[dict[str, Any]], purpose: str, shown: str
) -> dict[str, Any]:
    """The earlier fill's pinned copy of ``shown`` (``artifact_path``), carried onto the
    record when a Continue keeps that upload, so "What was sent" still holds the exact
    file the form has; {} when there is none."""
    path = str((_ours(prior_uploads, purpose, shown) or {}).get("artifact_path") or "")
    return {"artifact_path": path} if path else {}


def still_ours(
    prior_uploads: Iterable[dict[str, Any]], purpose: str, shown: str
) -> dict[str, Any]:
    """The upload record fields that keep ``shown`` known as the app's outdated upload
    after a replacement failed, so the next Continue tries again rather than keeping it
    as the applicant's file; {} when the app did not upload it."""
    prior = _ours(prior_uploads, purpose, shown)
    if prior is None:
        return {}
    return {"filename": shown, "uploaded_by_app": True,
            "artifact_sha256": str(prior.get("artifact_sha256") or "")}


#: Marks the one remove control in the upload component listing ``name``: from the
#: deepest element showing the name, the nearest ancestor holding exactly one
#: delete/remove control. Gives up when an ancestor holds several (ambiguous), or before
#: leaving the upload component (an ancestor holding any other kind of form control), so
#: a work-experience row's Delete is never the one pressed.
_MARK_REMOVE_JS = r"""(name) => {
  document.querySelectorAll('[data-rt-remove]').forEach(e => e.removeAttribute('data-rt-remove'));
  const remover = el => /\b(delete|remove|clear|trash)\b/i.test([el.innerText || '',
    el.getAttribute('aria-label') || '', el.getAttribute('title') || '',
    el.getAttribute('data-automation-id') || '', el.className || ''].join(' ').replace(/-/g, ' '));
  const holders = [...document.querySelectorAll('body *')].filter(el =>
    el.getClientRects().length > 0 && (el.textContent || '').includes(name)
    && ![...el.children].some(child => (child.textContent || '').includes(name)));
  if (holders.length !== 1) return false;
  const otherControl = 'input:not([type="file"]):not([type="hidden"]), select, textarea';
  for (let node = holders[0]; node && node !== document.body; node = node.parentElement) {
    if (node.querySelector(otherControl)) return false;
    const found = [...node.querySelectorAll('button, [role="button"]')].filter(remover);
    if (found.length === 1) { found[0].setAttribute('data-rt-remove', '1'); return true; }
    if (found.length > 1) return false;
  }
  return false;
}"""


def remove_listed(target: Any, name: str) -> bool:
    """Remove the file ``name`` from the upload widget listing it; True once it is gone."""
    try:
        if not target.evaluate(_MARK_REMOVE_JS, name):
            return False
        clicks.safe_click(target.locator("[data-rt-remove]").first, purpose="remove", timeout=3000)
        for _ in range(12):
            with contextlib.suppress(Exception):
                if target.get_by_text(name, exact=False).count() == 0:
                    return True
            target.wait_for_timeout(250)
    except Exception:  # noqa: BLE001 - the caller records the file as not replaced
        return False
    return False
