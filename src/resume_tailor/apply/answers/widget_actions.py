"""Carrying out a resolved field action on the page: comboboxes, radios, checkboxes, uploads."""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

from resume_tailor.apply.answers import questions, reference_data
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher
from resume_tailor.apply.forms.field_matcher import match_option
from resume_tailor.apply.forms.field_types import ObservedOption

from . import resolver_types

_log = logging.getLogger(__name__)


#: True for a file-upload control or anything inside one: clicking it opens the OS picker.
UPLOAD_WIDGET_JS = r"""(el) => el.matches('input[type="file"]') || !!el.closest(
  '[data-automation-id^="file" i], [data-automation-id*="-file" i], [data-automation-id*="file-" i], ' +
  '[data-automation-id*="upload" i], [data-automation-id*="attachment" i], ' +
  '[class*="dropzone" i], [class*="drop-zone" i], [class*="file-upload" i]')"""

def _is_upload_widget(locator: Any) -> bool:
    try:
        return locator.evaluate(UPLOAD_WIDGET_JS) is True
    except Exception:  # noqa: BLE001 - an unreadable control is not clicked blind either
        return True

def _option_match(options: list[str], target_value: str, *, key: str = "") -> str | None:
    """Choose one observed option; aliases never permit a partial-text match."""
    observed = [ObservedOption(option_id=str(index), label=label, value=label) for index, label in enumerate(options)]
    result = match_option(observed, target_value, key=key)
    return options[int(result.option_id)] if result.status == "matched" else None

#: The rows a menu renders its options as: ARIA options, React Select, Workday prompts,
#: Oracle JET, Oracle Recruiting's grid cells. A listbox with none of these lists its
#: options as plain ``li``.
_OPTION_ROWS = (
    "[role='option'], .select__option, [data-automation-id*='promptOption'], "
    ".oj-listbox-result, oj-option, .cx-select__list-item"
)
#: Open menus a trigger does not name: listboxes, React Select's menu (``select__menu``,
#: or emotion's ``css-…-menu``) and JET's drop. Not any class with "-menu" in it.
_MENUS = (
    "[role='listbox'], [class*='select__menu'], [class^='css-'][class*='-menu'], "
    "[class*=' css-'][class*='-menu'], .oj-listbox-drop, .cx-select__list"
)
#: Rows a menu shows in place of options: never chosen, and a loading one is waited out.
_LOADING_ROW = re.compile(r"^(?:loading|searching)\b", re.I)
_EMPTY_ROW = re.compile(r"^no (?:options|results|matches)\b", re.I)
_SEARCH_BOXES = (
    "input[data-automation-id='searchBox'], input[role='searchbox'], input[placeholder*='search' i]"
)


def _open_menus(page: Any) -> list[Any]:
    """Handles of the menus open now, so the one a click opens can be told apart."""
    with contextlib.suppress(Exception):
        return page.locator(_MENUS).filter(visible=True).element_handles()
    return []


def _owned_menu(page: Any, trigger: Any, opened_before: list[Any] | None = None) -> Any | None:
    """The trigger's menu: the one it names (``aria-controls``/``aria-owns``), else the
    listbox holding its ``aria-activedescendant``, else the one menu its click opened. None
    when that is unclear, so nothing is chosen from another field's menu."""
    menu_id = trigger.get_attribute("aria-controls") or trigger.get_attribute("aria-owns")
    if menu_id:
        menu = page.locator(f"[id='{menu_id}']")
        if menu.count() > 0:
            return menu.first
    active = trigger.get_attribute("aria-activedescendant")
    if active:
        holder = page.locator(f"[id='{active}']").locator("xpath=ancestor::*[@role='listbox'][1]")
        if holder.count() > 0:
            return holder.first
    menus = page.locator(_MENUS).filter(visible=True).all()
    if opened_before:
        fresh = [menu for menu in menus if not any(
            menu.evaluate("(el, old) => el === old", old) for old in opened_before
        )]
        if fresh:
            menus = fresh
    return menus[0] if len(menus) == 1 else None


