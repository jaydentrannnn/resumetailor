"""Workday repeater rows: reading rows, matching them to entries, adding and recovering a row."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher

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

def _attempt(action: Callable[[], bool]) -> bool:
    """One row field: an exception is that field's failure, not the whole row's."""
    try:
        return bool(action())
    except Exception:  # noqa: BLE001 - reported per field for review
        return False
