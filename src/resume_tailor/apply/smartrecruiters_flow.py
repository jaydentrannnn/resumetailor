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

The second step (``/screening``, captured live 2026-09-27 on Resultant) holds the
screening questions, each in a ``[data-test=question-container]``: Yes/No
``spl-radio-group``s whose ``spl-radio`` options have no native input, ``spl-autocomplete``
selects whose options load on ArrowDown, ``spl-input`` text boxes, and declaration
``spl-checkbox``es. The question text is slotted into the control's shadow ``<label>``
(``[slot=label-content]``), so the generic pass reads every label as "*". `fill_screening`
answers them through `questions` (profile facts and what follows from them), then
remembered answers (`answer_memory`); a declaration is never ticked for the applicant, and
a question with no known answer is left for review.

Like `workday_repeaters`: an entry already listed is reused, never edited or deleted; an
answer already present is kept; anything not verified on the page is reported for review.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from resume_tailor.apply import answer_memory, clicks, field_matcher, form_guards, questions
from resume_tailor.apply.packet import Packet, PacketEducation, PacketExperience

#: Entries added per section at most; the packet is already bounded by the resume.
MAX_ENTRIES = 10
#: How long a typeahead may take to show its options (the location search is remote).
_OPTIONS_WAIT_S = 5.0
#: The location typeahead's "Cannot find your city? ... fill in manually" row.
_MANUAL_LOCATION = "goToManualLocationMode"
#: The option that commits the typed text as-is (title, company, institution).
_CUSTOM_OPTION = "#spl-custom-option"

_LOCATION = "div[data-test=personal-info-location] spl-autocomplete"
#: Selectors `filler.js` reports for controls this flow owns: both dropzones' shared
#: ``#file-input`` and the message box. Its records for them are dropped in `fill`.
HANDLED_SELECTORS = frozenset({"#file-input", "#hiring-manager-message-input"})
_RESUME = "div[data-test=resume-upload-container]"
_MESSAGE = "oc-textarea[data-test=hiring-manager-message-text] textarea"

_STATE_CODES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC",
}
_US = {"us", "usa", "united states", "united states of america"}

#: ``[value, text]`` of every option a typeahead host shows (the menu renders inside the
#: host's own shadow root, under ``spl-dropdown``; light DOM is searched too).
_OPTIONS_JS = r"""(host) => {
  const out = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.tagName === 'SPL-SELECT-OPTION') {
        const label = (el.textContent || '').replace(/\s+/g, ' ').trim();
        out.push([el.getAttribute('value') || '', label]);
      }
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(host);
  if (host.shadowRoot) walk(host.shadowRoot);
  return out;
}"""

#: A typeahead host's committed value: a string (title/company/institution), a location
#: object, or null/"" when nothing is committed.
_HOST_VALUE_JS = "(host) => host.value === undefined ? null : host.value"

#: Saved entries of a section, as their visible text parts. The title/institution line
#: carries the date span ("AI Intern 2026 - 2026"), which is cut off.
_ENTRIES_JS = r"""([section, kind]) => {
  const root = document.querySelector(`div[data-test="${section}"]`);
  if (!root) return null;
  const text = (e) => e ? (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim() : '';
  const tag = kind === 'experience' ? 'oc-experience-entry' : 'oc-education-entry';
  const heading = kind === 'experience'
    ? '[data-test=experience-entry-title]' : '[data-test=education-entry-institution]';
  const saved = [...root.querySelectorAll(tag)]
    .filter(e => !e.querySelector('[data-test$="-edit-form"]'));
  return saved.map(e => {
    const first = e.querySelector(heading);
    const date = text(e.querySelector(`[data-test=${kind}-entry-date]`));
    let head = text(first);
    if (date && head.endsWith(date)) head = head.slice(0, head.length - date.length).trim();
    return kind === 'experience'
      ? {title: head, company: text(e.querySelector('[data-test=experience-entry-company]'))}
      : {school: head, major: text(e.querySelector('[data-test=education-entry-major]')),
         degree: text(e.querySelector('[data-test=education-entry-degree]'))};
  });
}"""

