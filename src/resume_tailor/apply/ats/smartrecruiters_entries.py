"""SmartRecruiters experience and education entries: open the editor, fill, save, de-duplicate."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.forms import form_guards
from resume_tailor.apply.funnel import packet_fields
from resume_tailor.apply.funnel.packet_models import Packet, PacketEducation, PacketExperience

from . import smartrecruiters_location, smartrecruiters_page

# The new SPL picker attaches Flatpickr to a wrapper inside its shadow root.
_FLATPICKR_DATE_JS = """(field, iso) => {
  let wrapper = field;
  while (wrapper && !wrapper._flatpickr) wrapper = wrapper.parentElement;
  const picker = wrapper?._flatpickr;
  if (!picker) return null;
  picker.setDate(iso, true, 'Y-m-d');
  const selected = picker.selectedDates[0];
  return !!selected && picker.formatDate(selected, 'Y-m-d') === iso
    && field.value === picker.formatDate(selected, picker.config.dateFormat);
}"""
_DRAFT_DATA_KEY = "resumeTailorEntry"
_MARK_DRAFT_JS = "(editor, label) => { editor.dataset.resumeTailorEntry = label; }"


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
    host = editor.locator(f"oc-datepicker[data-test={test_id}]")
    if not typed or not smartrecruiters_page._present(host):
        return False
    picker = host.locator("input.flatpickr-input").first
    month, year = typed.split("/")
    try:
        committed = picker.evaluate(_FLATPICKR_DATE_JS, f"{year}-{month}-01", timeout=3000)
        if committed is not None:
            return bool(committed)
        legacy = host.locator("spl-date-field").first
        if not smartrecruiters_page._present(legacy):
            return False
        picker.focus(timeout=3000)
        picker.fill(typed, timeout=3000)
        picker.press("Enter", timeout=3000)
        picker.press("Tab", timeout=3000)
        legacy_value = legacy.evaluate(smartrecruiters_page._HOST_VALUE_JS, timeout=3000)
        return _date_as_month_year(legacy_value) == typed
    except Exception:  # noqa: BLE001
        return False


def _date_as_month_year(value: Any) -> str:
    text = str(value or "")
    if re.fullmatch(r"(?:0[1-9]|1[0-2])/\d{4}", text):
        return text
    return smartrecruiters_location.month_year(text)

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

def _wait_closed(page: Any, handle: Any, timeout_s: float = 5.0) -> bool:
    """Until the editor ``handle`` names has left the page (saved), at most ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if not handle.evaluate("e => e.isConnected"):
                return True
        except Exception:  # noqa: BLE001 - a handle whose node is gone
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(200)

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
    """Press this editor's own Save and see this editor close; other open editors (the
    applicant's, or more of ours) are left as they are."""
    try:
        handle = editor.element_handle(timeout=3000)
        smartrecruiters_location._activate(
            editor.locator(f"oc-button[data-test={kind}-save] button").first
        )
    except Exception:  # noqa: BLE001
        return False
    return _wait_closed(page, handle)


def _verify_saved_dates(
    page: Any, kind: str, index: int, item: PacketExperience | PacketEducation, label: str,
) -> bool:
    """The saved card shows years only. Read its dates by reopening it when supported."""
    cards = page.locator(f"div[data-test={kind}] oc-{kind}-entry").filter(
        has_not=page.locator(f"[data-test={kind}-edit-form]")
    )
    edit = cards.nth(index).locator(f"[data-test={kind}-entry-edit] button").first
    try:
        if not edit.is_visible():
            return True  # the editor's committed months were checked before Save
        smartrecruiters_location._activate(edit)
        editor = _editor(page, kind).first
        editor.wait_for(state="visible", timeout=3500)
        editor.evaluate(_MARK_DRAFT_JS, label, timeout=3000)
        values = editor.evaluate(smartrecruiters_page._EDITOR_VALUES_JS)
        current = isinstance(item, PacketExperience) and item.current
        return _same_dates(values, kind, item.start, item.end, current) and _save(
            page, kind, editor
        )
    except Exception:  # noqa: BLE001
        return False

