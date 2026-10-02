"""SmartRecruiters location and typeahead fields: splitting, matching and picking a place."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher

from . import smartrecruiters_page


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
        if (
            key in smartrecruiters_page._STATE_CODES
            or part.upper() in smartrecruiters_page._STATE_CODES.values()
        ):
            state = part
            country = country or "United States"
        elif key in smartrecruiters_page._US:
            country = "United States"
        else:
            country = part
    return city, state, country

def _state_code(state: str) -> str:
    key = field_matcher.normalize(state)
    if key in smartrecruiters_page._STATE_CODES:
        return smartrecruiters_page._STATE_CODES[key]
    return (
        state.strip().upper()
        if state.strip().upper() in smartrecruiters_page._STATE_CODES.values()
        else ""
    )

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
    usa = field_matcher.normalize(country) in smartrecruiters_page._US if country else bool(code)
    found = []
    for value, text in options:
        if not value or value in {
            smartrecruiters_page._MANUAL_LOCATION,
            smartrecruiters_page._CUSTOM_OPTION,
        }:
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
        if value not in {
            smartrecruiters_page._CUSTOM_OPTION,
            smartrecruiters_page._MANUAL_LOCATION,
        } and smartrecruiters_page._same(value or text, wanted):
            return value
    for value, text in options:
        if value == smartrecruiters_page._CUSTOM_OPTION and smartrecruiters_page._same(
            text, wanted
        ):
            return value
    return None

def location_matches(committed: Any, city: str, state: str = "", country: str = "") -> bool:
    """Whether a committed location object names ``city`` (and ``state``/``country``)."""
    if not isinstance(committed, dict):
        return False
    if not smartrecruiters_page._same(str(committed.get("city") or ""), city):
        return False
    if state and not (
        smartrecruiters_page._same(str(committed.get("region") or ""), state)
        or str(committed.get("stateCode") or "").upper() == _state_code(state)
    ):
        return False
    if country:
        wanted = field_matcher.normalize(country)
        if wanted in smartrecruiters_page._US:
            wanted = "united states"
        have = field_matcher.normalize(str(committed.get("country") or ""))
        if have and have != wanted:
            return False
    return True

def _options(host: Any, *, want_results: bool) -> list[tuple[str, str]]:
    """The typeahead's options once they settle; with ``want_results``, wait for a real
    result (not just the typed-text or manual rows)."""
    deadline = time.monotonic() + smartrecruiters_page._OPTIONS_WAIT_S
    options: list[tuple[str, str]] = []
    while True:
        try:
            options = [
                (str(v), str(t)) for v, t in host.evaluate(smartrecruiters_page._OPTIONS_JS) or []
            ]
        except Exception:  # noqa: BLE001
            options = []
        real = [
            item
            for item in options
            if item[0]
            not in {smartrecruiters_page._CUSTOM_OPTION, smartrecruiters_page._MANUAL_LOCATION}
        ]
        if time.monotonic() >= deadline:
            return options
        if real if want_results else options:
            # The search is debounced: an earlier keystroke's results can be replaced
            # once more, so the list is read again after it has had time to settle.
            host.page.wait_for_timeout(500)
            try:
                return [
                    (str(v), str(t))
                    for v, t in host.evaluate(smartrecruiters_page._OPTIONS_JS) or []
                ]
            except Exception:  # noqa: BLE001
                return options
        host.page.wait_for_timeout(200)

def _committed(host: Any) -> Any:
    try:
        return host.evaluate(smartrecruiters_page._HOST_VALUE_JS)
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
        point = control.evaluate(smartrecruiters_page._POINT_JS)
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
    if not wanted or not smartrecruiters_page._present(host):
        return False
    def choose(options: list[tuple[str, str]]) -> str | None:
        return pick_text(options, wanted)

    if not _type_and_pick(host, wanted, choose, want_results=False):
        return False
    committed = _committed(host)
    return isinstance(committed, str) and smartrecruiters_page._same(committed, wanted, "school")

def _location_typeahead(host: Any, city: str, state: str, country: str) -> bool:
    if not city or not smartrecruiters_page._present(host):
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
    host = page.locator(smartrecruiters_page._LOCATION).first
    if not smartrecruiters_page._present(page.locator(smartrecruiters_page._LOCATION)):
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
