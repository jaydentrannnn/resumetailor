"""SmartRecruiters experience and education entries: open the editor, fill, save, de-duplicate."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.forms import form_guards
from resume_tailor.apply.funnel.packet_models import Packet, PacketEducation, PacketExperience

from . import smartrecruiters_location, smartrecruiters_page


def _entries(page: Any, kind: str) -> list[dict[str, str]] | None:
    try:
        found = page.evaluate(smartrecruiters_page._ENTRIES_JS, [kind, kind])
    except Exception:  # noqa: BLE001
        return None
    return None if found is None else [dict(item) for item in found]

def _editor(page: Any, kind: str) -> Any:
    return page.locator(f"div[data-test={kind}] [data-test={kind}-edit-form]")

def _set_text(control: Any, value: str, *, label: str, review: list[str]) -> bool:
    """Fill a plain input/textarea; a form limit shortens at a sentence end and flags it."""
    if not value:
        return False
    try:
        limit = int(control.evaluate("e => e.maxLength > 0 ? e.maxLength : 0"))
        if limit and len(value) > limit:
            value, _shortened = form_guards.fit_to_limit(value, limit)
            review.append(f"{label}: shortened to the form's {limit}-character limit")
            if not value:
                return False
        control.fill(value, timeout=3000)
        return control.input_value() == value
    except Exception:  # noqa: BLE001
        return False

def _set_date(editor: Any, test_id: str, value: str) -> bool:
    typed = smartrecruiters_location.month_year(value)
    picker = editor.locator(f"oc-datepicker[data-test={test_id}] input.flatpickr-input").first
    if not typed or not smartrecruiters_page._present(
        editor.locator(f"oc-datepicker[data-test={test_id}]")
    ):
        return False
    try:
        picker.focus(timeout=3000)
        picker.fill(typed, timeout=3000)
        picker.press("Enter", timeout=3000)
        picker.press("Tab", timeout=3000)
        return picker.input_value() == typed
    except Exception:  # noqa: BLE001
        return False

def _tick(editor: Any, test_id: str) -> bool:
    box = editor.locator(f"oc-checkbox[data-test={test_id}] input[type=checkbox]").first
    try:
        if not box.is_checked():
            # The native box is transparent but takes the press (its label text does not).
            smartrecruiters_location._activate(box)
        return box.is_checked()
    except Exception:  # noqa: BLE001
        return False

def _press(page: Any, selector: str) -> bool:
    try:
        smartrecruiters_location._activate(page.locator(selector).first)
        return True
    except Exception:  # noqa: BLE001
        return False

def _wait_closed(page: Any, editor: Any, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not smartrecruiters_page._present(editor):
            return True
        page.wait_for_timeout(200)
    return not smartrecruiters_page._present(editor)

def _open_editor(page: Any, kind: str) -> Any | None:
    """Press the section's Add button; the new (only) editor, or None."""
    if not _press(page, f"oc-button[data-test=add-{kind}] button"):
        return None
    editor = _editor(page, kind)
    try:
        editor.first.wait_for(state="visible", timeout=5000)
    except Exception:  # noqa: BLE001
        return None
    return editor.first if editor.count() == 1 else None

def _save(page: Any, kind: str, editor: Any) -> bool:
    if not _press(page, f"oc-button[data-test={kind}-save] button"):
        return False
    return _wait_closed(page, _editor(page, kind))

def _experience_entry(
    page: Any, editor: Any, exp: PacketExperience, label: str
) -> tuple[bool, list[str]]:
    """Fill one open experience editor; ``(complete, review notes)``."""
    review: list[str] = []
    title = editor.locator("spl-autocomplete[data-test=job-title-autocomplete]").first
    if not smartrecruiters_location._text_typeahead(title, exp.title):
        review.append(f"{label}: title")
    company = editor.locator("spl-autocomplete[data-test=company-autocomplete]").first
    if exp.employer and not smartrecruiters_location._text_typeahead(company, exp.employer):
        review.append(f"{label}: company")
    if exp.location:
        city, state, country = smartrecruiters_location.split_location(exp.location)
        office = editor.locator("[data-test=experience-form-location] spl-autocomplete").first
        if not smartrecruiters_location._location_typeahead(office, city, state, country):
            review.append(f"{label}: office location ({exp.location})")
    description = exp.description or "\n".join(exp.bullets)
    if description and not _set_text(
        editor.locator("oc-textarea[data-test=experience-description] textarea").first,
        description, label=f"{label}: description", review=review,
    ):
        review.append(f"{label}: description")
    if not _set_date(editor, "experience-date-from", exp.start):
        review.append(f"{label}: start date")
    if exp.current:
        if not _tick(editor, "experience-current"):
            review.append(f"{label}: currently work here")
    elif not _set_date(editor, "experience-date-to", exp.end):
        review.append(f"{label}: end date")
    return not review, review

def _degree(edu: PacketEducation) -> str:
    return edu.degree_level or edu.degree_name or edu.degree

