"""Offline SDK metadata, model-ID normalization and explicit Vertex endpoints."""

from __future__ import annotations

import os
import re
import sys
from functools import lru_cache

# Managed text models from the owner's Model Garden list, checked 2026-10-13.
# IDs: Google's model pages and models/maas/zaiorg; self-deployed, image,
# robotics, computer-use-only and embedding models need different integrations.
MODELS = (
    ("gemini-4-argon", "Gemini 4 Argon", "Google"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash", "Google"),
    ("gemini-3.7-flash", "Gemini 3.7 Flash", "Google"),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", "Google"),
    ("gemini-3.6-flash", "Gemini 3.6 Flash", "Google"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash", "Google"),
    ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", "Google"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview", "Google"),
    ("gemini-3-flash-preview", "Gemini 3 Flash Preview", "Google"),
    ("gemini-3-pro-preview", "Gemini 3 Pro Preview", "Google"),
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "Google"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro", "Google"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash", "Google"),
    ("claude-haiku-5-5", "Claude Haiku 5.5", "Anthropic"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "Anthropic"),
    ("claude-opus-5-5", "Claude Opus 5.5", "Anthropic"),
    ("claude-fable-5-1", "Claude Fable 5.1", "Anthropic"),
    ("claude-opus-5", "Claude Opus 5", "Anthropic"),
    ("claude-sonnet-5", "Claude Sonnet 5", "Anthropic"),
    ("claude-fable-5", "Claude Fable 5", "Anthropic"),
    ("claude-opus-4-8", "Claude Opus 4.8", "Anthropic"),
    ("zai-org/glm-5.2-maas", "GLM 5.2 API Service", "Zai-org"),
)

# Google model pages, checked 2026-10-13. These models are newer than the
# pinned SDK's region catalog; absent metadata must not suggest every region.
# https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/haiku-5-5
# https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/sonnet-5-5
_LOCATION_OVERRIDES = {
    "claude-haiku-5-5": ("global", "us", "eu"),
    "claude-sonnet-5-5": ("global", "us", "eu"),
}


def normalize_model(model: str) -> str:
    return model.strip().removeprefix("vertex_ai/")


def endpoint(project: str, location: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
        raise ValueError("Enter a Google Cloud project ID, not its display name.")
    if not re.fullmatch(r"global|us|eu|[a-z]+-[a-z]+[0-9]+", location):
        raise ValueError("Choose a Vertex location, such as global or us-central1.")
    host = f"aiplatform.{location}.rep.googleapis.com" if location in {"us", "eu"} else (
        "aiplatform.googleapis.com"
        if location == "global"
        else f"{location}-aiplatform.googleapis.com"
    )
    return f"https://{host}/v1/projects/{project}/locations/{location}"


@lru_cache(maxsize=1)
def sdk():
    # Importing LiteLLM must not download metadata or enable third-party logging.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    import litellm

    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    litellm.turn_off_message_logging = True
    return litellm


def clear_credentials() -> None:
    """Forget the pinned SDK's Vertex credential caches without importing it."""
    module = sys.modules.get("litellm.main")
    if module is None:
        return
    for handler in vars(module).values():
        cache = getattr(handler, "_credentials_project_mapping", None)
        lock = getattr(handler, "_sync_refresh_lock", None)
        if not isinstance(cache, dict) or lock is None:
            continue
        with lock:
            cache.clear()
            handler.access_token = handler.refresh_token = handler._credentials = None
            for task in getattr(handler, "_background_refresh_tasks", {}).values():
                loop = task.get_loop()
                if not loop.is_closed():
                    loop.call_soon_threadsafe(task.cancel)


def suggestions() -> list[dict]:
    return [
        {
            "id": model,
            "name": name,
            "publisher": publisher,
            "reasoning": supports_effort(model),
            "locations": model_locations(model),
        }
        for model, name, publisher in MODELS
    ]


def model_locations(model: str) -> list[str]:
    model = normalize_model(model)
    if model in _LOCATION_OVERRIDES:
        return list(_LOCATION_OVERRIDES[model])
    return list(sdk().model_cost.get(f"vertex_ai/{model}", {}).get("supported_regions") or [])


def supports_effort(model: str) -> bool:
    try:
        params = (
            sdk().get_supported_openai_params(model=f"vertex_ai/{normalize_model(model)}") or []
        )
        return "reasoning_effort" in params
    except Exception:  # noqa: BLE001 - unknown models are still usable without optional effort
        return False


def validate_location(model: str, location: str) -> None:
    regions = model_locations(model)
    if regions and location not in regions:
        # LiteLLM otherwise silently switches to its first catalog region.
        raise ValueError(
            f"This model does not support {location}. "
            f"Choose a supported location: {', '.join(regions)}."
        )
