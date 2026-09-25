"""Config and settings routes."""

from __future__ import annotations

import logging
import os
from contextlib import suppress

from fastapi import APIRouter

from resume_tailor import (
    config,
    coverletter,
    data,
    expand,
    fit,
    rewrite,
    style,
    workspace,
)
from resume_tailor.events import ProgressEvent
from resume_tailor.web import state as web_state
from resume_tailor.web import template_ops
from resume_tailor.web.schemas import (
    ConfigResponse,
    JobSettings,
    ProgressEventOut,
    SettingsResponse,
    SettingsUpdateRequest,
    WorkspaceEntryOut,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def _event_out(event: ProgressEvent) -> ProgressEventOut:
    """Map an internal progress event onto the wire shape."""
    return ProgressEventOut(stage=event.stage, message=event.message, detail=event.detail)


def _config_response(*, consume_migrated: bool = True) -> ConfigResponse:
    """Build the `GET /api/config` payload; also reused by `activate_workspace`.

    `consume_migrated` clears `web_state.migrated_from_legacy` after reporting it once — the
    banner is a one-time notice, not a persistent status field. Both call sites want
    that (an activation response is exactly as good a place to surface it as a config
    fetch would have been).
    """
    contact_name: str | None = None
    tags: list[str] = []
    try:
        resume = data.load()
        contact_name = resume.contact.name
        tags = list(resume.tag_vocabulary) or sorted(
            {t for b in resume.all_bullets() for t in b.tags}
        )
    except (FileNotFoundError, ValueError):
        # A missing or malformed master resume still lets the UI load; the editor and
        # the run page will surface the real error when the user tries to use them.
        pass

    active_id = config.active_workspace_id()
    active_label: str | None = None
    if active_id is not None:
        with suppress(workspace.WorkspaceError):
            active_label = workspace.resolve(active_id).label

    migrated = web_state.migrated_from_legacy
    if consume_migrated:
        web_state.migrated_from_legacy = False

    soft_min, hard_max = rewrite.length_band(fit.default_bullet_char_budget())

    return ConfigResponse(
        pages=config.DEFAULT_PAGE_TARGET,
        experience=config.MAX_EXPERIENCE_ENTRIES,
        projects=config.MAX_PROJECT_ENTRIES,
        model_profiles=sorted(config.MODEL_PROFILES),
        ollama_model=config.OLLAMA_MODEL,
        ollama_base_url=config.OLLAMA_BASE_URL,
        ollama_profiles=sorted(
            p for p in config.MODEL_PROFILES if config.provider_stages(p, "ollama")
        ),
        gemini_model=config.GEMINI_MODEL,
        gemini_base_url=config.GEMINI_BASE_URL,
        gemini_profiles=sorted(
            p for p in config.MODEL_PROFILES if config.provider_stages(p, "gemini")
        ),
        # Direct env check, not `credential_gaps` — that takes a *profile* name, and an
        # origin word coinciding with one (as "gemini" does today) would be a coincidence
        # to depend on, not a guarantee.
        provider_keys={
            origin: any(os.environ.get(name) for name in config.api_key_env_for(origin))
            for origin in config.PROVIDERS_REQUIRING_KEY
        },
        effort_options=["low", "medium", "high"],
        pdf_backend=config.PDF_BACKEND,
        calibration_source=config.CALIBRATION_SOURCE,
        calibration_rejection=config.CALIBRATION_REJECTION,
        chars_per_line=config.CHARS_PER_LINE,
        lines_per_page=config.LINES_PER_PAGE,
        bullet_char_soft_min=soft_min,
        bullet_char_max=hard_max,
        tag_vocabulary=tags,
        contact_name=contact_name,
        fill_target=config.UNDERFLOW_THRESHOLD,
        initial_bullet_share=config.INITIAL_BULLET_SHARE,
        experience_bullet_share=config.EXPERIENCE_BULLET_SHARE,
        max_bullets_per_entry=config.MAX_BULLETS_PER_ENTRY,
        rewrite_style_default=style.DEFAULT_REWRITE_STYLE.strip(),
        expand_style_default=style.DEFAULT_EXPAND_STYLE.strip(),
        cover_style_default=style.DEFAULT_COVER_STYLE.strip(),
        rewrite_core_rules=rewrite.locked_core_rules(),
        expand_core_rules=expand.locked_core_rules(),
        cover_core_rules=coverletter.locked_core_rules(),
        active_workspace_id=active_id,
        active_workspace_label=active_label,
        migrated_from_legacy=migrated,
    )


def _workspace_entry_out(entry: workspace.WorkspaceEntry) -> WorkspaceEntryOut:
    """Map a core `WorkspaceEntry` dataclass onto its wire shape."""
    return WorkspaceEntryOut(
        id=entry.id,
        label=entry.label,
        created_at=entry.created_at,
        is_active=entry.is_active,
        has_master_resume=entry.has_master_resume,
        has_template=entry.has_template,
    )


@router.get("/api/config", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    """Defaults and vocabulary the UI needs before a run starts."""
    return _config_response()


def _seed_include_gpa_if_missing(defaults: dict, settings: JobSettings) -> None:
    """A settings.json predating `include` has no saved opinion on GPA visibility.

    Pydantic fills the missing key with `IncludeOptions()`'s default (`gpa=True`)
    regardless of what the resume's `Education.show_gpa` actually says — for a profile
    that had deliberately hidden its GPA, that would silently reveal it on the very
    next run. Falling back to the resume's current `show_gpa` instead means upgrading
    to this feature changes nothing about a run's output until the user explicitly
    touches the new tile. A no-op once `include` has ever been saved once (`"include"
    in defaults`), since a value the user actually set must never be overridden.
    """
    if "include" in defaults:
        return
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError):
        return
    settings.include.gpa = any(edu.show_gpa and edu.gpa.strip() for edu in resume.education)


@router.get("/api/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """The active profile's saved run defaults, seeded from `JobSettings()` if unset."""
    raw = workspace.load_settings()
    settings = JobSettings.model_validate(raw["defaults"])
    _seed_include_gpa_if_missing(raw["defaults"], settings)
    return SettingsResponse(
        workspace_id=config.active_workspace_id(),
        settings=settings,
        seeded=not raw["defaults"],
    )


@router.put("/api/settings", response_model=SettingsResponse)
def put_settings(body: SettingsUpdateRequest) -> SettingsResponse:
    """Persist new run defaults for the active profile.

    Held under `template_ops.LOCK`: `workspace.save_settings(None)` resolves
    `config.SETTINGS_PATH` at call time, which `activate_workspace` rebinds under the
    same lock — without it, a save racing a profile switch can land in the *new*
    workspace's settings file.
    """
    with template_ops.LOCK:
        workspace.save_settings(body.settings.model_dump())
    return SettingsResponse(
        workspace_id=config.active_workspace_id(),
        settings=body.settings,
        seeded=False,
    )
