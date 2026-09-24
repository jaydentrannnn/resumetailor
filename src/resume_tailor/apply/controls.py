"""Frame-scoped Playwright actions with post-action observation."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from resume_tailor.apply.field_matcher import match_option, normalize, school_short_term
from resume_tailor.apply.field_types import FieldObservation, FieldOutcome, ObservedOption
from resume_tailor.apply.scanner import ScanSnapshot, scan


def _outcome(field: FieldObservation, state: str, *, value: str = "", reason: str = "") -> FieldOutcome:
    return FieldOutcome(
        field_id=field.field_id, frame_id=field.frame_id, label=field.label,
        canonical_key=field.canonical_key, state=state, required=field.required,
        observed_value=value, reason_code=reason,
    )


def _date_value(value: str, kind: str) -> str:
    if kind != "date":
        return value
    for pattern in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


async def _same_field(page: Any, original: FieldObservation) -> FieldObservation | None:
    matched = await _reacquire(page, original)
    return matched[1] if matched else None


async def _reacquire(page: Any, original: FieldObservation) -> tuple[ScanSnapshot, FieldObservation] | None:
    after = await scan(page)
    candidates = [
        field for field in after.fields
        if field.frame_id == original.frame_id
        and field.document_generation == original.document_generation
        and field.section_id == original.section_id
        and field.repeater_row_id == original.repeater_row_id
        and field.label == original.label
        and field.control_kind == original.control_kind
    ]
    return (after, candidates[0]) if len(candidates) == 1 else None


async def _owned_menu(frame: Any, trigger: Any) -> Any | None:
    menu_id = await trigger.get_attribute("aria-controls") or await trigger.get_attribute("aria-owns")
    if menu_id:
        menu = frame.locator(f"[id={json.dumps(menu_id)}]")
        try:
            await menu.wait_for(state="visible", timeout=5000)
        except Exception:  # noqa: BLE001 - unknown ownership remains unresolved
            return None
        return menu if await menu.count() == 1 else None
    menus = frame.locator("[role='listbox']:visible, [class*='-menu']:visible")
    try:
        await menus.first.wait_for(state="visible", timeout=5000)
    except Exception:  # noqa: BLE001
        return None
    return menus if await menus.count() == 1 else None


async def observe_options(
    page: Any, snapshot: ScanSnapshot, field: FieldObservation,
) -> list[ObservedOption]:
    """Inspect one owned dropdown without typing or changing its selection."""
    trigger = await snapshot.locator(field)
    frame, _selector = snapshot.locators[field.field_id]
    was_open = await trigger.get_attribute("aria-expanded") == "true"
    try:
        if not was_open:
            await trigger.click(timeout=5000)
        menu = await _owned_menu(frame, trigger)
        if menu is None:
            return []
        option_locs = menu.locator("[role='option'], .select__option, [data-automation-id*='promptOption']")
        result = []
        for index, option in enumerate(await option_locs.all()):
            if not await option.is_visible():
                continue
            label = (await option.inner_text()).strip()
            result.append(ObservedOption(
                option_id=f"{field.field_id}:option:{index}", label=label,
                value=await option.get_attribute("data-value") or await option.get_attribute("value") or "",
                enabled=await option.get_attribute("aria-disabled") != "true" and await option.is_enabled(),
                placeholder=bool(re.fullmatch(r"(?:select|choose|please select)(?:\s.*)?", label, re.I)),
                selected=await option.get_attribute("aria-selected") == "true",
            ))
        return result
    finally:
        if not was_open:
            await trigger.press("Escape", timeout=5000)


def _search_term(key: str, target: str) -> str:
    if key == "degree_level" and normalize(target).startswith("bachelor"):
        return "bachelor"
    if key == "school":
        return school_short_term(target) or target
    return target


def _phone_match(options: list[ObservedOption], code: str, region: str) -> ObservedOption | None:
    if not re.fullmatch(r"\+\d{1,4}", code):
        return None
    code_only = [option for option in options if option.enabled and not option.placeholder and normalize(option.label) == code]
    if len(code_only) == 1:
        return code_only[0]
    if not region:
        return None
    aliases = {"us": "united states", "usa": "united states", "ca": "canada", "uk": "united kingdom"}
    region_key = aliases.get(normalize(region), normalize(region))
    identifiers = {"united states": {"us", "usa"}, "canada": {"ca"}, "united kingdom": {"gb", "uk"}}
    region_codes = {"united states": "+1", "canada": "+1", "united kingdom": "+44"}
    matches = [
        option for option in options
        if option.enabled and not option.placeholder
        and (
            bool(re.search(rf"(?<!\d){re.escape(code)}(?!\d)", option.label))
            and normalize(re.sub(rf"(?<!\d){re.escape(code)}(?!\d)", "", option.label)) == region_key
            or region_codes.get(region_key) == code
            and normalize(option.label) == region_key
            and normalize(option.value) in identifiers.get(region_key, set())
        )
    ]
    return matches[0] if len(matches) == 1 else None


async def apply_value(
    page: Any, snapshot: ScanSnapshot, field: FieldObservation, value: str,
    *, phone_region: str = "", replace_existing: bool = False,
    requested_option: ObservedOption | None = None,
) -> FieldOutcome:
    """Write one supported field, preserving nonempty answers unless explicitly corrected."""
    try:
        current = await _reacquire(page, field)
        if current is None:
            return _outcome(field, "ambiguous", reason="stale_or_ambiguous_field")
        current_snapshot, before = current
        before.canonical_key = field.canonical_key
        target = await current_snapshot.locator(before)
        field = before
        snapshot = current_snapshot
        has_committed_value = bool(before.current_value) and (
            before.control_kind != "combobox" or before.selection_state == "committed"
        )
        if has_committed_value and not replace_existing:
            return _outcome(field, "preserved", value=before.current_value)
        kind = field.control_kind
        if kind in {"text", "textarea", "date", "number"}:
            expected = _date_value(value, kind)
            if not expected:
                return _outcome(field, "unanswered", reason="unsupported_date_precision")
            max_length = field.constraints.get("max_length")
            if isinstance(max_length, int) and len(expected) > max_length:
                return _outcome(field, "unanswered", reason="answer_too_long")
            await target.fill(expected, timeout=5000)
            await target.blur(timeout=5000)
            after = await _same_field(page, field)
            if after and after.current_value == expected and not after.validation_messages:
                return _outcome(field, "verified_filled", value=after.current_value)
            return _outcome(field, "failed", value=after.current_value if after else "", reason="value_not_retained")
        if kind == "native_select":
            candidates = [option for option in field.options if requested_option and option.enabled and not option.placeholder and option.label == requested_option.label and option.value == requested_option.value]
            match = match_option(field.options, value, key=field.canonical_key)
            if requested_option:
                if len(candidates) != 1:
                    return _outcome(field, "ambiguous", reason="requested_option_changed")
                match = match.model_copy(update={"status": "matched", "option_id": candidates[0].option_id})
            if match.status != "matched":
                return _outcome(field, "ambiguous" if match.status == "ambiguous" else "unanswered", reason=match.status)
            index = int(match.option_id.rsplit(":", 1)[-1])
            await target.select_option(index=index, timeout=5000)
            after = await _same_field(page, field)
            expected = field.options[index]
            if after and any(option.selected and option.label == expected.label and not option.placeholder for option in after.options):
                return _outcome(field, "verified_filled", value=expected.label)
            return _outcome(field, "failed", reason="selection_not_committed")
        if kind == "combobox":
            return await _select_combobox(page, snapshot, field, target, value, phone_region=phone_region, requested_option=requested_option)
        if kind == "radio_group":
            match = match_option(field.options, value, key=field.canonical_key)
            if requested_option:
                candidates = [option for option in field.options if option.enabled and not option.placeholder and option.label == requested_option.label and option.value == requested_option.value]
                if len(candidates) != 1:
                    return _outcome(field, "ambiguous", reason="requested_option_changed")
                match = match.model_copy(update={"status": "matched", "option_id": candidates[0].option_id})
            if match.status != "matched":
                return _outcome(field, "ambiguous" if match.status == "ambiguous" else "unanswered", reason=match.status)
            frame, _selector = snapshot.locators[field.field_id]
            name = await target.get_attribute("name")
            if not name:
                return _outcome(field, "ambiguous", reason="radio_group_unidentified")
            group = frame.locator(f"input[type='radio'][name={json.dumps(name)}]")
            index = int(match.option_id.rsplit(":", 1)[-1])
            if await group.count() != len(field.options):
                return _outcome(field, "ambiguous", reason="radio_group_changed")
            await group.nth(index).check(timeout=5000)
            after = await _same_field(page, field)
            if after and len(after.options) > index and after.options[index].selected:
                return _outcome(field, "verified_filled", value=after.options[index].label)
            return _outcome(field, "failed", reason="selection_not_committed")
        if kind == "checkbox":
            if normalize(value) not in {"yes", "no"}:
                return _outcome(field, "unanswered", reason="unsupported_checkbox_answer")
            checked = normalize(value) == "yes"
            await target.set_checked(checked, timeout=5000)
            after = await _same_field(page, field)
            if after and (after.current_value == "checked") == checked:
                return _outcome(field, "verified_filled", value="Yes" if checked else "No")
            return _outcome(field, "failed", reason="selection_not_committed")
        return _outcome(field, "unanswered", reason="unsupported_control")
    except Exception as exc:  # noqa: BLE001
        return _outcome(field, "failed", reason=f"{type(exc).__name__}")


async def _select_combobox(
    page: Any, snapshot: ScanSnapshot, field: FieldObservation,
    trigger: Any, value: str, *, phone_region: str, requested_option: ObservedOption | None = None,
) -> FieldOutcome:
    frame, _selector = snapshot.locators[field.field_id]
    await trigger.click(timeout=5000)
    menu = await _owned_menu(frame, trigger)
    if menu is None:
        return _outcome(field, "ambiguous", reason="menu_owner_unknown")
    search = _search_term(field.canonical_key, phone_region if field.canonical_key == "phone_country_code" and phone_region else value)
    tag = await trigger.evaluate("el => el.tagName.toLowerCase()")
    search_input = trigger if tag == "input" else menu.locator("input[role='searchbox'], input[type='search']")
    if search and await search_input.count() == 1:
        await search_input.fill(search, timeout=5000)
    options_locator = menu.locator("[role='option'], .select__option, [data-automation-id*='promptOption']")
    await options_locator.first.wait_for(state="visible", timeout=5000)
    option_locs = [option for option in await options_locator.all() if await option.is_visible()]
    observed = [
        ObservedOption(
            option_id=str(index), label=(await option.inner_text()).strip(),
            value=await option.get_attribute("data-value") or "",
            enabled=await option.get_attribute("aria-disabled") != "true",
            placeholder=False,
        )
        for index, option in enumerate(option_locs)
    ]
    if requested_option:
        matches = [option for option in observed if option.enabled and option.label == requested_option.label and option.value == requested_option.value]
        match_id = matches[0].option_id if len(matches) == 1 else ""
        match_status = "matched" if len(matches) == 1 else "ambiguous"
    elif field.canonical_key == "phone_country_code":
        chosen = _phone_match(observed, value, phone_region)
        match_id = chosen.option_id if chosen else ""
        match_status = "matched" if chosen else "ambiguous"
    else:
        match = match_option(observed, value, key=field.canonical_key)
        match_id, match_status = match.option_id, match.status
    if match_status != "matched":
        await trigger.press("Escape")
        return _outcome(field, "ambiguous" if match_status == "ambiguous" else "unanswered", reason=match_status)
    selected = observed[int(match_id)]
    await option_locs[int(match_id)].click(timeout=5000)
    after = await _same_field(page, field)
    if after is None or after.selection_state != "committed":
        return _outcome(field, "failed", reason="selection_not_committed")
    if field.canonical_key == "phone_country_code":
        if normalize(after.current_value) != normalize(value) and normalize(after.current_value) != normalize(selected.label):
            return _outcome(field, "failed", reason="selection_not_committed")
        # A display of +1 alone does not prove which country was selected.
        if normalize(after.current_value) == normalize(value) and normalize(selected.label) != normalize(value):
            fresh = await _reacquire(page, field)
            if fresh is None:
                return _outcome(field, "unanswered", reason="committed_region_unverified")
            fresh_snapshot, fresh_field = fresh
            trigger = await fresh_snapshot.locator(fresh_field)
            frame, _selector = fresh_snapshot.locators[fresh_field.field_id]
            await trigger.click(timeout=5000)
            owned = await _owned_menu(frame, trigger)
            if owned is None:
                return _outcome(field, "unanswered", reason="committed_region_unverified")
            selected_options = owned.locator("[role='option'][aria-selected='true'], .select__option[aria-selected='true']")
            labels = [(await option.inner_text()).strip() for option in await selected_options.all()]
            await trigger.press("Escape")
            if selected.label not in labels:
                return _outcome(field, "unanswered", reason="committed_region_unverified")
    elif normalize(after.current_value) != normalize(selected.label):
        return _outcome(field, "failed", reason="selection_not_committed")
    return _outcome(field, "verified_filled", value=after.current_value)
