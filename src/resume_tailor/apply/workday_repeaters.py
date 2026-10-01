"""Conservative, row-scoped filling of Workday employment, education and language lists.

Current Workday renders each row's controls with ids ``workExperience-<n>--<field>`` /
``education-<n>--<field>`` (captured live 2026-09), and a per-section "Add" / "Add
Another" button under the section heading. A row is reused only when its identity fields
match exactly, or when it is the single blank row; otherwise a row is added. Existing
answers are never replaced, and anything that cannot be verified is reported for review.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from typing import Any

from resume_tailor.apply import clicks, field_matcher
from resume_tailor.apply.packet import Packet

#: Field names (the part after ``--``) inside one row.
_WORK = {"title": "jobTitle", "company": "companyName", "location": "location",
         "description": "roleDescription", "current": "currentlyWorkHere"}
_EDU = {"school": "schoolName", "degree": "degree", "major": "fieldOfStudy", "gpa": "gradeAverage"}
#: Tenants name the school control ``schoolName`` (text) or ``school`` (a searchable
#: prompt, Upbound 2026-09).
_SCHOOL_FIELDS = ("schoolName", "school")
#: A Languages row's language control (``language-<n>--language``).
_LANGUAGE = "language"
#: Row identity fields whose committed option may be worded differently from the profile.
_MATCH_KEYS = {"schoolName": "school", "school": "school", "fieldOfStudy": "major", _LANGUAGE: "language"}

#: One row's visible controls, each with its form-field label (a checkbox: its own label).
_ROW_CONTROLS_JS = r"""(prefix) => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  return [...document.querySelectorAll(`[id^="${prefix}"]`)].filter(e => {
    const own = e.type === 'checkbox' && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
    return vis(e) || vis(own);
  }).map(e => {
    const own = e.type === 'checkbox' && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
    const field = e.closest("[data-automation-id^='formField-']");
    const label = own || (field && field.querySelector('label, legend'));
    return {id: e.id, checkbox: e.type === 'checkbox', checked: !!e.checked,
            listbox: e.getAttribute('aria-haspopup') === 'listbox',
            label: label ? (label.innerText || '').replace(/\*\s*$/, '').trim() : ''};
  });
}"""

#: Row prefixes only (``education-235--``): Workday's error/help elements end with the
#: same field name (``error1-education-235--school``) and are not rows.
_ROWS_JS = r"""(anchor) => [...document.querySelectorAll(`[id$="--${anchor}"]`)]
  .filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length)
  .map(e => e.id.slice(0, e.id.length - anchor.length))
  .filter(prefix => /^[A-Za-z]+-\d+--$/.test(prefix))"""

#: Index (among the visible add buttons) of the one under the section whose heading is
#: given. Hidden add buttons (a collapsed template) are skipped, so the index names the
#: button a person would press; with ``tag`` that button is also marked ``data-rt-add``
#: so the click targets it by attribute rather than by an index that can drift.
_ADD_BUTTON_JS = r"""([heading, tag]) => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  document.querySelectorAll('[data-rt-add]').forEach(e => e.removeAttribute('data-rt-add'));
  const buttons = [...document.querySelectorAll("[data-automation-id='add-button']")].filter(vis);
  const index = buttons.findIndex(b => {
    let node = b;
    for (let i = 0; i < 8 && node; i++) {
      node = node.parentElement;
      const h = node && node.querySelector('h3, h4, [role=heading], legend');
      if (h) return (h.innerText || '').trim().toLowerCase() === heading.toLowerCase();
    }
    return false;
  });
  if (tag && index >= 0) buttons[index].setAttribute('data-rt-add', '1');
  return index;
}"""


class AddRowError(RuntimeError):
    """The section's Add button was found but could not be pressed (e.g. a popup's
    dismiss layer over it); the message names what Playwright saw."""


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


def _same(value: str, wanted: str, key: str) -> bool:
    """Whether a row's ``value`` is the profile's ``wanted`` answer.

    A committed chip reads "University of California, Irvine" for the profile's
    "University of California - Irvine", and a one-result search can commit "Computer
    and Information Science" for "Computer Science": the match is tried both ways.
    """
    if value == wanted:
        return True
    if not (key and value and wanted):
        return False
    return bool(
        field_matcher.closest_option([value], wanted, key=key)
        or field_matcher.closest_option([wanted], value, key=key)
    )


def _choose_row(
    page: Any,
    rows: list[str],
    identity: tuple[str, ...],
    fields: tuple[str, ...],
    *,
    exclude: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """Pick the row for ``identity``: exact match, else one partially filled row that
    agrees on every filled identity field (a row an earlier run started), else the single
    blank row. Ambiguity at any stage returns None so a new row is added instead.
    Rows in ``exclude`` (already claimed by another entry this pass) are never picked.
    """
    rows = [row for row in rows if row not in exclude]
    expected = tuple(part.strip().casefold() for part in identity)
    values = {row: tuple(_value(page, row, field).casefold() for field in fields) for row in rows}
    keys = tuple(_MATCH_KEYS.get(field, "") for field in fields)

    def agrees(row: str, *, allow_blank: bool) -> bool:
        return all(
            (allow_blank and not v) or _same(v, e, k)
            for v, e, k in zip(values[row], expected, keys, strict=True)
        )

    exact = [row for row in rows if agrees(row, allow_blank=False)]
    if exact:
        return exact[0] if len(exact) == 1 else None
    partial = [row for row in rows if any(values[row]) and agrees(row, allow_blank=True)]
    if partial:
        return partial[0] if len(partial) == 1 else None
    blank = [row for row in rows if not any(values[row])]
    return blank[0] if len(blank) == 1 else None


def _anchor_rows(
    page: Any, rows: list[str], value: str, field: str, *, exclude: frozenset[str] | set[str] = frozenset()
) -> list[str]:
    """Unclaimed rows whose ``field`` (the school, the employer) already holds ``value``."""
    key = _MATCH_KEYS.get(field, "")
    wanted = value.strip().casefold()
    return [
        row for row in rows
        if row not in exclude and _same(_value(page, row, field).casefold(), wanted, key)
    ]


def _section_present(page: Any, heading: str, anchor: str) -> bool:
    """Whether this tenant's step asks for the section at all (rows or an Add button)."""
    if _rows(page, anchor):
        return True
    try:
        index = page.evaluate(_ADD_BUTTON_JS, [heading, False])
    except Exception:  # noqa: BLE001 - unknown is treated as present, so rows get flagged
        return True
    return isinstance(index, int) and index >= 0


