"""Workday- and SmartRecruiters-specific step handling for the legacy fill."""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from resume_tailor import config
from resume_tailor.apply.answers import hybrid_resolver
from resume_tailor.apply.ats import smartrecruiters_flow, workday_flow
from resume_tailor.apply.funnel.store import FillResult

from . import fill_outcomes, fill_page, fill_state, fill_widgets


class _FillAtsSteps(fill_state._FillState):
    """`_FillRun` steps that only run on Workday or SmartRecruiters forms."""

    def _workday_step_ready(self, step: int) -> FillResult | None:
        # Workday's own error page ("Error Code: VPS|..."), whether it is showing already
        # or replaces the step while it loads: refresh, which restores the saved draft.
        if not self.recover_site_error():
            return self._handoff(self.SITE_ERROR_MSG)
        if step and workday_flow.detect_state(self.page) in fill_outcomes.SIGNED_OUT_STATES:
            # The session timed out mid-application. Workday keeps the saved steps, and
            # Continue fill signs in again from this tab.
            return self._handoff(fill_outcomes.SESSION_EXPIRED_MSG)
        if workday_flow.wait_for_step_ready(self.page, deadline=self.deadline):
            return None
        if not workday_flow.is_site_error(workday_flow.snapshot(self.page)):
            self.progress("Workday step did not finish loading; scanning what is visible")
            return None
        if not self.recover_site_error():
            return self._handoff(self.SITE_ERROR_MSG)
        self.page, _state = workday_flow.enter_application(
            self.page, self.context, deadline=self.deadline, progress=self.progress
        )
        fill_widgets._guard_file_chooser(self.page, self.progress)
        if not workday_flow.wait_for_step_ready(self.page, deadline=self.deadline):
            return self._handoff(self.SITE_ERROR_MSG)
        return None

    def _workday_fill_widgets(self) -> None:
        """Workday's own dropdowns, radios, self-identification and prompts."""
        page, fields, pkt = self.page, self.fields, self.pkt
        self.progress(
            f"Workday step: {workday_flow.active_step(workday_flow.snapshot(page)) or 'unknown'}"
        )
        employers = [entry.company for entry in getattr(self.resume, "experience", []) or []]
        dropdown_review: list[str] = []
        wd_filled = workday_flow.fill_dropdowns(
            page, fields, progress=self.progress, deadline=self.deadline,
            select=workday_flow.select_listbox, review=dropdown_review, blank=self.blank_facts,
        )
        if any(item.get("key") == "country" for item in wd_filled):
            self.needs_review[:] = [
                label for label in self.needs_review if not label.startswith("Country is ")
            ]
        self._review(dropdown_review)
        wd_filled += workday_flow.fill_radios(
            page, fields, progress=self.progress,
            company=self.app.company or pkt.company or "",
            employers=employers,
            role=self.app.role or pkt.role or "",
            experience_titles=[entry.title for entry in pkt.experience],
            blank=self.blank_facts, review=dropdown_review,
        )
        self._review(dropdown_review)
        # Self-identification answers rendered as checkboxes (the disability form), then
        # the Self Identify step's signature Name and Date.
        self_id_review: list[str] = []
        ticked = workday_flow.fill_choice_checkboxes(
            page, fields, progress=self.progress, review=self_id_review, employers=employers,
        )
        wd_filled += ticked
        if ticked or workday_flow.is_self_identify_step(workday_flow.snapshot(page)):
            wd_filled += workday_flow.fill_self_identify(
                page, fields, today=date.today(), progress=self.progress, review=self_id_review,
            )
        self._review(self_id_review)
        wd_filled += workday_flow.fill_prompts(page, fields, progress=self.progress)
        wd_filled += self._workday_skills()
        self.merged["filled"].extend({**item, "frame_index": 0} for item in wd_filled)
        self._workday_phone_code()

    def _workday_skills(self) -> list[dict[str, Any]]:
        skills_deadline = min(self.deadline, time.monotonic() + 120)
        with config.pinned(self.settings.model_spec):
            skill_chips, skills_left = workday_flow.fill_skills(
                self.page, list(self.pkt.skills), progress=self.progress,
                deadline=skills_deadline,
                choose_many=lambda unmatched: hybrid_resolver.choose_skill_options(
                    unmatched, deadline=skills_deadline,
                ),
            )
        if skills_left:
            note = f"Skills not found on the form: {', '.join(skills_left)}"
            self.needs_review[:] = [
                item for item in self.needs_review if not item.startswith("Skills not found")
            ]
            self.needs_review.append(note)
        return skill_chips

    def _workday_phone_code(self) -> None:
        phone_code = workday_flow.ensure_phone_code(
            self.page, self.fields.get("phone_country_region", ""),
            self.fields.get("phone_country_code", ""), progress=self.progress,
        )
        if phone_code is False and "Country Phone Code" not in self.needs_review:
            self.needs_review.append("Country Phone Code")
        elif phone_code and "Country Phone Code" in self.needs_review:
            self.needs_review.remove("Country Phone Code")

    def _workday_blank_step(self) -> bool:
        """Commit typed textareas; True when the step scanned blank and is rescanned."""
        fill_widgets._commit_workday_textareas(self.frames, self.merged["filled"][self.pass_start:])
        # Philips (2026-09) paints My Information, then re-renders it for the account's
        # saved country: a scan in between finds no controls at all, and pressing Next
        # then leaves the whole step blank. Wait and rescan once.
        if (
            not self.blank_step_rescanned
            and fill_page._scanned_nothing(self.merged, self.step_filled_start)
            and not workday_flow.is_review_step(workday_flow.snapshot(self.page))
        ):
            self.blank_step_rescanned = True
            self.progress("Workday step showed no fields to fill yet; rescanning once it settles")
            self.page.wait_for_timeout(1500)
            return True
        return False

    def _workday_rows(self) -> None:
        # Workday structured experience & education injection (My Experience only).
        if "experience" not in workday_flow.active_step(
            workday_flow.snapshot(self.page)
        ).casefold():
            return
        rows_filled, rows_review = fill_widgets._fill_workday_experience_and_education(
            self.page, self.pkt, self.progress
        )
        self.merged["filled"].extend(
            {**item, "key": "workday_row", "frame_index": 0} for item in rows_filled
        )
        self._review(rows_review)

    def _workday_consent_needs_review(self) -> bool:
        from resume_tailor.apply.forms import form_routes  # noqa: PLC0415

        merged = self.merged
        consent_filled, consent_review = form_routes.accept_workday_sync(self.page)
        merged["filled"].extend({**item, "frame_index": 0} for item in consent_filled)
        accepted_labels = {item["label"] for item in consent_filled}
        merged["required_empty"] = [
            label for label in merged["required_empty"] if label not in accepted_labels
        ]
        merged["leftovers"] = [
            item for item in merged["leftovers"] if item.get("label") not in accepted_labels
        ]
        self.needs_review[:] = [
            label for label in self.needs_review if label not in accepted_labels
        ]
        self._review(consent_review)
        if consent_review:
            self.progress("Required Workday consent needs review; leaving this step open")
            return True
        return False

    def _smartrecruiters_step(self) -> None:
        # SmartRecruiters' one-click form: a City typeahead that drops typed text on blur,
        # inline Experience/Education editors, a Resume dropzone whose input shares its id
        # with the parse-and-prefill one, and the hiring-team message
        # (`smartrecruiters_flow`). The generic pass's records for them are replaced.
        merged, page = self.merged, self.page
        self.progress(
            "SmartRecruiters: filling city, experience, education, resume, message and "
            "screening"
        )
        sr_filled, sr_review = smartrecruiters_flow.fill(
            page, self.pkt, self.progress, resume_path=self.resume_path,
            deadline=self.deadline - 45,
        )
        # The screening step's controls read as "*" to the generic pass; the flow answered
        # or listed them, so those records are dropped too.
        handled = smartrecruiters_flow.HANDLED_SELECTORS
        owned = handled | smartrecruiters_flow.screening_selectors(page)
        for key in ("filled", "leftovers", "long_text"):
            merged[key] = [
                item for item in merged[key] if not isinstance(item, dict) or (
                    item.get("key") != "city" and item.get("label") != "City"
                    and item.get("selector") not in owned
                )
            ]
        if owned - handled:
            merged["required_empty"] = [
                label for label in merged.get("required_empty") or []
                if str(label).strip() not in {"", "*"}
            ]
        merged["file_inputs"] = [
            item for item in merged["file_inputs"]
            if not isinstance(item, dict) or item.get("selector") not in handled
        ]
        done = {
            item.get("label") for item in merged["filled"]
            if item.get("key") == "smartrecruiters_entry"
        }
        merged["filled"].extend(
            {**item, "key": "smartrecruiters_entry", "frame_index": 0}
            for item in sr_filled if item["label"] not in done
        )
        self._review(sr_review)
