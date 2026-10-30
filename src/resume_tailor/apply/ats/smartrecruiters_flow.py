"""SmartRecruiters' one-click form: City, Experience, Education, Resume and Message.

The form (``/oneclick-ui/``, captured live 2026-09-27 on Resultant and Wellmark) is an
Angular app built from ``spl-*`` web components whose controls sit in open shadow roots;
Playwright's CSS locators pierce them. Each area is found by its ``data-test`` attribute:

- City: ``div[data-test=personal-info-location] spl-autocomplete`` — a typeahead whose
  options (``spl-select-option``, text "Fountain Valley, CA, US") load from a location
  search; only a clicked option commits, as the host's ``value`` object (``city``,
  ``region``, ``stateCode``, ``country``). Typed text left uncommitted is cleared on blur.
  Some tenants (Wellmark) do not ask for a city at all.
- Experience / Education: ``div[data-test=experience|education]``, an "Add" button
  (``oc-button[data-test=add-experience]``) opening an inline editor
  (``[data-test=experience-edit-form]``) with typeaheads for title/company/institution
  (a ``#spl-custom-option`` commits the typed text), plain inputs for major/degree, a
  description textarea, flatpickr month pickers that accept typed "MM/YYYY" + Enter, and
  Save/Cancel. A saved entry renders as ``oc-experience-entry`` / ``oc-education-entry``.
- Resume: ``spl-dropzone[data-test=resume-upload]``; its ``input#file-input`` shares the id
  with the "Easy Apply" parse-and-prefill dropzone at the top of the form, which is never
  used. The accepted file shows as a file-list item carrying its name.
- Message: ``oc-textarea[data-test=hiring-manager-message-text] textarea`` under "Message
  to the Hiring Team".

The second step (``/screening``) holds the screening questions:
`smartrecruiters_screening`.

Like `workday_repeaters`: an entry already listed is reused, never edited or deleted; an
answer already present is kept; anything not verified on the page is reported for review.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from resume_tailor.apply.driver import clicks
from resume_tailor.apply.funnel.packet_models import Packet

from . import (
    smartrecruiters_entries,
    smartrecruiters_location,
    smartrecruiters_page,
    smartrecruiters_screening,
)


def _resume_state(zone: Any) -> dict[str, Any]:
    try:
        state = zone.evaluate(smartrecruiters_page._DROPZONE_FILES_JS)
    except Exception:  # noqa: BLE001
        return {"names": [], "listed": 0}
    return state if isinstance(state, dict) else {"names": [], "listed": 0}


def fill_resume(page: Any, resume_path: str | None) -> tuple[list[dict[str, str]], list[str]]:
    """Set the resume on the Resume section's dropzone and see its name listed.

    The "Easy Apply" dropzone at the top of the form also takes a resume, but parses it
    to prefill the form; it is never used.
    """
    zone = page.locator(f"{smartrecruiters_page._RESUME} spl-dropzone").first
    if not smartrecruiters_page._present(
        page.locator(f"{smartrecruiters_page._RESUME} spl-dropzone")
    ):
        return [], []
    state = _resume_state(zone)
    if state.get("listed"):
        name = (state.get("names") or [""])[0] or "a file"
        return [{"label": "Resume", "value": name, "state": "preserved"}], []
    if not resume_path or not Path(resume_path).is_file():
        return [], ["Resume: no prepared resume file to attach"]
    name = Path(resume_path).name
    for attempt in range(2):
        try:
            page.locator(f"{smartrecruiters_page._RESUME} input[type=file]").first.set_input_files(
                resume_path, timeout=5000
            )
        except Exception:  # noqa: BLE001
            return [], ["Resume: the file could not be set on the upload"]
        outcome = _upload_outcome(page, zone, name)
        if outcome == "listed":
            return [{"label": "Resume", "value": name}], []
        if outcome != "refused":
            return [], [f"Resume: {name} was set but is not listed on the form"]
        # "Cannot upload resume. Please try again in a while." (Batch 3, 2026-10-21):
        # closed, then tried once more after a pause.
        _close_upload_error(page)
        if attempt == 0:
            page.wait_for_timeout(3000)
    return [], [f"Resume: SmartRecruiters could not upload {name} (\"Cannot upload resume\"); "
                "attach it yourself"]


#: SmartRecruiters' dialog when its upload service refuses the file.
_UPLOAD_ERROR = "spl-dialog[open][title^='Cannot upload' i]"


def _upload_outcome(page: Any, zone: Any, name: str) -> str:
    """"listed" once the dropzone lists ``name``, "refused" when the upload error dialog
    opens instead, else "missing" after 8 s."""
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if name in _resume_state(zone).get("names", []):
            return "listed"
        if smartrecruiters_page._present(page.locator(_UPLOAD_ERROR)):
            return "refused"
        page.wait_for_timeout(250)
    return "missing"


def _close_upload_error(page: Any) -> None:
    """Close the upload error dialog so it no longer covers the form."""
    with contextlib.suppress(Exception):
        close = page.locator(f"{_UPLOAD_ERROR} spl-button").filter(has_text="Close").first
        clicks.safe_click(close, purpose="dismiss", timeout=3000)
    with contextlib.suppress(Exception):
        if smartrecruiters_page._present(page.locator(_UPLOAD_ERROR)):
            page.keyboard.press("Escape")


def fill_message(
    page: Any, cover_letter: str | Callable[[bool], str],
) -> tuple[list[dict[str, str]], list[str]]:
    """Put the cover letter in "Message to the Hiring Team" when the box is empty.

    ``cover_letter`` is the text, or a callable given whether the box is required that
    returns it ("" to leave the box empty) — Fill's cover-letter rule, which may write a
    letter first (`cover_on_demand`). A required box left empty is listed for review.
    """
    boxes = page.locator(smartrecruiters_page._MESSAGE)
    if not smartrecruiters_page._present(boxes):
        return [], []
    box = boxes.first
    try:
        current = box.input_value()
    except Exception:  # noqa: BLE001
        return [], ["Message to the Hiring Team"]
    if current.strip():
        kept = {"label": "Message to the Hiring Team", "value": current[:60], "state": "preserved"}
        return [kept], []
    if callable(cover_letter):
        required = False
        with contextlib.suppress(Exception):
            required = bool(box.evaluate(
                "e => e.required || e.getAttribute('aria-required') === 'true'"
            ))
        cover_letter = cover_letter(required)
        if not cover_letter.strip():
            return [], ["Message to the Hiring Team"] if required else []
    if not cover_letter.strip():
        return [], []
    review: list[str] = []
    if smartrecruiters_entries._set_text(
        box, cover_letter.strip(), label="Message to the Hiring Team", review=review
    ):
        with contextlib.suppress(Exception):
            box.evaluate("e => e.blur()")
        return [{"label": "Message to the Hiring Team", "value": "cover letter"}], review
    return [], [*review, "Message to the Hiring Team"]


def fill(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None],
    *,
    resume_path: str | None = None,
    deadline: Callable[[], float] | None = None,
    cover_text: Callable[[bool], str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Fill every area this form step shows; ``(filled, needs_review)`` like Workday's.

    ``cover_text`` decides the hiring-team message (see `fill_message`); without it the
    packet's letter, if any, is used. The message comes after the entries: a letter still
    being written in the background (parallel fills queue for the model) then never holds
    up the entries (2026-10-30: one of five experiences added while the letter waited).

    ``filled`` records are ``{"label", "value"}`` (plus ``"state"`` "preserved" for an
    answer that was already there, "partial" for a saved entry with a field left for
    review); ``needs_review`` holds human labels. Past ``deadline()`` (``time.monotonic``,
    read before each entry) no further entry is added; the rest are listed for review.
    """
    filled: list[dict[str, str]] = []
    review: list[str] = []
    for step in (
        lambda: smartrecruiters_location.fill_city(page, packet.fields),
        lambda: fill_resume(page, resume_path),
        lambda: smartrecruiters_entries.fill_experience(page, packet, progress, deadline=deadline),
        lambda: smartrecruiters_entries.fill_education(page, packet, progress, deadline=deadline),
        lambda: fill_message(page, cover_text or packet.cover_letter),
        lambda: smartrecruiters_screening.fill_screening(page, packet, progress),
    ):
        done, left = step()
        filled.extend(done)
        review.extend(label for label in left if label not in review)
    return filled, review
