"""Deterministic ATS form fill via the host browser over CDP (Edge recommended).

Injects ``filler.js``, uploads resume PDF, drafts long-text leftovers through
``answer.answer_question``, then either stops for review or auto-submits when
``ats`` is listed in ``ApplySettings.auto_submit_ats``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import time
from collections.abc import Callable
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config, data, report
from resume_tailor.apply import (
    answer,
    answer_memory,
    ats_hints,
    browser,
    clicks,
    field_matcher,
    hybrid_resolver,
    store,
    workday_auth,
    workday_flow,
)
from resume_tailor.apply import packet as apply_packet
from resume_tailor.apply import profile as profile_mod
from resume_tailor.apply import salary as salary_mod
from resume_tailor.apply.store import FillResult
from resume_tailor.jd import JobRequirements
from resume_tailor.web.schemas import ApplySettings, JobSettings


def _is_locator_present_and_visible(loc: Any) -> bool:
    """Safely check if locator exists and is visible without tripping over MagicMock in tests."""
    try:
        count = loc.count()
        if isinstance(count, int) and count > 0:
            return bool(loc.is_visible())
    except Exception:  # noqa: BLE001
        pass
    return False


def _locator_exists(loc: Any) -> bool:
    """Safely check if locator exists without tripping over MagicMock in tests."""
    try:
        count = loc.count()
        if isinstance(count, int):
            return count > 0
    except Exception:  # noqa: BLE001
        pass
    return False


def _click_and_track_popup(page: Any, context: Any, click_fn: Callable[[], None]) -> Any:
    """Execute click_fn while watching for popups.

    Returns the new active page if a popup was opened.
    """
    if not context or not hasattr(context, "expect_page"):
        click_fn()
        return page
    try:
        with context.expect_page(timeout=5000) as page_info:
            click_fn()
        new_page = page_info.value
        with contextlib.suppress(Exception):
            new_page.wait_for_load_state("domcontentloaded", timeout=45_000)
        return new_page
    except Exception:  # noqa: BLE001
        return page


def find_and_click_apply(page: Any, ats: str, context: Any = None) -> Any:
    """Find and click the Apply button/link, returning the resulting active page."""
    current_page = page

    # 1. ATS-specific hints
    for click_sel in ats_hints.ATS_PRE_FILL_CLICKS.get(ats.lower(), []):
        try:
            loc = current_page.locator(click_sel).first
            if _is_locator_present_and_visible(loc):
                current_page = _click_and_track_popup(
                    current_page, context, lambda loc=loc: clicks.safe_click(loc, purpose="enter", timeout=4000)
                )
                current_page.wait_for_timeout(1000)
                break
        except Exception:  # noqa: BLE001
            pass

    # 2. Semantic role-based button/link discovery
    apply_pattern = re.compile(
        r"\bapply(\s+now|\s+for\s+this\s+job|\s+manually)?\b", re.IGNORECASE
    )
    for role in ("button", "link"):
        try:
            loc = current_page.get_by_role(role, name=apply_pattern).first
            if _is_locator_present_and_visible(loc):
                current_page = _click_and_track_popup(
                    current_page, context, lambda loc=loc: clicks.safe_click(loc, purpose="enter", timeout=4000)
                )
                current_page.wait_for_timeout(1000)
                break
        except Exception:  # noqa: BLE001
            pass

    # 3. Workday "Apply Manually" modal handling
    try:
        manual_btn = current_page.get_by_role(
            "button", name=re.compile(r"apply\s+manually", re.IGNORECASE)
        ).first
        if _is_locator_present_and_visible(manual_btn):
            current_page = _click_and_track_popup(
                current_page, context, lambda: clicks.safe_click(manual_btn, purpose="enter", timeout=4000)
            )
            current_page.wait_for_timeout(1000)
    except Exception:  # noqa: BLE001
        pass

    return current_page


def _detect_barriers(page: Any) -> str | None:
    """Detect blocking barriers like Cloudflare walls or interactive CAPTCHAs.

    Invisible reCAPTCHA background badges ('size=invisible') are explicitly ignored
    since they do not block form filling or require user interaction.
    """
    # 1. Cloudflare challenge wall
    for cf_sel in ("#cf-challenge", "div#challenge-running", "div#challenge-stage"):
        try:
            loc = page.locator(cf_sel).first
            if _is_locator_present_and_visible(loc):
                return "Cloudflare challenge detected"
        except Exception:  # noqa: BLE001
            pass

    # 2. Interactive CAPTCHA challenge or checkbox
    try:
        recaptchas = page.locator("iframe[src*='recaptcha']").all()
        if isinstance(recaptchas, list):
            for iframe in recaptchas:
                get_attr = getattr(iframe, "get_attribute", None)
                src = str(get_attr("src") if callable(get_attr) else "")
                if "size=invisible" in src:
                    continue
                if _is_locator_present_and_visible(iframe):
                    return "CAPTCHA detected"
    except Exception:  # noqa: BLE001
        pass

    other_captcha_selectors = [
        "iframe[title*='recaptcha challenge' i]",
        "iframe[src*='hcaptcha'][src*='checkbox']",
        "iframe[src*='hcaptcha'][src*='challenge']",
        "iframe[src*='turnstile']",
        ".g-recaptcha:not([data-size='invisible'])",
    ]
    for sel in other_captcha_selectors:
        try:
            loc = page.locator(sel).first
            if _is_locator_present_and_visible(loc):
                return "CAPTCHA detected"
        except Exception:  # noqa: BLE001
            pass

    return None


#: A button that finishes the application is never a wizard "advance". Workday's Review
#: step labels its Submit button with the same `pageFooterNextButton` automation id as
#: Next, and clicking it submitted a Philips application (2026-09-24).
_SUBMIT_TEXT = clicks.SUBMIT_TEXT
_is_submit_like = clicks.is_submit_like


def _find_advance_button(page: Any) -> Any | None:
    """Find wizard 'Next' / 'Continue' / 'Save & Continue' button if present.

    Never returns a button whose text reads as submitting the application.
    """
    patterns = [
        re.compile(r"^\s*(next|continue|save\s*(?:&|and)\s*continue|proceed)\s*$", re.IGNORECASE),
    ]
    for pat in patterns:
        try:
            btn = page.get_by_role("button", name=pat).first
            if _is_locator_present_and_visible(btn) and not _is_submit_like(btn):
                return btn
        except Exception:  # noqa: BLE001
            pass

    advance_selectors = [
        "button[data-automation-id='pageFooterNextButton']",
        "button[data-automation-id='bottom-navigation-next-button']",
        "button[data-automation-id='page-footer-next-button']",
        "button[data-test-id='next-button']",
        "button.next-button",
        "button.btn-next",
    ]
    for sel in advance_selectors:
        try:
            loc = page.locator(sel).first
            if _is_locator_present_and_visible(loc) and not _is_submit_like(loc):
                return loc
        except Exception:  # noqa: BLE001
            pass
    return None


def _find_submit_button(page: Any, hints: dict[str, str]) -> Any | None:
    """Find the final submit button."""
    submit_sel = _hint_selector(hints, "submit")
    if submit_sel:
        try:
            loc = page.locator(submit_sel).first
            if _is_locator_present_and_visible(loc):
                return loc
        except Exception:  # noqa: BLE001
            pass
    try:
        btn = page.get_by_role(
            "button",
            name=re.compile(r"^\s*(submit|submit\s+application)\s*$", re.IGNORECASE),
        ).first
        if _is_locator_present_and_visible(btn):
            return btn
    except Exception:  # noqa: BLE001
        pass
    return None


def decide_submit_action(
    *,
    ats: str,
    settings: ApplySettings,
    ready_to_submit: bool,
    submit_mode: Literal["auto_submit", "awaiting_review"] | None = None,
) -> Literal["auto_submit", "awaiting_review"]:
    """Return ``auto_submit`` when policy allows it, else ``awaiting_review``."""
    if submit_mode == "awaiting_review":
        return "awaiting_review"
    if ats.lower() == "workday":
        # Workday applications are always handed over for review, whatever the settings.
        return "awaiting_review"
    if submit_mode == "auto_submit" and not settings.auto_submit_enabled:
        return "awaiting_review"
    auto = settings.auto_submit_enabled and ats.lower() in {
        a.lower() for a in settings.auto_submit_ats
    }
    if auto and ready_to_submit:
        return "auto_submit"
    return "awaiting_review"


def _load_filler_js() -> str:
    """Read the packaged filler script."""
    return (
        resources.files("resume_tailor.apply")
        .joinpath("filler.js")
        .read_text(encoding="utf-8")
    )


def _load_readiness_js() -> str:
    """Read the packaged required-empty checker, if present."""
    path = resources.files("resume_tailor.apply").joinpath("filler_readiness.js")
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return "( ) => ({ required_empty: [] })"


def _scanned_nothing(merged: dict[str, Any], filled_start: int) -> bool:
    """True when this step's passes neither filled nor even saw a single control."""
    return len(merged.get("filled") or []) == filled_start and not any(
        merged.get(key) for key in ("leftovers", "long_text", "file_inputs", "required_empty")
    )


