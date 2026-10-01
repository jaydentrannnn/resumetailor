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
Step = Literal["field", "model", "resume", "review", "basics", "done"]
Field = Literal["", "cs", "business", "engineering", "other"]


class OnboardingState(BaseModel):
    step: Step = "field"
    field: Field = ""
    completed: bool = False
    skipped: bool = False
    updated_at: str = ""


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
                return OnboardingState.model_validate(raw)
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
            current = OnboardingState.model_validate(raw) if isinstance(raw, dict) else None
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
