"""First-run onboarding progress for the active profile (`kv('onboarding')` in app.db).

The wizard itself is the SPA's `/welcome` page; this module only remembers where the
student got to, so closing the app mid-wizard resumes at the same step. Onboarding is
per profile because the database is.

Setup has two stages. Stage one (field, resume, content, tools) is what tailoring needs
and keeps the rest of the app closed until `completed`. Stage two (personal,
application, apply_tools, review) is what applying needs and runs with the app open,
until `apply_done`.

A profile that already has real content (an entry in the master resume, or an
installed template) and no onboarding row is an install from before onboarding
existed; it is recorded as complete the first time it is read, so an upgrade never
walks an existing user through setup again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.storage import db

KEY = "onboarding"
Step = Literal[
    "field", "tools", "resume", "personal", "content", "application", "apply_tools",
    "review", "done",
]
Field = Literal["", "cs", "business", "engineering", "other"]

#: Step ids from the five-step wizard, mapped onto the step that replaced each, so a
#: student mid-setup during an upgrade resumes where they were instead of at step one.
_LEGACY_STEPS = {"model": "tools", "basics": "application"}


class OnboardingState(BaseModel):
    step: Step = "field"
    field: Field = ""
    completed: bool = False
    skipped: bool = False
    #: Steps the student skipped (the Review step marks them); cleared when completed later.
    skipped_steps: list[Step] = []
    #: "Start from scratch" on the Resume step: no upload, but the step is answered.
    resume_from_scratch: bool = False
    #: Stage two is finished: the answers and tools that applying needs are set up.
    apply_done: bool = False
    #: The student hid the Getting started guide.
    guide_dismissed: bool = False
    updated_at: str = ""


def _upgrade(raw: dict) -> dict:
    """Map a stored row from an older wizard onto the current steps and stages."""
    step = raw.get("step")
    if step in _LEGACY_STEPS:
        raw = {**raw, "step": _LEGACY_STEPS[step]}
    elif step == "review" and "skipped_steps" not in raw:
        # The old "review" step checked the imported content; that is "content" now.
        raw = {**raw, "step": "content"}
    if "apply_done" in raw:
        return raw
    # A row from the one-stage wizard, where every step came before the app opened.
    if raw.get("completed"):
        # Setup was finished there: nothing new to walk through, and no guide.
        return {**raw, "apply_done": True, "guide_dismissed": True}
    step = raw.get("step")
    if step == "personal":
        # Personal info came third; the next stage-one step still to do is the content check.
        return {**raw, "step": "content"}
    if step in ("application", "review"):
        # Every stage-one step was already behind them: the app opens, stage two resumes here.
        return {**raw, "completed": True}
    return raw


def _conn():
    return db.connect(db.db_path(config.MASTER_RESUME_PATH.parent))


def _has_existing_content() -> bool:
    if config.DEFAULT_TEMPLATE_PATH.exists():
        return True
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError):
        return False
    return any(section.entries for section in resume.entry_sections)


def load() -> OnboardingState:
    conn = _conn()
    with db.transaction(conn):
        raw = db.kv_get(conn, KEY)
        if isinstance(raw, dict):
            try:
                return OnboardingState.model_validate(_upgrade(raw))
            except ValueError:
                pass  # a malformed row restarts the wizard rather than 500ing
        state = OnboardingState()
        if raw is None and _has_existing_content():
            state = OnboardingState(
                step="done", completed=True, apply_done=True, guide_dismissed=True,
                updated_at=_now(),
            )
            db.kv_set(conn, KEY, state.model_dump())
        return state


def save(**changes) -> OnboardingState:
    conn = _conn()
    with db.transaction(conn):
        raw = db.kv_get(conn, KEY)
        try:
            current = (
                OnboardingState.model_validate(_upgrade(raw)) if isinstance(raw, dict) else None
            )
        except ValueError:
            current = None
        merged = (current or OnboardingState()).model_dump() | changes
        merged["updated_at"] = _now()
        state = OnboardingState.model_validate(merged)
        if state.completed and state.apply_done and "step" not in changes:
            state.step = "done"
        db.kv_set(conn, KEY, state.model_dump())
        return state


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