def _synonym_payload() -> list[list[str]]:
    """Serialise ``SYNONYMS`` for the page evaluate argument."""
    return [[pat, key] for pat, key in ats_hints.SYNONYMS]


def _hint_selector(hints: dict[str, str], special: str) -> str | None:
    """Return the CSS selector mapped to a reserved hint value like ``submit``."""
    if special in hints and special not in ats_hints.CANONICAL_FIELD_KEYS:
        return special
    for selector, value in hints.items():
        if value == special:
            return selector
    return None


def _form_step_signature(page: Any) -> tuple[str, tuple[str, ...]] | None:
    """Identify visible controls so a disabled or ineffective Next cannot loop forever."""
    try:
        controls = page.locator("input:visible, select:visible, textarea:visible").evaluate_all(
            "els => els.map(el => [el.tagName, el.id, el.name, el.getAttribute('aria-label')].join(':'))"
        )
        if isinstance(controls, list) and all(isinstance(item, str) for item in controls):
            return (str(page.url), tuple(controls))
    except Exception:  # noqa: BLE001
        pass
    return None


def _submission_confirmed(
    page: Any,
    *,
    before_url: str,
    before_body: str,
    confirmation_text: str,
) -> bool:
    """Require a post-click confirmation signal that was absent before submission."""
    try:
        submitted_marker = page.locator(
            "[data-automation-id='applicationSubmitted'], "
            "[data-testid='application-submitted'], .application-confirmation"
        ).first
        if _is_locator_present_and_visible(submitted_marker):
            return True
    except Exception:  # noqa: BLE001
        pass
    after_body = page.inner_text("body")
    marker = confirmation_text.casefold().strip()
    marker_is_new = bool(
        marker
        and marker in after_body.casefold()
        and marker not in before_body.casefold()
    )
    return marker_is_new


def _attachment_purpose(
    label: str, selector: str, hints: dict[str, str], *, hint_key: str = "", section: str = "",
) -> str | None:
    """Classify one file control without relying on its position in the DOM.

    ``hint_key`` is what ``filler.js`` found by ``el.matches(hint)`` (Workday's generic
    "Upload a file (5MB max)" input is the resume by hint); ``section`` is the enclosing
    heading ("Resume/CV") for labels that name neither document.
    """
    text = f"{label} {section} {selector}".casefold()
    if "transcript" in text:
        return "transcript"
    if "cover" in text or "letter" in text:
        return "cover_letter"
    if hint_key == "resume_upload" or "resume" in text or "cv" in text:
        return "resume"
    for hint_selector, key in hints.items():
        if key == "resume_upload" and hint_selector == selector:
            return "resume"
    return None


def _set_and_verify_file(target: Any, selector: str, path: str) -> bool:
    """Verify either a retained input or an ATS replacement showing the filename."""
    control = target.locator(selector).first
    control.set_input_files(path, timeout=5000)
    expected = Path(path).name
    with contextlib.suppress(Exception):
        actual = control.evaluate(
            "el => el.files && el.files[0] ? el.files[0].name : ''",
            timeout=2000,
        )
        if str(actual) == expected:
            return True
    with contextlib.suppress(Exception):
        target.get_by_text(expected, exact=False).first.wait_for(state="visible", timeout=3000)
        return True
    return False


def _fill_declared_combobox(target: Any, item: dict[str, Any], fields: dict[str, str]) -> str | None:
    """Resolve a known fact from a visible option, never from typed search text."""
    key = str(item.get("key") or "")
    selector = str(item.get("selector") or "")
    if not selector or key in {"salary_expectation", ""}:
        return None
    for value in field_matcher.choice_values(key, fields):
        if value and hybrid_resolver._select_combobox_option(  # noqa: SLF001
            target, selector, value, key=key, phone_region=fields.get("phone_country_region", ""),
        ):
            return value
    return None


def _availability_note(earliest_start: str, jd_text: str) -> str | None:
    """Flag a declared availability later than an explicit program start in the JD."""
    try:
        available = date.fromisoformat(earliest_start)
    except ValueError:
        return None
    match = re.search(
        r"(?:program|internship)[^\n]{0,100}?\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
        jd_text,
        re.I,
    )
    if not match:
        return None
    try:
        starts = datetime.strptime(match.group(0)[match.start(1) - match.start():].replace(",", ""), "%B %d %Y").date()
    except ValueError:
        return None
    if available <= starts:
        return None
    return f"Availability {available.isoformat()} is after the posting's program start {starts.isoformat()}; review before submitting"


