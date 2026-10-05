"""MCP tool implementations — no ``mcp`` import; testable against ASGITransport.

Each tool takes a ``BackendClient`` as its first argument. Progress reporting goes
through a ``ProgressSink`` Protocol so ``server.py`` can adapt FastMCP's Context
without coupling this module to the SDK.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Protocol

from resume_tailor.mcp_server.client import BackendClient, BackendError


class ProgressSink(Protocol):
    """Optional progress callback — same one-way shape as ``events.ProgressCallback``."""

    def __call__(self, stage: str, message: str, **detail: Any) -> None:
        """Report one progress update (stage name + human message)."""
        ...


def _noop_progress(stage: str, message: str, **detail: Any) -> None:
    """Default sink that discards progress events."""


_ARTIFACT_KINDS: dict[str, tuple[str, str]] = {
    "resume_docx": ("download.docx", "tailored.docx"),
    "resume_pdf": ("download.pdf", "tailored.pdf"),
    "cover_docx": ("cover-letter.docx", "cover.docx"),
    "cover_pdf": ("cover-letter.pdf", "cover.pdf"),
    "expansion_md": ("expansion.md", "expansion.md"),
    "skills_md": ("skills.md", "skills.md"),
    "cover_md": ("cover-letter.md", "cover.md"),
    "packet_json": ("packet.json", "packet.json"),
}


async def list_profiles(client: BackendClient) -> dict[str, Any]:
    """List every profile (workspace) and which one is active."""
    return await client.list_workspaces()


async def activate_profile(client: BackendClient, profile_id: str) -> dict[str, Any]:
    """Switch the active profile. Refuses while a tailoring job is running (409)."""
    return await client.activate_workspace(profile_id)


async def tailor_application(
    client: BackendClient,
    jd_text: str,
    *,
    profile: str | None = None,
    cover_letter: bool = True,
    pages: int | None = None,
    posting_url: str = "",
    company: str = "",
    role: str = "",
    wait_seconds: float = 600.0,
    on_progress: ProgressSink | None = None,
) -> dict[str, Any]:
    """Start a tailoring run and wait (polling) for it to finish.

    Loads the active profile's saved settings, optionally flips ``cover_letter`` /
    ``pages``, then POSTs the whole ``JobSettings`` object (the API has no
    partial-patch path). Polls ``GET /api/jobs/{id}`` every ~2s and forwards new
    progress events. On ``wait_seconds`` expiry returns ``{job_id, status: "running"}``
    so the agent can fall back to ``get_run``.
    """
    progress = on_progress or _noop_progress
    if profile:
        await client.activate_workspace(profile)
        progress("profile", f"Activated profile {profile!r}")

    settings_resp = await client.get_settings()
    settings = dict(settings_resp.get("settings") or {})
    # This tool tailors for an application, whose form fields need the expansion that
    # ordinary runs now skip (as Apply's Prepare does in `daily_rows._job_settings`).
    settings["no_expand"] = False
    if cover_letter:
        settings["cover_letter"] = True
        settings["no_cover_letter"] = False
    if pages is not None:
        settings["pages"] = pages

    metadata = None
    if any((posting_url, company, role)):
        metadata = {
            "posting_url": posting_url,
            "company": company,
            "role": role,
        }
    created = await client.create_job(jd_text, settings=settings, metadata=metadata)
    job_id = created["job_id"]
    progress("fit", f"Job {job_id} queued", queue_position=created.get("queue_position"))

    deadline = time.monotonic() + wait_seconds
    seen_events = 0
    while time.monotonic() < deadline:
        status = await client.get_job(job_id)
        events = status.get("events") or []
        for event in events[seen_events:]:
            progress(
                event.get("stage", "fit"),
                event.get("message", ""),
                **(event.get("detail") or {}),
            )
        seen_events = len(events)

        state = status.get("status")
        if state in ("succeeded", "failed", "cancelled"):
            return status
        await asyncio.sleep(2.0)

    # Timed out while still running — return what we have so the agent can poll.
    status = await client.get_job(job_id)
    return {
        "job_id": job_id,
        "status": status.get("status", "running"),
        "message": (
            f"Still {status.get('status', 'running')} after {wait_seconds:.0f}s; "
            "call get_run to continue polling."
        ),
        "report": status.get("report"),
        "events": status.get("events"),
    }


async def get_run(
    client: BackendClient,
    job_id: str,
    sections: list[str] | None = None,
) -> dict[str, Any]:
    """Return one run's status. Optionally restrict to named top-level keys."""
    status = await client.get_job(job_id)
    if not sections:
        return status
    allowed = set(sections) | {"job_id", "status", "error", "title", "created_at"}
    return {k: v for k, v in status.items() if k in allowed}