def _menu_choices(page: Any, trigger: Any, opened_before: list[Any] | None = None) -> list[Any]:
    menu = _owned_menu(page, trigger, opened_before)
    if menu is None:
        return []
    rows = menu.locator(_OPTION_ROWS)
    if rows.count() == 0 and menu.get_attribute("role") == "listbox":
        rows = menu.locator("li")
    return rows.all()


def _choices(
    page: Any, trigger: Any, opened_before: list[Any] | None = None, *, wait_ms: int = 3000,
) -> list[tuple[Any, str]]:
    """The visible option rows of the trigger's menu with their text, once loaded: an
    empty menu or one showing "Loading…" is read again for up to ``wait_ms``."""
    waited = 0
    while True:
        rows = [row for row in _menu_choices(page, trigger, opened_before) if row.is_visible()]
        texts = [row.inner_text().strip() for row in rows]
        if (rows and not any(_LOADING_ROW.match(text) for text in texts)) or waited >= wait_ms:
            return [(row, text) for row, text in zip(rows, texts, strict=True)
                    if text and not _LOADING_ROW.match(text) and not _EMPTY_ROW.match(text)]
        page.wait_for_timeout(250)
        waited += 250


def _search_box(page: Any, trigger: Any, opened_before: list[Any] | None, is_input: bool) -> Any | None:
    """Where to type a search: a box inside the trigger's menu, else the trigger itself
    when it takes typing, else the page's one visible search box."""
    with contextlib.suppress(Exception):
        menu = _owned_menu(page, trigger, opened_before)
        if menu is not None:
            inside = menu.locator("input:not([type='hidden'])").filter(visible=True)
            if inside.count() > 0:
                return inside.first
    if is_input and trigger.get_attribute("readonly") is None:
        return trigger
    boxes = page.locator(_SEARCH_BOXES).filter(visible=True)
    return boxes.first if boxes.count() == 1 else None

