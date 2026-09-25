"""Typed httpx client over the ResumeTailor web API for MCP tools.

Error translation is the main job: FastAPI's ``detail`` is sometimes a string and
sometimes a dict, and a connect failure should tell the agent to start uvicorn
rather than dump a stack trace.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

#: Env override for the backend base URL. Claude Desktop launches with a minimal
#: environment, so this is the only config the MCP process needs.
DEFAULT_API_BASE = "http://127.0.0.1:8000"

_BACKEND_DOWN = (
    "ResumeTailor backend is not running. Start it with: "
    "uvicorn resume_tailor.web.app:app --reload --app-dir src"
)


class BackendError(Exception):
    """HTTP or connectivity failure talking to the ResumeTailor web API."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """Record a human-readable message and optional HTTP status."""
        super().__init__(message)
        self.status_code = status_code


def _detail(payload: Any) -> str:
    """Flatten FastAPI's string-or-dict ``detail`` into one agent-readable string."""
    if payload is None:
        return "Unknown error"
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        if "message" in payload and isinstance(payload["message"], str):
            return payload["message"]
        if "detail" in payload:
            return _detail(payload["detail"])
        return str(payload)
    if isinstance(payload, list):
        parts = [_detail(item) for item in payload]
        return "; ".join(parts)
    return str(payload)


def auth_headers() -> dict[str, str]:
    """The session-token header when the server requires one (`web/security.py`)."""
    from resume_tailor.web.security import HEADER_NAME, read_client_token

    token = read_client_token()
    return {HEADER_NAME: token} if token else {}


class BackendClient:
    """Async HTTP client for the routes the MCP tools wrap.

    Construct with an existing ``httpx.AsyncClient`` (tests inject
    ``ASGITransport(app=app)``) or call ``from_env()`` for production.
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Wrap an already-configured httpx client (base URL already set)."""
        self._http = http

    @classmethod
    def from_env(cls) -> BackendClient:
        """Build a client against ``RESUME_TAILOR_API`` (default localhost:8000)."""
        base = os.environ.get("RESUME_TAILOR_API", DEFAULT_API_BASE).rstrip("/")
        return cls(httpx.AsyncClient(base_url=base, timeout=30.0, headers=auth_headers()))

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue one request; raise ``BackendError`` on connect or HTTP failure."""
        try:
            response = await self._http.request(method, path, json=json, params=params)
        except httpx.ConnectError as exc:
            raise BackendError(_BACKEND_DOWN) from exc
        except httpx.HTTPError as exc:
            raise BackendError(f"HTTP error talking to ResumeTailor: {exc}") from exc

        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            detail = _detail(body.get("detail", body) if isinstance(body, dict) else body)
            raise BackendError(detail, status_code=response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.content

    async def get_config(self) -> dict[str, Any]:
        """GET /api/config — also used as the startup health probe."""
        return await self._request("GET", "/api/config")

    async def get_settings(self) -> dict[str, Any]:
        """GET /api/settings."""
        return await self._request("GET", "/api/settings")

    async def list_workspaces(self) -> dict[str, Any]:
        """GET /api/workspaces."""
        return await self._request("GET", "/api/workspaces")

    async def activate_workspace(self, workspace_id: str) -> dict[str, Any]:
        """POST /api/workspaces/{id}/activate."""
        return await self._request("POST", f"/api/workspaces/{workspace_id}/activate")

    async def create_job(
        self,
        jd_text: str,
        settings: dict[str, Any] | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/jobs."""
        body: dict[str, Any] = {"jd_text": jd_text}
        if settings is not None:
            body["settings"] = settings
        if metadata is not None:
            body["metadata"] = metadata
        return await self._request("POST", "/api/jobs", json=body)

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """GET /api/jobs/{id}."""
        return await self._request("GET", f"/api/jobs/{job_id}")

    async def list_jobs(self) -> dict[str, Any]:
        """GET /api/jobs (run history)."""
        return await self._request("GET", "/api/jobs")

    async def get_master_resume(self) -> dict[str, Any]:
        """GET /api/master-resume."""
        return await self._request("GET", "/api/master-resume")

    async def regenerate_cover_letter(
        self, job_id: str, *, instruction: str = ""
    ) -> dict[str, Any]:
        """POST /api/jobs/{id}/cover-letter."""
        return await self._request(
            "POST",
            f"/api/jobs/{job_id}/cover-letter",
            json={"instruction": instruction},
        )

    async def verify_claim(
        self,
        text: str,
        *,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/verify-claim."""
        body: dict[str, Any] = {"text": text}
        if job_id is not None:
            body["job_id"] = job_id
        return await self._request("POST", "/api/verify-claim", json=body)

    async def get_job_packet(self, job_id: str) -> dict[str, Any]:
        """GET /api/jobs/{id}/packet.json."""
        return await self._request("GET", f"/api/jobs/{job_id}/packet.json")

    async def answer_application_question(
        self,
        job_id: str,
        question: str,
        *,
        max_chars: int = 1500,
    ) -> dict[str, Any]:
        """POST /api/jobs/{id}/answer."""
        return await self._request(
            "POST",
            f"/api/jobs/{job_id}/answer",
            json={"question": question, "max_chars": max_chars},
        )

    async def list_applications(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """GET /api/applications."""
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        return await self._request("GET", "/api/applications", params=params)

    async def get_application(self, source_job_id: str) -> dict[str, Any]:
        """GET /api/applications/{source_job_id}."""
        return await self._request("GET", f"/api/applications/{source_job_id}")

    async def mark_application(
        self,
        source_job_id: str,
        status: str,
        *,
        note: str = "",
    ) -> dict[str, Any]:
        """POST /api/applications/{source_job_id}/status."""
        return await self._request(
            "POST",
            f"/api/applications/{source_job_id}/status",
            json={"status": status, "note": note},
        )

    async def download_bytes(self, path: str) -> bytes:
        """GET a download route and return raw bytes."""
        result = await self._request("GET", path)
        if isinstance(result, bytes):
            return result
        raise BackendError(f"Expected bytes from {path}, got {type(result).__name__}")