def _experience_entry(
    page: Any, editor: Any, exp: PacketExperience, label: str, *, repair: bool = False,
) -> tuple[bool, list[str]]:
    """Fill one open experience editor; ``(safe to save, review notes)``."""
    review: list[str] = []
    title = editor.locator("spl-autocomplete[data-test=job-title-autocomplete]").first
    title_ok = smartrecruiters_location._text_typeahead(title, exp.title)
    if not title_ok:
        review.append(f"{label}: title")
    company = editor.locator("spl-autocomplete[data-test=company-autocomplete]").first
    if not repair and exp.employer and not smartrecruiters_location._text_typeahead(
        company, exp.employer
    ):
        review.append(f"{label}: company")
    if not repair and exp.location:
        city, state, country = smartrecruiters_location.split_location(exp.location)
        office = editor.locator("[data-test=experience-form-location] spl-autocomplete").first
        if not smartrecruiters_location._location_typeahead(office, city, state, country):
            review.append(f"{label}: office location ({exp.location})")
    description = exp.description or "\n".join(exp.bullets)
    if not repair and description and not _set_text(
        editor.locator("oc-textarea[data-test=experience-description] textarea").first,
        description, label=f"{label}: description", review=review,
    ):
        review.append(f"{label}: description")
    start_ok = _set_date(editor, "experience-date-from", exp.start)
    if not start_ok:
        review.append(f"{label}: start date")
    if exp.current:
        end_ok = _tick(editor, "experience-current")
        if not end_ok:
            review.append(f"{label}: currently work here")
    else:
        end_ok = _set_date(editor, "experience-date-to", exp.end)
        if not end_ok:
            review.append(f"{label}: end date")
    return title_ok and start_ok and end_ok, review

def _degree(edu: PacketEducation) -> str:
    return edu.degree_level or edu.degree_name or edu.degree

def _education_entry(
    page: Any, editor: Any, edu: PacketEducation, label: str, *, repair: bool = False,
) -> tuple[bool, list[str]]:
    review: list[str] = []
    school = editor.locator("spl-autocomplete[data-test=institution-autocomplete]").first
    school_ok = smartrecruiters_location._text_typeahead(school, edu.school)
    if not school_ok:
        review.append(f"{label}: institution")
    if not repair and edu.major and not _set_text(
        editor.locator("oc-input[data-test=education-major] input").first, edu.major,
        label=f"{label}: major", review=review,
    ):
        review.append(f"{label}: major")
    degree = _degree(edu)
    if not repair and degree and not _set_text(
        editor.locator("oc-input[data-test=education-degree] input").first, degree,
        label=f"{label}: degree", review=review,
    ):
        review.append(f"{label}: degree")
    start_ok = not edu.start or _set_date(editor, "education-date-from", edu.start)
    if not start_ok:
        review.append(f"{label}: start date")
    end_ok = not edu.end or _set_date(editor, "education-date-to", edu.end)
    if not end_ok:
        review.append(f"{label}: end date")
    return school_ok and start_ok and end_ok, review

def _same_start(listed_date: str, start: str) -> bool:
    """A listed entry's "2025 - 2026" starts in ``start``'s year, when both say a year: two
    stints with one employer stay two entries."""
    shown = re.match(r"\s*(\d{4})", listed_date or "")
    wanted = re.match(r"\s*(\d{4})", start or "")
    return not (shown and wanted) or shown.group(1) == wanted.group(1)

def _listed_experience(entries: list[dict[str, str]], exp: PacketExperience) -> bool:
    return any(
        smartrecruiters_page._same(item.get("title", ""), exp.title)
        and smartrecruiters_page._same(item.get("company", ""), exp.employer)
        and _same_start(item.get("date", ""), exp.start)
        for item in entries
    )

def _same_dates(values: dict[str, Any], kind: str, start: str, end: str, current: bool) -> bool:
    month_year = smartrecruiters_location.month_year
    if _date_as_month_year(values.get(f"{kind}-date-from")) != month_year(start):
        return False
    if current:
        return bool(values.get("current"))
    return not values.get("current") and (
        _date_as_month_year(values.get(f"{kind}-date-to")) == month_year(end)
    )