def _select_combobox_option(
    page: Any, trigger_selector: str, target_value: str, *, key: str = "", phone_region: str = "",
    location_context: dict[str, str] | None = None, preserve_existing: bool = False,
) -> bool:
    """Click a custom combobox trigger and pick the matching option from the popup portal."""
    try:
        trigger = page.locator(trigger_selector).first
        if trigger.count() == 0 or not trigger.is_visible() or _is_upload_widget(trigger):
            return False

        tag_name = trigger.evaluate("el => el.tagName.toLowerCase()")
        is_input = tag_name == "input"

        before = _selected_combobox_text(trigger)
        # Normal fill callers preserve a user's committed answer. Explicit repair
        # callers have already checked its recorded automation provenance and can
        # replace it. A bare phone prefix establishes no country identity.
        if (key != "phone_country_code" and before and not _placeholder(before)
                and (preserve_existing or _option_match([before], target_value, key=key))):
            return True
        if key == "phone_country_code" and _phone_identity_matches(trigger, target_value, phone_region):
            return True
        opened_before = _open_menus(page)
        clicks.safe_click(trigger, purpose="select", timeout=3000)
        search_terms = [""]
        if key == "phone_country_code" and phone_region:
            search_terms.extend([phone_region, target_value])
        elif key in {"city", "location"}:
            city = (location_context or {}).get("city") or target_value.split(",")[0].strip()
            search_terms.extend([city, target_value])
        else:
            search_terms.extend(field_matcher.search_terms(key, target_value))
        # Search text typed into an empty input dropdown is cleared again when nothing is
        # picked, so it is never read back as the answer.
        was_empty = is_input and not str(trigger.input_value() or "").strip()
        typed_into_trigger = False
        match = None
        for term in search_terms:
            if term:
                search_box = _search_box(page, trigger, opened_before, is_input)
                if search_box is None:
                    continue
                search_box.fill(term)
                typed_into_trigger |= search_box is trigger and was_empty
            for _ in range(8 if term else 1):
                rows = _choices(page, trigger, opened_before, wait_ms=0 if term else 3000)
                choices = [row for row, _text in rows]
                option_texts = [text for _row, text in rows]
                if key == "phone_country_code":
                    chosen_text = _phone_option(option_texts, target_value, phone_region)
                elif key == "postal_code":
                    chosen_text = _postal_option(option_texts, target_value, location_context)
                elif key in {"city", "location"}:
                    chosen_text = _location_option(option_texts, target_value, location_context)
                else:
                    chosen_text = questions.choose(questions.Question(
                        "", kind="choice", options=tuple(option_texts),
                        part=("month" if key in {
                            "education_start_month", "graduation_month",
                        } else ""),
                    ), key, [target_value])
                if chosen_text:
                    match = choices[option_texts.index(chosen_text)]
                    break
                if term:
                    page.wait_for_timeout(250)
            if match is not None:
                break
        if match is None:
            trigger.press("Escape")
            if typed_into_trigger:  # typed search text is not an answer to leave behind
                trigger.fill("")
            return False
        if (key == "phone_country_code" and match.get_attribute("aria-selected") == "true"
                and _phone_prefix_matches(before, target_value)):
            trigger.press("Escape")
            return True
        selected_option = option_texts[choices.index(match)]
        clicks.safe_click(match, purpose="select", timeout=3000)
        page.wait_for_timeout(150)
        selected = _committed_text(trigger)
        # A postal lookup row ("95814, Sacramento, Sacramento, CA") leaves its code alone.
        if key == "postal_code":
            selected_option = selected_option.split(",")[0]
        # Some widgets (Workday listbox buttons) repaint their text a few hundred ms later.
        for _ in range(8):
            if key == "phone_country_code" or _norm(selected) == _norm(selected_option):
                break
            page.wait_for_timeout(250)
            selected = _committed_text(trigger)
        if key == "phone_country_code":
            if _phone_identity_matches(trigger, target_value, phone_region):
                return True
            # React Select often detaches the clicked option when its menu closes.
            # Reopen the owned menu and inspect the newly rendered committed choice.
            clicks.safe_click(trigger, purpose="select", timeout=3000)
            refreshed = _choices(page, trigger, wait_ms=0)
            labels = [text for _row, text in refreshed]
            committed_label = _phone_option(labels, target_value, phone_region)
            committed = bool(committed_label) and any(
                text == committed_label and row.get_attribute("aria-selected") == "true"
                for row, text in refreshed
            )
            trigger.press("Escape")
            return committed and _phone_prefix_matches(selected, target_value)
        return _norm(selected) == _norm(selected_option) and _norm(selected) != _norm(before)
    except Exception as exc:  # noqa: BLE001
        _log.debug("combobox selection failed: %s", exc)
        with contextlib.suppress(Exception):
            trigger.press("Escape")
        return False

def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w+]+", " ", value.casefold())).strip()


def _placeholder(value: str) -> bool:
    return bool(re.fullmatch(
        r"(?:(?:please )?(?:select|choose)(?: .*)?)?",
        _norm(value),
    ))


def _postal_code(text: str) -> str:
    """The code a postal-code lookup row or box shows: "95814, Sacramento, ..." -> 95814."""
    return re.sub(r"\s+", "", text.split(",")[0]).upper()


def _postal_option(
    options: list[str], target: str, context: dict[str, str] | None = None,
) -> str | None:
    """The postal-code lookup row for the profile's code: its first part is the code
    ("95814, Sacramento, Sacramento, CA"); of several, the one naming the profile's city.
    A ZIP+4 matches its five-digit rows."""
    code = _postal_code
    wanted = code(target)
    rows = [option for option in options if code(option) == wanted]
    if not rows and re.fullmatch(r"\d{5}-\d{4}", wanted):
        rows = [option for option in options if code(option) == wanted[:5]]
    if len(rows) > 1:
        city = _norm((context or {}).get("city", ""))
        rows = [
            option for option in rows
            if city and len(option.split(",")) > 1 and _norm(option.split(",")[1]) == city
        ]
    return rows[0] if len(rows) == 1 else None


