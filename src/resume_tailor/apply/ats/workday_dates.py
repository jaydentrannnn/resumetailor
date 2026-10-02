"""Workday repeater dates and blank fields: filling, retrying and re-checking date sections."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.driver import clicks

from . import workday_rows


def _school_field(page: Any, row: str | None = None) -> str:
    """This tenant's school control name, for one row or for the page."""
    for name in workday_rows._SCHOOL_FIELDS:
        if row is not None:
            if workday_rows._ctl(page, row, name).count() == 1:
                return name
        elif workday_rows._rows(page, name):
            return name
    return workday_rows._EDU["school"]

def _blank_fill(page: Any, prefix: str, field: str, value: str) -> bool:
    """Type into an empty text control; an existing answer is kept (ok only if equal)."""
    if not value:
        return True
    control = workday_rows._ctl(page, prefix, field)
    if control.count() != 1:
        return False
    target = control.first
    if not target.is_visible() or not target.is_enabled():
        return False
    existing = str(target.input_value() or "").strip()
    if existing:
        return existing.casefold() == value.strip().casefold()
    # Typing into a searchable prompt does not commit an option.
    if target.get_attribute("role") == "combobox" or target.get_attribute("aria-autocomplete"):
        return False
    target.fill(value, timeout=5000)
    return str(target.input_value() or "").strip() == value

def _text_or_prompt(page: Any, prefix: str, field: str, value: str, *, key: str) -> bool:
    """Plain text box, or a Workday multiselect prompt (type, then pick an exact option)."""
    if not value:
        return True
    try:
        in_prompt = bool(page.evaluate(
            "(id) => !!document.getElementById(id)?.closest(\"[data-automation-id='multiselectInputContainer']\")",
            f"{prefix}{field}",
        ))
    except Exception:  # noqa: BLE001
        in_prompt = False
    if not in_prompt:
        return _blank_fill(page, prefix, field, value)
    from resume_tailor.apply.ats import workday_prompts

    return workday_prompts.select_prompt(page, f"{prefix}{field}", value, key=key)

def _date_parts(value: str) -> tuple[str, str]:
    """``2025-01`` / ``2025`` -> (month, year); anything else -> ("", "")."""
    match = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-\d{2})?", value.strip())
    return (match.group(2) or "", match.group(1)) if match else ("", "")

def _fill_date(page: Any, prefix: str, field: str, value: str, *, with_month: bool) -> bool:
    """Type a Workday split date (MM / YYYY sections); keep an existing date."""
    month, year = _date_parts(value)
    if not year:
        return not value  # nothing to write is fine; an unparseable date needs review
    year_control = workday_rows._ctl(page, prefix, field)
    if year_control.count() == 1 and year_control.first.is_visible():
        target = year_control.first
        tag = str(target.evaluate("el => el.tagName") or "").upper()
        if tag == "SELECT":
            current = str(target.input_value() or "").strip()
            if current:
                return current == year
            target.select_option(label=year, timeout=3000)
            return str(target.input_value() or "").strip() == year
        if tag == "INPUT" and (target.get_attribute("role") or "") != "combobox":
            current = str(target.input_value() or "").strip()
            if current:
                return current == year
            target.fill(year, timeout=3000)
            target.press("Tab", timeout=3000)
            return str(target.input_value() or "").strip() == year
        if target.get_attribute("aria-haspopup") == "listbox":
            from resume_tailor.apply.ats import workday_dropdowns
            current = workday_rows._value(page, prefix, field)
            return (
                current == year
                if current
                else workday_dropdowns.select_listbox(page, f"[id='{prefix}{field}']", year)
            )
    parts = ([("dateSectionMonth", month)] if with_month else []) + [("dateSectionYear", year)]
    return fill_date_sections(page, f"{prefix}{field}", parts)

