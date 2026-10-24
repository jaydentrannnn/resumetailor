"""Profile (workspace) management routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from resume_tailor import (
    workspace,
)
from resume_tailor.apply.funnel import cover_on_demand, daily_progress
from resume_tailor.apply.funnel import operations as apply_operations
from resume_tailor.model_selection import migrated_models
from resume_tailor.web import section_title_sync, template_info, template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.routes.config import (
    _config_response,
    _seed_include_gpa_if_missing,
    _workspace_entry_out,
)
from resume_tailor.web.schemas import (
    JobSettings,
    WorkspaceActivateResponse,
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceRenameRequest,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def _workspace_list_response() -> WorkspaceListResponse:
    """Current registry contents, mapped onto the wire shape."""
    entries = workspace.list_workspaces()
    active_id = next((e.id for e in entries if e.is_active), None)
    return WorkspaceListResponse(
        entries=[_workspace_entry_out(e) for e in entries], active_id=active_id
    )


def _busy_conflict(action: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"A tailoring job is in progress; wait for it to finish before {action}.",
    )


@router.get("/api/workspaces", response_model=WorkspaceListResponse)
def get_workspaces() -> WorkspaceListResponse:
    """Every registered profile and which one is active."""
    return _workspace_list_response()


@router.post("/api/workspaces", response_model=WorkspaceListResponse)
def create_workspace(body: WorkspaceCreateRequest) -> WorkspaceListResponse:
    """Register a new, empty profile — or, with `copy_from` set, a duplicate of it.

    Duplicating reads another profile's live template files, so (like every other
    template-tab mutation) it refuses while a tailoring job is busy.
    """
    if body.copy_from is not None:
        if get_queue().busy():
            raise _busy_conflict("duplicating a profile")
        with template_ops.LOCK:
            try:
                workspace.create(body.label, copy_from=body.copy_from)
            except workspace.WorkspaceError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        try:
            workspace.create(body.label)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _workspace_list_response()


@router.post("/api/workspaces/{workspace_id}/activate", response_model=WorkspaceActivateResponse)
def activate_workspace(workspace_id: str) -> WorkspaceActivateResponse:
    """Switch the active profile — master resume, template, calibration, and settings.

    Refuses while a tailoring job is busy: rebinding paths mid-job would silently mix
    one profile's content with another's paths instead of failing loudly. The `busy()`
    check runs *inside* `template_ops.LOCK`, not before it — `create_job` holds this
    same lock across its own validate-then-submit, so a checked-then-acquired ordering
    here would still let a job submitted in the gap slip through against the new
    workspace.
    """
    with template_ops.LOCK:
        if get_queue().busy():
            raise _busy_conflict("switching profiles")
        if daily_progress.daily_busy():
            raise HTTPException(
                status_code=409,
                detail="Cannot switch profiles while the daily apply funnel is running.",
            )
        # Apply workers read the process-default workspace; `operations.start` registers
        # under this same lock, so a switch can't land between its reads and its start.
        if apply_operations.active() is not None:
            raise HTTPException(
                status_code=409,
                detail="Cannot switch profiles while an Apply operation is running.",
            )
        # A fill that ran out of time leaves its cover letter writing into this profile.
        if cover_on_demand.busy():
            raise HTTPException(
                status_code=409,
                detail="Cannot switch profiles while a cover letter is still being written.",
            )
        try:
            workspace.activate(workspace_id)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        from resume_tailor.apply.funnel import answer_harvest  # noqa: PLC0415
        answer_harvest.restore()
        # Its template was switched to movable sections while another profile was active.
        section_title_sync.apply_pending_unlocked()

        entries = workspace.list_workspaces()
        raw_defaults = workspace.load_settings()["defaults"]
        activated_settings = JobSettings.model_validate(raw_defaults)
        if activated_settings.ai_models is None:
            try:
                activated_settings.ai_models = migrated_models(activated_settings.model_dump())
                activated_settings = JobSettings.model_validate(activated_settings.model_dump())
            except ValueError:
                pass  # Keep invalid legacy choices editable.
        _seed_include_gpa_if_missing(raw_defaults, activated_settings)
        return WorkspaceActivateResponse(
            active_id=workspace_id,
            entries=[_workspace_entry_out(e) for e in entries],
            config=_config_response(),
            settings=activated_settings,
            template=template_info.info(),
        )


@router.patch("/api/workspaces/{workspace_id}", response_model=WorkspaceListResponse)
def rename_workspace(workspace_id: str, body: WorkspaceRenameRequest) -> WorkspaceListResponse:
    """Rename a profile. Its on-disk directory (named from the id) never moves."""
    try:
        workspace.rename(workspace_id, body.label)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _workspace_list_response()


@router.delete("/api/workspaces/{workspace_id}", response_model=WorkspaceListResponse)
def delete_workspace(workspace_id: str) -> WorkspaceListResponse:
    """Delete a profile. Refuses the active profile and the last remaining one."""
    if get_queue().busy():
        raise _busy_conflict("deleting a profile")
    with template_ops.LOCK:
        try:
            workspace.delete(workspace_id)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _workspace_list_response()