async def list_runs(client: BackendClient, limit: int = 10) -> dict[str, Any]:
    """Newest-first recent runs for the active profile."""
    history = await client.list_jobs()
    runs = list(history.get("runs") or [])[: max(1, limit)]
    return {"runs": runs}


async def get_application_answers(client: BackendClient, job_id: str) -> dict[str, Any]:
    """Paste-ready expansion entries, skills list, and contact fields for one run."""
    status = await client.get_job(job_id)
    if status.get("status") != "succeeded":
        raise BackendError(
            f"Job {job_id} is {status.get('status')}, not ready for application answers.",
            status_code=409,
        )
    resume = await client.get_master_resume()
    contact = resume.get("contact") or {}
    return {
        "job_id": job_id,
        "title": (status.get("report") or {}).get("title") or status.get("title"),
        "contact": {
            "name": contact.get("name", ""),
            "email": contact.get("email", ""),
            "phone": contact.get("phone", ""),
            "location": contact.get("location", ""),
            "linkedin": contact.get("linkedin", ""),
            "github": contact.get("github", ""),
        },
        "expansion": status.get("expansion"),
        "skills": status.get("skills"),
        "cover_letter": status.get("cover_letter"),
        "gaps": (status.get("report") or {}).get("gaps") or [],
    }


def _artifact_disk_path(job_id: str, filename: str) -> str | None:
    """Host filesystem path when the MCP process shares a volume with the backend."""
    try:
        from resume_tailor import config

        candidate = config.OUTPUT_DIR / "jobs" / job_id / filename
        if candidate.exists():
            return str(candidate.resolve())
    except Exception:  # noqa: BLE001 - optional enrichment
        return None
    return None


def _absolute_download_url(client: BackendClient, api_path: str) -> str:
    """Turn an API-relative path into a full URL against the client's base."""
    base = str(client._http.base_url).rstrip("/")
    path = api_path if api_path.startswith("/") else f"/{api_path}"
    return f"{base}{path}"


async def get_artifact_paths(client: BackendClient, job_id: str) -> dict[str, Any]:
    """Return download URLs and (when same-filesystem) disk paths for every artifact.

    Use this to enumerate what a run produced. ``read_artifact`` returns the same
    pointers for one kind, plus inline text for the markdown kinds.
    """
    status = await client.get_job(job_id)
    if status.get("status") != "succeeded":
        raise BackendError(
            f"Job {job_id} is {status.get('status')}, not ready for artifacts.",
            status_code=409,
        )
    api_paths: dict[str, str] = {}
    download_urls: dict[str, str] = {}
    disk: dict[str, str] = {}
    for kind, (route_suffix, filename) in _ARTIFACT_KINDS.items():
        api_path = f"/api/jobs/{job_id}/{route_suffix}"
        try:
            await client.download_bytes(api_path)
        except BackendError:
            continue
        api_paths[kind] = api_path
        download_urls[kind] = _absolute_download_url(client, api_path)
        host_path = _artifact_disk_path(job_id, filename)
        if host_path:
            disk[kind] = host_path
    return {
        "job_id": job_id,
        "api_paths": api_paths,
        "download_urls": download_urls,
        "disk_paths": disk,
        "hint": (
            "For resume/cover .docx/.pdf, give the user a disk_path or download_url — "
            "the file contents are never inlined."
        ),
    }


