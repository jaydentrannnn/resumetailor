"""Which models a job runs on: the Tailor settings' routing and its display label."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from typing import Any

from resume_tailor import config, workspace
from resume_tailor.content import data, industries
from resume_tailor.model_selection import ModelRole, legacy_routing
from resume_tailor.web.schemas import (
    JobSettings,
)


def model_routing(
    settings: JobSettings,
) -> tuple[str, dict[str, config.ModelSpec] | None, str | None]:
    """Capture light routing without resolving an unused heavy draft."""
    if settings.ai_models is None:
        profile, legacy, effort = legacy_routing(settings.model_dump())
        return profile, dict(legacy) if legacy else None, effort
    models = settings.ai_models
    overrides = dict.fromkeys(config.PURPOSES, models.light.spec("light"))
    overrides.update(models.legacy_light_overrides)
    return "ollama", overrides, settings.effort


@contextmanager
def pinned_role(role: ModelRole, settings: JobSettings | None = None):
    settings = settings or JobSettings.model_validate(workspace.load_settings()["defaults"])
    if role == "light":
        profile, overrides, effort = model_routing(settings)
        with config.pinned(profile, overrides=overrides, effort=effort) as backends:
            yield backends
    else:
        spec = settings.apply.model_spec
        with config.pinned(
            "ollama", overrides=dict.fromkeys(config.PURPOSES, spec),
        ) as backends:
            yield backends


def tailoring_guidance(
    settings: JobSettings, workspace_id: str | None, resume: Any = None
) -> industries.GuidanceSnapshot | None:
    """The profile guidance a tailor job with `settings` runs under (None: no target field).

    One helper for the job queue and the Apply screen: the guidance is part of the JD
    extraction's cache key, so the screen's extraction is the tailor job's cache hit only
    when both capture the identical snapshot. `resume` defaults to the saved one.
    """
    target_field = workspace.load_settings(workspace_id).get("target_field")
    if target_field is not None and resume is None:
        # The pipeline still reports source errors in the normal job flow.
        with suppress(FileNotFoundError, ValueError):
            resume = data.load()
    return industries.capture(
        target_field,
        {"rewrite": settings.rewrite_style, "expand": settings.expand_style,
         "cover": settings.cover_style},
        workspace_id=workspace_id, resume=resume,
    )


@contextmanager
def tailoring_context(guidance: industries.GuidanceSnapshot | None, workspace_id: str | None):
    """Run a block in `workspace_id`'s context with `guidance` bound, as a tailor job does
    (`JobQueue._execute`) — without touching the process default."""
    context = (
        config.context_for_workspace(workspace_id)
        if workspace_id is not None else config.default_context()
    )
    with config.use_context(context):
        industries.bind(guidance)
        yield


def model_label(settings: JobSettings) -> str:
    """Short ``provider:model`` label for the routing `model_routing` produces.

    Names the rewrite stage's backend (the one a tailoring run spends most calls on),
    suffixed ``+ stage overrides`` when other tailoring stages route elsewhere. A spec
    that doesn't resolve falls back to the raw profile string rather than raising — this
    is a display label, and the run itself reports the real error.
    """
    try:
        profile, overrides, effort = model_routing(settings)
        with config.pinned(profile, overrides=overrides, effort=effort) as backends:
            labels = {p: b.label() for p, b in backends.items() if p != "answer"}
    except ValueError:
        return settings.model
    label = labels["rewrite"]
    if len(set(labels.values())) > 1:
        label += " + stage overrides"
    return label
