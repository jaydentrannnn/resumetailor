"""Read-only review refresh and stale-safe, explicit one-field corrections."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from resume_tailor.apply import adapters, attachments, browser, controls, field_catalog, scanner, store, workday_auth
from resume_tailor.apply.field_types import FieldObservation, FieldOutcome

_PROTECTED = re.compile(
    r"password|passcode|verification code|one.time code|\botp\b|"
    r"username|sign.in email|login email|signature|attest|certif|agreement|"
    r"terms|consent|arbitration|social security|\bssn\b",
    re.I,
)


def state_hash(field: FieldObservation, url: str) -> str:
    state = {
        "url": url, "generation": field.document_generation,
        "frame_index": field.frame_id.split(":", 1)[0],
        "section": field.section_id, "row": field.repeater_row_id,
        "label": field.label, "kind": field.control_kind,
        "value": field.current_value,
        "selection_state": field.selection_state,
        "options": [
            (option.label, option.value, option.enabled, option.placeholder, option.selected)
            for option in field.options
        ],
        "validation": field.validation_messages,
        "constraints": field.constraints,
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def _outcome(field: FieldObservation) -> FieldOutcome:
    policy, key = field_catalog.classify(field)
    if policy == "manual_review":
        state, reason = "manual_review", key
    elif field.validation_messages:
        state, reason = "invalid_existing", "site_validation"
    elif field.control_kind == "combobox" and field.selection_state != "committed":
        state, reason = "unanswered", "selection_not_committed"
    elif field.current_value:
        state, reason = "preserved", ""
    else:
        state, reason = "unanswered", "current_page_blank"
    return FieldOutcome(
        field_id=field.field_id, frame_id=field.frame_id, label=field.label,
        canonical_key=key, state=state, required=field.required,
        observed_value=field.current_value, reason_code=reason,
    )


async def _record(app: store.Application, page: Any) -> store.FillResult:
    observed = await scanner.scan(page)
    for field in observed.fields:
        if field.control_kind == "combobox":
            try:
                field.options = await controls.observe_options(page, observed, field)
            except Exception:  # noqa: BLE001 - unresolved is safer than a false option list
                field.options = []
    result = store.FillResult.model_validate(app.fill) if app.fill else store.FillResult()
    current_step_id = await adapters.for_url(str(page.url)).step_id(page, observed.fields)
    prior_step_id = result.current_step_id
    completed_steps = [
        item for item in result.field_outcomes
        if item.get("step_id") and item.get("step_id") not in {prior_step_id, current_step_id}
    ]
    result.current_step_id = current_step_id
    result.review_snapshot_id = observed.snapshot_id
    result.review_fields = [
        {**field.model_dump(), "expected_state_hash": state_hash(field, str(page.url))}
        for field in observed.fields
    ]
    result.field_outcomes = completed_steps + [
        _outcome(field).model_copy(update={"step_id": current_step_id}).model_dump()
        for field in observed.fields
    ]
    uploads = {str(item.get("purpose") or ""): item for item in result.uploads}
    for field in observed.fields:
        if field.control_kind != "file":
            continue
        purpose = attachments.purpose_for(field)
        if not purpose:
            continue
        previous_upload = uploads.get(purpose, {})
        uploads[purpose] = {
            **previous_upload,
            "purpose": purpose,
            "state": "preserved" if field.current_value else "unverifiable",
            "observed_filename": field.current_value,
            "reason": "" if field.current_value else "No retained attachment was observed in this component",
        }
    result.uploads = list(uploads.values())
    result.ready_to_submit = False
    result.browser_url = str(page.url)
    if observed.errors:
        result.handoff_reason = f"Inspection incomplete: {', '.join(observed.errors)}"
    app.fill = result
    store.upsert(app)
    return result


async def refresh(source_job_id: str) -> store.FillResult:
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(source_job_id)
    previous = store.FillResult.model_validate(app.fill) if app.fill else None
    if previous is None or not previous.browser_target_id:
        raise ValueError("No recorded review tab")
    async with browser.async_cdp_browser() as connected:
        for context in connected.contexts:
            page = await browser.async_find_target(context, previous.browser_target_id)
            if page is not None:
                return await _record(app, page)
    raise ValueError("The recorded review tab is closed")


def _reidentify(target: FieldObservation, fields: list[FieldObservation]) -> FieldObservation:
    matches = [
        item for item in fields
        if item.frame_id.split(":", 1)[0] == target.frame_id.split(":", 1)[0]
        and item.document_generation == target.document_generation
        and item.section_id == target.section_id
        and item.repeater_row_id == target.repeater_row_id
        and item.label == target.label
        and item.control_kind == target.control_kind
    ]
    if len(matches) != 1:
        raise ValueError("stale_snapshot")
    return matches[0]


async def correct(
    source_job_id: str, *, snapshot_id: str, field_id: str,
    expected_state_hash: str, value: str | None, option_ids: list[str],
) -> FieldOutcome:
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(source_job_id)
    previous = store.FillResult.model_validate(app.fill) if app.fill else None
    if previous is None or not previous.browser_target_id:
        raise ValueError("No recorded review tab")
    if snapshot_id != previous.review_snapshot_id:
        raise ValueError("stale_snapshot")
    saved = next((item for item in previous.review_fields if item.get("field_id") == field_id), None)
    if saved is None or saved.get("expected_state_hash") != expected_state_hash:
        raise ValueError("stale_snapshot")
    target = FieldObservation.model_validate(saved)
    policy, _key = field_catalog.classify(target)
    if (
        target.control_kind == "file"
        or str(target.constraints.get("input_type") or "").casefold() == "password"
        or _PROTECTED.search(target.label)
        or policy == "manual_review" and _key != "salary_expectation"
    ):
        raise ValueError("This field must be handled in the browser")
    if target.control_kind in {"text", "textarea", "date", "number"}:
        if value is None or option_ids or len(value) > 5000:
            raise ValueError("Provide one text value within the field limit")
        wanted = value
    elif target.control_kind in {"native_select", "radio_group", "combobox"}:
        if value is not None or len(option_ids) != 1:
            raise ValueError("Provide exactly one observed option")
        option = next((item for item in target.options if item.option_id == option_ids[0]), None)
        if option is None or not option.enabled or option.placeholder:
            raise ValueError("The requested option was not observed")
        wanted = option.label
    else:
        raise ValueError("This control cannot be corrected here")
    async with browser.async_cdp_browser() as connected:
        for context in connected.contexts:
            page = await browser.async_find_target(context, previous.browser_target_id)
            if page is None:
                continue
            if workday_auth.is_workday_url(str(page.url)) and await page.locator(
                "input[type='password'], input[autocomplete='one-time-code']"
            ).count():
                raise ValueError("Complete Workday authentication in the browser")
            current = await scanner.scan(page)
            observed = _reidentify(target, current.fields)
            if observed.control_kind == "combobox":
                observed.options = await controls.observe_options(page, current, observed)
            if state_hash(observed, str(page.url)) != expected_state_hash:
                raise ValueError("stale_snapshot")
            observed.canonical_key = _key
            outcome = await controls.apply_value(
                page, current, observed, wanted, replace_existing=True,
                requested_option=option if target.control_kind in {"native_select", "radio_group", "combobox"} else None,
            )
            outcome.answer_source = "explicit_user_correction"
            if outcome.state not in {"verified_filled", "preserved"}:
                raise ValueError(outcome.reason_code or "Correction was not verified")
            await _record(app, page)
            return outcome
    raise ValueError("The recorded review tab is closed")