def _education_entry(
    page: Any, editor: Any, edu: PacketEducation, label: str
) -> tuple[bool, list[str]]:
    review: list[str] = []
    school = editor.locator("spl-autocomplete[data-test=institution-autocomplete]").first
    if not smartrecruiters_location._text_typeahead(school, edu.school):
        review.append(f"{label}: institution")
    if edu.major and not _set_text(
        editor.locator("oc-input[data-test=education-major] input").first, edu.major,
        label=f"{label}: major", review=review,
    ):
        review.append(f"{label}: major")
    degree = _degree(edu)
    if degree and not _set_text(
        editor.locator("oc-input[data-test=education-degree] input").first, degree,
        label=f"{label}: degree", review=review,
    ):
        review.append(f"{label}: degree")
    if edu.start and not _set_date(editor, "education-date-from", edu.start):
        review.append(f"{label}: start date")
    if edu.end and not _set_date(editor, "education-date-to", edu.end):
        review.append(f"{label}: end date")
    return not review, review

def _listed_experience(entries: list[dict[str, str]], exp: PacketExperience) -> bool:
    return any(
        smartrecruiters_page._same(item.get("title", ""), exp.title)
        and smartrecruiters_page._same(item.get("company", ""), exp.employer)
        for item in entries
    )

def _listed_education(entries: list[dict[str, str]], edu: PacketEducation) -> bool:
    """Same school, and the same major or degree when the entry names one."""
    for item in entries:
        if not smartrecruiters_page._same(item.get("school", ""), edu.school, "school"):
            continue
        major, degree = item.get("major", ""), item.get("degree", "")
        if (not major or smartrecruiters_page._same(major, edu.major, "major")) and (
            not degree
            or smartrecruiters_page._same(degree, _degree(edu))
            or smartrecruiters_page._same(degree, edu.degree)
        ):
            return True
    return False

def _fill_section(
    page: Any,
    kind: str,
    items: list[Any],
    *,
    describe: Callable[[Any], str],
    listed: Callable[[list[dict[str, str]], Any], bool],
    fill_one: Callable[[Any, Any, Any, str], tuple[bool, list[str]]],
    progress: Callable[[str], None],
    deadline: float | None,
) -> tuple[list[dict[str, str]], list[str]]:
    filled: list[dict[str, str]] = []
    review: list[str] = []
    entries = _entries(page, kind)
    if entries is None or not items:
        return filled, review  # no such section on this form
    heading = kind.capitalize()
    if smartrecruiters_page._present(_editor(page, kind)):
        # Someone's entry is open mid-edit: pressing Add or Save could lose it.
        return filled, [f"{heading}: an entry is open for editing; finish it, then Continue fill"]
    for index, item in enumerate(items[:smartrecruiters_page.MAX_ENTRIES], start=1):
        name = describe(item)
        label = f"{heading} {index} ({name})"
        if listed(entries, item):
            filled.append({"label": label, "value": name, "state": "preserved"})
            continue
        if deadline is not None and time.monotonic() >= deadline:
            review.extend(f"{heading} {later} ({describe(rest)})" for later, rest in
                          enumerate(items[index - 1:smartrecruiters_page.MAX_ENTRIES], start=index))
            break
        progress(f"SmartRecruiters: adding {kind} {name}")
        editor = _open_editor(page, kind)
        if editor is None:
            review.append(f"{label}: the Add button did not open an entry")
            break
        complete, notes = fill_one(page, editor, item, label)
        review.extend(notes)
        if not _save(page, kind, editor):
            # Left open with what was filled; later entries would need another editor.
            review.append(f"{label}: not saved; complete the open entry and press Save")
            review.extend(f"{heading} {later} ({describe(rest)})" for later, rest in
                          enumerate(items[index:smartrecruiters_page.MAX_ENTRIES], start=index + 1))
            break
        entries = _entries(page, kind) or []
        if listed(entries, item):
            filled.append({"label": label, "value": name} if complete else
                          {"label": label, "value": name, "state": "partial"})
        else:
            review.append(f"{label}: saved but not found in the list")
    if len(items) > smartrecruiters_page.MAX_ENTRIES:
        review.append(
            f"{heading}: only the first {smartrecruiters_page.MAX_ENTRIES} entries were added"
        )
    return filled, review

def fill_experience(
    page: Any, packet: Packet, progress: Callable[[str], None], *, deadline: float | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    return _fill_section(
        page, "experience", list(packet.experience),
        describe=lambda exp: " at ".join(part for part in (exp.title, exp.employer) if part),
        listed=_listed_experience, fill_one=_experience_entry, progress=progress, deadline=deadline,
    )

def fill_education(
    page: Any, packet: Packet, progress: Callable[[str], None], *, deadline: float | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    return _fill_section(
        page, "education", list(packet.education),
        describe=lambda edu: edu.school, listed=_listed_education, fill_one=_education_entry,
        progress=progress, deadline=deadline,
    )
