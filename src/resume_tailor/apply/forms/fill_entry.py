"""Opening the application form: the posting, Workday entry, route choice and sign-in."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from resume_tailor.apply.answers import questions
from resume_tailor.apply.ats import (
    ats_fingerprint,
    ats_hints,
    workday_auth,
    workday_flow,
    workday_page,
)
from resume_tailor.apply.discovery import identity
from resume_tailor.apply.driver import browser
from resume_tailor.apply.forms import form_guards, wizards
from resume_tailor.apply.funnel.store_models import FillResult

from . import fill_buttons, fill_outcomes, fill_page, fill_state, fill_widgets

_log = logging.getLogger(__name__)

#: Progress line when Continue finds the review tab gone and opens the posting again.
CLOSED_TAB_REOPENED = (
    "Review tab was closed; reopening the posting (Workday restores the saved draft)"
)
#: Progress line when the review tab now shows another page; that tab is left open.
OTHER_PAGE_REOPENED = (
    "Review tab shows another page now; leaving it open and opening the posting in a new tab"
)


class _FillEntry(fill_state._FillState):
    """`_FillRun` steps that get from the posting to the first form step."""

    def _open_form(self) -> FillResult | None:
        context = self.context
        keep_tab = False
        if self.fill_mode == "continue":
            self.page = browser.find_target(context, self.target_id)
            if self.page is None:
                # A closed tab is reopened rather than failing: Workday restores the
                # saved draft once the applicant is signed in again.
                self.progress(CLOSED_TAB_REOPENED)
                self.fill_mode = "reopen"
            elif identity.retained_tab(str(self.page.url), (
                self.previous_fill.browser_url, self.app.final_url, self.app.posting_url,
            )) == "different":
                # The applicant took the tab to another page; it is theirs now and stays.
                self.progress(OTHER_PAGE_REOPENED)
                self.fill_mode, keep_tab = "reopen", True
        if self.fill_mode == "continue":
            self.progress("continuing the existing application tab")
            if self.is_workday:
                # A popup left open by the last fill or by the applicant blocks this one.
                workday_page.close_stray_popups(self.page)
        else:
            # A fresh fill replaces this application's earlier tab rather than adding one.
            if self.previous_fill.browser_target_id and not keep_tab:
                browser.close_target(self.previous_fill.browser_target_id)
            self.page = context.new_page()
            self.target_id = browser.target_id(context, self.page)
            self._record_target(self.url)
        with contextlib.suppress(Exception):
            self.page.set_default_timeout(10_000)
        if self.fill_mode != "continue":
            handoff = self._load_posting()
            if handoff is not None:
                return handoff
        self._recheck_platform()
        if self.is_workday:
            handoff = self._enter_workday()
            if handoff is not None:
                return handoff
        if self.fill_mode != "continue" or self.is_workday:
            self.target_id = browser.target_id(context, self.page)
            self._record_target(self.page.url)
        self.progress("application form opened")
        if self.fill_mode == "continue":
            from resume_tailor.apply.funnel import submission_monitor  # noqa: PLC0415
            try:
                evidence = submission_monitor.confirmation(
                    self.app.final_url or self.app.posting_url, str(self.page.url),
                    self.page.inner_text("body"), self.app.ats,
                    self.page.evaluate(submission_monitor.ROWS_JS) if self.app.ats == "workday" else None,
                )
            except Exception:  # noqa: BLE001 - ordinary form inspection continues
                evidence = None
            if evidence:
                return submission_monitor.record(self.app, evidence)
        language = form_guards.form_language(fill_page._page_lang(self.page))
        if language:
            return self._handoff(f"{language}. Fill it in this tab.")
        return None

    def _recheck_platform(self) -> None:
        """Use the handling of the platform the entry landed on (a company careers page
        that hands over to iCIMS or Workday, an Oracle site on a company domain).

        The stored ATS only moves from "other"/"unknown" to a name older app versions can
        read (`ats_fingerprint.stored_ats`)."""
        platform = ats_fingerprint.page_platform(self.page)
        if not platform:
            return
        self.landed_platform = platform
        stored = ats_fingerprint.stored_ats(platform)
        current = (self.ats_name or "").lower()
        if stored in {None, "other", "unknown", current} or (stored == "workday" and self.is_workday):
            return
        self.progress(f"the application is on {platform}; using its handling")
        if (self.app.ats or "") in {"", "other", "unknown"}:
            self.app.ats = stored
        self.ats_name = stored
        self.is_smartrecruiters = stored == "smartrecruiters"
        if stored == "workday":
            self.is_workday, self.wizard = True, None
        else:
            self.wizard = wizards.for_fill(stored)
        if not self.pkt.field_hints:
            self.hints = ats_hints.hints_for(stored)

    def _load_posting(self) -> FillResult | None:
        page = self.page
        self.progress(f"opening posting: {self.url}")
        response = page.goto(
            self.url, wait_until="domcontentloaded", timeout=self._ms_left(60_000)
        )
        status_code = getattr(response, "status", None)
        refusal = form_guards.bot_block(
            status=status_code if isinstance(status_code, int) else None,
            title=fill_page._page_title(page),
        )
        if refusal:
            form_guards.block_host(self.url)
            return self._handoff(
                f"{refusal}. Automatic filling leaves this site alone for an hour; "
                "fill it yourself in this tab, or try again later.",
            )
        self.progress("posting loaded; waiting for form controls")
        fill_page.wait_for_entry(page, timeout_ms=self._ms_left(10_000))
        if identity.lost_posting(self.url or "", str(page.url)):
            return self._handoff(fill_outcomes.LOST_POSTING_MSG, status="fill_failed")
        self.progress("locating application form")
        if not self.is_workday:
            self.page = fill_buttons.find_and_click_apply(
                page, self.app.ats or self.pkt.ats, context=self.context
            )
        return None

    def _enter_workday(self) -> FillResult | None:
        # Continue fill resumes from wherever the tab is (posting, dialog, auth, form).
        self.page, wd_state = workday_flow.enter_application(
            self.page, self.context, deadline=self.deadline, progress=self.progress,
        )
        self.progress(f"Workday screen: {wd_state}")
        if wd_state == "unknown":
            # Not yet explained (location variants of a requisition already applied to,
            # 2026-10): log what the screen showed — automation ids and URL, never text.
            snap = workday_page.snapshot(self.page)
            _log.info("Workday screen unknown at %s; ids=%s",
                      snap.get("url") or self.page.url, sorted(snap.get("ids") or [])[:80])
        if wd_state == "already_applied":
            from resume_tailor.apply.funnel import submission_monitor  # noqa: PLC0415
            evidence = submission_monitor.confirmation(self.app.final_url or self.app.posting_url,
                str(self.page.url), self.page.inner_text("body"), "workday")
            if evidence:
                return submission_monitor.record(self.app, evidence)
        if wd_state not in {"already_applied", "unavailable", "posting", "start_dialog", "unknown"}:
            return None
        reason = {
            "already_applied": "Workday says you have already applied to this job.",
            "unavailable": "Posting is unavailable: Workday says this job no longer exists.",
        }.get(
            wd_state,
            f"Workday application did not open (stuck on {wd_state}); open it in this tab, "
            "then Continue fill.",
        )
        return self._handoff(reason, error=reason if wd_state == "unavailable" else None)

    def _choose_route_and_sign_in(self) -> FillResult | None:
        # Select an explicit email route before any site-specific credential flow.
        from resume_tailor.apply.forms import form_routes  # noqa: PLC0415

        route = form_routes.choose_email_sync(self.page, deadline=self.deadline)
        if route in {"ambiguous", "unchanged", "unavailable"}:
            return self._handoff(
                f"Email sign-in route {route}; choose it in this tab, then Continue fill."
            )
        if route == "selected" and not self.is_workday:
            return self._handoff(
                "Email sign-in route selected; complete authentication in this tab, "
                "then Continue fill."
            )
        if not self.is_workday:
            return None
        auth_result = workday_auth.handle_workday_auth(
            self.page, self.source_job_id, self.profile, on_progress=self.progress,
            deadline=self.deadline,
        )
        if auth_result != "authenticated":
            return self._handoff(
                workday_auth.AUTH_HANDOFF[auth_result],
                status="awaiting_otp" if auth_result == "verification_needed" else "awaiting_review",
                error="Workday authentication failed" if auth_result == "failed" else None,
            )
        self.recover_site_error()  # the apply_form wait below decides
        if workday_flow.wait_for_state(
            self.page, {"apply_form"}, timeout_s=15, deadline=self.deadline
        ) != "apply_form":
            return self._handoff(
                "Signed in, but the Workday application form did not open; open it in this "
                "tab, then Continue fill.",
            )
        return None

    def _start_fill(self) -> None:
        self.merged: dict[str, Any] = {
            "filled": [],
            "leftovers": [],
            "long_text": [],
            "file_inputs": [],
            "required_empty": [],
            "frames_skipped": 0,
        }
        self.uploads: list[dict[str, Any]] = []
        self.completed_step_outcomes: dict[tuple[int, str], dict[str, Any]] = {}
        self.uploaded_controls: set[tuple[str, str]] = set()
        self.long_text_answers: dict[str, str] = {}
        self.needs_review: list[str] = []
        # Questions recognised as a profile fact the profile leaves blank (every step).
        self.blank_facts: list[dict[str, Any]] = []
        self.facts = questions.facts_from_packet(self.pkt, fields=self.fields)
        if self.fill_mode == "continue":
            from . import fill_repairs

            self.merged["filled"].extend(fill_repairs.correct_previous_answers(
                self.page, self.previous_fill.filled, self.facts,
            ))
        posting_text = self.jd_text
        with contextlib.suppress(Exception):
            posting_text += "\n" + self.page.locator("body").inner_text(timeout=2000)[:50000]
        availability_note = fill_widgets._availability_note(
            self.fields.get("earliest_start", ""), posting_text
        )
        if availability_note:
            self.needs_review.append(availability_note)
        self.barrier_hit: str | None = None
        self.final_step_reached = False
        self.model_unavailable = False
        self.country_rechecked = False
        self.blank_step_rescanned = False
        self.entered = False
