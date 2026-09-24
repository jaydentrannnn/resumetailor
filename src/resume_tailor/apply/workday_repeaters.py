"""Conservative, row-scoped filling of Workday employment and education lists.

Current Workday renders each row's controls with ids ``workExperience-<n>--<field>`` /
``education-<n>--<field>`` (captured live 2026-09), and a per-section "Add" / "Add
Another" button under the section heading. A row is reused only when its identity fields
match exactly, or when it is the single blank row; otherwise a row is added. Existing
answers are never replaced, and anything that cannot be verified is reported for review.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.packet import Packet

#: Field names (the part after ``--``) inside one row.
_WORK = {"title": "jobTitle", "company": "companyName", "location": "location",
         "description": "roleDescription", "current": "currentlyWorkHere"}
_EDU = {"school": "schoolName", "degree": "degree", "major": "fieldOfStudy", "gpa": "gradeAverage"}

_ROWS_JS = r"""(anchor) => [...document.querySelectorAll(`[id$="--${anchor}"]`)]
  .filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length)
  .map(e => e.id.slice(0, e.id.length - anchor.length))"""

#: Index (among all add buttons) of the one under the section whose heading is given.
_ADD_BUTTON_JS = r"""(heading) => {
  const buttons = [...document.querySelectorAll("[data-automation-id='add-button']")];
  return buttons.findIndex(b => {
    let node = b;
    for (let i = 0; i < 8 && node; i++) {
      node = node.parentElement;
      const h = node && node.querySelector('h3, h4, [role=heading], legend');
      if (h) return (h.innerText || '').trim().toLowerCase() === heading.toLowerCase();
    }
    return false;
  });
}"""


#: A prompt field's value is its committed chips, not the text in its search box.
_CHIPS_JS = r"""(id) => {
  const input = document.getElementById(id);
  if (!input || !input.closest("[data-automation-id='multiselectInputContainer']")) return null;
  const field = input.closest("[data-automation-id^='formField-']");
  return [...field.querySelectorAll("[data-automation-id='selectedItem']")]
    .map(e => (e.innerText || '').trim()).join(', ');
}"""


def _ctl(page: Any, prefix: str, field: str) -> Any:
    return page.locator(f"[id='{prefix}{field}']")


def _value(page: Any, prefix: str, field: str) -> str:
    control = _ctl(page, prefix, field)
    try:
        if control.count() != 1:
            return ""
        target = control.first
        chips = page.evaluate(_CHIPS_JS, f"{prefix}{field}")
        if chips is not None:
            return str(chips).strip()
        if (target.get_attribute("aria-haspopup") or "") == "listbox":
            text = str(target.inner_text() or "").strip()
            return "" if re.fullmatch(r"select one|select", text, re.I) else text
        return str(target.input_value() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _rows(page: Any, anchor: str) -> list[str]:
    try:
        return [str(prefix) for prefix in page.evaluate(_ROWS_JS, anchor) or []]
    except Exception:  # noqa: BLE001
        return []


def _choose_row(page: Any, rows: list[str], identity: tuple[str, ...], fields: tuple[str, ...]) -> str | None:
    """Pick the row for ``identity``: exact match, else one partially filled row that
    agrees on every filled identity field (a row an earlier run started), else the single
    blank row. Ambiguity at any stage returns None so a new row is added instead.
    """
    expected = tuple(part.strip().casefold() for part in identity)
    values = {row: tuple(_value(page, row, field).casefold() for field in fields) for row in rows}
    exact = [row for row in rows if values[row] == expected]
    if exact:
        return exact[0] if len(exact) == 1 else None
    partial = [
        row for row in rows
        if any(values[row]) and all(v in {"", e} for v, e in zip(values[row], expected, strict=True))
    ]
    if partial:
        return partial[0] if len(partial) == 1 else None
    blank = [row for row in rows if not any(values[row])]
    return blank[0] if len(blank) == 1 else None


def _section_present(page: Any, heading: str, anchor: str) -> bool:
    """Whether this tenant's step asks for the section at all (rows or an Add button)."""
    if _rows(page, anchor):
        return True
    try:
        index = page.evaluate(_ADD_BUTTON_JS, heading)
    except Exception:  # noqa: BLE001 - unknown is treated as present, so rows get flagged
        return True
    return isinstance(index, int) and index >= 0


