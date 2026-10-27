"""Deterministic ATS form fill via the host browser over CDP (Edge recommended).

Injects ``filler.js``, uploads resume PDF, drafts long-text leftovers through
``answer.answer_question``, then either stops for review or auto-submits when
``ats`` is listed in ``ApplySettings.auto_submit_ats``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any, Literal

from resume_tailor import config
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.driver import browser, watchdog
from resume_tailor.apply.funnel import store
from resume_tailor.apply.funnel.store_models import FillResult
from resume_tailor.infra import model_queue, wait_clock
from resume_tailor.web.schemas import ApplySettings, JobSettings

from . import fill_diagnostics, fill_entry, fill_finish, fill_widgets, fill_wizard, submit_guard


@model_queue.observe_progress
def fill_application(
    source_job_id: str,
    *,
    settings: ApplySettings | None = None,
    submit_mode: Literal["auto_submit", "awaiting_review"] | None = None,
    fill_mode: Literal["initial", "continue", "reopen"] = "initial",
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[str], None] | None = None,
    applicant_profile: profile_mod.ApplicantProfile | None = None,
    on_deadline: Callable[[float], None] | None = None,
) -> FillResult:
    """Fill one application's ATS form; leave the tab open under policy A.

    ``on_deadline`` hears the fill's new deadline (epoch seconds) each time forward
    progress extends it, so a countdown can follow."""
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(f"Unknown application {source_job_id!r}")
    from resume_tailor.apply.funnel import preparation

    if settings is None:
        from resume_tailor import workspace

        settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply
    eligibility = preparation.check(app)
    if not eligibility.eligible:
        raise RuntimeError(f"Application needs Prepare: {', '.join(eligibility.reasons)}")
    engine_name = config.apply_fill_engine()
    if engine_name not in {"legacy", "verified"}:
        raise ValueError(f"Unsupported APPLY_FILL_ENGINE={engine_name!r}")
    if engine_name == "verified":
        from resume_tailor.apply.forms import engine

        return asyncio.run(engine.fill_application(
            source_job_id, settings=settings, submit_mode=submit_mode,
            fill_mode=fill_mode, should_cancel=should_cancel,
            on_progress=on_progress, applicant_profile=applicant_profile,
            on_deadline=on_deadline,
        ))

    if not app.job_id:
        result = FillResult(error="No tailored job_id on application", status="fill_failed")
        store.set_status(app, "fill_failed", note=result.error or "")
        app.fill = result
        store.upsert(app)
        return result

    try:
        run = _FillRun(
            app,
            source_job_id=source_job_id,
            settings=settings,
            submit_mode=submit_mode,
            fill_mode=fill_mode,
            should_cancel=should_cancel,
            on_progress=on_progress,
            applicant_profile=applicant_profile,
            on_deadline=on_deadline,
        )
    except Exception as exc:  # noqa: BLE001 - recorded on the row, never left "filling"
        return _failed_before_start(app, exc)
    return run.run()


def _failed_before_start(app: Any, exc: Exception) -> FillResult:
    """The fill could not start (its packet, profile or site check failed): the row says
    exactly why, keeping its recorded tab so Continue fill still finds it."""
    previous = FillResult.model_validate(app.fill) if app.fill else FillResult()
    result = previous.model_copy(update={"error": str(exc), "status": "fill_failed"})
    store.set_status(app, "fill_failed", note=str(exc))
    app.fill = result
    store.upsert(app)
    return result


class _FillRun(fill_entry._FillEntry, fill_wizard._FillWizard, fill_finish._FillFinish):
    """The state and steps of one legacy-engine `fill_application` call.

    `__init__` gathers everything the fill needs before touching the browser; `run`
    opens the form, walks the wizard one step at a time (`_fill_step`), then verifies,
    optionally submits, and records the result (`_finish`). Step methods that can end the
    fill return a `FillResult` (a handoff) or `_BREAK`/`_CONTINUE` for the wizard loop.
    """

    def run(self) -> FillResult:
        started = time.monotonic()
        # A fill has someone waiting on it: its model requests go ahead of tailoring, and
        # time queued behind other work does not count against its deadline (audit #28).
        with (
            model_queue.count_requests() as requests,
            model_queue.interactive(),
            wait_clock.track(self.progress) as self.waits,
        ):
            result = self._run()
        return self._record_diagnostics(result, time.monotonic() - started, requests[0])

    def _record_diagnostics(self, result: FillResult, elapsed_s: float, calls: int) -> FillResult:
        """Attach `fill_diagnostics` to the result every exit path returns, and save it
        where that path saved the result. Never fails the fill."""
        with contextlib.suppress(Exception):
            page = getattr(self, "page", None)
            result.tab_history = list(getattr(self, "tab_history", result.tab_history))
            result.diagnostics = {**result.diagnostics, **fill_diagnostics.build(
                result, posting_url=getattr(self, "url", "") or "",
                landed_url=str(page.url) if page is not None else "", elapsed_s=elapsed_s,
                model_calls=calls, needs_review=getattr(self, "needs_review", None),
                landed_platform=getattr(self, "landed_platform", ""),
            )}
            # `upsert` refreshed ``self.app.fill`` to a copy, so the saved result is found
            # by content: everything but what was just added.
            saved = self.app.fill
            added = {"diagnostics", "tab_history"}
            if isinstance(saved, FillResult) and (
                saved.model_dump(exclude=added) == result.model_dump(exclude=added)
            ):
                saved.diagnostics, saved.tab_history = result.diagnostics, result.tab_history
                store.upsert(self.app)
            path = self.out_dir / "fill.json"
            if path.is_file() and path.stat().st_mtime >= time.time() - elapsed_s - 1:
                path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def _run(self) -> FillResult:
        stall = watchdog.Stall()
        try:
            self.progress("connecting to browser")
            with browser.cdp_browser(self.target_id) as pw_browser:
                pid = watchdog.driver_pid(pw_browser)
                with watchdog.stall_guard(
                    lambda: self.deadline,
                    cut=(lambda: watchdog.kill_driver(pid)) if pid else None,
                    label=f"{self.app.company or 'fill'} {self.source_job_id[:8]}",
                ) as stall:
                    return self._run_connected(pw_browser)
        except Exception as exc:  # noqa: BLE001
            error = stall.message() if stall.fired else str(exc)
            if self.submit_dispatched:
                return self._failed_after_submit(error)
            result = self.previous_fill.model_copy(update={
                "error": error, "status": "fill_failed", "browser_target_id": self.target_id,
                "browser_url": (
                    self.page.url if self.page is not None else self.previous_fill.browser_url
                ),
                "handoff_reason": "fill stopped responding" if stall.fired else "fill failed",
            })
            store.set_status(self.app, "fill_failed", note=error)
            self.app.fill = result
            self.app.error = error
            store.upsert(self.app)
            return result

    def _failed_after_submit(self, error: str) -> FillResult:
        """The fill failed after sending the final submit. The employer may have the
        application, so it stays unconfirmed: the caps and duplicate checks count it, and
        no retry submits it again (a failed fill would free both)."""
        sent = FillResult.model_validate(self.app.fill) if self.app.fill else self.previous_fill
        result = sent.model_copy(update={
            "error": error, "status": "submit_unconfirmed", "submit_action": "auto_submit",
            "browser_target_id": self.target_id,
            "handoff_reason": "Submission sent; the fill failed before confirming it",
        })
        store.set_status(self.app, "submit_unconfirmed", note=submit_guard.AUTO_NOTE)
        self.app.fill = result
        self.app.error = error
        store.upsert(self.app)
        return result

    def _run_connected(self, pw_browser: object) -> FillResult:
        self.context = (
            pw_browser.contexts[0]
            if pw_browser.contexts
            else pw_browser.new_context()
        )
        handoff = self._open_form()
        if handoff is None:
            handoff = self._choose_route_and_sign_in()
        if handoff is not None:
            return handoff
        fill_widgets._guard_file_chooser(self.page, self.progress)
        self._start_fill()
        handoff = self._walk_wizard()
        if handoff is not None:
            return handoff
        return self._finish()
