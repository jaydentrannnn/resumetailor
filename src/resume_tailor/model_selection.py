"""App model choices and legacy migration, independent of the web layer."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from resume_tailor import config

ModelRole = Literal["light", "heavy"]
#: How the model is paid for; sets its server's default request concurrency
#: (`infra.model_queue.PLAN_CONCURRENCY`). "subscription" = an API plan with a monthly
#: allowance (BytePlus ModelArk, Cursor), as opposed to pay-as-you-go ("paid").
ModelPlan = Literal["free", "paid", "subscription", "local"]
ModelProvider = Literal[
    "ollama", "ollama-cloud", "lmstudio", "gemini", "anthropic", "openai", "custom", "vertex_ai"
]


def custom_credential_name(role: ModelRole, api_format: str, base_url: str) -> str:
    identity = f"{api_format}|{base_url.strip().rstrip('/')}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return f"CUSTOM_{role.upper()}_{digest}"


def is_custom_credential(name: str) -> bool:
    return re.fullmatch(r"CUSTOM_(LIGHT|HEAVY)_[0-9a-f]{24}", name) is not None


class ModelSelection(BaseModel):
    provider: ModelProvider = "ollama"
    model_name: str = Field(default="", max_length=200)
    api_format: Literal["openai", "anthropic"] = "openai"
    base_url: str = Field(default="", max_length=2048)
    #: None = inferred from the provider (`effective_plan`).
    plan: ModelPlan | None = None
    vertex_project: str = Field(default="", max_length=63)
    vertex_location: str = Field(default="", max_length=40)

    def effective_plan(self) -> ModelPlan | None:
        """The chosen plan, else a guess: Gemini's free tier, paid Anthropic/OpenAI.
        None (Ollama, LM Studio, a custom server) keeps the queue's local/cloud default."""
        if self.plan is not None:
            return self.plan
        if self.provider == "gemini":
            return "free"
        if self.provider in {"anthropic", "openai", "vertex_ai"}:
            return "paid"
        return None

    @field_validator("model_name", "base_url", "vertex_project", "vertex_location")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value:
            return value
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("Server URL must be an HTTP(S) URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Server URL must not contain credentials, a query, or a fragment")
        return value.rstrip("/")

    def spec(self, role: ModelRole) -> str | dict[str, Any]:
        """Resolve a selection; incomplete drafts may be saved but cannot run."""
        if self.provider == "vertex_ai":
            from resume_tailor.infra import vertex_auth, vertex_catalog

            model = vertex_catalog.normalize_model(self.model_name)
            if not model or not self.vertex_project or not self.vertex_location:
                raise ValueError("Vertex AI needs a model, project ID and location")
            return {
                "provider": "vertex_ai", "origin": "vertex_ai", "model": model,
                "base_url": vertex_catalog.endpoint(self.vertex_project, self.vertex_location),
                "vertex_project": self.vertex_project, "vertex_location": self.vertex_location,
                "credential_ref": vertex_auth.SECRET,
                "credential_revision": vertex_auth.state()["revision"],
            }
        if self.provider == "custom":
            if not self.base_url or not self.model_name:
                raise ValueError("Custom server needs a server URL and model name")
            return {
                "provider": self.api_format,
                "origin": "custom",
                "model": self.model_name,
                "base_url": self.base_url,
                "credential_ref": custom_credential_name(role, self.api_format, self.base_url),
            }
        if self.provider == "openai":
            if not self.model_name:
                raise ValueError("OpenAI needs a model name")
            return {
                "provider": "openai",
                "origin": "openai",
                "model": self.model_name,
                "base_url": "https://api.openai.com/v1",
                "credential_ref": "OPENAI_API_KEY",
            }
        profile = "claude" if self.provider == "anthropic" else self.provider
        default = config.MODEL_PROFILES[profile]["rewrite"]
        origin, model, base = config.parse_spec(default)
        spec = f"{origin}:{self.model_name or model}"
        if self.base_url or base:
            spec += f"@{self.base_url or base}"
        return spec


class AiModels(BaseModel):
    light: ModelSelection = Field(default_factory=ModelSelection)
    heavy: ModelSelection = Field(
        default_factory=lambda: ModelSelection(model_name="nemotron-3-super:cloud")
    )
    # Preserved on migration; an explicit light-model edit clears this compatibility map.
    legacy_light_overrides: dict[str, str] = Field(default_factory=dict)


def legacy_routing(defaults: dict[str, Any]) -> tuple[str, dict[str, str] | None, str | None]:
    profile = defaults.get("model") or "ollama"
    overrides: dict[str, str] = {}
    if defaults.get("model_name"):
        overrides = dict.fromkeys(config.PURPOSES, defaults["model_name"])
    for origin in ("ollama", "gemini"):
        if defaults.get(f"{origin}_model"):
            for purpose in config.provider_stages(profile, origin):
                overrides[purpose] = defaults[f"{origin}_model"]
    for purpose in ("rewrite", "expand", "skills", "cover", "review", "answer"):
        if defaults.get(f"{purpose}_model"):
            overrides[purpose] = defaults[f"{purpose}_model"]
    return profile, overrides or None, defaults.get("effort")


def migrated_models(defaults: dict[str, Any]) -> AiModels:
    """Capture effective legacy routes, including hidden stage overrides."""
    if defaults.get("ai_models"):
        return AiModels.model_validate(defaults["ai_models"])
    profile, overrides, effort = legacy_routing(defaults)
    backends = config._backends_for(profile, overrides=overrides, effort=effort)
    primary = backends["rewrite"]
    provider = primary.origin or primary.provider
    if provider == "ollama" and config.is_ollama_cloud(primary.base_url):
        provider = "ollama-cloud"
    if provider in {"openai", "anthropic"} and primary.base_url:
        official = (
            "https://api.openai.com/v1" if provider == "openai" else "https://api.anthropic.com"
        )
        if primary.base_url.rstrip("/") != official:
            provider = "custom"
    light = ModelSelection(
        provider=provider,
        model_name=primary.model,
        base_url=primary.base_url or "",
        api_format=primary.provider if provider == "custom" else "openai",
    )
    apply = defaults.get("apply") or {}
    heavy = (
        ModelSelection.model_validate(apply["model_selection"])
        if apply.get("model_selection")
        else ModelSelection(
            provider=apply.get("model_provider", "ollama"),
            model_name=apply.get("model_name", "nemotron-3-super:cloud"),
        )
    )
    preserved = {
        purpose: config.spec_for_backend(backend)
        for purpose, backend in backends.items()
        if purpose != "answer"
        and (backend.provider, backend.origin, backend.model, backend.base_url)
        != (primary.provider, primary.origin, primary.model, primary.base_url)
    }
    return AiModels(light=light, heavy=heavy, legacy_light_overrides=preserved)
