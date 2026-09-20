"""stdio MCP entrypoint for Claude Desktop.

This is the only module in ``mcp_server`` that imports the ``mcp`` SDK. Tools live in
``tools.py`` and stay SDK-free so they can be tested against ``ASGITransport``.

Hard rules:
- All logging goes to stderr (stdout is the JSON-RPC channel).
- Never spawn uvicorn — a second process would mean two independent
  ``config._ACTIVE`` values.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from resume_tailor.mcp_server import tools
from resume_tailor.mcp_server.client import BackendClient, BackendError

# Stdout is the MCP JSON-RPC channel — never log there.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s [resume-tailor-mcp] %(message)s",
)
log = logging.getLogger("resume_tailor.mcp_server")

mcp = FastMCP(
    "resume-tailor",
    instructions=(
        "ResumeTailor backend tools: tailor a resume/cover letter/application answers "
        "for a job posting, then read the resulting artifacts. The web UI must already "
        "be running (uvicorn). Scope is read-plus-starting-runs — no master-resume "
        "edits, template installs, or vocabulary-library mutations."
    ),
)

#: Process-wide client, created lazily on first tool call (or at startup probe).
_client: BackendClient | None = None


def _get_client() -> BackendClient:
    """Return the shared BackendClient, creating it from env on first use."""
    global _client
    if _client is None:
        _client = BackendClient.from_env()
    return _client


class _ContextProgress:
    """Adapt FastMCP ``Context.report_progress`` to the tools ``ProgressSink`` Protocol."""

    def __init__(self, ctx: Context) -> None:
        """Hold the MCP request context for progress notifications."""
        self._ctx = ctx
        self._n = 0

    def __call__(self, stage: str, message: str, **detail: Any) -> None:
        """Forward one progress event; schedule the async report on the running loop."""
        self._n += 1
        # report_progress is async; fire-and-forget on the running event loop.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._ctx.report_progress(
                    progress=float(self._n),
                    total=None,
                    message=f"[{stage}] {message}",
                )
            )
        except RuntimeError:
            # No running loop (shouldn't happen inside a tool call) — log only.
            log.info("[%s] %s %s", stage, message, detail)


def _tool_error(exc: BaseException) -> str:
    """Format a BackendError (or unexpected exception) for the MCP host."""
    if isinstance(exc, BackendError):
        return str(exc)
    log.exception("Unexpected MCP tool error")
    return f"Unexpected error: {exc}"


@mcp.tool()
async def list_profiles() -> dict[str, Any]:
    """List every ResumeTailor profile (workspace) and which one is active."""
    try:
        return await tools.list_profiles(_get_client())
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def activate_profile(profile_id: str) -> dict[str, Any]:
    """Switch the active profile. Fails if a tailoring job is currently running."""
    try:
        return await tools.activate_profile(_get_client(), profile_id)
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def tailor_application(
    jd_text: str,
    profile: str | None = None,
    cover_letter: bool = True,
    pages: int | None = None,
    wait_seconds: float = 600.0,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Tailor a resume (and optional cover letter) for a job description.

    Starts a run on the ResumeTailor backend, waits up to wait_seconds (polling),
    and returns the finished job status including report, expansion, skills, and
    cover letter. If still running when the wait expires, returns job_id so you
    can call get_run to continue.
    """
    progress = _ContextProgress(ctx) if ctx is not None else None
    try:
        return await tools.tailor_application(
            _get_client(),
            jd_text,
            profile=profile,
            cover_letter=cover_letter,
            pages=pages,
            wait_seconds=wait_seconds,
            on_progress=progress,
        )
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def get_run(
    job_id: str,
    sections: list[str] | None = None,
) -> dict[str, Any]:
    """Get one run's status. Optionally restrict to named top-level keys (e.g. report)."""
    try:
        return await tools.get_run(_get_client(), job_id, sections=sections)
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def list_runs(limit: int = 10) -> dict[str, Any]:
    """List recent tailoring runs for the active profile (newest first)."""
    try:
        return await tools.list_runs(_get_client(), limit=limit)
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def get_application_answers(job_id: str) -> dict[str, Any]:
    """Paste-ready expansion entries, skills list, contact fields, and cover letter."""
    try:
        return await tools.get_application_answers(_get_client(), job_id)
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def get_artifact_paths(job_id: str) -> dict[str, Any]:
    """Download URLs and disk paths for a finished run's files.

    Prefer this over read_artifact for resume/cover .docx/.pdf — those exceed
    Claude Desktop's 1MB tool-result limit when base64-encoded.
    """
    try:
        return await tools.get_artifact_paths(_get_client(), job_id)
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def read_artifact(job_id: str, kind: str) -> dict[str, Any]:
    """Read one artifact. Markdown returns text; large binaries return paths only.

    kind is one of: resume_docx, resume_pdf, cover_docx, cover_pdf,
    expansion_md, skills_md, cover_md.

    For resume_docx / resume_pdf / cover_*, use get_artifact_paths instead —
    inlining those files as base64 exceeds the 1MB tool-result limit.
    """
    try:
        return await tools.read_artifact(_get_client(), job_id, kind)
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def regenerate_cover_letter(
    job_id: str,
    instruction: str = "",
) -> dict[str, Any]:
    """Re-draft a job's cover letter with an optional one-off instruction."""
    try:
        return await tools.regenerate_cover_letter(
            _get_client(), job_id, instruction=instruction
        )
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def get_resume_facts() -> dict[str, Any]:
    """Contact info and entry headers from the master resume (projected, not full dump)."""
    try:
        return await tools.get_resume_facts(_get_client())
    except Exception as exc:
        return {"error": _tool_error(exc)}


@mcp.tool()
async def verify_claim(job_id: str, text: str) -> dict[str, Any]:
    """Check free-text application prose against a finished run's tailored bullets.

    Returns ok=false with unsupported_terms / unsupported_numbers when the text
    invents facts not present in the tailored resume or the job posting's numbers.
    """
    try:
        return await tools.verify_claim(_get_client(), job_id, text)
    except Exception as exc:
        return {"error": _tool_error(exc)}


def main() -> None:
    """Run the MCP server over stdio. Never spawns the ResumeTailor web process."""
    # Sync probe only — do not asyncio.run() here; that would open (and close) a
    # loop before FastMCP's stdio loop starts, and leave a half-used AsyncClient.
    import httpx as _httpx
    import os

    base = os.environ.get("RESUME_TAILOR_API", "http://127.0.0.1:8000").rstrip("/")
    try:
        with _httpx.Client(base_url=base, timeout=5.0) as probe:
            probe.get("/api/config").raise_for_status()
        log.info("Backend reachable at %s", base)
    except Exception as exc:  # noqa: BLE001 - probe must never block startup
        log.warning(
            "ResumeTailor backend is not reachable at %s (%s). "
            "Start it with: uvicorn resume_tailor.web.app:app --reload --app-dir src",
            base,
            exc,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