def _location_option(
    options: list[str], target: str, context: dict[str, str] | None = None,
) -> str | None:
    """A city option must match every region it names, with explicit geo aliases."""
    fields = context or {}
    parts = [part.strip() for part in target.split(",")]
    city = fields.get("city") or parts[0]
    state = fields.get("state") or (parts[1] if len(parts) > 1 else "")
    country = fields.get("country") or (parts[2] if len(parts) > 2 else "")
    canonical = reference_data.region_key(country)
    state_aliases = {_norm(state)} - {""}
    state_aliases |= {
        _norm(reference_data.state_code(state, canonical.title())),
        _norm(reference_data.state_name(state, canonical.title())),
    } - {""}
    candidates = []
    for option in options:
        segments = [part.strip() for part in option.split(",")]
        if not segments or _norm(segments[0]) != _norm(city):
            continue
        score = 0
        valid = True
        for index, segment in enumerate(segments[1:], start=1):
            # "CA" as the state part of "Fountain Valley, CA" is California,
            # while the last part of a three-part option can name Canada.
            if index == 1 and _norm(segment) in state_aliases:
                score += 1
                continue
            named_country = reference_data.country(segment)
            if named_country is not None:
                if canonical and reference_data.region_key(segment) != canonical:
                    valid = False
                    break
                score += 1
            elif index == 1 and not state_aliases:
                # A profile can identify the city and country without supplying
                # the site's intervening state/region. It is not a contradictory
                # fact; any country named later must still match.
                continue
            elif state_aliases or country:
                valid = False
                break
        if valid:
            candidates.append((score, option))
    if not candidates:
        return None
    best = max(score for score, _option in candidates)
    matches = [option for score, option in candidates if score == best]
    return matches[0] if len(matches) == 1 else None


_PHONE_CONTROL_JS = r"""(el) => {
  const clues = [el.id, el.name, el.getAttribute('autocomplete'),
    el.getAttribute('aria-label')].filter(Boolean).join(' ');
  const codeLabel = /tel-country-code|dial(?:ling|ing)?[ _-]*code|calling[ _-]*code/;
  if (codeLabel.test(clues.toLowerCase()) ||
    /phone[ _-]*country|country[ _/-]*code/i.test(clues)) return true;
  const group = el.closest('fieldset, [class*="phone" i], [data-field*="phone" i], .form-group');
  const groupLabel = group && [group.className, group.getAttribute('data-field'),
    group.querySelector('label,legend')?.textContent].filter(Boolean).join(' ');
  return !!group && !!group.querySelector('input[type="tel"], input[name*="phone" i]') &&
    /country/i.test(clues) && /phone/i.test(groupLabel);
}"""


def _is_phone_code_control(trigger: Any, label: str = "") -> bool:
    if re.search(
        r"dial(?:ling|ing)?[ _-]*code|calling[ _-]*code|phone[ _-]*country|country[ _/-]*code",
        label, re.I,
    ):
        return True
    with contextlib.suppress(Exception):
        return trigger.evaluate(_PHONE_CONTROL_JS) is True
    return False


_PHONE_REGION_JS = r"""(el) => {
  const control = el.closest('.select__control, [class*="-control"], ' +
    '[class*="phone-country"], [data-automation-id*="countryPhoneCode"]') || el;
  const hints = [control.getAttribute('aria-label'), el.getAttribute('aria-label')];
  const flags = control.querySelectorAll('[data-country], [data-country-code], ' +
    '[data-region], img[alt], svg[aria-label], [class*="flag"]');
  for (const flag of flags) {
    for (const attr of ['data-country', 'data-country-code', 'data-region',
      'alt', 'aria-label', 'title']) hints.push(flag.getAttribute(attr));
    const classes = String(flag.className?.baseVal || flag.className || '');
    const code = classes.match(/(?:flag|fi)[_-]+([a-z]{2})(?:\b|_)/i);
    if (code) hints.push(code[1]);
  }
  return hints.filter(Boolean);
}"""


def _phone_prefix_matches(selected: str, code: str) -> bool:
    prefixes = re.findall(r"\+\d{1,4}\b", selected)
    return prefixes == [code] or (not prefixes and reference_data.country(selected) is not None)