def _add_row(page: Any, heading: str, anchor: str) -> str | None:
    before = set(_rows(page, anchor))
    try:
        index = page.evaluate(_ADD_BUTTON_JS, heading)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(index, int) or index < 0:
        return None
    page.locator("[data-automation-id='add-button']").nth(index).click(timeout=5000)
    for _ in range(12):
        page.wait_for_timeout(250)
        added = [row for row in _rows(page, anchor) if row not in before]
        if len(added) == 1:
            return added[0]
    return None


def _blank_fill(page: Any, prefix: str, field: str, value: str) -> bool:
    """Type into an empty text control; an existing answer is kept (ok only if equal)."""
    if not value:
        return True
    control = _ctl(page, prefix, field)
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
    from resume_tailor.apply import workday_flow  # noqa: PLC0415

    return workday_flow.select_prompt(page, f"{prefix}{field}", value, key=key)


def _date_parts(value: str) -> tuple[str, str]:
    """``2025-01`` / ``2025`` -> (month, year); anything else -> ("", "")."""
    match = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-\d{2})?", value.strip())
    return (match.group(2) or "", match.group(1)) if match else ("", "")


def _fill_date(page: Any, prefix: str, field: str, value: str, *, with_month: bool) -> bool:
    """Type a Workday split date (MM / YYYY sections); keep an existing date."""
    month, year = _date_parts(value)
    if not year:
        return not value  # nothing to write is fine; an unparseable date needs review
    year_control = _ctl(page, prefix, field)
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
            from resume_tailor.apply import workday_flow  # noqa: PLC0415
            current = _value(page, prefix, field)
            return current == year if current else workday_flow.select_listbox(page, f"[id='{prefix}{field}']", year)
    parts = ([("dateSectionMonth", month)] if with_month else []) + [("dateSectionYear", year)]
    for section, text in parts:
        if not text:
            return False
        box = page.locator(f"[id='{prefix}{field}-{section}-input']")
        if box.count() != 1:
            return False
        current = str(box.first.input_value() or "").strip()
        if current:
            if current.lstrip("0") != text.lstrip("0"):
                return False
            continue
        # The real spinbutton input is a 0px overlay; its visible "MM"/"YYYY" display
        # div takes the click and focuses it.
        page.locator(f"[id='{prefix}{field}-{section}-display']").first.click(timeout=3000)
        page.keyboard.type(text, delay=40)
    page.wait_for_timeout(150)
    return all(
        str(page.locator(f"[id='{prefix}{field}-{section}-input']").first.input_value() or "").strip().lstrip("0")
        == text.lstrip("0")
        for section, text in parts
    )


