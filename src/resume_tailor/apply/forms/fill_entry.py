"""Opening the application form: the posting, Workday entry, route choice and sign-in."""

from __future__ import annotations

import contextlib
from typing import Any

from resume_tailor.apply.answers import questions
from resume_tailor.apply.ats import workday_auth, workday_flow, workday_page
from resume_tailor.apply.driver import browser
from resume_tailor.apply.forms import form_guards
from resume_tailor.apply.funnel.store_models import FillResult

from . import fill_buttons, fill_page, fill_state, fill_widgets


class _FillEntry(fill_state._FillState):
    """`_FillRun` steps that get from the posting to the first form step."""

    def _open_form(self) -> FillResult | None:
        context = self.context
        if self.fill_mode == "continue":
            self.page = browser.find_target(context, self.target_id)
            if self.page is None:
                raise RuntimeError(
                    "Review tab was closed. Use Reopen and fill to start a new tab; "
                    "unsaved answers may be lost."
                )
            self.progress("continuing the existing application tab")
            if self.is_workday:
                # A popup left open by the last fill or by the applicant blocks this one.
                workday_page.close_stray_popups(self.page)
        else:
            self.page = context.new_page()
            self.target_id = browser.target_id(context, self.page)
            self._record_target(self.url)
        with contextlib.suppress(Exception):
            self.page.set_default_timeout(10_000)
        if self.fill_mode != "continue":
            handoff = self._load_posting()
            if handoff is not None:
                return handoff
        if self.is_workday:
            handoff = self._enter_workday()
            if handoff is not None:
                return handoff
        if self.fill_mode != "continue" or self.is_workday:
            self.target_id = browser.target_id(context, self.page)
            self._record_target(self.page.url)
        self.progress("application form opened")
        language = form_guards.form_language(fill_page._page_lang(self.page))
        if language:
            return self._handoff(f"{language}. Fill it in this tab.")
        return None

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
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=self._ms_left(10_000))
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
        self.needs_review: list[str] = (
            [self.authorization_note] if self.authorization_note else []
        )
        # Questions recognised as a profile fact the profile leaves blank (every step).
        self.blank_facts: list[dict[str, Any]] = []
        self.facts = questions.facts_from_packet(self.pkt, fields=self.fields)
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