#: Playwright call-log lines that say why an action could not happen; the message's
#: first line is only "Timeout 5000ms exceeded."
_BLOCKER = re.compile(
    r"intercepts pointer events|not visible|not enabled|not stable|outside of the viewport"
    r"|detached|not attached", re.I,
)


def _reason(exc: BaseException) -> str:
    """A one-line reason: the exception's first line plus the call-log line that says what
    blocked the action (for a click, the element that "intercepts pointer events")."""
    lines = [line.strip(" -\t") for line in str(exc).strip().splitlines() if line.strip()]
    if not lines:
        return type(exc).__name__
    blocker = next((line for line in reversed(lines[1:]) if _BLOCKER.search(line)), "")
    text = lines[0][:160] + (f"; {blocker[:200]}" if blocker else "")
    return f"{type(exc).__name__}: {text}"


def _press_add(page: Any, heading: str) -> bool:
    """Mark and press the section's Add button; False when there is none."""
    try:
        index = page.evaluate(_ADD_BUTTON_JS, [heading, True])
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(index, int) or index < 0:
        return False
    button = page.locator("[data-rt-add]").first
    try:
        button.scroll_into_view_if_needed(timeout=2000)
    except Exception:  # noqa: BLE001 - the click reports what is really wrong
        pass
    clicks.safe_click(button, purpose="select", timeout=5000)
    return True


