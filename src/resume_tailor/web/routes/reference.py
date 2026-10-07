"""`/api/reference/profile-options`: fixed option lists for the Profile page's pickers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from resume_tailor.apply.answers import reference_data

router = APIRouter()


@router.get("/api/reference/profile-options")
def profile_options() -> dict[str, Any]:
    return reference_data.options()
