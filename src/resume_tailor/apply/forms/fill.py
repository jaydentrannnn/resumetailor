"""Deterministic ATS form fill via the host browser over CDP (Edge recommended).

Injects ``filler.js``, uploads resume PDF, drafts long-text leftovers through
``answer.answer_question``, then either stops for review or auto-submits when
``ats`` is listed in ``ApplySettings.auto_submit_ats``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Literal

from resume_tailor import config
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.driver import browser
from resume_tailor.apply.funnel import store
from resume_tailor.apply.funnel.store_models import FillResult
from resume_tailor.web.schemas import ApplySettings, JobSettings

from . import fill_entry, fill_finish, fill_widgets, fill_wizard


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
    app = store.get(source_job_id)
    if app is None:
        raise KeyError(f"Unknown application {source_job_id!r}")
    from resume_tailor.apply.funnel import preparation

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
        from resume_tailor.apply.forms import engine

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

    return _FillRun(
        app,
        source_job_id=source_job_id,
        settings=settings,
        submit_mode=submit_mode,
        fill_mode=fill_mode,
        should_cancel=should_cancel,
        on_progress=on_progress,
        applicant_profile=applicant_profile,
    ).run()


class _FillRun(fill_entry._FillEntry, fill_wizard._FillWizard, fill_finish._FillFinish):
    """The state and steps of one legacy-engine `fill_application` call.

    `__init__` gathers everything the fill needs before touching the browser; `run`
    opens the form, walks the wizard one step at a time (`_fill_step`), then verifies,
    optionally submits, and records the result (`_finish`). Step methods that can end the
    fill return a `FillResult` (a handoff) or `_BREAK`/`_CONTINUE` for the wizard loop.
    """

    def run(self) -> FillResult:
        try:
            self.progress("connecting to browser")
            with browser.cdp_browser() as pw_browser:
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
        except Exception as exc:  # noqa: BLE001
            result = self.previous_fill.model_copy(update={
                "error": str(exc), "status": "fill_failed", "browser_target_id": self.target_id,
                "browser_url": (
                    self.page.url if self.page is not None else self.previous_fill.browser_url
                ),
                "handoff_reason": "fill failed",
            })
            store.set_status(self.app, "fill_failed", note=str(exc))
            self.app.fill = result
            self.app.error = str(exc)
            store.upsert(self.app)
            return result