#: The resume dropzone's listed files: ``li.c-spl-file-list-item`` rows in its shadow
#: root, each with a ``.c-spl-file-list-item-name``.
_DROPZONE_FILES_JS = r"""(zone) => {
  const names = [];
  let listed = 0;
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.matches('.c-spl-file-list-item')) listed += 1;
      if (el.matches('.c-spl-file-list-item-name')) names.push((el.textContent || '').trim());
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(zone.shadowRoot || zone);
  return {names: names.filter(Boolean), listed};
}"""


#: The centre of ``el`` when a press there lands on ``el`` (``elementFromPoint`` followed
#: into open shadow roots, slotted nodes back through their slots); else null.
_POINT_JS = r"""(el) => {
  el.scrollIntoView({block: 'nearest'});
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  let hit = document.elementFromPoint(x, y);
  while (hit && hit.shadowRoot) {
    const inner = hit.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === hit) break;
    hit = inner;
  }
  for (let n = hit; n; n = n.assignedSlot || n.parentNode || n.host) if (n === el) return [x, y];
  return null;
}"""


def is_form(page: Any) -> bool:
    """Whether ``page`` shows the one-click application form."""
    return "/oneclick-ui/" in str(getattr(page, "url", "") or "")


def _present(locator: Any) -> bool:
    try:
        return locator.count() > 0
    except Exception:  # noqa: BLE001
        return False


def _same(value: str, wanted: str, key: str = "") -> bool:
    """Normalised equality, or (for a ``key`` like "school") the catalog's aliases."""
    a, b = field_matcher.normalize(value or ""), field_matcher.normalize(wanted or "")
    if a == b:
        return True
    if not (key and a and b):
        return False
    return bool(field_matcher.closest_option([value], wanted, key=key)
                or field_matcher.closest_option([wanted], value, key=key))


def month_year(value: str) -> str:
    """The pickers' typed format: "2026-06" -> "06/2026"; "" when the month is unknown."""
    match = re.fullmatch(r"\s*(\d{4})-(\d{1,2})(?:-\d{1,2})?\s*", value or "")
    if not match:
        return ""
    return f"{int(match.group(2)):02d}/{match.group(1)}"


def split_location(location: str, *, state: str = "", country: str = "") -> tuple[str, str, str]:
    """``(city, state, country)`` from "Glendale, California" / "Ho Chi Minh City, Vietnam".

    A trailing part that names a US state is the state (the country is then the US);
    anything else is the country.
    """
    parts = [part.strip() for part in (location or "").split(",") if part.strip()]
    if not parts:
        return "", state, country
    city, rest = parts[0], parts[1:]
    for part in rest:
        key = field_matcher.normalize(part)
        if key in _STATE_CODES or part.upper() in _STATE_CODES.values():
            state = part
            country = country or "United States"
        elif key in _US:
            country = "United States"
        else:
            country = part
    return city, state, country


def _state_code(state: str) -> str:
    key = field_matcher.normalize(state)
    if key in _STATE_CODES:
        return _STATE_CODES[key]
    return state.strip().upper() if state.strip().upper() in _STATE_CODES.values() else ""


def pick_location(
    options: list[tuple[str, str]], city: str, state: str = "", country: str = ""
) -> str | None:
    """The one option naming ``city`` (in ``state`` when known); None when unsure.

    Options read "Glendale, CA, US" with values "US_CA_CITY_glendale"; the "fill in
    manually" row is never picked, and two equally good cities are no answer.
    """
    if not city:
        return None
    code = _state_code(state) if state else ""
    usa = field_matcher.normalize(country) in _US if country else bool(code)
    found = []
    for value, text in options:
        if not value or value in {_MANUAL_LOCATION, _CUSTOM_OPTION}:
            continue
        parts = [part.strip() for part in text.split(",")]
        if field_matcher.normalize(parts[0]) != field_matcher.normalize(city):
            continue
        country_code = value.split("_", 1)[0].upper()
        if code:
            region = parts[1] if len(parts) > 2 else ""
            same_state = field_matcher.normalize(region) == field_matcher.normalize(state)
            if region.upper() != code and not same_state:
                continue
        if usa and country_code != "US":
            continue
        found.append(value)
    return found[0] if len(found) == 1 else None


