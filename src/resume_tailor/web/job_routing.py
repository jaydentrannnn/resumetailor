"""Which models a job runs on: the Tailor settings' routing and its display label."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.web.schemas import (
    JobSettings,
)


def model_routing(
    settings: JobSettings,
) -> tuple[str, dict[str, str] | None, str | None]:
    """``(profile, overrides, effort)`` for `config.resolve`/`config.pinned` from run settings.

    The one place a `JobSettings`' model fields become backend routing — shared by the
    job runner and the Apply funnel's own screening extraction, so Prepare tailors and
    screens with exactly the routing a Tailor-tab run with the same settings would use.
    """
    overrides: dict[str, str] = {}
    # Broadest first: a blanket model name repoints every stage, then origin-specific
    # tags, then per-stage fields overwrite whichever of them they name.
    if settings.model_name:
        for purpose in config.PURPOSES:
            overrides[purpose] = settings.model_name
    if settings.ollama_model:
        for purpose in config.provider_stages(settings.model, "ollama"):
            overrides[purpose] = settings.ollama_model
    if settings.gemini_model:
        for purpose in config.provider_stages(settings.model, "gemini"):
            overrides[purpose] = settings.gemini_model
    if settings.rewrite_model:
        overrides["rewrite"] = settings.rewrite_model
    if settings.expand_model:
        overrides["expand"] = settings.expand_model
    if settings.skills_model:
        overrides["skills"] = settings.skills_model
    if settings.cover_model:
        overrides["cover"] = settings.cover_model
    if settings.review_model:
        overrides["review"] = settings.review_model
    if settings.answer_model:
        overrides["answer"] = settings.answer_model
    return settings.model, overrides or None, settings.effort

def model_label(settings: JobSettings) -> str:
    """Short ``provider:model`` label for the routing `model_routing` produces.

    Names the rewrite stage's backend (the one a tailoring run spends most calls on),
    suffixed ``+ stage overrides`` when other tailoring stages route elsewhere. A spec
    that doesn't resolve falls back to the raw profile string rather than raising — this
    is a display label, and the run itself reports the real error.
    """
    profile, overrides, effort = model_routing(settings)
    try:
        with config.pinned(profile, overrides=overrides, effort=effort) as backends:
            labels = {p: b.label() for p, b in backends.items() if p != "answer"}
    except ValueError:
        return settings.model
    label = labels["rewrite"]
    if len(set(labels.values())) > 1:
        label += " + stage overrides"
    return label