def _holds_experience(values: dict[str, Any], exp: PacketExperience) -> bool:
    """Whether an open editor holds exactly ``exp`` (title, company and dates)."""
    return (
        smartrecruiters_page._same(values.get("job-title-autocomplete", ""), exp.title)
        and smartrecruiters_page._same(values.get("company-autocomplete", ""), exp.employer)
        and _same_dates(values, "experience", exp.start, exp.end, exp.current)
    )

def _holds_education(values: dict[str, Any], edu: PacketEducation) -> bool:
    """Whether an open editor holds ``edu`` (school, its dates, and major/degree as given)."""
    major, degree = values.get("education-major", ""), values.get("education-degree", "")
    return (
        smartrecruiters_page._same(values.get("institution-autocomplete", ""), edu.school, "school")
        and _same_dates(values, "education", edu.start, edu.end, False)
        and (not major or smartrecruiters_page._same(major, edu.major, "major"))
        and (not degree or smartrecruiters_page._same(degree, _degree(edu))
             or smartrecruiters_page._same(degree, edu.degree))
    )

def _save_reopened(
    page: Any, kind: str, candidates: dict[str, Any],
    listed: Callable[[list[dict[str, str]], Any], bool],
    holds: Callable[[dict[str, Any], Any], bool],
    fill_one: Callable[..., tuple[bool, list[str]]],
    review: list[str],
) -> bool:
    """Save each open editor holding one of ``items``; True when none is left open.

    SmartRecruiters shows every saved entry as an open editor again once the applicant goes
    Back from the screening step (live 2026-10-30). An editor holding anything else is the
    applicant's own edit unless the fill marked it when opening it. Only a marked
    draft can be repaired in place.
    """
    for _ in range(smartrecruiters_page.MAX_ENTRIES):
        editors = _editor(page, kind)
        try:
            count = editors.count()
        except Exception:  # noqa: BLE001
            return False
        if not count:
            return True
        ours, draft_label = None, ""
        for index in range(count):
            try:
                values = editors.nth(index).evaluate(smartrecruiters_page._EDITOR_VALUES_JS)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(values, dict):
                continue
            editor = editors.nth(index)
            label = values.get(_DRAFT_DATA_KEY)
            if label in candidates:
                if not holds(values, candidates[label]):
                    can_save, notes = fill_one(page, editor, candidates[label], label, repair=True)
                    review.extend(notes)
                    if not can_save:
                        return False
                ours, draft_label = editor, label
                break
            if any(holds(values, item) for item in candidates.values()):
                ours = editor
                break
        if ours is None or not _save(page, kind, ours):
            return False
        if draft_label:
            detail = _verified_card(
                page, kind, _entries(page, kind) or [], candidates[draft_label],
                draft_label, listed,
            )
            if detail:
                review.append(f"{draft_label}: {detail}")
                return False
    return not smartrecruiters_page._present(_editor(page, kind))

def _listed_education(entries: list[dict[str, str]], edu: PacketEducation) -> bool:
    """Same school, and the same major or degree when the entry names one."""
    for item in entries:
        if not smartrecruiters_page._same(item.get("school", ""), edu.school, "school"):
            continue
        if not _same_start(item.get("date", ""), edu.start):
            continue
        major, degree = item.get("major", ""), item.get("degree", "")
        if (not major or smartrecruiters_page._same(major, edu.major, "major")) and (
            not degree
            or smartrecruiters_page._same(degree, _degree(edu))
            or smartrecruiters_page._same(degree, edu.degree)
        ):
            return True
    return False


def _verified_card(
    page: Any, kind: str, entries: list[dict[str, str]], item: Any, label: str,
    listed: Callable[[list[dict[str, str]], Any], bool],
) -> str:
    matches = [i for i, entry in enumerate(entries) if listed([entry], item)]
    if not matches:
        return "saved but not found in the list"
    if len(matches) != 1 or not _verify_saved_dates(page, kind, matches[0], item, label):
        return "saved dates could not be verified"
    return ""