def pick_text(options: list[tuple[str, str]], wanted: str) -> str | None:
    """A catalog option spelled exactly like ``wanted``, else the typed-text option."""
    for value, text in options:
        if value not in {_CUSTOM_OPTION, _MANUAL_LOCATION} and _same(value or text, wanted):
            return value
    for value, text in options:
        if value == _CUSTOM_OPTION and _same(text, wanted):
            return value
    return None


def location_matches(committed: Any, city: str, state: str = "", country: str = "") -> bool:
    """Whether a committed location object names ``city`` (and ``state``/``country``)."""
    if not isinstance(committed, dict):
        return False
    if not _same(str(committed.get("city") or ""), city):
        return False
    if state and not (
        _same(str(committed.get("region") or ""), state)
        or str(committed.get("stateCode") or "").upper() == _state_code(state)
    ):
        return False
    if country:
        wanted = field_matcher.normalize(country)
        if wanted in _US:
            wanted = "united states"
        have = field_matcher.normalize(str(committed.get("country") or ""))
        if have and have != wanted:
            return False
    return True


def _options(host: Any, *, want_results: bool) -> list[tuple[str, str]]:
    """The typeahead's options once they settle; with ``want_results``, wait for a real
    result (not just the typed-text or manual rows)."""
    deadline = time.monotonic() + _OPTIONS_WAIT_S
    options: list[tuple[str, str]] = []
    while True:
        try:
            options = [(str(v), str(t)) for v, t in host.evaluate(_OPTIONS_JS) or []]
        except Exception:  # noqa: BLE001
            options = []
        real = [item for item in options if item[0] not in {_CUSTOM_OPTION, _MANUAL_LOCATION}]
        if time.monotonic() >= deadline:
            return options
        if real if want_results else options:
            # The search is debounced: an earlier keystroke's results can be replaced
            # once more, so the list is read again after it has had time to settle.
            host.page.wait_for_timeout(500)
            try:
                return [(str(v), str(t)) for v, t in host.evaluate(_OPTIONS_JS) or []]
            except Exception:  # noqa: BLE001
                return options
        host.page.wait_for_timeout(200)


def _committed(host: Any) -> Any:
    try:
        return host.evaluate(_HOST_VALUE_JS)
    except Exception:  # noqa: BLE001
        return None


def _activate(control: Any) -> None:
    """Click ``control`` with a real mouse press at its centre, never a submit control.

    The applicant's tab runs in the background, where Edge throttles animation frames
    to about one a second (live 2026-09-27): Playwright's click waits ~2s per control
    for it to be "stable", minutes over a form. The menus ignore dispatched (untrusted)
    events, so the press is a real one, made only after ``elementFromPoint`` confirms
    it lands on ``control`` itself; otherwise the ordinary click (with its waits) runs.
    """
    if clicks.is_submit_like(control):
        raise clicks.SubmitRefused(
            "refused a click on a control that reads as submitting the application"
        )
    page = control.page
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        point = control.evaluate(_POINT_JS)
        if point:
            clicks.mouse_click(page, float(point[0]), float(point[1]), purpose="select")
            return
        page.wait_for_timeout(200)
    clicks.safe_click(control, purpose="select", timeout=8000)


def _clear_typeahead(host: Any) -> None:
    try:
        field = host.locator("input[role=combobox]").first
        field.fill("", timeout=2000)
        field.press("Escape", timeout=2000)
    except Exception:  # noqa: BLE001
        pass


def _type_and_pick(
    host: Any,
    query: str,
    choose: Callable[[list[tuple[str, str]]], str | None],
    *,
    want_results: bool,
) -> bool:
    """Type ``query`` into the typeahead and click the option ``choose`` names.

    Nothing is left typed when no option is chosen: the component would drop
    uncommitted text anyway, and a half-typed value reads as filled.
    """
    field = host.locator("input[role=combobox]").first
    try:
        field.fill("", timeout=3000)
        field.focus(timeout=3000)
        field.press_sequentially(query, delay=20, timeout=10000)
    except Exception:  # noqa: BLE001
        _clear_typeahead(host)
        return False
    value = choose(_options(host, want_results=want_results))
    if value is None:
        _clear_typeahead(host)
        return False
    literal = value.replace("\\", "\\\\").replace('"', '\\"')
    try:
        _activate(host.locator(f'spl-select-option[value="{literal}"]').first)
        host.page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        _clear_typeahead(host)
        return False
    return True


