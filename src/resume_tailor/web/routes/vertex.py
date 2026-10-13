"""Google connection lifecycle and non-generating Vertex discovery."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from resume_tailor.infra import vertex_auth, vertex_catalog, vertex_oauth

router = APIRouter(prefix="/api/vertex")


@router.get("/connection")
def connection() -> dict:
    try:
        return {**vertex_auth.state(), "configured": bool(vertex_oauth.client_config())}
    except vertex_auth.ConnectionError as exc:
        raise HTTPException(503, str(exc)) from None


@router.delete("/connection")
def disconnect() -> dict:
    vertex_oauth.cancel_all()
    try:
        vertex_auth.disconnect()
        return connection()
    except vertex_auth.ConnectionError as exc:
        raise HTTPException(503, str(exc)) from None


@router.post("/auth")
def authorize() -> dict:
    try:
        return vertex_oauth.start()
    except (vertex_auth.ConnectionError, OSError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, vertex_auth.ConnectionError)
            else "Cannot start the local sign-in callback. Retry."
        )
        raise HTTPException(503, detail) from None


@router.get("/auth/{flow_id}")
def authorization_status(flow_id: str) -> dict:
    try:
        return vertex_oauth.status(flow_id)
    except KeyError:
        raise HTTPException(404, "Sign-in session not found. Connect again.") from None


@router.delete("/auth/{flow_id}")
def cancel_authorization(flow_id: str) -> dict:
    try:
        vertex_oauth.cancel(flow_id)
        return vertex_oauth.status(flow_id)
    except KeyError:
        raise HTTPException(404, "Sign-in session not found.") from None


@router.get("/projects")
def projects(page_token: str = Query(default="", max_length=2048)) -> dict:
    try:
        current = vertex_auth.state()
        token = vertex_auth.access_token(current["revision"])
        response = httpx.get(
            "https://cloudresourcemanager.googleapis.com/v3/projects:search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "state:ACTIVE", "pageSize": 100, "pageToken": page_token},
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
    except vertex_auth.ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            503, "Project listing unavailable. Enter your project ID manually."
        ) from None
    return {
        "projects": [
            {"id": p["projectId"], "name": p.get("displayName", p["projectId"])}
            for p in result.get("projects", [])
            if p.get("projectId")
        ],
        "next_page_token": result.get("nextPageToken", ""),
    }


@router.get("/models")
def models() -> dict:
    return {"models": vertex_catalog.suggestions()}
