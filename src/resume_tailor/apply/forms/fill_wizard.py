"""Walking the application wizard: one step at a time, scanning frames, and advancing."""

from __future__ import annotations

import contextlib
import time
from typing import Any

from resume_tailor import config
from resume_tailor.apply.answers import hybrid_resolver, questions
from resume_tailor.apply.ats import smartrecruiters_flow, workday_flow
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import wizards
from resume_tailor.apply.funnel import packet as apply_packet
from resume_tailor.apply.funnel.store import FillResult

from . import fill_answers, fill_ats_steps, fill_buttons, fill_outcomes, fill_page, fill_widgets


class _FillWizard(fill_answers._FillAnswers, fill_ats_steps._FillAtsSteps):
    """`_FillRun` steps that fill each wizard step and move to the next one."""

    def _walk_wizard(self) -> FillResult | None:
        """Fill and advance up to `_MAX_WIZARD_STEPS` steps. A `FillResult` is a handoff."""
        for step in range(fill_outcomes._MAX_WIZARD_STEPS):
            if self._cancelled():
                self.needs_review.append("Fill cancelled")
                break
            if time.monotonic() >= self.deadline:
                self.needs_review.append("Application fill reached its four-minute limit")
                break
            outcome = self._fill_step(step)
            if isinstance(outcome, FillResult):
                return outcome
            if outcome == fill_outcomes._BREAK:
                break
        return None

    def _fill_step(self, step: int) -> FillResult | str | None:
        self.progress(f"scanning form step {step + 1}")
        self._start_step()
        if self.is_workday:
            handoff = self._workday_step_ready(step)
            if handoff is not None:
                return handoff
            self._workday_fill_widgets()
        if self.wizard is not None:
            handoff = self._wizard_gate(self.wizard)
            if handoff is not None:
                return handoff
        if self._interstitial_barrier():
            return fill_outcomes._BREAK

        self._scan_frames()
        if self.is_workday and self._workday_blank_step():
            return fill_outcomes._CONTINUE
        if self.is_smartrecruiters and smartrecruiters_flow.is_form(self.page):
            self._smartrecruiters_step()
        self._upload_attachments()
        if self._stop_if_out_of_time("Fill stopped before this form step was complete"):
            return fill_outcomes._BREAK
        self._answer_long_text()
        if self._stop_if_out_of_time("Fill stopped before this form step was complete"):
            return fill_outcomes._BREAK
        self._resolve_leftovers()
        # A Greenhouse choice can reveal another EEO control, and a "How did you hear"
        # answer of "Other" reveals "please specify" (filled by the rescan). Scan once more
        # after declared choices, without repeating unresolved model guesses.
        if self.ats_name == "greenhouse" or self.other_chosen:
            self._rescan_revealed_choices()
        if self._stop_if_out_of_time("Fill stopped before this form step was complete"):
            return fill_outcomes._BREAK

        if self.is_workday:
            self._workday_rows()
            if self._workday_consent_needs_review():
                return fill_outcomes._BREAK
            # A wrong Country (the account's saved "Vietnam") re-labels the name and
            # address fields and empties the phone code; correct it and fill the
            # re-rendered step again, once.
            if not self.country_rechecked:
                wrong_country = workday_flow.country_mismatch(self.page, self.fields)
                if wrong_country:
                    self.country_rechecked = True
                    self.progress(
                        f"Workday: Country reads {wrong_country} after filling; correcting "
                        "it and rescanning this step"
                    )
                    return fill_outcomes._CONTINUE
        if self._final_step():
            return fill_outcomes._BREAK
        return self._advance(step)

    def _start_step(self) -> None:
        # One ledger per frame for this step: every resolver pass on the step shares it,
        # so a stuck field is retried alone instead of the whole page again.
        self.ledgers: dict[int, hybrid_resolver.StepLedger] = {}
        self.verified_purposes: set[tuple[str, int]] = set()
        self.attempted_purposes: set[tuple[str, int]] = set()
        self.other_chosen = False
        for key in ("leftovers", "long_text", "file_inputs", "required_empty"):
            self.merged[key] = []
        self.step_filled_start = len(self.merged["filled"])

    def _wizard_gate(self, wizard: wizards.WizardAdapter) -> FillResult | None:
        # A sign-in, an emailed code or a closed posting is the applicant's; checked
        # before this step is filled, so nothing is typed into it.
        page = self.page
        state = wizard.detect_state(page)
        if state == "posting":
            # Still the job description (iCIMS keeps the form behind "Apply for this job
            # online"): open the form once, else hand it over.
            if not self.entered and wizard.enter(page):
                self.entered = True
                self.progress(f"opening the {wizard.label} application form")
                with contextlib.suppress(Exception):
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                state = wizard.detect_state(page)
            if state == "posting":
                return self._handoff(fill_outcomes.NO_FORM_MSG)
        stop = wizard.stop_for(state)
        if stop is not None:
            return self._handoff(stop.message, status=stop.status)
        return None

    def _interstitial_barrier(self) -> bool:
        """Note a CAPTCHA; True when an interstitial (Cloudflare) hides the whole form."""
        barrier = fill_buttons._detect_barriers(self.page)
        if barrier and "Cloudflare" in barrier:
            if not fill_buttons._locator_exists(self.page.locator("input, select, textarea")):
                self.barrier_hit = barrier
                self.progress(f"interstitial barrier encountered: {barrier}")
                return True
        elif barrier:
            self.barrier_hit = barrier
            self.progress(
                f"CAPTCHA noted on form: {barrier} (will fill form then await review)"
            )
        return False

    def _final_step(self) -> bool:
        wizard = self.wizard
        if wizard is not None and wizard.is_final_step(wizard.snapshot(self.page)):
            self.final_step_reached = True
            self.progress(f"{wizard.label} review page reached; the applicant submits")
            return True
        # Workday's Review step is the end: its footer button submits. Stop here whatever
        # the button is called; submission is always the applicant's.
        if self.is_workday and workday_flow.is_review_step(workday_flow.snapshot(self.page)):
            self.final_step_reached = True
            self.progress("Workday Review step reached; leaving it for the applicant to submit")
            return True
        return False

    def _scan_frames(self) -> None:
        self.frames = self.page.frames
        self.pass_start = len(self.merged["filled"])
        for frame_index, frame in enumerate(self.frames):
            try:
                partial = fill_widgets._fill_frame(
                    frame, self.filler_js, self.fields, self.hints, self.facts,
                    self.classify_unkeyed,
                )
            except Exception as exc:  # noqa: BLE001 - cross-origin frames fail evaluate
                self.merged["frames_skipped"] = int(self.merged["frames_skipped"]) + 1
                if frame_index == 0:
                    reason = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
                    self.progress(f"form scan failed on the page: {reason}")
                continue
            if not isinstance(partial, dict):
                continue
            if partial.get("revealed"):
                partial = self._rescan_revealing_frame(frame, partial)
            self._merge_partial(frame_index, partial)

    def _rescan_revealing_frame(self, frame: Any, partial: dict[str, Any]) -> dict[str, Any]:
        # A tick ("I have a preferred name") can reveal more inputs: scan the frame once
        # more and keep the first pass's own fills.
        self.page.wait_for_timeout(600)
        with contextlib.suppress(Exception):
            again = fill_widgets._fill_frame(
                frame, self.filler_js, self.fields, self.hints, self.facts, self.classify_unkeyed
            )
            if isinstance(again, dict):
                first = [item for item in partial.get("filled") or [] if isinstance(item, dict)]
                seen = {item.get("selector") for item in first}
                extra = [
                    item for item in again.get("filled") or []
                    if isinstance(item, dict) and item.get("selector") not in seen
                ]
                partial = {**again, "filled": [*first, *extra]}
        return partial

    def _merge_partial(self, frame_index: int, partial: dict[str, Any]) -> None:
        merged = self.merged
        for key in ("filled", "leftovers", "long_text", "file_inputs", "required_empty"):
            items = partial.get(key) or []
            if key in {"filled", "leftovers", "long_text", "file_inputs"}:
                items = [
                    {**item, "frame_index": frame_index} for item in items
                    if isinstance(item, dict)
                ]
            merged[key].extend(items)
        merged["frames_skipped"] += int(partial.get("frames_skipped") or 0)
        # A derived answer ("currently enrolled?") is blank for want of the profile field
        # it comes from (the graduation date).
        self.blank_facts.extend(
            {**item, "key": questions.profile_field(str(item.get("key") or ""))}
            for item in partial.get("leftovers") or []
            if isinstance(item, dict) and item.get("reason") == apply_packet.BLANK_PROFILE_REASON
        )

    def _advance(self, step: int) -> FillResult | str | None:
        """Press the step's advance button (resolving blockers first when needed), or end
        the walk when there is none."""
        last_step = step >= fill_outcomes._MAX_WIZARD_STEPS - 1
        advance_btn = fill_buttons._find_advance_button(self.page)
        if (not advance_btn or self.merged.get("required_empty")) and not last_step:
            with config.pinned(self.settings.model_spec):
                for frame_index, frame in enumerate(self.frames):
                    hybrid_resolver.resolve_step_blockers(
                        frame, self.pkt, self.profile, on_progress=self.progress,
                        deadline=self.deadline,
                        ledger=self.ledgers.setdefault(frame_index, hybrid_resolver.StepLedger()),
                    )
                    self.model_unavailable |= self.ledgers[frame_index].model_unavailable
            advance_btn = fill_buttons._find_advance_button(self.page)

        if not advance_btn or last_step:
            self.final_step_reached = advance_btn is None and (
                fill_buttons._find_submit_button(self.page, self.hints) is not None or
                (self.is_workday and workday_flow.is_review_step(workday_flow.snapshot(self.page)))
            )
            return fill_outcomes._BREAK

        page = self.page
        attempted_step = {
            (item.get("frame_index", 0), item.get("selector")): item
            for item in self.merged["filled"] if isinstance(item, dict)
        }
        self.completed_step_outcomes.update(
            fill_widgets._observe_fields(page, self.filler_js, self.hints, attempted_step)
        )
        self.progress(f"advancing wizard step {step + 1}")
        before_step = fill_page._form_step_signature(page)
        wd_before = (
            workday_flow.active_step(workday_flow.snapshot(page)) if self.is_workday else ""
        )
        return self._click_advance(advance_btn, before_step, wd_before)

    def _settle_after_advance(self, fallback_ms: int, wd_before: str) -> None:
        # Workday saves the step server-side before painting the next one.
        if self.is_workday:
            workday_flow.wait_for_step_change(self.page, wd_before, deadline=self.deadline)
        else:
            self.page.wait_for_timeout(fallback_ms)

    def _step_unchanged(self, before_step: Any, wd_before: str) -> bool:
        if self.is_workday:
            return workday_flow.active_step(workday_flow.snapshot(self.page)) == wd_before
        return before_step is not None and fill_page._form_step_signature(self.page) == before_step

    def _resolve_invalid_blockers(self) -> None:
        with config.pinned(self.settings.model_spec):
            hybrid_resolver.resolve_step_blockers(
                self.page, self.pkt, self.profile, max_retries=1, on_progress=self.progress,
                deadline=self.deadline,
                ledger=self.ledgers.setdefault(0, hybrid_resolver.StepLedger()),
                only_invalid=True,
            )
            self.model_unavailable |= self.ledgers[0].model_unavailable

    def _click_advance(
        self, advance_btn: Any, before_step: Any, wd_before: str
    ) -> FillResult | str | None:
        retried_advance = False
        try:
            clicks.safe_click(advance_btn, purpose="advance", timeout=5000)
            self._settle_after_advance(1000, wd_before)
            with contextlib.suppress(Exception):
                self.page.wait_for_load_state("networkidle", timeout=self._ms_left(5000))
            if self.is_workday and workday_flow.is_site_error(workday_flow.snapshot(self.page)):
                # Save and Continue hit Workday's error page; after a refresh the draft
                # reopens on whichever step it saved, so scan that one afresh.
                if not self.recover_site_error():
                    return self._handoff(self.SITE_ERROR_MSG)
                return fill_outcomes._CONTINUE
        except Exception:  # noqa: BLE001
            retried_advance = True
            self.progress("wizard advance was blocked; resolving visible blockers once")
            self._resolve_invalid_blockers()
            retry_button = fill_buttons._find_advance_button(self.page)
            if retry_button is None:
                return fill_outcomes._BREAK
            try:
                clicks.safe_click(retry_button, purpose="advance", timeout=5000)
                self._settle_after_advance(500, wd_before)
            except Exception:  # noqa: BLE001
                return fill_outcomes._BREAK
        if not self._step_unchanged(before_step, wd_before):
            return None
        if retried_advance:
            self.progress("wizard is unchanged; handing this tab over for review")
            return fill_outcomes._BREAK
        self.progress("wizard did not advance; resolving visible blockers once")
        self._resolve_invalid_blockers()
        retry_button = fill_buttons._find_advance_button(self.page)
        if retry_button is None:
            return fill_outcomes._BREAK
        with contextlib.suppress(Exception):
            clicks.safe_click(retry_button, purpose="advance", timeout=5000)
            self._settle_after_advance(500, wd_before)
        if self._step_unchanged(before_step, wd_before):
            self.progress("wizard is unchanged; handing this tab over for review")
            return fill_outcomes._BREAK
        return None