def _add_row(
    page: Any,
    heading: str,
    anchor: str | tuple[str, ...],
    *,
    dismiss: Callable[[Any], Any] | None = None,
) -> str | None:
    """Press the section's Add button and return the one new row's prefix.

    An earlier pass (the Skills prompt, 2026-09 F5) can leave a popup open whose
    full-viewport dismiss layer swallows the click; ``dismiss`` (`workday_flow.
    close_stray_popups`) closes it and the press is tried once more. A press that still
    fails raises `AddRowError` with Playwright's reason, not a bare TimeoutError.
    """
    anchors = (anchor,) if isinstance(anchor, str) else anchor

    def all_rows() -> list[str]:
        return list(dict.fromkeys(row for name in anchors for row in _rows(page, name)))

    before = set(all_rows())
    try:
        pressed = _press_add(page, heading)
    except Exception as first:  # noqa: BLE001
        if dismiss is None:
            raise AddRowError(f"Add button not clickable ({_reason(first)})") from first
        dismiss(page)
        try:
            pressed = _press_add(page, heading)
        except Exception as second:  # noqa: BLE001
            raise AddRowError(f"Add button not clickable ({_reason(second)})") from second
    if not pressed:
        return None
    for _ in range(12):
        page.wait_for_timeout(250)
        added = [row for row in all_rows() if row not in before]
        if len(added) == 1:
            return added[0]
    # A slow tenant can render the row after the wait: one late look, so the next pass
    # does not find two blank rows, call that ambiguous, and add a third.
    page.wait_for_timeout(1500)
    added = [row for row in all_rows() if row not in before]
    return added[0] if len(added) == 1 else None


def _recover_row(
    page: Any,
    anchor: str | tuple[str, ...],
    claimed: set[str],
    press_again: Callable[[], str | None],
    *,
    dismiss: Callable[[Any], Any] | None = None,
) -> str | None:
    """A row for an entry after an Add press that showed no single new row.

    A slow tenant renders the row after `_add_row` stops looking, and a double-registered
    press renders two: either way an unclaimed blank row is now there to use. When none
    is, the press did not land; stray popups are closed and Add is pressed once more.
    """
    anchors = (anchor,) if isinstance(anchor, str) else anchor

    def blank_rows() -> list[str]:
        rows = dict.fromkeys(row for name in anchors for row in _rows(page, name))
        return [row for row in rows
                if row not in claimed and not any(_value(page, row, name) for name in anchors)]

    found = blank_rows()
    if found:
        return found[0]
    if dismiss is not None:
        dismiss(page)
    row = press_again()
    if row is not None:
        return row
    found = blank_rows()
    return found[0] if found else None


def _school_field(page: Any, row: str | None = None) -> str:
    """This tenant's school control name, for one row or for the page."""
    for name in _SCHOOL_FIELDS:
        if row is not None:
            if _ctl(page, row, name).count() == 1:
                return name
        elif _rows(page, name):
            return name
    return _EDU["school"]


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
    if _attempt(lambda: _fill_date(page, prefix, field, value, with_month=with_month)):
        return True
    try:
        focused = bool(page.evaluate("() => document.hasFocus()"))
    except Exception:  # noqa: BLE001
        focused = None
    with contextlib.suppress(Exception):
        page.bring_to_front()
    ok = _attempt(lambda: _fill_date(page, prefix, field, value, with_month=with_month))
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
        _ctl(page, prefix, field).count() == 0
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


def _attempt(action: Callable[[], bool]) -> bool:
    """One row field: an exception is that field's failure, not the whole row's."""
    try:
        return bool(action())
    except Exception:  # noqa: BLE001 - reported per field for review
        return False


def _tick(page: Any, prefix: str, field: str) -> bool:
    box = _ctl(page, prefix, field)
    if box.count() == 1 and not box.first.is_checked():
        try:
            box.first.check(timeout=2000)
        except Exception:  # noqa: BLE001 - styled checkbox: its label takes the click
            clicks.safe_click(page.locator(f"label[for='{prefix}{field}']").first, purpose="select", timeout=3000)
    return box.count() == 1 and box.first.is_checked()


def _tick_current(page: Any, prefix: str) -> bool:
    return _tick(page, prefix, _WORK["current"])


