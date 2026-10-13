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

def _menu_choices(page: Any, trigger: Any) -> list[Any]:
    menu_id = trigger.get_attribute("aria-controls") or trigger.get_attribute("aria-owns")
    if menu_id:
        menu = page.locator(f"[id='{menu_id}']")
        if menu.count() > 0:
            return menu.locator("[role='option'], .select__option, [data-automation-id*='promptOption']").all()
    visible_menus = page.locator("[role='listbox']:visible, [class*='-menu']:visible")
    if visible_menus.count() != 1:
        return []
    return visible_menus.first.locator("[role='option'], .select__option, [data-automation-id*='promptOption']").all()

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
        clicks.safe_click(trigger, purpose="select", timeout=3000)
        search_terms = [""]
        if key == "phone_country_code" and phone_region:
            search_terms.extend([phone_region, target_value])
        elif key in {"city", "location"}:
            city = (location_context or {}).get("city") or target_value.split(",")[0].strip()
            search_terms.extend([city, target_value])
        else:
            search_terms.extend(field_matcher.search_terms(key, target_value))
        match = None
        for term in search_terms:
            if term:
                search_box = trigger if is_input else page.locator(
                    "input[data-automation-id='searchBox'], input[role='searchbox'], input[placeholder*='search' i]"
                ).first
                if search_box.count() == 0 or not search_box.is_visible():
                    continue
                search_box.fill(term)
            for _ in range(8 if term else 1):
                choices = [choice for choice in _menu_choices(page, trigger) if choice.is_visible()]
                option_texts = [choice.inner_text().strip() for choice in choices]
                if key == "phone_country_code":
                    chosen_text = _phone_option(option_texts, target_value, phone_region)
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
                    match = next(choice for choice in choices if choice.inner_text().strip() == chosen_text)
                    break
                if term:
                    page.wait_for_timeout(250)
            if match is not None:
                break
        if match is None:
            trigger.press("Escape")
            return False
        if (key == "phone_country_code" and match.get_attribute("aria-selected") == "true"
                and _phone_prefix_matches(before, target_value)):
            trigger.press("Escape")
            return True
        selected_option = match.inner_text().strip()
        clicks.safe_click(match, purpose="select", timeout=3000)
        page.wait_for_timeout(150)
        selected = _selected_combobox_text(trigger)
        # Some widgets (Workday listbox buttons) repaint their text a few hundred ms later.
        for _ in range(8):
            if key == "phone_country_code" or _norm(selected) == _norm(selected_option):
                break
            page.wait_for_timeout(250)
            selected = _selected_combobox_text(trigger)
        if key == "phone_country_code":
            if _phone_identity_matches(trigger, target_value, phone_region):
                return True
            # React Select often detaches the clicked option when its menu closes.
            # Reopen the owned menu and inspect the newly rendered committed choice.
            clicks.safe_click(trigger, purpose="select", timeout=3000)
            refreshed = [choice for choice in _menu_choices(page, trigger) if choice.is_visible()]
            labels = [choice.inner_text().strip() for choice in refreshed]
            committed_label = _phone_option(labels, target_value, phone_region)
            committed = bool(committed_label) and any(
                choice.inner_text().strip() == committed_label
                and choice.get_attribute("aria-selected") == "true"
                for choice in refreshed
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
    selected = _selected_combobox_text(trigger)
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

def _phone_option(options: list[str], code: str, region: str) -> str | None:
    """Resolve a calling-code menu only when the declared phone region disambiguates it."""
    region_key = _norm(reference_data.region_key(region))
    if (not region_key or not re.fullmatch(r"\+\d{1,4}", code)
            or reference_data.region_dial(region) != code):
        return None
    code_pattern = re.compile(rf"(?<!\d){re.escape(code)}(?!\d)")
    matches = [
        option for option in options
        if (code_pattern.search(option) or not re.search(r"\+\d{1,4}\b", option))
        and _norm(reference_data.region_key(
            code_pattern.sub("", option).strip(" ()-"),
        )) == region_key
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

def _check_options(page: Any, group_selector: str, values: list[str]) -> bool:
    """Tick the checkboxes labelled ``values`` in one group; True when all are ticked."""
    wanted = {_norm(value) for value in values}
    ticked = 0
    try:
        for box in page.locator(f"{group_selector} input[type='checkbox']").all():
            bid = box.get_attribute("id")
            label = page.locator(f"label[for='{bid}']").first if bid else None
            if label is None or label.count() == 0 or _norm(label.inner_text()) not in wanted:
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