def _phone_identity_matches(trigger: Any, code: str, region: str) -> bool:
    """Trust a visible selected flag/region and prefix together, never a bare +1."""
    selected = _committed_text(trigger)
    if not _phone_prefix_matches(selected, code) or reference_data.region_dial(region) != code:
        return False
    if _phone_option([selected], code, region) is not None:
        return True
    with contextlib.suppress(Exception):
        hints = trigger.evaluate(_PHONE_REGION_JS)
        if isinstance(hints, list):
            regions = set()
            for hint in hints:
                value = re.sub(r"\bflag\b|\+\d{1,4}\b", "", str(hint), flags=re.I).strip(" ()-:")
                found = reference_data.country(value)
                if found is not None:
                    regions.add(reference_data.region_key(value))
            return regions == {reference_data.region_key(region)}
    return False

def _selected_combobox_text(trigger: Any) -> str:
    """React Select keeps its chosen value in a sibling, not in the search input."""
    with contextlib.suppress(Exception):
        selected = trigger.evaluate(
            "el => el.closest('.select__control, [class*=-control]')?.querySelector('.select__single-value, [class*=-singleValue]')?.textContent || ''"
        )
        if isinstance(selected, str) and selected.strip():
            return selected.strip()
    with contextlib.suppress(Exception):
        if trigger.get_attribute("role") == "combobox":
            return ""
    return str(trigger.inner_text() or "").strip()


_COMMITTED_JS = r"""(el) => {
  if (el.getAttribute('aria-expanded') === 'true') return '';
  const id = el.getAttribute('aria-controls') || el.getAttribute('aria-owns');
  const menu = id && document.getElementById(id);
  const shown = (e) => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  if (menu && shown(menu) && menu.querySelector('[role="option"], li')) return '';
  if (el.matches('input, textarea')) return el.value || '';
  if (el.querySelector('input, textarea, select')) return '';
  return (el.innerText || '').trim();
}"""


def committed_option(page: Any, trigger_selector: str, *, key: str = "") -> str | None:
    """The answer an input dropdown that takes typing already shows, when it is one of
    the dropdown's own options (a committed choice, the applicant's or an earlier fill's);
    None for an empty box or search text no option carries. A postal-code lookup shows
    only the code of the row picked ("95815" for "95815, Sacramento, ..."). Opens the menu
    to compare, types nothing, and closes it again."""
    try:
        trigger = page.locator(trigger_selector).first
        if trigger.evaluate("el => el.tagName") != "INPUT":
            return None
        shown = _committed_text(trigger)
        if not shown or _placeholder(shown):
            return None
        opened_before = _open_menus(page)
        clicks.safe_click(trigger, purpose="select", timeout=3000)
        try:
            texts = [text for _row, text in _choices(page, trigger, opened_before)]
        finally:
            trigger.press("Escape")
        if key == "postal_code":
            code = _postal_code(shown)
            return shown if any(_postal_code(text) == code for text in texts) else None
        return shown if any(_norm(text) == _norm(shown) for text in texts) else None
    except Exception as exc:  # noqa: BLE001
        _log.debug("reading a dropdown's committed choice failed: %s", exc)
        return None


def _committed_text(trigger: Any) -> str:
    """The choice a combobox shows once its menu has closed: React Select's value, else a
    ``role=combobox`` input's own value or a div trigger's own text (Rippling, Workable).
    While its menu is open or an option row still shows, nothing counts as chosen, so
    text typed into a search box is never read as a commit."""
    shown = _selected_combobox_text(trigger)
    if shown:
        return shown
    with contextlib.suppress(Exception):
        if trigger.get_attribute("role") == "combobox":
            return str(trigger.evaluate(_COMMITTED_JS) or "").strip()
    return ""

