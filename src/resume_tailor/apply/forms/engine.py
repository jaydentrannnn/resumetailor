"""Deadline-bounded verified Apply engine (gated during migration)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from resume_tailor import config
from resume_tailor.infra import model_queue
from resume_tailor.apply.answers import answer, answer_memory, model_resolver, notice, profile, salary
from resume_tailor.apply.ats import (
    adapters,
    workday_auth,
    workday_page,
    workday_repeaters,
)
from resume_tailor.apply.driver import browser, clicks, controls, scanner
from resume_tailor.apply.forms import attachments, field_catalog, form_routes
from resume_tailor.apply.forms.field_types import FieldObservation, FieldOutcome
from resume_tailor.apply.funnel import (
    packet,
    packet_profile_fields,
    preparation,
    store,
    store_models,
)
from resume_tailor.content import data
from resume_tailor.pipeline.jd import JobRequirements
from resume_tailor.web.schemas import ApplySettings

APPLICATION_BUDGET_SECONDS = 240
MAX_FORM_STEPS = 8


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _national_phone_value(value: str, calling_code: str, *, separate_code_committed: bool) -> str:
    """Remove one duplicate prefix only for an established same-group code control."""
    if not separate_code_committed or not re.fullmatch(r"\+\d{1,4}", calling_code):
        return value
    return re.sub(rf"^{re.escape(calling_code)}[\s.-]*", "", value, count=1)


def _availability_for_field(value: str, control_kind: str) -> str:
    if control_kind == "date":
        return value
    if control_kind != "text":
        return value
    try:
        date = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return value
    return f"{date.strftime('%B')} {date.day}, {date.year}"


def _notice_for_field(value: str, question: str) -> str:
    """The notice period in the unit the question names ("in days" -> "14")."""
    parsed = notice.parse(value)
    return value if parsed is None else notice.for_label(question, *parsed)


class _Cancelled(RuntimeError):
    pass


def _current_outcome(field: FieldObservation, prior: FieldOutcome | None) -> FieldOutcome:
    """Report retained state, keeping verified evidence only when it still agrees."""
    policy, key = field_catalog.classify(field)
    committed = bool(field.current_value) and (
        field.control_kind != "combobox" or field.selection_state == "committed"
    )
    if policy == "manual_review":
        state, reason = "manual_review", key
    elif field.validation_messages:
        state, reason = "invalid_existing", "site_validation"
    elif not committed:
        state = "unanswered"
        reason = "selection_not_committed" if field.control_kind == "combobox" and field.current_value else "current_page_blank"
    elif prior and prior.state == "verified_filled" and prior.observed_value == field.current_value:
        state, reason = "verified_filled", ""
    else:
        state, reason = "preserved", ""
    return FieldOutcome(
        field_id=field.field_id, frame_id=field.frame_id, label=field.label,
        canonical_key=key, state=state, required=field.required,
        observed_value=field.current_value,
        answer_source=prior.answer_source if prior and committed else "existing_browser_answer" if committed else "",
        reason_code=reason,
    )


@model_queue.observe_progress
async def fill_application(
    source_job_id: str, *, settings: ApplySettings,
    submit_mode: Literal["auto_submit", "awaiting_review"] | None,
    fill_mode: Literal["initial", "continue", "reopen"],
    should_cancel: Callable[[], bool] | None,
    on_progress: Callable[[str], None] | None,
    applicant_profile: profile.ApplicantProfile | None = None,
) -> store_models.FillResult:
    """Run one attempt; only verified outcomes can contribute to readiness."""
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(source_job_id)
    eligible = preparation.check(app, require_cover=settings.cover_letter)
    if not eligible.eligible:
        raise RuntimeError(f"Application needs Prepare: {', '.join(eligible.reasons)}")
    if not app.job_id:
        raise RuntimeError("Application has no prepared Tailor job")
    pkt = (
        packet.build_packet(app.job_id)
        if applicant_profile is None else
        packet.build_packet(app.job_id, applicant_profile=applicant_profile)
    )
    applicant = applicant_profile
    if applicant is None:
        applicant, _seeded = profile.load_profile()
    resume = data.load()
    fields = dict(pkt.fields)
    # A posting clearly in another country than the profile's authorization: its
    # eligibility questions are the applicant's (`packet_profile_fields.authorization_mismatch`).
    authorization_elsewhere = packet_profile_fields.authorization_mismatch(
        applicant, app.location or ""
    )
    if authorization_elsewhere:
        fields.pop("authorized_to_work", None)
    job_dir = config.OUTPUT_DIR / "jobs" / app.job_id
    bullets_path = job_dir / "bullets.json"
    bullets = json.loads(bullets_path.read_text(encoding="utf-8")) if bullets_path.is_file() else {}
    requirements_path = job_dir / "requirements.json"
    requirements = (
        JobRequirements.model_validate_json(requirements_path.read_text(encoding="utf-8"))
        if requirements_path.is_file() and not app.reused_from_job_id else None
    )
    if requirements is not None:
        requirements = requirements.model_copy(update={"title": app.role})
    jd_path = Path(app.jd_text_path) if app.jd_text_path else job_dir / "jd.txt"
    jd_text = jd_path.read_text(encoding="utf-8") if jd_path.is_file() else ""
    fields.update(salary.salary_fields(
        role=app.role, listing_salary=app.salary, jd_text=jd_text,
        hourly_max=applicant.salary_hourly_max, yearly_max=applicant.salary_yearly_max,
    ))
    previous = (
        store_models.FillResult.model_validate(app.fill) if app.fill else store_models.FillResult()
    )
    result = store_models.FillResult(
        browser_target_id=previous.browser_target_id,
        browser_url=previous.browser_url,
        status="filling",
    )
    store.set_status(app, "filling")
    app.fill = result
    store.upsert(app)
    started = time.monotonic()
    deadline = started + APPLICATION_BUDGET_SECONDS
    last_checkpoint = 0.0
    outcomes: dict[str, FieldOutcome] = {}
    attachment_outcomes: dict[str, dict] = {}
    inspection_errors: list[str] = []

    def progress(message: str) -> None:
        if on_progress:
            on_progress(message)

    def check_budget() -> None:
        if should_cancel and should_cancel():
            raise _Cancelled("Batch cancelled")
        if time.monotonic() >= deadline:
            raise TimeoutError("Application automation reached its four-minute budget")

    def checkpoint(*, force: bool = False) -> None:
        nonlocal last_checkpoint
        if not force and time.monotonic() - last_checkpoint < 1:
            return
        result.field_outcomes = [item.model_dump() for item in outcomes.values()]
        result.uploads = list(attachment_outcomes.values())
        result.required_empty = [
            item.label for item in outcomes.values()
            if item.required and item.state not in {"verified_filled", "preserved"}
        ]
        result.missing_profile = packet_profile_fields.missing_profile(
            [{"key": item.canonical_key, "label": item.label, "required": item.required}
             for item in outcomes.values()
             if item.reason_code == "unsupported_fact"],
            {item.label for item in outcomes.values() if item.state == "verified_filled"},
        )
        app.fill = result
        store.upsert(app)
        last_checkpoint = time.monotonic()

    def record(step_id: str, outcome: FieldOutcome) -> None:
        outcome.step_id = step_id
        outcome.observed_at = _now()
        outcomes[f"{step_id}:{outcome.frame_id}:{outcome.field_id}"] = outcome
        checkpoint()

    try:
        async with asyncio.timeout(APPLICATION_BUDGET_SECONDS):
            progress("Connecting to browser")
            async with browser.async_cdp_browser() as connected:
                if not connected.contexts:
                    raise RuntimeError("No connected browser context is available")
                context = connected.contexts[0]
                if fill_mode == "continue":
                    page = await browser.async_find_target(context, previous.browser_target_id)
                    if page is None:
                        raise RuntimeError("The recorded review tab is closed. Use Reopen and fill.")
                    progress("Resuming the current review tab")
                else:
                    page, target_id = await browser.open_background_page(connected, context)
                    result.browser_target_id = target_id
                    result.browser_url = str(page.url)
                    checkpoint(force=True)
                    check_budget()
                    url = app.final_url or app.posting_url
                    if not url:
                        raise RuntimeError("Application has no posting URL")
                    progress(f"Navigating to {url}")
                    await page.goto(url, wait_until="domcontentloaded", timeout=min(30000, int((deadline-time.monotonic())*1000)))
                    result.browser_url = str(page.url)
                    checkpoint(force=True)
                adapter = adapters.for_url(str(page.url))
                if type(adapter).enter_application is not adapters.FormAdapter.enter_application:
                    # Workday's "Apply", SmartRecruiters' "I'm interested"; other forms
                    # are the posting page itself.
                    progress(f"Opening the {adapter.platform} application")
                    page = await adapter.enter_application(
                        page, timeout_ms=min(5000, max(1, int((deadline-time.monotonic())*1000))),
                    )
                    result.browser_target_id = await browser.async_target_id(context, page)
                    result.browser_url = str(page.url)
                    checkpoint(force=True)
                route = await form_routes.choose_email_async(page, deadline=deadline)
                if route in {"ambiguous", "unchanged", "unavailable"} or route == "selected" and not isinstance(adapter, adapters.WorkdayAdapter):
                    result.status = "awaiting_review"
                    result.handoff_reason = (
                        "Email sign-in route selected; complete authentication in this tab, then Continue fill."
                        if route == "selected" else
                        f"Email sign-in route {route}; choose it in this tab, then Continue fill."
                    )
                    checkpoint(force=True)
                    return result
                if isinstance(adapter, adapters.WorkdayAdapter):
                    progress("Checking Workday authentication")
                    auth = await workday_auth.handle_workday_auth_async(page, applicant, deadline=deadline)
                    if auth != "authenticated":
                        result.status = "awaiting_otp" if auth == "verification_needed" else "awaiting_review"
                        result.handoff_reason = {
                            "verification_needed": "Enter the Workday verification code in this tab, then Continue fill.",
                            "credentials_needed": "Add an applicant email before continuing Workday authentication.",
                            "terms_needed": "Review and accept Workday account terms in this tab, then Continue fill.",
                            "failed": "Workday authentication could not be verified; review this tab.",
                        }[auth]
                        checkpoint(force=True)
                        return result
                final_step = False
                for step_number in range(1, MAX_FORM_STEPS + 1):
                    check_budget()
                    progress(f"Observing form step {step_number}")
                    observed = await scanner.scan(page)
                    inspection_errors.extend(observed.errors)
                    step_id = await adapter.step_id(page, observed.fields)
                    result.current_step_id = step_id
                    def identity(field):
                        return (
                            field.frame_id, field.document_generation, field.section_id,
                            field.repeater_row_id, field.label, field.control_kind,
                        )

                    pending = [(observed, field) for field in observed.fields]
                    seen = {identity(field) for field in observed.fields}
                    dependency_rescans = 0
                    for field_snapshot, field in pending:
                        check_budget()
                        policy, key = adapter.classify(field)
                        field.canonical_key = key
                        if field.control_kind == "file":
                            purpose = attachments.purpose_for(field)
                            if purpose and purpose in attachment_outcomes and attachment_outcomes[purpose].get("state") in {"verified", "preserved"}:
                                continue
                            progress(f"Step {step_number}: attaching {purpose or field.label}")
                            attachment = await attachments.upload(
                                field_snapshot, field, pkt,
                                applicant_name=fields.get("full_name", "Applicant"),
                                role=app.role, out_dir=config.APPLICATIONS_OUTPUT_DIR / source_job_id,
                                deadline=deadline,
                            )
                            attachment_outcomes[purpose or field.field_id] = attachment.model_dump()
                            record(step_id, FieldOutcome(
                                field_id=field.field_id, frame_id=field.frame_id,
                                label=field.label,
                                state="verified_filled" if attachment.state == "verified" else
                                "preserved" if attachment.state == "preserved" else "unanswered",
                                required=field.required,
                                observed_value=attachment.observed_filename,
                                reason_code="" if attachment.state in {"verified", "preserved"} else attachment.state,
                            ))
                            continue
                        if policy == "manual_review":
                            record(step_id, FieldOutcome(
                                field_id=field.field_id, frame_id=field.frame_id,
                                label=field.label, canonical_key=key,
                                state="manual_review", required=field.required,
                                observed_value=field.current_value, reason_code=key,
                            ))
                            continue
                        has_committed_value = bool(field.current_value) and (
                            field.control_kind != "combobox" or field.selection_state == "committed"
                        )
                        correct_preferred = (
                            key == "preferred_name" and fields.get("preferred_name")
                            and fields.get("first_name")
                            and field.current_value.strip().casefold() == fields["first_name"].strip().casefold()
                            and fields["preferred_name"].strip().casefold() != fields["first_name"].strip().casefold()
                        )
                        if has_committed_value and not correct_preferred:
                            record(step_id, FieldOutcome(
                                field_id=field.field_id, frame_id=field.frame_id,
                                label=field.label, canonical_key=key,
                                state="invalid_existing" if field.validation_messages else "preserved",
                                required=field.required,
                                observed_value=field.current_value,
                                answer_source="existing_browser_answer",
                                reason_code="site_validation" if field.validation_messages else "",
                            ))
                            continue
                        value = adapter.value_for(field, key, pkt, fields) if policy == "known" else ""
                        if key == "race" and fields.get("race_detail"):
                            value = fields["race_detail"]
                        # "decline" picks a decline option; it is never typed into a text box.
                        if value == "decline" and field.control_kind in {"text", "textarea"}:
                            value = ""
                        generated = False
                        remembered = False
                        if not value and not field.current_value:
                            recalled = answer_memory.recall(
                                field.label, company=app.company or "", ats=app.ats or "",
                                canonical_key=key or "",
                            )
                            if recalled is not None and recalled.needs_review:
                                record(step_id, FieldOutcome(
                                    field_id=field.field_id, frame_id=field.frame_id,
                                    label=field.label, canonical_key=key,
                                    state="unanswered", required=field.required,
                                    reason_code="saved_answer_other_company",
                                ))
                                continue
                            if recalled is not None:
                                value = recalled.answer
                                remembered = True
                        if not value and not field.current_value and field_catalog.may_generate_written_answer(field):
                            progress(f"Step {step_number}: drafting {field.label}")
                            max_length = field.constraints.get("max_length")
                            max_chars = min(1500, max_length) if isinstance(max_length, int) and max_length > 0 else 1500
                            try:
                                with config.pinned(settings.model_spec):
                                    drafted = await answer.answer_question_async(
                                        field.label, resume=resume, bullets=bullets,
                                        requirements=requirements, profile=applicant,
                                        max_chars=max_chars, jd_text=jd_text,
                                        deadline=deadline,
                                        extras=answer.AnswerExtras(company=app.company or ""),
                                    )
                                if drafted.answer and not drafted.warnings:
                                    value = drafted.answer
                                    generated = True
                            except Exception as exc:  # noqa: BLE001
                                progress(f"Written answer needs review: {field.label} ({type(exc).__name__})")
                        if not value:
                            record(step_id, FieldOutcome(
                                field_id=field.field_id, frame_id=field.frame_id,
                                label=field.label, canonical_key=key,
                                state="unanswered", required=field.required,
                                observed_value=field.current_value,
                                reason_code=(
                                    "authorization_elsewhere"
                                    if authorization_elsewhere and key == "authorized_to_work"
                                    else "unsupported_fact" if policy == "known"
                                    else "unknown_field"
                                ),
                            ))
                            continue
                        if key == "phone":
                            current_phone_group = await scanner.scan(page)
                            separate_code_committed = any(
                                other.section_id and other.section_id == field.section_id
                                and other.control_kind in {"combobox", "native_select"}
                                and other.current_value
                                and (other.control_kind != "combobox" or other.selection_state == "committed")
                                and field_catalog.classify(other)[1] == "phone_country_code"
                                for other in current_phone_group.fields
                            )
                            value = _national_phone_value(
                                value, fields.get("phone_country_code", ""),
                                separate_code_committed=separate_code_committed,
                            )
                            if not value:
                                record(step_id, FieldOutcome(
                                    field_id=field.field_id, frame_id=field.frame_id,
                                    label=field.label, canonical_key=key, state="unanswered",
                                    required=field.required, reason_code="phone_number_missing",
                                ))
                                continue
                        if key == "earliest_start":
                            value = _availability_for_field(value, field.control_kind)
                        if key == "notice_period" and field.control_kind == "text":
                            value = _notice_for_field(value, field.label)
                        progress(f"Step {step_number}: filling {field.label or key}")
                        outcome = await controls.apply_value(
                            page, field_snapshot, field, value,
                            phone_region=fields.get("phone_country_region", ""),
                            replace_existing=bool(correct_preferred),
                        )
                        if (
                            key == "race" and value == fields.get("race_detail")
                            and outcome.state == "unanswered" and outcome.reason_code == "no_match"
                            and fields.get("race")
                        ):
                            outcome = await controls.apply_value(
                                page, field_snapshot, field, fields["race"],
                                phone_region=fields.get("phone_country_region", ""),
                            )
                        outcome.answer_source = (
                            "generated" if generated else "memory" if remembered else "profile"
                        )
                        record(step_id, outcome)
                        if (
                            outcome.state == "verified_filled"
                            and field.control_kind in {"combobox", "native_select", "radio_group", "checkbox"}
                            and dependency_rescans < 2
                        ):
                            dependency_rescans += 1
                            revealed = await scanner.scan(page)
                            inspection_errors.extend(revealed.errors)
                            for new_field in revealed.fields:
                                marker = identity(new_field)
                                if marker not in seen:
                                    seen.add(marker)
                                    pending.append((revealed, new_field))
                    for model_pass in range(2):
                        check_budget()
                        latest = await scanner.scan(page)
                        unresolved_choices = [
                            item for item in latest.fields
                            if not item.current_value and item.control_kind in {"native_select", "radio_group"}
                            and field_catalog.classify(item)[0] == "unknown"
                            and any(option.enabled and not option.placeholder for option in item.options)
                        ]
                        if not unresolved_choices:
                            break
                        progress(f"Step {step_number}: resolving remaining choices, pass {model_pass + 1}")
                        try:
                            with config.pinned(settings.model_spec):
                                proposals = await model_resolver.propose(
                                    unresolved_choices, model_resolver.safe_facts(fields), deadline=deadline,
                                )
                        except Exception as exc:  # noqa: BLE001
                            progress(f"Choice resolution needs review ({type(exc).__name__})")
                            break
                        if not proposals:
                            break
                        for field, value in proposals:
                            check_budget()
                            result_field = await controls.apply_value(page, latest, field, value)
                            result_field.answer_source = "model_mapped_profile_fact"
                            record(step_id, result_field)
                    if isinstance(adapter, adapters.WorkdayAdapter):
                        workday_step = workday_page.active_step(await page.evaluate(workday_page.SNAPSHOT_JS)).casefold()
                        if "experience" in workday_step:
                            years_filled, years_review = await workday_repeaters.fill_education_years_async(page, pkt)
                            inspection_errors.extend(years_review)
                            for year in years_filled:
                                record(step_id, FieldOutcome(
                                    field_id=year["label"], frame_id="main", label=year["label"],
                                    canonical_key="education_start_year" if "firstYear" in year["label"] else "education_end_year",
                                    state="verified_filled", observed_value=year["value"], answer_source="resume",
                                ))
                    result.browser_url = str(page.url)
                    checkpoint(force=True)
                    settled = await scanner.scan(page)
                    inspection_errors.extend(settled.errors)
                    if isinstance(adapter, adapters.WorkdayAdapter):
                        accepted, unresolved = await form_routes.accept_workday_async(page)
                        for item in accepted:
                            matched = [field for field in settled.fields if field.control_kind == "checkbox" and
                                       (field.label == item["label"] or item["id"] and field.constraints.get("id") == item["id"])]
                            if len(matched) == 1:
                                field = matched[0]
                                record(step_id, FieldOutcome(
                                    field_id=field.field_id, frame_id=field.frame_id, label=field.label,
                                    canonical_key="workday_consent", state="verified_filled",
                                    required=True, observed_value="checked", answer_source="required_consent",
                                ))
                            else:
                                record(step_id, FieldOutcome(
                                    field_id=f"workday-consent:{item['id'] or item['label']}",
                                    frame_id="main", label=item["label"], canonical_key="workday_consent",
                                    state="verified_filled", required=True, observed_value="checked",
                                    answer_source="required_consent",
                                ))
                        if unresolved:
                            inspection_errors.extend(f"Required consent: {label}" for label in unresolved)
                            break
                    settled_step_id = await adapter.step_id(page, settled.fields)
                    next_button = await adapter.advance(page)
                    if next_button is None:
                        review_step = False
                        if isinstance(adapter, adapters.WorkdayAdapter):
                            review_step = workday_page.is_review_step(await page.evaluate(workday_page.SNAPSHOT_JS))
                        final_step = await adapter.final_submit(page) is not None or review_step
                        break
                    check_budget()
                    progress(f"Advancing from form step {step_number}")
                    await clicks.async_safe_click(next_button, purpose="advance", timeout=min(5000, int((deadline-time.monotonic())*1000)))
                    await page.wait_for_timeout(300)
                    next_scan = await scanner.scan(page)
                    next_step_id = await adapter.step_id(page, next_scan.fields)
                    if next_step_id == settled_step_id:
                        progress("Form step did not advance; leaving tab for review")
                        break
                    result.current_step_id = next_step_id
                    result.browser_url = str(page.url)
                    checkpoint(force=True)
                # A click result is only an attempt. Reconcile the current step
                # against a fresh observation before publishing review/readiness.
                current = await scanner.scan(page)
                inspection_errors.extend(current.errors)
                current_step_id = await adapter.step_id(page, current.fields)
                result.current_step_id = current_step_id
                earlier = {
                    item.field_id: item for item in outcomes.values()
                    if item.step_id in {step_id, current_step_id}
                }
                outcomes = {
                    identity: item for identity, item in outcomes.items()
                    if item.step_id not in {step_id, current_step_id}
                }
                for field in current.fields:
                    if field.control_kind == "file":
                        purpose = attachments.purpose_for(field)
                        if purpose:
                            previous_upload = attachment_outcomes.get(purpose, {})
                            if field.current_value:
                                attachment_outcomes[purpose] = {
                                    **previous_upload, "purpose": purpose,
                                    "state": "preserved" if previous_upload.get("state") != "verified" else "verified",
                                    "observed_filename": field.current_value,
                                }
                            elif previous_upload.get("state") in {"verified", "preserved"}:
                                attachment_outcomes[purpose] = {
                                    **previous_upload, "state": "unverifiable",
                                    "reason": "Attachment is no longer visible in its upload component",
                                }
                    record(current_step_id, _current_outcome(field, earlier.get(field.field_id)))
                result.final_step_reached = final_step
                if settings.cover_letter and "cover_letter" not in attachment_outcomes:
                    attachment_outcomes["cover_letter"] = {
                        "purpose": "cover_letter", "state": "not_requested",
                        "reason": "No cover-letter upload control was observed",
                    }
                result.ready_to_submit = (
                    final_step and not inspection_errors and all(
                        item.state in {"verified_filled", "preserved"} or
                        (not item.required and item.state == "unanswered")
                        for item in outcomes.values()
                    )
                    and not any(item.state == "manual_review" for item in outcomes.values())
                    and all(item.get("state") in {"verified", "preserved", "not_requested"} for item in attachment_outcomes.values())
                )
                # Submission stays disabled until attachment, authentication and
                # generated-answer parity gates are wired into this engine.
                result.status = "awaiting_review"
                result.handoff_reason = "Ready for review" if result.ready_to_submit else "Fields need review"
                checkpoint(force=True)
    except (_Cancelled, TimeoutError) as exc:
        result.status = "awaiting_review"
        result.handoff_reason = str(exc)
    except Exception as exc:  # noqa: BLE001
        result.status = "fill_failed"
        result.error = str(exc)
        result.handoff_reason = str(exc)
    finally:
        checkpoint(force=True)
        store.set_status(app, result.status, note=result.handoff_reason)
        app.fill = result
        store.upsert(app)
    return result