def _text_typeahead(host: Any, wanted: str) -> bool:
    """Commit ``wanted`` in a title/company/institution typeahead and verify it."""
    if not wanted or not _present(host):
        return False
    def choose(options: list[tuple[str, str]]) -> str | None:
        return pick_text(options, wanted)

    if not _type_and_pick(host, wanted, choose, want_results=False):
        return False
    committed = _committed(host)
    return isinstance(committed, str) and _same(committed, wanted, "school")


def _location_typeahead(host: Any, city: str, state: str, country: str) -> bool:
    if not city or not _present(host):
        return False
    def choose(options: list[tuple[str, str]]) -> str | None:
        return pick_location(options, city, state, country)

    if not _type_and_pick(host, city, choose, want_results=True):
        return False
    if location_matches(_committed(host), city, state, country):
        return True
    _clear_typeahead(host)
    return False


def fill_city(page: Any, fields: dict[str, str]) -> tuple[list[dict[str, str]], list[str]]:
    """Commit the profile's city in the personal-information location typeahead."""
    host = page.locator(_LOCATION).first
    if not _present(page.locator(_LOCATION)):
        return [], []  # this tenant does not ask for a city
    city, state = fields.get("city", ""), fields.get("state", "")
    country = fields.get("country", "")
    committed = _committed(host)
    if isinstance(committed, dict) and committed.get("city"):
        # An applicant's (or an earlier run's) choice is kept as it is.
        text = str(committed.get("displayString") or committed.get("text") or committed.get("city"))
        return [{"label": "City", "value": text, "state": "preserved"}], []
    if not city:
        return [], ["City: no city in the applicant profile"]
    if _location_typeahead(host, city, state, country):
        committed = _committed(host)
        return [{"label": "City", "value": str(committed.get("displayString") or city)}], []
    where = ", ".join(part for part in (city, state) if part)
    return [], [f"City: no confident match for {where}"]


def _entries(page: Any, kind: str) -> list[dict[str, str]] | None:
    try:
        found = page.evaluate(_ENTRIES_JS, [kind, kind])
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
    typed = month_year(value)
    picker = editor.locator(f"oc-datepicker[data-test={test_id}] input.flatpickr-input").first
    if not typed or not _present(editor.locator(f"oc-datepicker[data-test={test_id}]")):
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
            _activate(box)
        return box.is_checked()
    except Exception:  # noqa: BLE001
        return False


def _press(page: Any, selector: str) -> bool:
    try:
        _activate(page.locator(selector).first)
        return True
    except Exception:  # noqa: BLE001
        return False


def _wait_closed(page: Any, editor: Any, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _present(editor):
            return True
        page.wait_for_timeout(200)
    return not _present(editor)


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
    if not _text_typeahead(title, exp.title):
        review.append(f"{label}: title")
    company = editor.locator("spl-autocomplete[data-test=company-autocomplete]").first
    if exp.employer and not _text_typeahead(company, exp.employer):
        review.append(f"{label}: company")
    if exp.location:
        city, state, country = split_location(exp.location)
        office = editor.locator("[data-test=experience-form-location] spl-autocomplete").first
        if not _location_typeahead(office, city, state, country):
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
    if not _text_typeahead(school, edu.school):
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
        _same(item.get("title", ""), exp.title) and _same(item.get("company", ""), exp.employer)
        for item in entries
    )


def _listed_education(entries: list[dict[str, str]], edu: PacketEducation) -> bool:
    """Same school, and the same major or degree when the entry names one."""
    for item in entries:
        if not _same(item.get("school", ""), edu.school, "school"):
            continue
        major, degree = item.get("major", ""), item.get("degree", "")
        if (not major or _same(major, edu.major, "major")) and (
            not degree or _same(degree, _degree(edu)) or _same(degree, edu.degree)
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
    if _present(_editor(page, kind)):
        # Someone's entry is open mid-edit: pressing Add or Save could lose it.
        return filled, [f"{heading}: an entry is open for editing; finish it, then Continue fill"]
    for index, item in enumerate(items[:MAX_ENTRIES], start=1):
        name = describe(item)
        label = f"{heading} {index} ({name})"
        if listed(entries, item):
            filled.append({"label": label, "value": name, "state": "preserved"})
            continue
        if deadline is not None and time.monotonic() >= deadline:
            review.extend(f"{heading} {later} ({describe(rest)})" for later, rest in
                          enumerate(items[index - 1:MAX_ENTRIES], start=index))
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
                          enumerate(items[index:MAX_ENTRIES], start=index + 1))
            break
        entries = _entries(page, kind) or []
        if listed(entries, item):
            filled.append({"label": label, "value": name} if complete else
                          {"label": label, "value": name, "state": "partial"})
        else:
            review.append(f"{label}: saved but not found in the list")
    if len(items) > MAX_ENTRIES:
        review.append(f"{heading}: only the first {MAX_ENTRIES} entries were added")
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