def _phone_option(options: list[str], code: str, region: str) -> str | None:
    """Resolve a calling-code menu only when the declared phone region disambiguates it."""
    region_key = _norm(reference_data.region_key(region))
    if (not region_key or not re.fullmatch(r"\+\d{1,4}", code)
            or reference_data.region_dial(region) != code):
        return None
    code_pattern = re.compile(rf"(?<!\d){re.escape(code)}(?!\d)")
    identifiers = reference_data.region_identifiers(region)

    def names_region(rest: str) -> bool:
        # "United States", or Rippling's "US - United States" / "US": every part is the
        # region's name or one of its short codes.
        if _norm(reference_data.region_key(rest)) == region_key:
            return True
        parts = [part for part in re.split(r"\s+[-–]\s+", rest) if part.strip()]
        return bool(parts) and all(
            part.strip().casefold() in identifiers
            or _norm(reference_data.region_key(part)) == region_key
            for part in parts
        )

    matches = [
        option for option in options
        if (code_pattern.search(option) or not re.search(r"\+\d{1,4}\b", option))
        and names_region(code_pattern.sub("", option).strip(" ()-"))
    ]
    return matches[0] if len(matches) == 1 else None

def _choose_radio_option(page: Any, radio_selector: str, target_value: str) -> bool:
    """Select the radio button matching target_value."""
    target_lower = _norm(target_value)
    try:
        radios = page.locator(radio_selector).all()
        for r in radios:
            # Check associated label
            rid = r.get_attribute("id")
            text = ""
            if rid:
                lbl = page.locator(f"label[for='{rid}']").first
                if lbl.count() > 0:
                    text = lbl.inner_text()
            if not text:
                text = _wrapping_label(r)
            if not text:
                text = r.get_attribute("value") or ""
            if target_lower == _norm(text):
                clicks.safe_click(r, purpose="select", timeout=3000)
                return True
    except Exception as exc:  # noqa: BLE001
        _log.debug("radio selection failed: %s", exc)
    return False

#: A checkbox-group option that answers "none of these"; it is never ticked with another.
_EXCLUSIVE_OPTION = re.compile(r"^(?:no|none(?: of the above)?|not available|n/?a)$", re.I)

def checked_values(value: str) -> list[str]:
    """The option texts a check_options action names (joined by ``|``)."""
    return [part.strip() for part in value.split("|") if part.strip()]

def _wrapping_label(box: Any) -> str:
    """The text of the ``<label>`` an option's input sits in (Lever), else ""."""
    try:
        wrap = box.locator("xpath=ancestor::label[1]")
        return wrap.first.inner_text() if wrap.count() else ""
    except Exception:  # noqa: BLE001
        return ""


def _check_options(page: Any, group_selector: str, values: list[str]) -> bool:
    """Tick the checkboxes labelled ``values`` in one group (a container, or the boxes
    themselves when they share a name); True when all are ticked."""
    wanted = {_norm(value) for value in values}
    ticked = 0
    try:
        boxes = (page.locator(group_selector).all() if "input[type=" in group_selector
                 else page.locator(f"{group_selector} input[type='checkbox']").all())
        for box in boxes:
            bid = box.get_attribute("id")
            label = page.locator(f"label[for='{bid}']").first if bid else None
            if label is None or label.count() == 0:
                label = box.locator("xpath=ancestor::label[1]").first
            if label.count() == 0 or _norm(label.inner_text()) not in wanted:
                continue
            if not box.is_checked():
                clicks.safe_click(label, purpose="select", timeout=3000)
                page.wait_for_timeout(150)
            ticked += box.is_checked()
    except Exception as exc:  # noqa: BLE001
        _log.debug("checkbox selection failed: %s", exc)
        return False
    return ticked == len(wanted)

def execute_action(page: Any, action: resolver_types.FieldAction) -> bool:
    """Execute one resolved action in the browser page."""
    if action.action == "select_combobox":
        match = questions.classify(questions.Question(action.label, kind="typeahead"))
        return _select_combobox_option(
            page, action.selector, action.value, key=match.key if match is not None else "",
            preserve_existing=True,
        )
    if action.action == "choose_radio":
        return _choose_radio_option(page, action.selector, action.value)
    if action.action == "check_options":
        return _check_options(page, action.selector, checked_values(action.value))
    if action.action == "fill_text":
        try:
            loc = page.locator(action.selector).first
            if loc.count() > 0 and loc.is_visible():
                loc.fill(action.value)
                page.wait_for_timeout(300)
                return True
        except Exception:  # noqa: BLE001
            pass
    return False