async def read_artifact(
    client: BackendClient,
    job_id: str,
    kind: str,
) -> dict[str, Any]:
    """Read one artifact for the agent.

    Markdown returns inline ``text``. Binary artifacts (``.docx`` / ``.pdf``) return
    ``disk_path`` / ``download_url`` only: a base64 blob of a zip or PDF carries no
    information the model can read, and a single tailored PDF costs ~20k tokens.
    """
    if kind not in _ARTIFACT_KINDS:
        raise BackendError(
            f"Unknown artifact kind {kind!r}; choose one of: {', '.join(_ARTIFACT_KINDS)}"
        )
    route_suffix, filename = _ARTIFACT_KINDS[kind]
    api_path = f"/api/jobs/{job_id}/{route_suffix}"
    raw = await client.download_bytes(api_path)
    download_url = _absolute_download_url(client, api_path)
    disk_path = _artifact_disk_path(job_id, filename)
    media = _media_type(filename)
    out: dict[str, Any] = {
        "job_id": job_id,
        "kind": kind,
        "filename": filename,
        "media_type": media,
        "size_bytes": len(raw),
        "download_url": download_url,
    }
    if disk_path:
        out["disk_path"] = disk_path

    # Text artifacts: inline the content (markdown/json application bundles are tiny).
    if filename.endswith(".md") or filename.endswith(".json"):
        out["inline"] = True
        out["text"] = raw.decode("utf-8", errors="replace")
        return out

    out["inline"] = False
    out["message"] = (
        f"{filename} is a binary artifact ({len(raw)} bytes) and is never inlined. "
        "Open disk_path on the host, or download_url in a browser "
        "(http://127.0.0.1:8000/... while the backend is running)."
    )
    return out


def _media_type(filename: str) -> str:
    """Guess a media type from an artifact filename."""
    suffix = Path(filename).suffix.lower()
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


async def regenerate_cover_letter(
    client: BackendClient,
    job_id: str,
    instruction: str = "",
) -> dict[str, Any]:
    """Re-draft a job's cover letter with an optional one-off instruction."""
    return await client.regenerate_cover_letter(job_id, instruction=instruction)


async def get_resume_facts(client: BackendClient) -> dict[str, Any]:
    """Projected contact + entry headers from the master resume (not the full superset)."""
    resume = await client.get_master_resume()
    contact = resume.get("contact") or {}
    experience: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    education: list[dict[str, Any]] = []
    for section in resume.get("sections") or []:
        kind = section.get("kind")
        if kind == "experience":
            for entry in section.get("entries") or []:
                experience.append(
                    {
                        "id": entry.get("id"),
                        "company": entry.get("company"),
                        "title": entry.get("title"),
                        "location": entry.get("location"),
                        "start": entry.get("start"),
                        "end": entry.get("end"),
                    }
                )
        elif kind == "project":
            for entry in section.get("entries") or []:
                projects.append(
                    {
                        "id": entry.get("id"),
                        "name": entry.get("name"),
                        "tech": entry.get("tech") or [],
                        "date": entry.get("date"),
                    }
                )
        elif kind == "education":
            for entry in section.get("entries") or []:
                education.append(
                    {
                        "school": entry.get("school"),
                        "degree": entry.get("degree"),
                        "dates": entry.get("dates"),
                        "location": entry.get("location"),
                        "gpa": entry.get("gpa"),
                    }
                )
    return {
        "contact": {
            "name": contact.get("name", ""),
            "email": contact.get("email", ""),
            "phone": contact.get("phone", ""),
            "location": contact.get("location", ""),
            "linkedin": contact.get("linkedin", ""),
            "github": contact.get("github", ""),
        },
        "experience": experience,
        "projects": projects,
        "education": education,
    }


async def verify_claim(
    client: BackendClient,
    text: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Check free-text application prose against tailored or master-resume bullets."""
    return await client.verify_claim(text, job_id=job_id)


async def get_application_packet(client: BackendClient, job_id: str) -> dict[str, Any]:
    """Return ``packet.json`` for a finished tailoring run."""
    return await client.get_job_packet(job_id)


async def answer_application_question(
    client: BackendClient,
    job_id: str,
    question: str,
    *,
    max_chars: int = 1500,
) -> dict[str, Any]:
    """Draft a guarded ATS free-text answer for one job run."""
    return await client.answer_application_question(
        job_id,
        question,
        max_chars=max_chars,
    )


async def list_applications(
    client: BackendClient,
    *,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List tracked applications newest-first with per-status counts."""
    return await client.list_applications(status=status, limit=limit)


async def get_application(client: BackendClient, source_job_id: str) -> dict[str, Any]:
    """Return one application with packet and JD text when available."""
    return await client.get_application(source_job_id)


async def mark_application(
    client: BackendClient,
    source_job_id: str,
    status: str,
    *,
    note: str = "",
) -> dict[str, Any]:
    """Update one application's funnel status."""
    return await client.mark_application(source_job_id, status, note=note)