def _observe_fields(page: Any, filler_js: str, hints: dict[str, str], attempted: dict[tuple[int, str], dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    """Read current selected values without filling any new answer."""
    observed: dict[tuple[int, str], dict[str, Any]] = {}
    for frame_index, frame in enumerate(page.frames):
        with contextlib.suppress(Exception):
            current = frame.evaluate(filler_js, {"fields": {}, "hints": hints, "synonyms": _synonym_payload()})
            for item in current.get("filled") or []:
                selector = item.get("selector")
                if not selector:
                    continue
                prior = attempted.get((frame_index, selector), {})
                observed[(frame_index, selector)] = {
                    **item,
                    "key": prior.get("key") or item.get("key"),
                    "preserved": bool(prior.get("preserved")),
                    "frame_index": frame_index,
                }
    return observed


def _stage_attachment(
    source: str,
    *,
    purpose: Literal["resume", "cover_letter"],
    applicant_name: str,
    role: str,
    out_dir: Path,
) -> str:
    """Copy an internal artifact to the user-facing filename sent to the ATS."""
    source_path = Path(source)
    suffix = source_path.suffix or ".pdf"
    if purpose == "resume":
        filename = report.export_filename(applicant_name, role, suffix=suffix)
    else:
        resume_name = report.export_filename(applicant_name, role, suffix=suffix)
        filename = resume_name.replace(f" Resume - ", " Cover Letter - ", 1)
    attachment_dir = out_dir / "attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    staged = attachment_dir / filename
    if source_path.resolve() != staged.resolve():
        shutil.copyfile(source_path, staged)
    return str(staged)


def _job_artifacts(job_id: str) -> tuple[dict[str, str], JobRequirements | None, str]:
    """Load bullets, requirements, and JD text for the answer stage."""
    out = config.OUTPUT_DIR / "jobs" / job_id
    bullets: dict[str, str] = {}
    bullets_path = out / "bullets.json"
    if bullets_path.is_file():
        raw = json.loads(bullets_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            bullets = {str(k): str(v) for k, v in raw.items()}
    requirements: JobRequirements | None = None
    req_path = out / "requirements.json"
    if req_path.is_file():
        requirements = JobRequirements.model_validate_json(
            req_path.read_text(encoding="utf-8")
        )
    jd_text = ""
    jd_path = out / "jd.txt"
    if jd_path.is_file():
        jd_text = jd_path.read_text(encoding="utf-8")
    return bullets, requirements, jd_text


def _fill_workday_experience_and_education(
    page: Any,
    pkt: apply_packet.Packet,
    progress: Callable[[str], None],
) -> tuple[list[dict[str, str]], list[str]]:
    """Fill only Workday rows whose identity is unambiguous; preserve manual rows."""
    from resume_tailor.apply import workday_repeaters

    return workday_repeaters.fill(page, pkt, progress, select=workday_flow.select_listbox)


def _guard_file_chooser(page: Any, progress: Callable[[str], None]) -> None:
    """Swallow any OS file picker a stray click opens while the fill runs.

    Attachments are set with ``set_input_files`` and never need the picker; with a
    ``filechooser`` listener attached, Playwright intercepts the dialog instead of
    showing it, so nothing is left blocking the applicant's browser. The interception
    ends with the CDP connection, before the tab is handed over.
    """
    def _blocked(_chooser: Any) -> None:
        # No page calls from inside a sync Playwright event handler: log only.
        progress("blocked an unexpected file picker")

    with contextlib.suppress(Exception):
        page.on("filechooser", _blocked)


def _commit_workday_textareas(frames: list[Any], items: list[Any]) -> None:
    """Re-enter the filler's textarea answers with real input events, then blur.

    Workday's questionnaire textareas ignore a value set from page JS (live 2026-09-24,
    Excellus: the salary box showed "$18/hour" yet validated as empty); its text inputs
    accept one, so only textareas are re-committed.
    """
    for item in items:
        if not isinstance(item, dict) or item.get("preserved") or not item.get("selector"):
            continue
        index = int(item.get("frame_index") or 0)
        target = frames[index] if 0 <= index < len(frames) else frames[0]
        with contextlib.suppress(Exception):
            control = target.locator(str(item["selector"])).first
            if control.evaluate("el => el.tagName") != "TEXTAREA":
                continue
            control.fill(str(item.get("value") or ""), timeout=3000)
            control.evaluate("el => el.blur()")


def _workday_handoff(
    app: Any,
    context: Any,
    page: Any,
    reason: str,
    *,
    status: Literal["awaiting_review", "awaiting_otp", "fill_failed"] = "awaiting_review",
    error: str | None = None,
) -> FillResult:
    """Leave the Workday tab open for the applicant with a readable reason."""
    workday_flow.close_stray_popups(page)
    result = FillResult(
        error=error,
        status=status,
        browser_target_id=browser.target_id(context, page),
        browser_url=str(page.url),
        handoff_reason=reason,
    )
    store.set_status(app, status, note=reason)
    app.fill = result
    store.upsert(app)
    return result


def fill_application(
    source_job_id: str,
    *,
    settings: ApplySettings | None = None,
    submit_mode: Literal["auto_submit", "awaiting_review"] | None = None,
    fill_mode: Literal["initial", "continue", "reopen"] = "initial",
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[str], None] | None = None,
    applicant_profile: profile_mod.ApplicantProfile | None = None,
) -> FillResult:
    """Fill one application's ATS form; leave the tab open under policy A."""
    def progress(msg: str) -> None:
        """Forward a progress line when a callback is set."""
        if on_progress:
            on_progress(msg)

    app = store.get(source_job_id)
    if app is None:
        raise KeyError(f"Unknown application {source_job_id!r}")
    from resume_tailor.apply import preparation

    if settings is None:
        from resume_tailor import workspace

        settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
    eligibility = preparation.check(app, require_cover=settings.cover_letter)
    if not eligibility.eligible:
        raise RuntimeError(f"Application needs Prepare: {', '.join(eligibility.reasons)}")
    engine_name = config.apply_fill_engine()
    if engine_name not in {"legacy", "verified"}:
        raise ValueError(f"Unsupported APPLY_FILL_ENGINE={engine_name!r}")
    if engine_name == "verified":
        from resume_tailor.apply import engine

        return asyncio.run(engine.fill_application(
            source_job_id, settings=settings, submit_mode=submit_mode,
            fill_mode=fill_mode, should_cancel=should_cancel,
            on_progress=on_progress, applicant_profile=applicant_profile,
        ))

    if not app.job_id:
        result = FillResult(error="No tailored job_id on application", status="fill_failed")
        store.set_status(app, "fill_failed", note=result.error or "")
        app.fill = result
        store.upsert(app)
        return result

    previous_fill = FillResult.model_validate(app.fill) if app.fill else FillResult()
    store.set_status(app, "filling", note="")
    store.upsert(app)
    progress("building packet")
    pkt = (
        apply_packet.build_packet(app.job_id)
        if applicant_profile is None else
        apply_packet.build_packet(app.job_id, applicant_profile=applicant_profile)
    )
    profile = applicant_profile
    if profile is None:
        profile, _ = profile_mod.load_profile()
    resume = data.load()
    contact_name = getattr(getattr(resume, "contact", None), "name", "")
    bullets, requirements, jd_text = _job_artifacts(app.job_id)
    filler_js = _load_filler_js()
    readiness_js = _load_readiness_js()
    hints = dict(pkt.field_hints) or ats_hints.hints_for(app.ats)
    fields = dict(pkt.fields)
    if fields.get("degree_level") and not fields.get("degree_name"):
        # Packets prepared before ``degree_name`` existed.
        fields["degree_name"] = apply_packet.degree_name(pkt.education, fields["degree_level"])
    fields.update(salary_mod.salary_fields(
        role=app.role or pkt.role or "", listing_salary=app.salary or "", jd_text=jd_text or "",
        hourly_max=profile.salary_hourly_max, yearly_max=profile.salary_yearly_max,
    ))
    applicant_name = str(
        fields.get("full_name")
        or " ".join(
            part for part in (fields.get("first_name", ""), fields.get("last_name", "")) if part
        )
        or "Applicant"
    )
    if isinstance(contact_name, str) and contact_name.strip():
        applicant_name = contact_name.strip()
    if profile.f1_opt_eligible is not None:
        fields["f1_opt_eligible"] = "Yes" if profile.f1_opt_eligible else "No"
    if profile.pronouns:
        fields["pronouns"] = profile.pronouns
    # "Authorized to work" answers for the profile's country; a posting clearly in another
    # country leaves eligibility questions to the applicant, the model included.
    authorization_note = ""
    mismatch = apply_packet.authorization_mismatch(profile, app.location or "")
    if mismatch:
        fields.pop("authorized_to_work", None)
        pkt.fields.pop("authorized_to_work", None)
        profile = profile.model_copy(update={"authorized_to_work": None})
        authorization_note = (
            f"Job is in {mismatch[0]}; your work authorization is for {mismatch[1]}. "
            "Answer eligibility questions yourself"
        )
        progress(authorization_note)
    url = app.final_url or app.posting_url
    is_workday = (app.ats or pkt.ats or "").lower() == "workday" or workday_auth.is_workday_url(url or "")
    out_dir = config.APPLICATIONS_OUTPUT_DIR / source_job_id
    deadline = time.monotonic() + 240
    page: Any | None = None
    target_id = previous_fill.browser_target_id

    try:
        progress("connecting to browser")
        with browser.cdp_browser() as pw_browser:
            context = (
                pw_browser.contexts[0]
                if pw_browser.contexts
                else pw_browser.new_context()
            )
            if fill_mode == "continue":
                page = browser.find_target(context, target_id)
                if page is None:
                    raise RuntimeError("Review tab was closed. Use Reopen and fill to start a new tab; unsaved answers may be lost.")
                progress("continuing the existing application tab")
                if is_workday:
                    # A popup left open by the last fill or by the applicant blocks this one.
                    workday_flow.close_stray_popups(page)
            else:
                page = context.new_page()
                target_id = browser.target_id(context, page)
                app.fill = previous_fill.model_copy(update={"browser_target_id": target_id, "browser_url": url})
                store.upsert(app)
            with contextlib.suppress(Exception):
                page.set_default_timeout(10_000)
            if fill_mode != "continue":
                progress(f"opening posting: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=min(60_000, max(1000, int((deadline - time.monotonic()) * 1000))))
                progress("posting loaded; waiting for form controls")
                with contextlib.suppress(Exception):
                    page.wait_for_load_state("networkidle", timeout=min(10_000, max(1000, int((deadline - time.monotonic()) * 1000))))
                progress("locating application form")
                if not is_workday:
                    page = find_and_click_apply(page, app.ats or pkt.ats, context=context)
            if is_workday:
                # Continue fill resumes from wherever the tab is (posting, dialog, auth, form).
                page, wd_state = workday_flow.enter_application(
                    page, context, deadline=deadline, progress=progress,
                )
                progress(f"Workday screen: {wd_state}")
                if wd_state in {"already_applied", "unavailable", "posting", "start_dialog", "unknown"}:
                    reason = {
                        "already_applied": "Workday says you have already applied to this job.",
                        "unavailable": "Posting is unavailable: Workday says this job no longer exists.",
                    }.get(
                        wd_state,
                        f"Workday application did not open (stuck on {wd_state}); open it in this tab, then Continue fill.",
                    )
                    return _workday_handoff(
                        app, context, page, reason, error=reason if wd_state == "unavailable" else None,
                    )
            if fill_mode != "continue" or is_workday:
                target_id = browser.target_id(context, page)
                app.fill = previous_fill.model_copy(update={"browser_target_id": target_id, "browser_url": page.url})
                store.upsert(app)
            progress("application form opened")

            #: Refreshes of Workday's "Something went wrong" page this fill may still spend.
            site_error_left = 2 * workday_flow.SITE_ERROR_RELOADS
            site_error_msg = (
                "Workday kept showing 'Something went wrong' after refreshing. Close other tabs "
                "open on this application, refresh this tab, then Continue fill."
            )

            def recover_site_error() -> bool:
                nonlocal site_error_left
                recovered, used = workday_flow.recover_site_error(
                    page, deadline=deadline, progress=progress,
                    attempts=min(workday_flow.SITE_ERROR_RELOADS, max(0, site_error_left)),
                )
                site_error_left -= used
                return recovered

            # Select an explicit email route before any site-specific credential flow.
            ats_name = (app.ats or pkt.ats or "").lower()
            from resume_tailor.apply import form_routes  # noqa: PLC0415
            route = form_routes.choose_email_sync(page, deadline=deadline)
            if route in {"ambiguous", "unchanged", "unavailable"}:
                return _workday_handoff(app, context, page, f"Email sign-in route {route}; choose it in this tab, then Continue fill.")
            if route == "selected" and not is_workday:
                return _workday_handoff(app, context, page, "Email sign-in route selected; complete authentication in this tab, then Continue fill.")
            if is_workday:
                auth_result = workday_auth.handle_workday_auth(
                    page, source_job_id, profile, on_progress=progress, deadline=deadline,
                )
                if auth_result != "authenticated":
                    return _workday_handoff(
                        app, context, page, workday_auth.AUTH_HANDOFF[auth_result],
                        status="awaiting_otp" if auth_result == "verification_needed" else "awaiting_review",
                        error="Workday authentication failed" if auth_result == "failed" else None,
                    )
                recover_site_error()  # the apply_form wait below decides
                if workday_flow.wait_for_state(page, {"apply_form"}, timeout_s=15, deadline=deadline) != "apply_form":
                    return _workday_handoff(
                        app, context, page,
                        "Signed in, but the Workday application form did not open; open it in this tab, then Continue fill.",
                    )

            _guard_file_chooser(page, progress)
            merged: dict[str, Any] = {
                "filled": [],
                "leftovers": [],
                "long_text": [],
                "file_inputs": [],
                "required_empty": [],
                "frames_skipped": 0,
            }
            uploads: list[dict[str, Any]] = []
            completed_step_outcomes: dict[tuple[int, str], dict[str, Any]] = {}
            uploaded_controls: set[tuple[str, str]] = set()
            long_text_answers: dict[str, str] = {}
            needs_review: list[str] = [authorization_note] if authorization_note else []
            # Questions recognised as a profile fact the profile leaves blank (every step).
            blank_facts: list[dict[str, Any]] = []
            posting_text = jd_text
            with contextlib.suppress(Exception):
                posting_text += "\n" + page.locator("body").inner_text(timeout=2000)[:50000]
            availability_note = _availability_note(fields.get("earliest_start", ""), posting_text)
            if availability_note:
                needs_review.append(availability_note)
            barrier_hit: str | None = None

            # One pass more than the steps it may advance: a blank Workday step is rescanned once.
            MAX_WIZARD_STEPS = 9
            final_step_reached = False
            country_rechecked = False
            blank_step_rescanned = False
            for step in range(MAX_WIZARD_STEPS):
                if should_cancel and should_cancel():
                    needs_review.append("Fill cancelled")
                    break
                if time.monotonic() >= deadline:
                    needs_review.append("Application fill reached its four-minute limit")
                    break
                progress(f"scanning form step {step + 1}")
                # One ledger per frame for this step: every resolver pass on the step shares
                # it, so a stuck field is retried alone instead of the whole page again.
                ledgers: dict[int, hybrid_resolver.StepLedger] = {}
                verified_purposes: set[tuple[str, int]] = set()
                attempted_purposes: set[tuple[str, int]] = set()
                other_chosen = False
                for key in ("leftovers", "long_text", "file_inputs", "required_empty"):
                    merged[key] = []
                step_filled_start = len(merged["filled"])
                if is_workday:
                    # Workday's own error page ("Error Code: VPS|..."), whether it is showing
                    # already or replaces the step while it loads: refresh, which restores the
                    # saved draft.
                    if not recover_site_error():
                        return _workday_handoff(app, context, page, site_error_msg)
                    if not workday_flow.wait_for_step_ready(page, deadline=deadline):
                        if workday_flow.is_site_error(workday_flow.snapshot(page)):
                            if not recover_site_error():
                                return _workday_handoff(app, context, page, site_error_msg)
                            page, _state = workday_flow.enter_application(page, context, deadline=deadline, progress=progress)
                            _guard_file_chooser(page, progress)
                            if not workday_flow.wait_for_step_ready(page, deadline=deadline):
                                return _workday_handoff(app, context, page, site_error_msg)
                        else:
                            progress("Workday step did not finish loading; scanning what is visible")
                    progress(f"Workday step: {workday_flow.active_step(workday_flow.snapshot(page)) or 'unknown'}")
                    dropdown_review: list[str] = []
                    wd_filled = workday_flow.fill_dropdowns(
                        page, fields, synonyms=ats_hints.SYNONYMS, progress=progress, deadline=deadline,
                        select=workday_flow.select_listbox, review=dropdown_review, blank=blank_facts,
                    )
                    if any(item.get("key") == "country" for item in wd_filled):
                        needs_review[:] = [label for label in needs_review if not label.startswith("Country is ")]
                    needs_review.extend(label for label in dropdown_review if label not in needs_review)
                    wd_filled += workday_flow.fill_radios(
                        page, fields, synonyms=ats_hints.SYNONYMS, progress=progress,
                        company=app.company or pkt.company or "",
                        employers=[entry.company for entry in getattr(resume, "experience", []) or []],
                        blank=blank_facts,
                    )
                    # Self-identification answers rendered as checkboxes (the disability
                    # form), then the Self Identify step's signature Name and Date.
                    self_id_review: list[str] = []
                    ticked = workday_flow.fill_choice_checkboxes(
                        page, fields, synonyms=ats_hints.SYNONYMS, progress=progress, review=self_id_review,
                    )
                    wd_filled += ticked
                    if ticked or workday_flow.is_self_identify_step(workday_flow.snapshot(page)):
                        wd_filled += workday_flow.fill_self_identify(
                            page, fields, today=date.today(), progress=progress, review=self_id_review,
                        )
                    needs_review.extend(label for label in self_id_review if label not in needs_review)
                    wd_filled += workday_flow.fill_prompts(
                        page, fields, synonyms=ats_hints.SYNONYMS, progress=progress,
                    )
                    skills_deadline = min(deadline, time.monotonic() + 120)
                    with config.pinned(settings.model_spec):
                        skill_chips, skills_left = workday_flow.fill_skills(
                            page, list(pkt.skills), progress=progress, deadline=skills_deadline,
                            choose_many=lambda unmatched: hybrid_resolver.choose_skill_options(
                                unmatched, deadline=skills_deadline,
                            ),
                        )
                    wd_filled += skill_chips
                    if skills_left:
                        note = f"Skills not found on the form: {', '.join(skills_left)}"
                        needs_review[:] = [item for item in needs_review if not item.startswith("Skills not found")]
                        needs_review.append(note)
                    merged["filled"].extend({**item, "frame_index": 0} for item in wd_filled)
                    phone_code = workday_flow.ensure_phone_code(
                        page, fields.get("phone_country_region", ""), fields.get("phone_country_code", ""),
                        progress=progress,
                    )
                    if phone_code is False and "Country Phone Code" not in needs_review:
                        needs_review.append("Country Phone Code")
                    elif phone_code and "Country Phone Code" in needs_review:
                        needs_review.remove("Country Phone Code")
                barrier = _detect_barriers(page)
                if barrier and "Cloudflare" in barrier:
                    if not _locator_exists(page.locator("input, select, textarea")):
                        barrier_hit = barrier
                        progress(f"interstitial barrier encountered: {barrier}")
                        break
                elif barrier:
                    barrier_hit = barrier
                    progress(f"CAPTCHA noted on form: {barrier} (will fill form then await review)")

                frames = page.frames
                pass_start = len(merged["filled"])
                for frame_index, frame in enumerate(frames):
                    try:
                        partial = frame.evaluate(
                            filler_js,
                            {
                                "fields": fields,
                                "hints": hints,
                                "synonyms": _synonym_payload(),
                                "eeo": field_matcher.eeo_patterns(fields),
                            },
                        )
                    except Exception as exc:  # noqa: BLE001 - cross-origin frames fail evaluate
                        merged["frames_skipped"] = int(merged["frames_skipped"]) + 1
                        if frame_index == 0:
                            reason = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
                            progress(f"form scan failed on the page: {reason}")
                        continue
                    if not isinstance(partial, dict):
                        continue
                    if partial.get("revealed"):
                        # A tick ("I have a preferred name") can reveal more inputs: scan the
                        # frame once more and keep the first pass's own fills.
                        page.wait_for_timeout(600)
                        with contextlib.suppress(Exception):
                            again = frame.evaluate(
                                filler_js,
                                {"fields": fields, "hints": hints, "synonyms": _synonym_payload(),
                                 "eeo": field_matcher.eeo_patterns(fields)},
                            )
                            if isinstance(again, dict):
                                first = [item for item in partial.get("filled") or [] if isinstance(item, dict)]
                                seen = {item.get("selector") for item in first}
                                extra = [
                                    item for item in again.get("filled") or []
                                    if isinstance(item, dict) and item.get("selector") not in seen
                                ]
                                partial = {**again, "filled": [*first, *extra]}
                    for key in (
                        "filled", "leftovers", "long_text", "file_inputs", "required_empty"
                    ):
                        items = partial.get(key) or []
                        if key in {"filled", "leftovers", "long_text", "file_inputs"}:
                            items = [{**item, "frame_index": frame_index} for item in items if isinstance(item, dict)]
                        merged[key].extend(items)
                    merged["frames_skipped"] += int(partial.get("frames_skipped") or 0)
                    blank_facts.extend(
                        item for item in partial.get("leftovers") or []
                        if isinstance(item, dict) and item.get("reason") == apply_packet.BLANK_PROFILE_REASON
                    )

                if is_workday:
                    _commit_workday_textareas(frames, merged["filled"][pass_start:])
                    # Philips (2026-09) paints My Information, then re-renders it for the
                    # account's saved country: a scan in between finds no controls at all,
                    # and pressing Next then leaves the whole step blank. Wait and rescan once.
                    if (
                        not blank_step_rescanned
                        and _scanned_nothing(merged, step_filled_start)
                        and not workday_flow.is_review_step(workday_flow.snapshot(page))
                    ):
                        blank_step_rescanned = True
                        progress("Workday step showed no fields to fill yet; rescanning once it settles")
                        page.wait_for_timeout(1500)
                        continue

                # File uploads via Playwright (cannot set from page JS).
                resume_path = pkt.artifacts.get("resume_pdf") or pkt.artifacts.get("resume_docx")
                cover_path = pkt.artifacts.get("cover_pdf") or pkt.artifacts.get("cover_docx")
                file_inputs = list(merged.get("file_inputs") or [])

                # Proactively discover file inputs if not yet registered
                existing_sels = {
                    f.get("selector") for f in file_inputs if isinstance(f, dict)
                }
                for fin_sel in (
                    "input[type='file']#resume",
                    "input[type='file'][id*='resume' i]",
                    "input[type='file'][name*='resume' i]",
                ):
                    if fin_sel not in existing_sels and _locator_exists(page.locator(fin_sel)):
                        file_inputs.insert(0, {"selector": fin_sel, "label": "Resume"})
                        break
                for cov_sel in (
                    "input[type='file']#cover_letter",
                    "input[type='file'][id*='cover' i]",
                    "input[type='file'][name*='cover_letter' i]",
                    "input[type='file'][name*='cover' i]",
                ):
                    if cov_sel not in existing_sels and _locator_exists(page.locator(cov_sel)):
                        file_inputs.append({"selector": cov_sel, "label": "Cover Letter"})
                        break

                for fin in file_inputs:
                    if time.monotonic() >= deadline or (should_cancel and should_cancel()):
                        needs_review.append("Fill stopped before all attachments were checked")
                        break
                    sel = fin.get("selector") if isinstance(fin, dict) else None
                    label = str(fin.get("label") or "") if isinstance(fin, dict) else ""
                    purpose = _attachment_purpose(
                        label, str(sel or ""), hints,
                        hint_key=str(fin.get("hint_key") or "") if isinstance(fin, dict) else "",
                        section=str(fin.get("section") or "") if isinstance(fin, dict) else "",
                    )
                    frame_index = int(fin.get("frame_index") or 0) if isinstance(fin, dict) else 0
                    upload_target = frames[frame_index] if 0 <= frame_index < len(frames) else page
                    if not sel or not purpose:
                        if sel and ("file", sel) not in uploaded_controls:
                            uploads.append({"selector": sel, "label": label, "purpose": "unknown", "verified": False, "error": "Attachment purpose is ambiguous"})
                            uploaded_controls.add(("file", sel))
                        continue
                    path = (
                        resume_path if purpose == "resume"
                        else pkt.artifacts.get("transcript_pdf") if purpose == "transcript"
                        else cover_path
                    )
                    key = (purpose, f"{frame_index}:{sel}")
                    if (purpose, frame_index) in verified_purposes:
                        continue
                    if (purpose, frame_index) in attempted_purposes:
                        continue
                    if key in uploaded_controls:
                        continue
                    uploaded_controls.add(key)
                    attempted_purposes.add((purpose, frame_index))
                    try:
                        existing_control = upload_target.locator(sel).first
                        existing_filename = (
                            existing_control.evaluate(
                                "el => el.files && el.files[0] ? el.files[0].name : ''",
                                timeout=500,
                            )
                            if _locator_exists(existing_control) else ""
                        )
                    except Exception:  # noqa: BLE001
                        existing_filename = ""
                    if isinstance(existing_filename, str) and existing_filename:
                        uploads.append({"selector": sel, "label": label, "purpose": purpose, "filename": existing_filename, "verified": True, "preserved": True, "frame_index": frame_index})
                        verified_purposes.add((purpose, frame_index))
                        continue
                    if not path or not Path(path).is_file():
                        uploads.append({"selector": sel, "label": label, "purpose": purpose, "verified": False, "error": f"No {purpose.replace('_', ' ')} artifact available", "frame_index": frame_index})
                        continue
                    staged_path = _stage_attachment(
                        path,
                        purpose=purpose,
                        applicant_name=applicant_name,
                        role=pkt.role or app.role or "Application",
                        out_dir=out_dir,
                    )
                    # Upload widgets that keep a file list (Workday) empty their input after
                    # each upload; the listed filename is what says it is already attached.
                    already_listed = False
                    with contextlib.suppress(Exception):
                        listed = upload_target.get_by_text(Path(staged_path).name, exact=False).count()
                        already_listed = isinstance(listed, int) and listed > 0
                    if already_listed:
                        uploads.append({"selector": sel, "label": label, "purpose": purpose, "filename": Path(staged_path).name, "verified": True, "preserved": True, "frame_index": frame_index})
                        verified_purposes.add((purpose, frame_index))
                        progress(f"{purpose.replace('_', ' ')} already attached: {Path(staged_path).name}")
                        continue
                    progress(
                        f"uploading {purpose.replace('_', ' ')}: {Path(staged_path).name}"
                    )
                    uploaded = False
                    upload_error = "Upload could not be verified on the form"
                    try:
                        uploaded = _set_and_verify_file(upload_target, sel, staged_path)
                    except Exception as exc:  # noqa: BLE001
                        upload_error = f"Browser rejected upload: {type(exc).__name__}"
                        for frame in frames:
                            try:
                                uploaded = _set_and_verify_file(frame, sel, staged_path)
                                break
                            except Exception:  # noqa: BLE001
                                continue
                    uploads.append({"selector": sel, "label": label, "purpose": purpose, "filename": Path(staged_path).name, "verified": uploaded, "error": "" if uploaded else upload_error, "frame_index": frame_index})
                    if uploaded:
                        verified_purposes.add((purpose, frame_index))
                        progress(f"{purpose.replace('_', ' ')} attachment verified")

                if time.monotonic() >= deadline or (should_cancel and should_cancel()):
                    needs_review.append("Fill stopped before this form step was complete")
                    break

                with config.pinned(settings.model_spec):
                    for item in merged.get("long_text") or []:
                        if time.monotonic() >= deadline or (should_cancel and should_cancel()):
                            needs_review.append("Fill stopped before all written answers were checked")
                            break
                        if not isinstance(item, dict):
                            continue
                        label = str(item.get("label") or "question")
                        if label in long_text_answers or label in needs_review:
                            continue
                        maxlength = int(item.get("maxlength") or 1500)
                        recalled = answer_memory.recall(
                            label, company=app.company or pkt.company or "", ats=ats_name
                        )
                        if recalled is not None:
                            if recalled.needs_review or (0 < maxlength < len(recalled.answer)):
                                needs_review.append(label)
                                continue
                            long_text_answers[label] = recalled.answer
                            sel = item.get("selector")
                            if sel:
                                with contextlib.suppress(Exception):
                                    target = frames[int(item.get("frame_index") or 0)]
                                    if not target.locator(str(sel)).first.input_value().strip():
                                        target.fill(sel, recalled.answer)
                            continue
                        ans = answer.answer_question(
                            label,
                            resume=resume,
                            bullets=bullets,
                            requirements=requirements,
                            profile=profile,
                            max_chars=maxlength if maxlength > 0 else 1500,
                            jd_text=jd_text,
                            deadline=deadline,
                        )
                        if ans.offenders or not ans.answer:
                            needs_review.append(label)
                            continue
                        long_text_answers[label] = ans.answer
                        sel = item.get("selector")
                        if sel:
                            with contextlib.suppress(Exception):
                                target = frames[int(item.get("frame_index") or 0)]
                                existing = target.locator(str(sel)).first.input_value()
                                if not existing.strip():
                                    target.fill(sel, ans.answer)

                if time.monotonic() >= deadline or (should_cancel and should_cancel()):
                    needs_review.append("Fill stopped before this form step was complete")
                    break

                for leftover in merged.get("leftovers") or []:
                    if time.monotonic() >= deadline or (should_cancel and should_cancel()):
                        needs_review.append("Fill stopped before all choices were checked")
                        break
                    if not isinstance(leftover, dict):
                        continue
                    label = str(leftover.get("label") or "")
                    if leftover.get("key") == "salary_expectation":
                        if label not in needs_review:
                            needs_review.append(label)
                        continue
                    if label in needs_review:
                        continue
                    if leftover.get("type") == "combobox" and leftover.get("key"):
                        target = frames[int(leftover.get("frame_index") or 0)]
                        selected = _fill_declared_combobox(target, leftover, fields)
                        if selected:
                            merged["filled"].append({"key": leftover["key"], "label": label, "value": selected, "selector": leftover["selector"], "frame_index": leftover.get("frame_index", 0)})
                            if leftover["key"] == "how_heard" and selected != fields.get("how_heard"):
                                other_chosen = True
                            continue
                    recalled = answer_memory.recall(
                        label, company=app.company or pkt.company or "", ats=ats_name,
                        canonical_key=str(leftover.get("key") or ""),
                    )
                    if recalled is not None and recalled.needs_review:
                        needs_review.append(label)
                        continue
                    canned = (
                        recalled.answer if recalled is not None
                        else answer._profile_answer(label, profile)  # noqa: SLF001
                    )
                    if canned and leftover.get("selector"):
                        try:
                            target = frames[int(leftover.get("frame_index") or 0)]
                            selector = str(leftover["selector"])
                            control_type = str(leftover.get("type") or "")
                            if control_type == "select":
                                target.locator(selector).first.select_option(label=canned)
                            elif control_type == "radio":
                                if not hybrid_resolver._choose_radio_option(target, selector, canned):  # noqa: SLF001
                                    raise RuntimeError("No matching radio option")
                            elif control_type in {"combobox", "button"}:
                                if not hybrid_resolver._select_combobox_option(target, selector, canned):  # noqa: SLF001
                                    raise RuntimeError("No matching dropdown option")
                            elif not target.locator(selector).first.input_value().strip():
                                target.fill(selector, canned)
                            merged["filled"].append(
                                {
                                    "key": "memory" if recalled is not None else "custom",
                                    "label": label,
                                    "value": canned,
                                    "selector": leftover["selector"],
                                }
                            )
                        except Exception:  # noqa: BLE001
                            needs_review.append(label)
                    elif leftover.get("required"):
                        needs_review.append(label)

                # A Greenhouse choice can reveal another EEO control, and a "How did you
                # hear" answer of "Other" reveals "please specify" (filled by the rescan).
                # Scan once more after declared choices, without repeating unresolved
                # model guesses.
                if ats_name == "greenhouse" or other_chosen:
                    known = {(item.get("frame_index", 0), item.get("selector")) for item in merged["leftovers"] if isinstance(item, dict)}
                    known_filled = {(item.get("frame_index", 0), item.get("selector")) for item in merged["filled"] if isinstance(item, dict)}
                    for frame_index, frame in enumerate(frames):
                        with contextlib.suppress(Exception):
                            revealed = frame.evaluate(filler_js, {"fields": fields, "hints": hints, "synonyms": _synonym_payload(),
                                 "eeo": field_matcher.eeo_patterns(fields)})
                            merged["filled"].extend(
                                {**item, "frame_index": frame_index} for item in revealed.get("filled") or []
                                if isinstance(item, dict) and item.get("key") != "existing"
                                and (frame_index, item.get("selector")) not in known_filled
                            )
                            for item in revealed.get("leftovers") or []:
                                identity = (frame_index, item.get("selector"))
                                if identity in known or item.get("type") != "combobox":
                                    continue
                                item = {**item, "frame_index": frame_index}
                                merged["leftovers"].append(item)
                                known.add(identity)
                                selected = _fill_declared_combobox(frame, item, fields)
                                if selected:
                                    merged["filled"].append({"key": item.get("key"), "label": item.get("label"), "value": selected, "selector": item.get("selector"), "frame_index": frame_index})

                if time.monotonic() >= deadline or (should_cancel and should_cancel()):
                    needs_review.append("Fill stopped before this form step was complete")
                    break

                # Workday structured experience & education injection (My Experience only)
                if is_workday and "experience" in workday_flow.active_step(workday_flow.snapshot(page)).casefold():
                    rows_filled, rows_review = _fill_workday_experience_and_education(page, pkt, progress)
                    merged["filled"].extend({**item, "key": "workday_row", "frame_index": 0} for item in rows_filled)
                    needs_review.extend(label for label in rows_review if label not in needs_review)

                if is_workday:
                    consent_filled, consent_review = form_routes.accept_workday_sync(page)
                    merged["filled"].extend({**item, "frame_index": 0} for item in consent_filled)
                    accepted_labels = {item["label"] for item in consent_filled}
                    merged["required_empty"] = [label for label in merged["required_empty"] if label not in accepted_labels]
                    merged["leftovers"] = [item for item in merged["leftovers"] if item.get("label") not in accepted_labels]
                    needs_review[:] = [label for label in needs_review if label not in accepted_labels]
                    needs_review.extend(label for label in consent_review if label not in needs_review)
                    if consent_review:
                        progress("Required Workday consent needs review; leaving this step open")
                        break

                # A wrong Country (the account's saved "Vietnam") re-labels the name and
                # address fields and empties the phone code; correct it and fill the
                # re-rendered step again, once.
                if is_workday and not country_rechecked:
                    wrong_country = workday_flow.country_mismatch(page, fields, synonyms=ats_hints.SYNONYMS)
                    if wrong_country:
                        country_rechecked = True
                        progress(f"Workday: Country reads {wrong_country} after filling; correcting it and rescanning this step")
                        continue

                # Workday's Review step is the end: its footer button submits. Stop here
                # whatever the button is called; submission is always the applicant's.
                if is_workday and workday_flow.is_review_step(workday_flow.snapshot(page)):
                    final_step_reached = True
                    progress("Workday Review step reached; leaving it for the applicant to submit")
                    break

                # Check if there is an advance/next button for multi-step wizard
                advance_btn = _find_advance_button(page)
                if (not advance_btn or merged.get("required_empty")) and step < MAX_WIZARD_STEPS - 1:
                    with config.pinned(settings.model_spec):
                        for frame_index, frame in enumerate(frames):
                            hybrid_resolver.resolve_step_blockers(
                                frame, pkt, profile, on_progress=progress, deadline=deadline,
                                ledger=ledgers.setdefault(frame_index, hybrid_resolver.StepLedger()),
                            )
                    advance_btn = _find_advance_button(page)

                if advance_btn and step < MAX_WIZARD_STEPS - 1:
                    attempted_step = {(item.get("frame_index", 0), item.get("selector")): item for item in merged["filled"] if isinstance(item, dict)}
                    completed_step_outcomes.update(_observe_fields(page, filler_js, hints, attempted_step))
                    progress(f"advancing wizard step {step + 1}")
                    before_step = _form_step_signature(page)
                    wd_before = workday_flow.active_step(workday_flow.snapshot(page)) if is_workday else ""

                    def settle_after_advance(fallback_ms: int) -> None:
                        # Workday saves the step server-side before painting the next one.
                        if is_workday:
                            workday_flow.wait_for_step_change(page, wd_before, deadline=deadline)
                        else:
                            page.wait_for_timeout(fallback_ms)

                    def step_unchanged() -> bool:
                        if is_workday:
                            return workday_flow.active_step(workday_flow.snapshot(page)) == wd_before
                        return before_step is not None and _form_step_signature(page) == before_step

                    retried_advance = False
                    try:
                        clicks.safe_click(advance_btn, purpose="advance", timeout=5000)
                        settle_after_advance(1000)
                        with contextlib.suppress(Exception):
                            page.wait_for_load_state("networkidle", timeout=min(5000, max(1000, int((deadline - time.monotonic()) * 1000))))
                        if is_workday and workday_flow.is_site_error(workday_flow.snapshot(page)):
                            # Save and Continue hit Workday's error page; after a refresh the
                            # draft reopens on whichever step it saved, so scan that one afresh.
                            if not recover_site_error():
                                return _workday_handoff(app, context, page, site_error_msg)
                            continue
                    except Exception:  # noqa: BLE001
                        retried_advance = True
                        progress("wizard advance was blocked; resolving visible blockers once")
                        with config.pinned(settings.model_spec):
                            hybrid_resolver.resolve_step_blockers(
                                page, pkt, profile, max_retries=1, on_progress=progress, deadline=deadline,
                                ledger=ledgers.setdefault(0, hybrid_resolver.StepLedger()), only_invalid=True,
                            )
                        retry_button = _find_advance_button(page)
                        if retry_button is None:
                            break
                        try:
                            clicks.safe_click(retry_button, purpose="advance", timeout=5000)
                            settle_after_advance(500)
                        except Exception:  # noqa: BLE001
                            break
                    if step_unchanged():
                        if retried_advance:
                            progress("wizard is unchanged; handing this tab over for review")
                            break
                        progress("wizard did not advance; resolving visible blockers once")
                        with config.pinned(settings.model_spec):
                            hybrid_resolver.resolve_step_blockers(
                                page, pkt, profile, max_retries=1, on_progress=progress, deadline=deadline,
                                ledger=ledgers.setdefault(0, hybrid_resolver.StepLedger()), only_invalid=True,
                            )
                        retry_button = _find_advance_button(page)
                        if retry_button is None:
                            break
                        with contextlib.suppress(Exception):
                            clicks.safe_click(retry_button, purpose="advance", timeout=5000)
                            settle_after_advance(500)
                        if step_unchanged():
                            progress("wizard is unchanged; handing this tab over for review")
                            break
                else:
                    final_step_reached = advance_btn is None and (
                        _find_submit_button(page, hints) is not None or
                        (is_workday and workday_flow.is_review_step(workday_flow.snapshot(page)))
                    )
                    break

            required_empty: list[str] = []
            for frame in page.frames:
                try:
                    ready = frame.evaluate(readiness_js)
                    if isinstance(ready, list):
                        required_empty.extend(str(item) for item in ready)
                    elif isinstance(ready, dict):
                        required_empty.extend(str(item) for item in ready.get("required_empty") or [])
                except Exception:  # noqa: BLE001
                    continue
            if not required_empty:
                required_empty = list(merged.get("required_empty") or [])
            required_empty = list(dict.fromkeys(required_empty))

            attempted_count = len(merged.get("filled") or []) + len(merged.get("leftovers") or []) + len(merged.get("long_text") or [])

            attempted = {
                (item.get("frame_index", 0), item.get("selector")): item
                for item in merged.get("leftovers") or [] if isinstance(item, dict) and item.get("selector")
            }
            attempted.update({
                (item.get("frame_index", 0), item.get("selector")): item
                for item in merged.get("filled") or [] if isinstance(item, dict)
            })
            observed = {**completed_step_outcomes, **_observe_fields(page, filler_js, hints, attempted)}
            observed_labels = {str(item.get("label") or "") for item in observed.values()}
            needs_review = [label for label in needs_review if label not in observed_labels or label == "No salary range in the applicant profile"]
            if not observed and attempted:
                needs_review.append("Filled values could not be verified on the current form")
            merged["filled"] = list(observed.values())

            if is_workday:
                workday_flow.close_stray_popups(page)
            out_dir.mkdir(parents=True, exist_ok=True)
            shot = out_dir / "fill.png"
            try:
                progress("capturing fill evidence")
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                shot = None  # type: ignore[assignment]

            # Readiness guard: if 0 controls detected & no barrier, fail
            total_controls = attempted_count
            if total_controls == 0 and not barrier_hit and is_workday and workday_flow.is_site_error(workday_flow.snapshot(page)):
                return _workday_handoff(app, context, page, site_error_msg)
            if total_controls == 0 and not barrier_hit:
                guard_msg = "No application form controls detected on page"
                with contextlib.suppress(Exception):
                    if "page you are looking for doesn't exist" in page.inner_text("body").casefold():
                        guard_msg = "Posting is unavailable: Workday says this page does not exist"
                result = FillResult(
                    error=guard_msg,
                    status="fill_failed",
                    screenshot_path=str(shot) if shot else None,
                    browser_target_id=target_id,
                    browser_url=page.url,
                    handoff_reason="form unavailable",
                )
                store.set_status(app, "fill_failed", note=guard_msg)
                app.fill = result
                store.upsert(app)
                progress("done status=fill_failed (no controls detected)")
                return result

            progress("verifying required fields and attachments")
            if fill_mode == "continue":
                for prior in previous_fill.uploads:
                    purpose = prior.get("purpose")
                    filename = prior.get("filename")
                    if purpose not in {"resume", "cover_letter"} or any(
                        item.get("purpose") == purpose and item.get("verified") for item in uploads
                    ):
                        continue
                    visible = False
                    if filename:
                        for frame in page.frames:
                            with contextlib.suppress(Exception):
                                count = frame.get_by_text(str(filename), exact=False).count()
                                if isinstance(count, int) and count > 0:
                                    visible = True
                                    break
                    uploads.append({"purpose": purpose, "filename": filename or "", "verified": visible, "preserved": visible, "error": "" if visible else "Previous attachment is not visible in this tab"})
            by_purpose: dict[str, dict[str, Any]] = {}
            for item in uploads:
                purpose = str(item.get("purpose") or "unknown")
                current = by_purpose.get(purpose)
                if current is None or (not current.get("verified") and item.get("verified")):
                    by_purpose[purpose] = item
            uploads = list(by_purpose.values())
            required_upload_failed = any(
                not item.get("verified")
                for item in uploads
            )
            ready_to_submit = (
                len(required_empty) == 0
                and not needs_review
                and not barrier_hit
                and not required_upload_failed
                and final_step_reached
            )

            submit_action = "awaiting_review"
            confirmation = ""
            final_status = "awaiting_review"
            action = decide_submit_action(
                ats=app.ats or pkt.ats,
                settings=settings,
                ready_to_submit=ready_to_submit,
                submit_mode=submit_mode,
            )
            if should_cancel and should_cancel():
                action = "awaiting_review"
            if action == "auto_submit":
                submit_sel = _hint_selector(hints, "submit")
                confirm_text = hints.get("confirmation_text") or "thank you"
                dispatched = False
                try:
                    before_url = page.url
                    before_body = page.inner_text("body")
                    submit_btn = page.locator(submit_sel).first if submit_sel else _find_submit_button(page, hints)
                    if submit_btn is None or submit_btn.count() == 0:
                        raise RuntimeError("Final submit button was not found")
                    # Persist intent before dispatch. A crash after this point must
                    # never cause an automatic second click on restart.
                    app.fill = FillResult(
                        filled=list(merged.get("filled") or []),
                        leftovers=list(merged.get("leftovers") or []),
                        uploads=uploads,
                        required_empty=required_empty,
                        ready_to_submit=ready_to_submit,
                        submit_action="auto_submit",
                        status="submit_unconfirmed",
                        browser_target_id=target_id,
                        browser_url=before_url,
                        handoff_reason="Submission dispatched; confirmation pending",
                        final_step_reached=final_step_reached,
                    )
                    store.upsert(app)
                    dispatched = True
                    clicks.submit_click(submit_btn, decision=action, timeout=10_000)
                    page.wait_for_load_state("networkidle", timeout=30_000)
                    if _submission_confirmed(
                        page,
                        before_url=before_url,
                        before_body=before_body,
                        confirmation_text=confirm_text,
                    ):
                        confirmation = confirm_text
                        submit_action = "auto_submit"
                        final_status = "submitted"
                    else:
                        confirmation = "missing"
                        submit_action = "auto_submit"
                        final_status = "submit_unconfirmed"
                except Exception as exc:  # noqa: BLE001
                    confirmation = str(exc)
                    submit_action = "auto_submit"
                    final_status = "submit_unconfirmed" if dispatched else "fill_failed"

            outcomes = {
                (item.get("frame_index", 0), item.get("selector")): item
                for item in merged.get("filled") or []
                if isinstance(item, dict)
            }
            remaining = [
                item for item in merged.get("leftovers") or []
                if isinstance(item, dict)
                and (item.get("frame_index", 0), item.get("selector")) not in outcomes
            ]
            result = FillResult(
                filled=list(outcomes.values()),
                leftovers=remaining
                + [{"label": n, "reason": "needs_review"} for n in needs_review if not any(item.get("label") == n and item.get("key") == "salary_expectation" for item in remaining)]
                + ([{"label": barrier_hit, "reason": "barrier"}] if barrier_hit else []),
                long_text_answers=long_text_answers,
                uploads=uploads,
                required_empty=required_empty,
                ready_to_submit=ready_to_submit,
                submit_action=submit_action,
                confirmation=confirmation,
                screenshot_path=str(shot) if shot else None,
                status=final_status,
                browser_target_id=target_id,
                browser_url=page.url,
                handoff_reason=barrier_hit or ("missing answers" if required_empty or needs_review else "ready for review"),
                final_step_reached=final_step_reached,
                field_outcomes=list(outcomes.values()),
                missing_profile=apply_packet.missing_profile(
                    # Withheld for another country's posting, not blank in the profile.
                    [
                        item for item in blank_facts
                        if not (mismatch and item.get("key") == "authorized_to_work")
                    ],
                    {str(item.get("label") or "") for item in merged.get("filled") or [] if isinstance(item, dict)},
                ),
            )
            (out_dir / "fill.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )
            # Policy B: leave the tab open when awaiting human review.
            note = barrier_hit if barrier_hit else submit_action
            store.set_status(app, final_status, note=note)  # type: ignore[arg-type]
            app.fill = result
            store.upsert(app)
            progress(f"done status={final_status}")
            return result
    except Exception as exc:  # noqa: BLE001
        result = previous_fill.model_copy(update={
            "error": str(exc), "status": "fill_failed", "browser_target_id": target_id,
            "browser_url": page.url if page is not None else previous_fill.browser_url,
            "handoff_reason": "fill failed",
        })
        store.set_status(app, "fill_failed", note=str(exc))
        app.fill = result
        app.error = str(exc)
        store.upsert(app)
        return result
