"""First-run onboarding progress for the active profile (`kv('onboarding')` in app.db).

The wizard itself is the SPA's `/welcome` page; this module only remembers where the
student got to, so closing the app mid-wizard resumes at the same step. Onboarding is
per profile because the database is.

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
    "field", "tools", "resume", "personal", "content", "application", "review", "done"
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
    updated_at: str = ""


def _upgrade(raw: dict) -> dict:
    """Map a stored row from the older wizard onto the current step ids."""
    step = raw.get("step")
    if step in _LEGACY_STEPS:
        return {**raw, "step": _LEGACY_STEPS[step]}
    if step == "review" and "skipped_steps" not in raw:
        # The old "review" step checked the imported content; that is "content" now.
        return {**raw, "step": "content"}
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
            state = OnboardingState(step="done", completed=True, updated_at=_now())
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
        if state.completed:
            state.step = "done"
        db.kv_set(conn, KEY, state.model_dump())
        return state


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