def _choose(page: Any, prefix: str, field: str, value: str, *, key: str, select: Callable[..., bool] | None) -> bool:
    """A listbox button or a prompt; an existing answer is kept (ok only if it means ``value``)."""
    current = _value(page, prefix, field)
    if current:
        return current.casefold() == value.casefold() or bool(field_matcher.closest_option([current], value, key=key))
    control = _ctl(page, prefix, field)
    if control.count() == 1 and control.first.get_attribute("aria-haspopup") == "listbox":
        return bool(select and select(page, f"[id='{prefix}{field}']", value, key=key))
    return _text_or_prompt(page, prefix, field, value, key=key)


def _fill_language(page: Any, row: str, entry: Any, select: Callable[..., bool] | None) -> dict[str, bool]:
    """Language, the fluent checkbox, and one level per proficiency control of one row.

    Levels are matched by the control's label ("Reading", "Speaking", ...); a lone
    unlabelled level control takes the "Overall" level. A level the profile does not give
    is a gap for the applicant, not a guess.
    """
    from resume_tailor.apply.profile import LANGUAGE_CATEGORIES  # noqa: PLC0415

    results = {"Language": _attempt(lambda: _choose(page, row, _LANGUAGE, entry.language, key="language", select=select))}
    try:
        controls = page.evaluate(_ROW_CONTROLS_JS, row) or []
    except Exception:  # noqa: BLE001
        controls = []
    for control in controls:
        field = str(control["id"])[len(row):]
        if control.get("checkbox"):
            if re.search(r"fluent|native", str(control.get("label") or ""), re.I) and entry.fluent:
                results["Fluent"] = _attempt(lambda f=field: _tick(page, row, f))
            continue
        if not control.get("listbox") or field == _LANGUAGE:
            continue
        label = str(control.get("label") or "")
        category = next((name for name in LANGUAGE_CATEGORIES if name.casefold() in label.casefold()), "Overall")
        level = entry.levels.get(category, "")
        if _value(page, row, field):
            continue
        name = label or category
        results[name] = bool(level) and _attempt(
            lambda f=field, v=level: bool(select and select(page, f"[id='{row}{f}']", v, key="language_level")),
        )
    return results


def _reuse_or_guard(
    page: Any, rows: list[str], anchors: list[str], field: str, claimed: set[str]
) -> tuple[str | None, bool]:
    """When no row matches an entry's full identity: (row to reuse, add is blocked).

    ``anchors`` is this entry's school/employer followed by the remaining entries'. The
    single unclaimed row holding it is reused when no later entry shares the value. When
    the page already holds at least as many such rows as the entries still to place,
    adding one would duplicate an existing row, so the add is blocked for review.
    """
    wanted = anchors[0]
    if not wanted:
        return None, False
    matching = _anchor_rows(page, rows, wanted, field, exclude=claimed)
    key = _MATCH_KEYS.get(field, "")
    still_to_place = sum(1 for other in anchors if _same(other.strip().casefold(), wanted.strip().casefold(), key))
    if len(matching) == 1 and still_to_place == 1:
        return matching[0], False
    return None, len(matching) >= still_to_place


