"""In-app update routes (Settings → About, header chip); see `desktop_update`.

Only the desktop build can update itself. In a dev checkout or Docker, ``GET`` reports
``supported: false`` and the actions answer 409.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from resume_tailor.infra import desktop_update

router = APIRouter()

_UNSUPPORTED = "Updates here come from git pull or docker compose up --build, not the app."


@router.get("/api/update")
def get_update() -> dict[str, Any]:
    return desktop_update.status()


@router.post("/api/update/check")
def check_update() -> dict[str, Any]:
    if not desktop_update.ENABLED:
        raise HTTPException(409, _UNSUPPORTED)
    desktop_update.request("check")
    return desktop_update.status()


@router.post("/api/update/install")
def install_update() -> dict[str, Any]:
    """Download the update found by the last check; it installs once nothing is running."""
    if not desktop_update.ENABLED:
        raise HTTPException(409, _UNSUPPORTED)
    if desktop_update.status()["state"] != "available":
        raise HTTPException(409, "No update is ready to install. Check for updates first.")
    desktop_update.request("download")
    return desktop_update.status()