def _fill_section(
    page: Any,
    kind: str,
    items: list[Any],
    *,
    describe: Callable[[Any], str],
    listed: Callable[[list[dict[str, str]], Any], bool],
    holds: Callable[[dict[str, Any], Any], bool],
    fill_one: Callable[..., tuple[bool, list[str]]],
    progress: Callable[[str], None],
    deadline: Callable[[], float] | None,
) -> tuple[list[dict[str, str]], list[str]]:
    filled: list[dict[str, str]] = []
    review: list[str] = []
    entries = _entries(page, kind)
    if entries is None or not items:
        return filled, review  # no such section on this form
    heading = kind.capitalize()
    labels = {
        f"{heading} {index} ({describe(item)})": item
        for index, item in enumerate(items[:smartrecruiters_page.MAX_ENTRIES], start=1)
    }
    if smartrecruiters_page._present(_editor(page, kind)):
        if not _save_reopened(page, kind, labels, listed, holds, fill_one, review):
            review.append(f"{heading}: an entry is open for editing; finish it, then Continue fill")
            return filled, review
        entries = _entries(page, kind) or []
    for index, item in enumerate(items[:smartrecruiters_page.MAX_ENTRIES], start=1):
        name = describe(item)
        label = f"{heading} {index} ({name})"
        if listed(entries, item):
            filled.append({"label": label, "value": name, "state": "preserved"})
            continue
        if deadline is not None and time.monotonic() >= deadline():
            review.extend(f"{heading} {later} ({describe(rest)})" for later, rest in
                          enumerate(items[index - 1:smartrecruiters_page.MAX_ENTRIES], start=index))
            break
        progress(f"SmartRecruiters: adding {kind} {name}")
        editor = _open_editor(page, kind)
        if editor is None:
            review.append(f"{label}: the Add button did not open an entry")
            break
        try:
            editor.evaluate(_MARK_DRAFT_JS, label, timeout=3000)
        except Exception:  # noqa: BLE001
            review.append(f"{label}: the entry editor changed while opening")
            break
        can_save, notes = fill_one(page, editor, item, label)
        review.extend(notes)
        if not can_save or not _save(page, kind, editor):
            # Left open with what was filled; later entries would need another editor.
            review.append(f"{label}: not saved; complete the open entry and press Save")
            review.extend(f"{heading} {later} ({describe(rest)})" for later, rest in
                          enumerate(items[index:smartrecruiters_page.MAX_ENTRIES], start=index + 1))
            break
        entries = _entries(page, kind) or []
        detail = _verified_card(page, kind, entries, item, label, listed)
        if not detail:
            progress(f"SmartRecruiters: added {kind} {name}")
            filled.append({"label": label, "value": name} if not notes else
                          {"label": label, "value": name, "state": "partial"})
        else:
            review.append(f"{label}: {detail}")
            review.extend(f"{heading} {later} ({describe(rest)})" for later, rest in
                          enumerate(items[index:smartrecruiters_page.MAX_ENTRIES], start=index + 1))
            break
    if len(items) > smartrecruiters_page.MAX_ENTRIES:
        review.append(
            f"{heading}: only the first {smartrecruiters_page.MAX_ENTRIES} entries were added"
        )
    return filled, review

def fill_experience(
    page: Any, packet: Packet, progress: Callable[[str], None], *,
    deadline: Callable[[], float] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Add the packet's experience entries; past ``deadline()`` (``time.monotonic``, read
    before each entry, so the fill's own extensions count) the rest go to review."""
    return _fill_section(
        page, "experience", list(packet.experience),
        describe=lambda exp: " at ".join(part for part in (exp.title, exp.employer) if part),
        listed=_listed_experience, holds=_holds_experience, fill_one=_experience_entry,
        progress=progress, deadline=deadline,
    )

def fill_education(
    page: Any, packet: Packet, progress: Callable[[str], None], *,
    deadline: Callable[[], float] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    return _fill_section(
        page, "education", packet_fields.education_rows(packet.education),
        describe=lambda edu: edu.school, listed=_listed_education, holds=_holds_education,
        fill_one=_education_entry, progress=progress, deadline=deadline,
    )