def fill(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None],
    *,
    select: Callable[..., bool] | None = None,
    dismiss: Callable[[Any], Any] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Populate prepared entries where an exact or blank row is observable.

    Returns (filled, needs_review): filled rows as ``{"label", "value"}`` records and the
    human labels of rows or fields left for the applicant. ``dismiss`` closes a popup an
    earlier pass left open (`workday_flow.close_stray_popups`); it runs before the rows
    and again when an Add press is blocked.
    """
    filled: list[dict[str, str]] = []
    review: list[str] = []
    if dismiss is not None:
        dismiss(page)
    #: Section heading -> why its Add button could not be pressed; later entries in the
    #: section are flagged with the same reason instead of waiting on the same failure.
    blocked_add: dict[str, str] = {}

    def add(heading: str, anchor: str | tuple[str, ...]) -> str | None:
        if heading in blocked_add:
            raise AddRowError(blocked_add[heading])
        try:
            row = _add_row(page, heading, anchor, dismiss=dismiss)
            if row is None:
                # AmerisourceBergen (2026-10): two employment rows were dropped when the
                # press showed no single new row. Recover instead of skipping the entry.
                row = _recover_row(page, anchor, claimed, lambda: _add_row(page, heading, anchor, dismiss=dismiss),
                                   dismiss=dismiss)
                progress(f"Workday: {heading} Add showed no new row; "
                         + (f"recovered row {row}" if row else "no row after a second press"))
            return row
        except AddRowError as exc:
            blocked_add[heading] = str(exc)
            raise

    def why(exc: BaseException) -> str:
        return str(exc) if isinstance(exc, AddRowError) else _reason(exc)

    # Some tenants (Capital Group, 2026-09) ask only for a resume on My Experience; a
    # section that is not on the page is not a gap to review.
    experience = packet.experience
    if experience and not _section_present(page, "Work Experience", _WORK["title"]):
        progress("This Workday step has no Work Experience section; skipping employment rows")
        experience = []
    if experience:
        progress("Inspecting Workday employment rows")
    claimed: set[str] = set()
    #: Filled rows and their dates, re-checked once every row is placed.
    placed: list[tuple[str, str, list[tuple[str, str, bool]]]] = []
    for index, exp in enumerate(experience):
        label = f"Work experience: {exp.title} at {exp.employer}"
        try:
            rows = _rows(page, _WORK["title"])
            row = _choose_row(page, rows, (exp.title, exp.employer),
                              (_WORK["title"], _WORK["company"]), exclude=claimed)
            if row is None:
                row, blocked = _reuse_or_guard(
                    page, rows, [e.employer for e in experience[index:]], _WORK["company"], claimed,
                )
                if blocked:
                    progress(f"Workday: {label} already has a row; not adding another")
                    review.append(f"{label} (possible duplicate row: check the list)")
                    continue
            if row is None:
                row = add("Work Experience", _WORK["title"])
            if row is None:
                review.append(label)
                continue
            claimed.add(row)
            results = {
                "Job Title": _attempt(lambda: _blank_fill(page, row, _WORK["title"], exp.title)),
                "Company": _attempt(lambda: _blank_fill(page, row, _WORK["company"], exp.employer)),
                "Location": _attempt(lambda: _blank_fill(page, row, _WORK["location"], exp.location)),
                "Role Description": _attempt(lambda: _blank_fill(page, row, _WORK["description"], exp.description)),
            }
            if exp.current:
                results["I currently work here"] = _attempt(lambda: _tick_current(page, row))
            results["From"] = _fill_date_retrying(page, row, "startDate", exp.start, with_month=True, note=progress)
            if not exp.current:
                results["To"] = _fill_date_retrying(page, row, "endDate", exp.end, with_month=True, note=progress)
            failed = [name for name, ok in results.items() if not ok]
            if not failed:
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": f"{exp.start} - {exp.end or 'present'}"})
                placed.append((row, label, [("startDate", exp.start, True)]
                               + ([] if exp.current else [("endDate", exp.end, True)])))
            else:
                review.append(f"{label} ({', '.join(failed)})")
        except Exception as exc:  # noqa: BLE001 - preserve the rest of the batch
            progress(f"Workday employment row needs review: {exp.title} at {exp.employer} ({why(exc)})")
            review.append(f"{label} ({why(exc)})")

    _recheck_dates(page, placed, filled, review, progress)

    education = packet.education
    school = _school_field(page)
    if education and not _section_present(page, "Education", school):
        progress("This Workday step has no Education section; skipping education rows")
        education = []
    if education:
        progress("Inspecting Workday education rows")
    claimed = set()
    for index, edu in enumerate(education):
        label = f"Education: {edu.school}"
        try:
            rows = _rows(page, school)
            row = _choose_row(page, rows, (edu.school, edu.major), (school, _EDU["major"]), exclude=claimed)
            reused_by_school = False
            if row is None:
                # Continue / Reopen / error recovery re-run this step: the row this fill
                # added earlier may now carry a Field of Study the applicant picked or
                # fixed. Its school still identifies it; adding a row would duplicate it.
                row, blocked = _reuse_or_guard(
                    page, rows, [e.school for e in education[index:]], school, claimed,
                )
                reused_by_school = row is not None
                if blocked:
                    progress(f"Workday: {label} already has a row; not adding another")
                    review.append(f"{label} (possible duplicate row: check the list)")
                    continue
            if row is None:
                row = add("Education", _SCHOOL_FIELDS)
            if row is None:
                progress(f"Workday: no education row available for {edu.school}")
                review.append(label)
                continue
            claimed.add(row)
            school = _school_field(page, row)
            current_major = _value(page, row, _EDU["major"])
            kept_major = current_major if reused_by_school or _same(
                current_major.casefold(), edu.major.strip().casefold(), "major"
            ) else ""
            # Each field on its own: a school search that fails (Upbound, 2026-09) must
            # not leave the major, years, and degree unfilled.
            results = {
                "School": _attempt(lambda: _text_or_prompt(page, row, school, edu.school, key="school")),
                # A Field of Study already there that matches (or, on a row found by its
                # school, any one: the applicant's reviewed answer) is kept, not flagged
                # again on every Continue.
                "Field of Study": bool(kept_major) or _attempt(
                    lambda: _text_or_prompt(page, row, _EDU["major"], edu.major, key="major")
                ),
                # Most tenants do not ask for a GPA; an absent control is not a gap.
                "GPA": _attempt(lambda: _ctl(page, row, _EDU["gpa"]).count() == 0
                                or _blank_fill(page, row, _EDU["gpa"], edu.gpa)),
                # Years attended are optional per tenant (F5 asks none): absent is not a gap.
                "From": _attempt(lambda: _date_absent(page, row, "firstYearAttended")
                                 or _fill_date_retrying(page, row, "firstYearAttended", edu.start,
                                                         with_month=False, note=progress)),
                "To": _attempt(lambda: _date_absent(page, row, "lastYearAttended")
                               or _fill_date_retrying(page, row, "lastYearAttended", edu.end,
                                                       with_month=False, note=progress)),
            }
            degree = edu.degree_name or edu.degree_level or edu.degree
            if degree and not _value(page, row, _EDU["degree"]):
                # Most specific first: "Bachelor of Science in X" -> "Bachelor of Science" -> "Bachelors".
                candidates = [edu.degree_name, re.sub(r"\s+in\s+.*$", "", edu.degree_name or ""),
                              edu.degree_level, edu.degree]
                chosen = False
                for candidate in dict.fromkeys(c for c in candidates if c):
                    if select and _attempt(lambda c=candidate: select(page, f"[id='{row}{_EDU['degree']}']", c, key="degree_level")):
                        chosen = True
                        break
                results["Degree"] = chosen
            failed = [name for name, ok in results.items() if not ok]
            if not failed:
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": degree})
            else:
                progress(f"Workday: {label} needs review ({', '.join(failed)})")
                review.append(f"{label} ({', '.join(failed)})")
        except Exception as exc:  # noqa: BLE001
            progress(f"Workday education row needs review: {edu.school} ({why(exc)})")
            review.append(f"{label} ({why(exc)})")

    languages = getattr(packet, "languages", [])
    if languages and not _section_present(page, "Languages", _LANGUAGE):
        languages = []
    if languages:
        progress("Inspecting Workday language rows")
    for entry in languages:
        label = f"Language: {entry.language}"
        try:
            row = _choose_row(page, _rows(page, _LANGUAGE), (entry.language,), (_LANGUAGE,))
            if row is None:
                row = add("Languages", _LANGUAGE)
            if row is None:
                progress(f"Workday: no language row available for {entry.language}")
                review.append(label)
                continue
            results = _fill_language(page, row, entry, select)
            failed = [name for name, ok in results.items() if not ok]
            if not failed:
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": entry.language})
            else:
                progress(f"Workday: {label} needs review ({', '.join(failed)})")
                review.append(f"{label} ({', '.join(failed)})")
        except Exception as exc:  # noqa: BLE001
            progress(f"Workday language row needs review: {entry.language} ({why(exc)})")
            review.append(f"{label} ({why(exc)})")
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
                await clicks.async_safe_click(display, purpose="select", timeout=3000)
                await page.keyboard.type(year, delay=40)
                await page.keyboard.press("Tab")
            if str(await year_input.input_value() or "").strip() == year:
                filled.append({"label": label, "value": year})
            else:
                review.append(label)
    return filled, review
