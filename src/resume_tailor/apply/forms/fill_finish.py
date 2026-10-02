"""Finishing a fill: readiness checks, upload verification, submit, and the recorded result."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

from resume_tailor.apply.ats import workday_flow, workday_page
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import submit_guard
from resume_tailor.apply.funnel import packet as apply_packet
from resume_tailor.apply.funnel import store
from resume_tailor.apply.funnel.store import FillResult

from . import fill_buttons, fill_outcomes, fill_page, fill_state, fill_widgets


class _FillFinish(fill_state._FillState):
    """`_FillRun` steps that verify, optionally submit, and record the result."""

    def _finish(self) -> FillResult:
        page, merged = self.page, self.merged
        required_empty = self._final_required_empty()
        attempted_count = (
            len(merged.get("filled") or []) + len(merged.get("leftovers") or [])
            + len(merged.get("long_text") or [])
        )
        self._reconcile_observed()
        if self.is_workday:
            workday_page.close_stray_popups(page)
        shot = self._capture_screenshot()
        guarded = self._readiness_guard(attempted_count, shot)
        if guarded is not None:
            return guarded

        self.progress("verifying required fields and attachments")
        self._verify_uploads()
        required_upload_failed = any(not item.get("verified") for item in self.uploads)
        ready_to_submit = (
            len(required_empty) == 0
            and not self.needs_review
            and not self.barrier_hit
            and not required_upload_failed
            and self.final_step_reached
        )
        self._submit(required_empty, ready_to_submit)
        result = self._build_result(required_empty, ready_to_submit, shot)
        (self.out_dir / "fill.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        # Policy B: leave the tab open when awaiting human review.
        note = self.barrier_hit or (self.held.message if self.held else self.submit_action)
        store.set_status(self.app, self.final_status, note=note)  # type: ignore[arg-type]
        self.app.fill = result
        store.upsert(self.app)
        self.progress(f"done status={self.final_status}")
        return result

    def _final_required_empty(self) -> list[str]:
        required_empty: list[str] = []
        for frame in self.page.frames:
            try:
                ready = frame.evaluate(self.readiness_js)
                if isinstance(ready, list):
                    required_empty.extend(str(item) for item in ready)
                elif isinstance(ready, dict):
                    required_empty.extend(str(item) for item in ready.get("required_empty") or [])
            except Exception:  # noqa: BLE001
                continue
        if not required_empty:
            required_empty = list(self.merged.get("required_empty") or [])
        return list(dict.fromkeys(required_empty))

    def _reconcile_observed(self) -> None:
        """Replace the fill's own records with what the form shows now."""
        merged = self.merged
        attempted = {
            (item.get("frame_index", 0), item.get("selector")): item
            for item in merged.get("leftovers") or []
            if isinstance(item, dict) and item.get("selector")
        }
        attempted.update({
            (item.get("frame_index", 0), item.get("selector")): item
            for item in merged.get("filled") or [] if isinstance(item, dict)
        })
        observed = {
            **self.completed_step_outcomes,
            **fill_widgets._observe_fields(self.page, self.filler_js, self.hints, attempted),
        }
        observed_labels = {str(item.get("label") or "") for item in observed.values()}
        self.needs_review = [
            label for label in self.needs_review
            if label not in observed_labels or label == "No salary range in the applicant profile"
        ]
        if not observed and attempted:
            self.needs_review.append("Filled values could not be verified on the current form")
        # Repeater rows have no single selector to observe by; without this they vanished
        # from the record even when every field was filled.
        rows_done = [
            item for item in merged.get("filled") or []
            if isinstance(item, dict)
            and item.get("key") in {"workday_row", "smartrecruiters_entry"}
        ]
        merged["filled"] = list(observed.values()) + rows_done

    def _capture_screenshot(self) -> Path | None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        shot: Path | None = self.out_dir / "fill.png"
        try:
            self.progress("capturing fill evidence")
            self.page.screenshot(path=str(shot), full_page=True)
        except Exception:  # noqa: BLE001
            shot = None
        return shot

    def _readiness_guard(self, total_controls: int, shot: Path | None) -> FillResult | None:
        """Fail or hand over a fill that never reached a real form."""
        page = self.page
        if self.barrier_hit:
            return None
        if (
            total_controls == 0 and self.is_workday
            and workday_flow.is_site_error(workday_page.snapshot(page))
        ):
            return self._handoff(self.SITE_ERROR_MSG)
        if total_controls and not fill_page._form_questions(self.merged):
            # iCIMS (2026-09): the job page's language picker was "filled", and the
            # untouched posting was reported ready for review.
            return self._handoff(fill_outcomes.NO_FORM_MSG)
        if total_controls:
            return None
        guard_msg = "No application form controls detected on page"
        with contextlib.suppress(Exception):
            if "page you are looking for doesn't exist" in page.inner_text("body").casefold():
                guard_msg = "Posting is unavailable: Workday says this page does not exist"
        result = FillResult(
            error=guard_msg,
            status="fill_failed",
            screenshot_path=str(shot) if shot else None,
            browser_target_id=self.target_id,
            browser_url=page.url,
            handoff_reason="form unavailable",
        )
        store.set_status(self.app, "fill_failed", note=guard_msg)
        self.app.fill = result
        store.upsert(self.app)
        self.progress("done status=fill_failed (no controls detected)")
        return result

    def _verify_uploads(self) -> None:
        uploads = self.uploads
        if self.fill_mode == "continue":
            for prior in self.previous_fill.uploads:
                purpose = prior.get("purpose")
                filename = prior.get("filename")
                if purpose not in {"resume", "cover_letter"} or any(
                    item.get("purpose") == purpose and item.get("verified") for item in uploads
                ):
                    continue
                visible = bool(filename) and self._filename_visible(str(filename))
                uploads.append({
                    "purpose": purpose, "filename": filename or "", "verified": visible,
                    "preserved": visible,
                    "error": "" if visible else "Previous attachment is not visible in this tab",
                })
        by_purpose: dict[str, dict[str, Any]] = {}
        for item in uploads:
            purpose = str(item.get("purpose") or "unknown")
            current = by_purpose.get(purpose)
            if current is None or (not current.get("verified") and item.get("verified")):
                by_purpose[purpose] = item
        self.uploads = list(by_purpose.values())

    def _filename_visible(self, filename: str) -> bool:
        for frame in self.page.frames:
            with contextlib.suppress(Exception):
                count = frame.get_by_text(filename, exact=False).count()
                if isinstance(count, int) and count > 0:
                    return True
        return False

    def _submit(self, required_empty: list[str], ready_to_submit: bool) -> None:
        """Auto-submit when policy, the guards and pacing all allow it."""
        self.submit_action = "awaiting_review"
        self.confirmation = ""
        self.final_status = "awaiting_review"
        self.held: submit_guard.Hold | None = None
        action = fill_buttons.decide_submit_action(
            ats=self.app.ats or self.pkt.ats,
            settings=self.settings,
            ready_to_submit=ready_to_submit,
            submit_mode=self.submit_mode,
        )
        if self._cancelled():
            action = "awaiting_review"
        if action == "auto_submit":
            self.held = submit_guard.check(self.app, self.settings)
            if self.held is not None:
                action = "awaiting_review"
                self.progress(f"auto-submit held: {self.held.message}")
        if action != "auto_submit":
            return
        with submit_guard.pace(
            should_cancel=self.should_cancel,
            on_wait=lambda seconds: self.progress(f"waiting {seconds:.0f}s before submitting"),
            can_submit=self._submit_still_allowed,
        ) as go:
            if not go:
                self.held = self.held or submit_guard.Hold(
                    "paused", "Submit stopped: cancelled or paused while waiting"
                )
            else:
                self._dispatch_submit(action, required_empty, ready_to_submit)

    def _submit_still_allowed(self) -> bool:
        self.held = submit_guard.check(self.app, self.settings)
        return self.held is None

    def _dispatch_submit(
        self, action: str, required_empty: list[str], ready_to_submit: bool
    ) -> None:
        page, merged = self.page, self.merged
        submit_sel = fill_page._hint_selector(self.hints, "submit")
        confirm_text = self.hints.get("confirmation_text") or "thank you"
        dispatched = False
        try:
            before_url = page.url
            before_body = page.inner_text("body")
            submit_btn = (
                page.locator(submit_sel).first
                if submit_sel
                else fill_buttons._find_submit_button(page, self.hints)
            )
            if submit_btn is None or submit_btn.count() == 0:
                raise RuntimeError("Final submit button was not found")
            # Persist intent before dispatch. A crash after this point must never cause an
            # automatic second click on restart.
            self.app.fill = FillResult(
                filled=list(merged.get("filled") or []),
                leftovers=list(merged.get("leftovers") or []),
                uploads=self.uploads,
                required_empty=required_empty,
                ready_to_submit=ready_to_submit,
                submit_action="auto_submit",
                status="submit_unconfirmed",
                browser_target_id=self.target_id,
                browser_url=before_url,
                handoff_reason="Submission dispatched; confirmation pending",
                final_step_reached=self.final_step_reached,
            )
            store.upsert(self.app)
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            audit_dir = self.out_dir / f"submit-{stamp}"
            fill_page._record_submit_evidence(page, audit_dir, "before", {
                "url": before_url,
                "fields": list(merged.get("filled") or []),
                "uploads": self.uploads,
            }, required=True)
            dispatched = True
            clicks.submit_click(submit_btn, decision=action, timeout=10_000)
            page.wait_for_load_state("networkidle", timeout=30_000)
            self.submit_action = "auto_submit"
            if fill_page._submission_confirmed(
                page,
                before_url=before_url,
                before_body=before_body,
                confirmation_text=confirm_text,
                ats=self.app.ats or self.pkt.ats,
            ):
                self.confirmation = confirm_text
                self.final_status = "submitted"
            else:
                self.confirmation = "missing"
                self.final_status = "submit_unconfirmed"
        except Exception as exc:  # noqa: BLE001
            self.confirmation = str(exc)
            self.submit_action = "auto_submit"
            self.final_status = "submit_unconfirmed" if dispatched else "fill_failed"
        if dispatched:
            fill_page._record_submit_evidence(page, audit_dir, "after", {
                "url": fill_page._page_url(page),
                "status": self.final_status,
                "confirmation": self.confirmation,
            })

    def _build_result(
        self, required_empty: list[str], ready_to_submit: bool, shot: Path | None
    ) -> FillResult:
        merged, barrier_hit, held = self.merged, self.barrier_hit, self.held
        # A repeater row has no selector; its label keeps each row its own entry.
        outcomes = {
            (item.get("frame_index", 0), item.get("selector") or f"label:{item.get('label')}"): item
            for item in merged.get("filled") or []
            if isinstance(item, dict)
        }
        remaining = [
            item for item in merged.get("leftovers") or []
            if isinstance(item, dict)
            and (item.get("frame_index", 0), item.get("selector")) not in outcomes
        ]
        review_rows = [
            {"label": n, "reason": "needs_review"} for n in self.needs_review
            if not any(
                item.get("label") == n and item.get("key") == "salary_expectation"
                for item in remaining
            )
        ]
        return FillResult(
            filled=list(outcomes.values()),
            leftovers=remaining
            + review_rows
            + ([{"label": barrier_hit, "reason": "barrier"}] if barrier_hit else []),
            long_text_answers=self.long_text_answers,
            uploads=self.uploads,
            required_empty=required_empty,
            ready_to_submit=ready_to_submit,
            submit_action=self.submit_action,
            confirmation=self.confirmation,
            screenshot_path=str(shot) if shot else None,
            status=self.final_status,
            browser_target_id=self.target_id,
            browser_url=self.page.url,
            handoff_reason=barrier_hit or (
                "autofill model unavailable" if self.model_unavailable and required_empty
                else "missing answers" if required_empty or self.needs_review
                else held.message if held
                else "ready for review"
            ),
            final_step_reached=self.final_step_reached,
            field_outcomes=list(outcomes.values()),
            missing_profile=apply_packet.missing_profile(
                # Withheld for another country's posting, not blank in the profile.
                [
                    item for item in self.blank_facts
                    if not (self.mismatch and item.get("key") == "authorized_to_work")
                ],
                {
                    str(item.get("label") or "") for item in merged.get("filled") or []
                    if isinstance(item, dict)
                },
            ),
        )