def fill(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None],
    *,
    select: Callable[..., bool] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Populate prepared entries where an exact or blank row is observable.

    Returns (filled, needs_review): filled rows as ``{"label", "value"}`` records and the
    human labels of rows or fields left for the applicant.
    """
    filled: list[dict[str, str]] = []
    review: list[str] = []

    # Some tenants (Capital Group, 2026-09) ask only for a resume on My Experience; a
    # section that is not on the page is not a gap to review.
    experience = packet.experience
    if experience and not _section_present(page, "Work Experience", _WORK["title"]):
        progress("This Workday step has no Work Experience section; skipping employment rows")
        experience = []
    if experience:
        progress("Inspecting Workday employment rows")
    for exp in experience:
        label = f"Work experience: {exp.title} at {exp.employer}"
        try:
            row = _choose_row(page, _rows(page, _WORK["title"]), (exp.title, exp.employer),
                              (_WORK["title"], _WORK["company"]))
            if row is None:
                row = _add_row(page, "Work Experience", _WORK["title"])
            if row is None:
                review.append(label)
                continue
            results = [
                _blank_fill(page, row, _WORK["title"], exp.title),
                _blank_fill(page, row, _WORK["company"], exp.employer),
                _blank_fill(page, row, _WORK["location"], exp.location),
                _blank_fill(page, row, _WORK["description"], exp.description),
            ]
            if exp.current:
                box = _ctl(page, row, _WORK["current"])
                if box.count() == 1 and not box.first.is_checked():
                    try:
                        box.first.check(timeout=2000)
                    except Exception:  # noqa: BLE001 - styled checkbox: its label takes the click
                        page.locator(f"label[for='{row}{_WORK['current']}']").first.click(timeout=3000)
                results.append(box.count() == 1 and box.first.is_checked())
            results.append(_fill_date(page, row, "startDate", exp.start, with_month=True))
            if not exp.current:
                results.append(_fill_date(page, row, "endDate", exp.end, with_month=True))
            if all(results):
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": f"{exp.start} - {exp.end or 'present'}"})
            else:
                review.append(label)
        except Exception as exc:  # noqa: BLE001 - preserve the rest of the batch
            progress(f"Workday employment row needs review: {exp.title} at {exp.employer} ({type(exc).__name__})")
            review.append(label)

    education = packet.education
    if education and not _section_present(page, "Education", _EDU["school"]):
        progress("This Workday step has no Education section; skipping education rows")
        education = []
    if education:
        progress("Inspecting Workday education rows")
    for edu in education:
        label = f"Education: {edu.school}"
        try:
            row = _choose_row(page, _rows(page, _EDU["school"]), (edu.school, edu.major),
                              (_EDU["school"], _EDU["major"]))
            if row is None:
                row = _add_row(page, "Education", _EDU["school"])
            if row is None:
                review.append(label)
                continue
            results = [
                _text_or_prompt(page, row, _EDU["school"], edu.school, key="school"),
                _text_or_prompt(page, row, _EDU["major"], edu.major, key="major"),
                _blank_fill(page, row, _EDU["gpa"], edu.gpa),
                _fill_date(page, row, "firstYearAttended", edu.start, with_month=False),
                _fill_date(page, row, "lastYearAttended", edu.end, with_month=False),
            ]
            degree = edu.degree_name or edu.degree_level or edu.degree
            if degree and not _value(page, row, _EDU["degree"]):
                # Most specific first: "Bachelor of Science in X" -> "Bachelor of Science" -> "Bachelors".
                candidates = [edu.degree_name, re.sub(r"\s+in\s+.*$", "", edu.degree_name or ""),
                              edu.degree_level, edu.degree]
                chosen = False
                for candidate in dict.fromkeys(c for c in candidates if c):
                    if select and select(page, f"[id='{row}{_EDU['degree']}']", candidate, key="degree_level"):
                        chosen = True
                        break
                results.append(chosen)
            if all(results):
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": degree})
            else:
                review.append(label)
        except Exception as exc:  # noqa: BLE001
            progress(f"Workday education row needs review: {edu.school} ({type(exc).__name__})")
            review.append(label)
    return filled, review


async def fill_education_years_async(page: Any, packet: Packet) -> tuple[list[dict[str, str]], list[str]]:
    """Fill split Workday education year controls in the verified engine.

    The ordinary scanner handles visible inputs and selectors. This covers Workday's
    zero-width year spinbuttons, which the scanner intentionally cannot observe.
    """
    rows = await page.evaluate(r"""() => [...document.querySelectorAll('[id$="--schoolName"]')]
      .map(el => ({prefix: el.id.slice(0, -'schoolName'.length), school: el.value || '',
        major: document.getElementById(el.id.replace('schoolName', 'fieldOfStudy'))?.value || ''}))""")
    filled: list[dict[str, str]] = []
    review: list[str] = []
    for row in rows or []:
        matches = [edu for edu in packet.education if edu.school.strip().casefold() == str(row["school"]).strip().casefold()
                   and (not row["major"] or edu.major.strip().casefold() == str(row["major"]).strip().casefold())]
        if len(matches) != 1:
            continue
        edu = matches[0]
        for field, date in (("firstYearAttended", edu.start), ("lastYearAttended", edu.end)):
            _month, year = _date_parts(date)
            if not year:
                continue
            prefix = str(row["prefix"])
            year_input = page.locator(f"[id='{prefix}{field}-dateSectionYear-input']")
            if await year_input.count() != 1:
                continue  # ordinary visible controls belong to the scanner
            current = str(await year_input.input_value() or "").strip()
            label = f"Education: {edu.school} {field}"
            if current and current != year:
                review.append(label)
                continue
            if not current:
                display = page.locator(f"[id='{prefix}{field}-dateSectionYear-display']")
                if await display.count() != 1:
                    review.append(label)
                    continue
                await display.click(timeout=3000)
                await page.keyboard.type(year, delay=40)
                await page.keyboard.press("Tab")
            if str(await year_input.input_value() or "").strip() == year:
                filled.append({"label": label, "value": year})
            else:
                review.append(label)
    return filled, review