def _fill_date_retrying(
    page: Any, prefix: str, field: str, value: str, *, with_month: bool, note: Callable[[str], None],
) -> bool:
    """`_fill_date`, typed once more with the tab in front when the keys did not land.

    Invesco (2026-10) left one row's From/To and Education's years empty while other rows
    in the same tab typed: three fills shared one window, and keystrokes sent to a tab
    that is not in front can miss the spinbutton. Whether the page had focus is logged
    so the next failure says whether that was the cause.
    """
    if workday_rows._attempt(lambda: _fill_date(page, prefix, field, value, with_month=with_month)):
        return True
    try:
        focused = bool(page.evaluate("() => document.hasFocus()"))
    except Exception:  # noqa: BLE001
        focused = None
    with contextlib.suppress(Exception):
        page.bring_to_front()
    ok = workday_rows._attempt(
        lambda: _fill_date(page, prefix, field, value, with_month=with_month)
    )
    note(f"Workday: retyped {prefix}{field} in front (page had focus: {focused}); "
         + ("filled" if ok else "still not filled"))
    return ok

def _recheck_dates(
    page: Any,
    placed: list[tuple[str, str, list[tuple[str, str, bool]]]],
    filled: list[dict[str, str]],
    review: list[str],
    progress: Callable[[str], None],
) -> None:
    """Re-read every filled row's dates once the section is done, retyping any that went
    blank: adding and filling later rows re-renders earlier ones before Continue."""
    for row, label, dates in placed:
        lost = [field for field, value, with_month in dates
                if not _fill_date_retrying(page, row, field, value, with_month=with_month, note=progress)]
        if lost:
            filled[:] = [item for item in filled if item.get("label") != label]
            names = {"startDate": "From", "endDate": "To"}
            review.append(f"{label} ({', '.join(names.get(field, field) for field in lost)})")

def _date_absent(page: Any, prefix: str, field: str) -> bool:
    """Whether this tenant's row has no such date at all (F5's Education, 2026-09)."""
    return (
        workday_rows._ctl(page, prefix, field).count() == 0
        and page.locator(f"[id^='{prefix}{field}-dateSection']").count() == 0
    )

def fill_date_sections(page: Any, control: str, parts: list[tuple[str, str]]) -> bool:
    """Type Workday's split date sections (``<control>-dateSectionMonth/Day/Year``).

    An existing section is kept (ok only when equal); a partial one ("0" of "03", a
    keystroke that landed) is retyped. Each section is read back as it is typed and
    typed once more when the keys did not land: CACI (2026-09) left one row's From month
    and year empty while every other date filled, because the typing went to whatever
    held focus and nothing checked the section until the end.
    """
    def value_of(section: str) -> str:
        return str(page.locator(f"[id='{control}-{section}-input']").first.input_value() or "").strip()

    def same(current: str, text: str) -> bool:
        return current.lstrip("0") == text.lstrip("0")

    for section, text in parts:
        if not text:
            return False
        box = page.locator(f"[id='{control}-{section}-input']")
        if box.count() != 1:
            return False
        current = value_of(section)
        if current and same(current, text):
            continue
        if current and not text.startswith(current):
            return False  # the applicant's own date
        for attempt in range(2):
            # The real spinbutton input is a 0px overlay; its visible "MM"/"DD"/"YYYY"
            # display div takes the click. The input is also focused directly, so the
            # keys cannot go to the control that had focus before.
            clicks.safe_click(page.locator(f"[id='{control}-{section}-display']").first, purpose="select", timeout=3000)
            with contextlib.suppress(Exception):
                box.first.focus()
            if attempt or value_of(section):
                with contextlib.suppress(Exception):
                    page.keyboard.press("ControlOrMeta+A")  # Cmd+A on macOS
                    page.keyboard.press("Backspace")
            page.keyboard.type(text, delay=40)
            page.wait_for_timeout(150)
            if same(value_of(section), text):
                break
    page.wait_for_timeout(150)
    return all(same(value_of(section), text) for section, text in parts)
