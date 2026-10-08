"""The state one legacy-engine fill carries, and the small helpers every step uses."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

from resume_tailor import config
from resume_tailor.apply.answers import answer, questions
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.answers import salary as salary_mod
from resume_tailor.apply.ats import ats_hints, workday_auth, workday_flow, workday_page
from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.driver import browser
from resume_tailor.apply.forms import form_guards, wizards
from resume_tailor.apply.funnel import packet as apply_packet
from resume_tailor.apply.funnel import packet_fields, packet_profile_fields, store
from resume_tailor.apply.funnel.store_models import FillResult
from resume_tailor.content import data
from resume_tailor.web.schemas import ApplySettings

from . import fill_page, fill_widgets


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
    workday_page.close_stray_popups(page)
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


class _FillState:
    """What one `_FillRun` gathers before touching the browser, and its shared helpers.

    Progress, cancellation, deadline and handoff helpers live here so every step layer
    (`fill_entry`, `fill_wizard`, `fill_answers`, `fill_ats_steps`, `fill_finish`) can use
    them; `_FillRun` itself adds only `run`.
    """

    SITE_ERROR_MSG = (
        "Workday kept showing 'Something went wrong' after refreshing. Close other tabs "
        "open on this application, refresh this tab, then Continue fill."
    )

    # Per-run state the step layers set after `__init__` (mostly in `_start_fill` and
    # `_start_step`). Declared here, annotation only, so every layer type-checks.
    barrier_hit: str | None
    blank_facts: list[dict[str, Any]]
    blank_step_rescanned: bool
    completed_step_outcomes: dict[tuple[int, str], dict[str, Any]]
    country_rechecked: bool
    entered: bool
    facts: questions.Facts
    final_step_reached: bool
    frames: Any
    long_text_answers: dict[str, str]
    merged: dict[str, Any]
    model_unavailable: bool
    needs_review: list[str]
    other_chosen: bool
    pass_start: int
    step_filled_start: int
    uploaded_controls: set[tuple[str, str]]
    uploads: list[dict[str, Any]]
    attempted_purposes: set[tuple[str, int]]
    verified_purposes: set[tuple[str, int]]

    def __init__(
        self,
        app: Any,
        *,
        source_job_id: str,
        settings: ApplySettings,
        submit_mode: Literal["auto_submit", "awaiting_review"] | None,
        fill_mode: Literal["initial", "continue", "reopen"],
        should_cancel: Callable[[], bool] | None,
        on_progress: Callable[[str], None] | None,
        applicant_profile: profile_mod.ApplicantProfile | None,
    ) -> None:
        self.app = app
        self.source_job_id = source_job_id
        self.settings = settings
        self.submit_mode = submit_mode
        self.fill_mode = fill_mode
        self.should_cancel = should_cancel
        self.on_progress = on_progress

        self.previous_fill = FillResult.model_validate(app.fill) if app.fill else FillResult()
        store.set_status(app, "filling", note="")
        store.upsert(app)
        self.progress("building packet")
        self.pkt = (
            apply_packet.build_packet(app.job_id)
            if applicant_profile is None else
            apply_packet.build_packet(app.job_id, applicant_profile=applicant_profile)
        )
        profile = applicant_profile
        if profile is None:
            profile, _ = profile_mod.load_profile()
        self.profile = profile
        self.resume = data.load()
        contact_name = getattr(getattr(self.resume, "contact", None), "name", "")
        self.bullets, self.requirements, self.jd_text = fill_widgets._job_artifacts(app.job_id)
        self.filler_js = fill_page._load_filler_js()
        self.readiness_js = fill_page._load_readiness_js()
        self.hints = dict(self.pkt.field_hints) or ats_hints.hints_for(app.ats)
        self.fields = self._build_fields()
        self.applicant_name = self._applicant_name(contact_name)
        self._apply_profile_fields()
        self._check_work_authorization()

        pkt = self.pkt
        self.url = app.final_url or app.posting_url
        url = self.url or ""
        self.is_workday = (
            (app.ats or pkt.ats or "").lower() == "workday" or workday_auth.is_workday_url(url)
        )
        self.is_smartrecruiters = (
            (app.ats or pkt.ats or "").lower() == "smartrecruiters"
            or "smartrecruiters.com" in url
        )
        # Other multi-step platforms (iCIMS, Taleo, SuccessFactors, Oracle): each step's
        # screen is named first, so a sign-in, an emailed code or the review page is handed
        # over.
        wizard_ats = app.ats or pkt.ats or ""
        if wizard_ats in {"", "other", "unknown"}:
            wizard_ats = fetch_jd.detect_ats(url)
        self.wizard = None if self.is_workday else wizards.for_ats(wizard_ats)
        self.ats_name = (app.ats or pkt.ats or "").lower()
        self.out_dir = config.APPLICATIONS_OUTPUT_DIR / source_job_id
        self.deadline = time.monotonic() + 240
        self.page: Any = None
        self.context: Any = None
        self.target_id = self.previous_fill.browser_target_id
        #: Refreshes of Workday's "Something went wrong" page this fill may still spend.
        self.site_error_left = 2 * workday_page.SITE_ERROR_RELOADS

        rest = form_guards.host_blocked(url) if fill_mode != "continue" else None
        if rest is not None:
            minutes = max(1, int(rest.total_seconds() // 60) + 1)
            raise RuntimeError(
                f"This site refused automated visits recently; try again in about {minutes} min"
            )

    # -- inputs ------------------------------------------------------------------------

    def _build_fields(self) -> dict[str, Any]:
        from resume_tailor.apply.answers import education  # noqa: PLC0415

        app, pkt, profile = self.app, self.pkt, self.profile
        fields = dict(pkt.fields)
        education.refresh_fields(fields, profile.highest_education_obtained)
        # ATS flows that consume the packet directly must see the same live fact.
        education.refresh_fields(pkt.fields, profile.highest_education_obtained)
        if fields.get("degree_level") and not fields.get("degree_name"):
            # Packets prepared before ``degree_name`` existed.
            fields["degree_name"] = packet_fields.degree_name(pkt.education, fields["degree_level"])
        fields.update(salary_mod.salary_fields(
            role=app.role or pkt.role or "", listing_salary=app.salary or "",
            jd_text=self.jd_text or "",
            hourly_max=profile.salary_hourly_max, yearly_max=profile.salary_yearly_max,
            hourly_min=profile.salary_hourly_min, yearly_min=profile.salary_yearly_min,
        ))
        return fields

    def _applicant_name(self, contact_name: Any) -> str:
        fields = self.fields
        applicant_name = str(
            fields.get("full_name")
            or " ".join(
                part for part in (fields.get("first_name", ""), fields.get("last_name", ""))
                if part
            )
            or "Applicant"
        )
        if isinstance(contact_name, str) and contact_name.strip():
            applicant_name = contact_name.strip()
        return applicant_name

    def _apply_profile_fields(self) -> None:
        profile, fields = self.profile, self.fields
        if profile.f1_opt_eligible is not None:
            fields["f1_opt_eligible"] = "Yes" if profile.f1_opt_eligible else "No"
        if profile.pronouns:
            fields["pronouns"] = profile.pronouns
        # Location checkbox lists fall back to the posting's own city (filler.js).
        if self.app.location:
            fields["posting_location"] = self.app.location

    def _check_work_authorization(self) -> None:
        # "Authorized to work" answers for the profile's country; a posting clearly in
        # another country leaves eligibility questions to the applicant, the model included.
        self.authorization_note = ""
        self.mismatch = packet_profile_fields.authorization_mismatch(
            self.profile, self.app.location or ""
        )
        if self.mismatch:
            self.fields.pop("authorized_to_work", None)
            self.pkt.fields.pop("authorized_to_work", None)
            self.profile = self.profile.model_copy(update={"authorized_to_work": None})
            self.authorization_note = (
                f"Job is in {self.mismatch[0]}; your work authorization is for "
                f"{self.mismatch[1]}. Answer eligibility questions yourself"
            )
            self.progress(self.authorization_note)

    # -- small helpers -----------------------------------------------------------------

    def progress(self, msg: str) -> None:
        """Forward a progress line when a callback is set."""
        if self.on_progress:
            self.on_progress(msg)

    def _cancelled(self) -> bool:
        return bool(self.should_cancel and self.should_cancel())

    def _out_of_time(self) -> bool:
        return time.monotonic() >= self.deadline or self._cancelled()

    def _ms_left(self, cap: int) -> int:
        return min(cap, max(1000, int((self.deadline - time.monotonic()) * 1000)))

    def _handoff(self, reason: str, **kwargs: Any) -> FillResult:
        return _workday_handoff(self.app, self.context, self.page, reason, **kwargs)

    def _review(self, labels: list[str]) -> None:
        """Add `labels` to the review list, skipping any already on it."""
        self.needs_review.extend(label for label in labels if label not in self.needs_review)

    def _record_target(self, url: str | None) -> None:
        self.app.fill = self.previous_fill.model_copy(
            update={"browser_target_id": self.target_id, "browser_url": url}
        )
        store.upsert(self.app)

    def recover_site_error(self) -> bool:
        recovered, used = workday_flow.recover_site_error(
            self.page, deadline=self.deadline, progress=self.progress,
            attempts=min(workday_page.SITE_ERROR_RELOADS, max(0, self.site_error_left)),
        )
        self.site_error_left -= used
        return recovered

    def classify_unkeyed(self, asked: list[questions.Question]) -> list[str | None]:
        with config.pinned(self.settings.model_spec):
            return answer.classify_questions(asked)

    @property
    def resume_path(self) -> Any:
        return self.pkt.artifacts.get("resume_pdf") or self.pkt.artifacts.get("resume_docx")

    @property
    def cover_path(self) -> Any:
        return self.pkt.artifacts.get("cover_pdf") or self.pkt.artifacts.get("cover_docx")

    def _stop_if_out_of_time(self, note: str) -> bool:
        if self._out_of_time():
            self.needs_review.append(note)
            return True
        return False
