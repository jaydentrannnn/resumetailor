"""`GET/PUT /api/onboarding`: where the first-run wizard left off (see `onboarding.py`)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from resume_tailor.content import onboarding

router = APIRouter()


class OnboardingUpdate(BaseModel):
    step: onboarding.Step | None = None
    field: onboarding.Field | None = None
    completed: bool | None = None
    skipped: bool | None = None
    skipped_steps: list[onboarding.Step] | None = None
    resume_from_scratch: bool | None = None


@router.get("/api/onboarding", response_model=onboarding.OnboardingState)
def get_onboarding() -> onboarding.OnboardingState:
    return onboarding.load()


@router.put("/api/onboarding", response_model=onboarding.OnboardingState)
def put_onboarding(body: OnboardingUpdate) -> onboarding.OnboardingState:
    return onboarding.save(**body.model_dump(exclude_none=True))
