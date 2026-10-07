"""Carrying out a resolved field action on the page: comboboxes, radios, checkboxes, uploads."""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

from resume_tailor.apply.answers import reference_data
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
) -> bool:
    """Click a custom combobox trigger and pick the matching option from the popup portal."""
    try:
        trigger = page.locator(trigger_selector).first
        if trigger.count() == 0 or not trigger.is_visible() or _is_upload_widget(trigger):
            return False

        tag_name = trigger.evaluate("el => el.tagName.toLowerCase()")
        is_input = tag_name == "input"

        before = _selected_combobox_text(trigger)
        if key != "phone_country_code" and before and _option_match([before], target_value, key=key):
            return True
        clicks.safe_click(trigger, purpose="select", timeout=3000)
        search_terms = [""]
        if key == "phone_country_code" and phone_region:
            search_terms.extend([phone_region, target_value])
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
                    if not chosen_text:
                        chosen_text = _option_match(option_texts, target_value, key=key)
                else:
                    chosen_text = field_matcher.closest_option(option_texts, target_value, key=key)
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
        if key == "phone_country_code" and match.get_attribute("aria-selected") == "true":
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
            # React Select often detaches the clicked option when its menu closes.
            # Reopen the owned menu and inspect the newly rendered committed choice.
            clicks.safe_click(trigger, purpose="select", timeout=3000)
            refreshed = [choice for choice in _menu_choices(page, trigger) if choice.is_visible()]
            labels = [choice.inner_text().strip() for choice in refreshed]
            committed_label = _phone_option(labels, target_value, phone_region) or _option_match(
                labels, target_value, key=key,
            )
            committed = bool(committed_label) and any(
                choice.inner_text().strip() == committed_label
                and choice.get_attribute("aria-selected") == "true"
                for choice in refreshed
            )
            trigger.press("Escape")
            return committed and _norm(selected) == _norm(target_value)
        return _norm(selected) == _norm(selected_option) and _norm(selected) != _norm(before)
    except Exception as exc:  # noqa: BLE001
        _log.debug("combobox selection failed: %s", exc)
        with contextlib.suppress(Exception):
            trigger.press("Escape")
        return False

def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w+]+", " ", value.casefold())).strip()

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
    if not region_key or not re.fullmatch(r"\+\d{1,4}", code):
        return None
    code_pattern = re.compile(rf"(?<!\d){re.escape(code)}(?!\d)")
    matches = [
        option for option in options
        if code_pattern.search(option)
        and _norm(reference_data.region_key(code_pattern.sub("", option).strip(" ()-"))) == region_key
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
        return _select_combobox_option(page, action.selector, action.value)
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