def _resume_state(zone: Any) -> dict[str, Any]:
    try:
        state = zone.evaluate(_DROPZONE_FILES_JS)
    except Exception:  # noqa: BLE001
        return {"names": [], "listed": 0}
    return state if isinstance(state, dict) else {"names": [], "listed": 0}


def fill_resume(page: Any, resume_path: str | None) -> tuple[list[dict[str, str]], list[str]]:
    """Set the resume on the Resume section's dropzone and see its name listed.

    The "Easy Apply" dropzone at the top of the form also takes a resume, but parses it
    to prefill the form; it is never used.
    """
    zone = page.locator(f"{_RESUME} spl-dropzone").first
    if not _present(page.locator(f"{_RESUME} spl-dropzone")):
        return [], []
    state = _resume_state(zone)
    if state.get("listed"):
        name = (state.get("names") or [""])[0] or "a file"
        return [{"label": "Resume", "value": name, "state": "preserved"}], []
    if not resume_path or not Path(resume_path).is_file():
        return [], ["Resume: no prepared resume file to attach"]
    name = Path(resume_path).name
    try:
        page.locator(f"{_RESUME} input[type=file]").first.set_input_files(resume_path, timeout=5000)
    except Exception:  # noqa: BLE001
        return [], ["Resume: the file could not be set on the upload"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        state = _resume_state(zone)
        if name in state.get("names", []):
            return [{"label": "Resume", "value": name}], []
        page.wait_for_timeout(250)
    return [], [f"Resume: {name} was set but is not listed on the form"]


def fill_message(page: Any, cover_letter: str) -> tuple[list[dict[str, str]], list[str]]:
    """Put the cover letter in "Message to the Hiring Team" when the box is empty."""
    boxes = page.locator(_MESSAGE)
    if not _present(boxes) or not cover_letter.strip():
        return [], []
    box = boxes.first
    try:
        current = box.input_value()
    except Exception:  # noqa: BLE001
        return [], ["Message to the Hiring Team"]
    if current.strip():
        kept = {"label": "Message to the Hiring Team", "value": current[:60], "state": "preserved"}
        return [kept], []
    review: list[str] = []
    if _set_text(box, cover_letter.strip(), label="Message to the Hiring Team", review=review):
        with contextlib.suppress(Exception):
            box.evaluate("e => e.blur()")
        return [{"label": "Message to the Hiring Team", "value": "cover letter"}], review
    return [], [*review, "Message to the Hiring Team"]


#: Every screening question on the page, one record per control: ``kind`` (radio, select,
#: text, checkbox), the control's ``id``, the ``question``, whether it is ``required``,
#: the ``value`` already given ("" when none) and, for radios, the ``options``. The
#: containers sit inside open shadow roots, so they are searched for deeply.
_QUESTIONS_JS = r"""() => {
  const deep = (root, sel, out = []) => {
    out.push(...root.querySelectorAll(sel));
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) deep(el.shadowRoot, sel, out);
    return out;
  };
  const text = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const labelOf = (host) => {
    const slotted = host.querySelector(':scope > [slot=label-content]');
    if (slotted) return text(slotted.textContent);
    return text(host.getAttribute('aria-label')).replace(/^Select\s+/i, '');
  };
  const HOSTS = 'spl-radio-group, spl-autocomplete, spl-input, spl-textarea, spl-checkbox';
  // Up one level through shadow boundaries; a control inside another (the text box
  // inside a select, the info checkbox inside its question field) belongs to that one.
  const up = (n) => n.parentElement || (n.getRootNode() && n.getRootNode().host) || null;
  const nested = (el, box) => {
    for (let n = up(el); n && n !== box; n = up(n)) if (n.matches && n.matches(HOSTS)) return true;
    return false;
  };
  const out = [];
  for (const box of deep(document, '[data-test=question-container]')) {
    for (const host of deep(box, HOSTS)) {
      if (!host.id || nested(host, box)) continue;
      const required = host.hasAttribute('required');
      const question = labelOf(host);
      if (host.localName === 'spl-radio-group') {
        const options = [...host.querySelectorAll('spl-radio')].map((r) => ({
          label: text(r.getAttribute('label')), value: r.getAttribute('value') || '',
          checked: r.getAttribute('aria-checked') === 'true',
        }));
        const picked = options.find((o) => o.checked);
        out.push({kind: 'radio', id: host.id, question, required, options,
                  value: picked ? picked.label : ''});
      } else if (host.localName === 'spl-autocomplete') {
        const v = host.value;
        const shown = v && typeof v === 'object'
          ? text(v.label || v.text || v.name || v.value || JSON.stringify(v)) : text(v);
        out.push({kind: 'select', id: host.id, question, required, value: shown});
      } else if (host.localName === 'spl-checkbox') {
        const input = host.shadowRoot && host.shadowRoot.querySelector('input[type=checkbox]');
        out.push({kind: 'checkbox', id: host.id, required,
                  question: question || text(host.textContent),
                  value: input && input.checked ? 'checked' : ''});
      } else {
        const field = host.shadowRoot && host.shadowRoot.querySelector('input, textarea');
        out.push({kind: 'text', id: host.id, question, required,
                  value: text(field ? field.value : host.value)});
      }
    }
  }
  // The privacy-notice consent below the questions: the applicant's to give.
  for (const consent of deep(document, 'spl-checkbox[data-test=consent-box]')) {
    const input = consent.shadowRoot && consent.shadowRoot.querySelector('input[type=checkbox]');
    out.push({kind: 'checkbox', id: consent.id, question: 'Consent to the privacy notice',
              required: consent.hasAttribute('required'),
              value: input && input.checked ? 'checked' : ''});
  }
  return out;
}"""

def _choose_radio(page: Any, group_id: str, label: str) -> bool:
    literal = label.replace("\\", "\\\\").replace('"', '\\"')
    radio = page.locator(f'spl-radio-group[id="{group_id}"] spl-radio[label="{literal}"]').first
    try:
        _activate(radio)
        page.wait_for_timeout(200)
        return radio.get_attribute("aria-checked") == "true"
    except Exception:  # noqa: BLE001
        return False


def _choose_select(
    host: Any, question: questions.Question, key: str, answers: list[str],
) -> str | None:
    """Open the select and click the option that says one of ``answers``; the text committed.

    ArrowDown lists the options; a long list (majors, schools) shows only its first ones,
    so when none of them says the answer, the answer's search terms are typed to filter it.
    """
    field = host.locator("input[role=combobox]").first
    try:
        field.focus(timeout=3000)
        field.press("ArrowDown", timeout=3000)
    except Exception:  # noqa: BLE001
        return None

    def pick(options: list[tuple[str, str]]) -> tuple[str, str] | None:
        real = [item for item in options if item[0] not in {_CUSTOM_OPTION, _MANUAL_LOCATION}]
        offered = replace(question, options=tuple(text for _value, text in real))
        chosen = questions.choose(offered, key, answers)
        value = next((v for v, t in real if t == chosen), None) if chosen else None
        return (value, chosen) if value is not None and chosen else None

    hit = pick(_options(host, want_results=True))
    if hit is None:
        for term in field_matcher.search_terms(key, answers[0]) if answers else []:
            found: list[tuple[str, str]] = []

            def choose(options: list[tuple[str, str]], found: list = found) -> str | None:
                picked = pick(options)
                if picked:
                    found.append(picked)
                return picked[0] if picked else None

            if _type_and_pick(host, term, choose, want_results=True):
                return found[0][1] if _committed(host) not in (None, "", [], {}) else None
        _clear_typeahead(host)
        return None
    literal = hit[0].replace("\\", "\\\\").replace('"', '\\"')
    try:
        _activate(host.locator(f'spl-select-option[value="{literal}"]').first)
        host.page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        _clear_typeahead(host)
        return None
    return hit[1] if _committed(host) not in (None, "", [], {}) else None


def _short(question: str) -> str:
    return question if len(question) <= 90 else question[:87].rstrip() + "..."


def fill_screening(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None] = lambda _msg: None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Answer the screening step's questions from profile facts and remembered answers.

    What each question asks and its answer come from `questions` (the decision layer every
    fill path shares). Declarations and acknowledgements are never ticked for the
    applicant; a question no profile fact or saved answer covers is left for review, never
    guessed.
    """
    try:
        found = page.evaluate(_QUESTIONS_JS) or []
    except Exception:  # noqa: BLE001
        return [], []
    facts = questions.facts_from_packet(packet)
    filled: list[dict[str, str]] = []
    review: list[str] = []
    for item in found:
        text = str(item.get("question") or item.get("id") or "question")
        label = _short(text)
        selector = f'[id="{item.get("id")}"]'
        if item.get("value"):
            filled.append({"label": label, "value": str(item["value"]), "state": "preserved"})
            continue
        kind = item.get("kind")
        if kind == "checkbox":
            if item.get("required"):
                review.append(f"{label}: read and tick it yourself")
            continue
        options = tuple(str(opt.get("label") or "") for opt in item.get("options") or [])
        question = questions.Question(
            text, kind={"radio": "choice", "select": "typeahead"}.get(str(kind), "text"),
            options=options,
        )
        match = questions.classify(question)
        key = match.key if match else ""
        answers = questions.answers(match, question, facts)
        if not answers and key not in field_matcher.EEO_KEYS:
            recalled = answer_memory.recall(
                text, company=packet.company, ats="smartrecruiters", canonical_key=key
            )
            if recalled is not None and not recalled.needs_review:
                answers = [recalled.answer]
        if not answers:
            if item.get("required") or key:
                review.append(f"{label}: no answer in the applicant profile")
            continue
        answer: str | None = None
        if kind == "radio":
            chosen = questions.choose(question, key, answers)
            if chosen is None:
                review.append(f"{label}: no option matches {answers[0]!r}")
                continue
            if _choose_radio(page, str(item["id"]), chosen):
                answer = chosen
        elif kind == "select":
            host = page.locator(f"spl-autocomplete{selector}").first
            answer = _choose_select(host, question, key, answers)
        elif kind == "text":
            control = page.locator(f"{selector} input, {selector} textarea").first
            if _set_text(control, answers[0], label=label, review=review):
                answer = answers[0]
                with contextlib.suppress(Exception):
                    control.evaluate("e => e.blur()")
        if answer is None:
            review.append(f"{label}: could not set {answers[0]!r}")
            continue
        progress(f"SmartRecruiters: answered {label[:60]} = {answer}")
        filled.append({"label": label, "value": answer})
    return filled, review


def screening_selectors(page: Any) -> set[str]:
    """Selectors the generic pass reports for the screening controls this flow owns."""
    try:
        questions = page.evaluate(_QUESTIONS_JS) or []
    except Exception:  # noqa: BLE001
        return set()
    return {f"#{item['id']}" for item in questions if item.get("id")}


def fill(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None],
    *,
    resume_path: str | None = None,
    deadline: float | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Fill every area this form step shows; ``(filled, needs_review)`` like Workday's.

    ``filled`` records are ``{"label", "value"}`` (plus ``"state"`` "preserved" for an
    answer that was already there, "partial" for a saved entry with a field left for
    review); ``needs_review`` holds human labels. Past ``deadline`` (``time.monotonic``)
    no further entry is added; the rest are listed for review.
    """
    filled: list[dict[str, str]] = []
    review: list[str] = []
    for step in (
        lambda: fill_city(page, packet.fields),
        lambda: fill_resume(page, resume_path),
        lambda: fill_message(page, packet.cover_letter),
        lambda: fill_experience(page, packet, progress, deadline=deadline),
        lambda: fill_education(page, packet, progress, deadline=deadline),
        lambda: fill_screening(page, packet, progress),
    ):
        done, left = step()
        filled.extend(done)
        review.extend(label for label in left if label not in review)
    return filled, review
