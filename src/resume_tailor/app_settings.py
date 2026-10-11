"""App-wide AI settings, shared by every profile.

The model choice, effort, job-description reads and run concurrency describe this
computer, not one person's resume, so they live in `DATA_ROOT/ai_settings.json`
rather than in each profile's `settings.json`. `workspace.load_settings` overlays
them onto a profile's `defaults` and `workspace.save_settings` strips them back out,
so every caller keeps reading one merged `JobSettings` dict.

Only keys present in the app file override: until it exists (a fresh install before
`seed`, or a test that writes `settings.json` directly) a profile's own values are
used unchanged. Core module: never import `resume_tailor.web`.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from resume_tailor import config

#: Top-level `JobSettings` keys that are app-wide.
TOP_KEYS = (
    "ai_models",
    "model",
    "model_name",
    "ollama_model",
    "gemini_model",
    "effort",
    "extract_runs",
    "max_concurrent_jobs",
)
#: `JobSettings.apply` keys that are app-wide (the Heavy task model).
APPLY_KEYS = ("model_provider", "model_name", "model_selection")

_LOCK = threading.Lock()


def path() -> Path:
    return config.DATA_ROOT / "ai_settings.json"


def load() -> dict[str, Any]:
    """The saved app-wide values (`{key: value, "apply": {...}}`); `{}` when absent."""
    target = path()
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _pick(defaults: dict[str, Any]) -> dict[str, Any]:
    picked: dict[str, Any] = {k: defaults[k] for k in TOP_KEYS if k in defaults}
    apply = defaults.get("apply")
    if isinstance(apply, dict):
        nested = {k: apply[k] for k in APPLY_KEYS if k in apply}
        if nested:
            picked["apply"] = nested
    return picked


def overlay(defaults: dict[str, Any]) -> dict[str, Any]:
    """`defaults` with the app-wide values laid over it (a new dict)."""
    app = load()
    merged = {**defaults, **{k: app[k] for k in TOP_KEYS if k in app}}
    if isinstance(app.get("apply"), dict):
        apply = dict(defaults.get("apply") or {})
        apply.update({k: v for k, v in app["apply"].items() if k in APPLY_KEYS})
        merged["apply"] = apply
    return merged


def split(defaults: dict[str, Any]) -> dict[str, Any]:
    """Save the app-wide part of `defaults`; return the rest for the profile file."""
    app = _pick(defaults)
    if app:
        current = load()
        merged = {**current, **app}
        if "apply" in app:
            merged["apply"] = {**(current.get("apply") or {}), **app["apply"]}
        if not defaults.get("ai_models") and (
            any(k in defaults for k in ("model", "model_name", "ollama_model", "gemini_model"))
            or any(k in (defaults.get("apply") or {}) for k in APPLY_KEYS)
        ):
            # A legacy client edited model fields: do not let a stale canonical selection win.
            merged.pop("ai_models", None)
            legacy_apply = defaults.get("apply") or {}
            if "model_selection" not in legacy_apply and any(
                k in legacy_apply for k in ("model_provider", "model_name")
            ):
                merged["apply"].pop("model_selection", None)
        save(merged)
    profile = {k: v for k, v in defaults.items() if k not in TOP_KEYS}
    if isinstance(profile.get("apply"), dict):
        profile["apply"] = {
            k: v for k, v in profile["apply"].items() if k not in APPLY_KEYS
        }
    return profile


def save(values: dict[str, Any]) -> None:
    """Atomically write the app-wide values."""
    with _LOCK:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)


def seed(defaults: dict[str, Any]) -> bool:
    """Create the app file from one profile's values when it does not exist yet.

    Run at bootstrap with the active profile, so upgrading keeps the model that
    profile was using. Returns True when the file was written.
    """
    from resume_tailor.model_selection import migrated_models

    current = load() if path().exists() else _pick(defaults)
    if current.get("ai_models"):
        return False
    has_light = any(
        defaults.get(k) for k in ("model", "model_name", "ollama_model", "gemini_model")
    )
    if not has_light and not any(
        (defaults.get("apply") or {}).get(k)
        for k in ("model_provider", "model_name", "model_selection")
    ):
        if path().exists():
            return False
        save(current)
        return True
    try:
        models = migrated_models(defaults)
        current["ai_models"] = models.model_dump()
        if models.light.provider == "custom":
            from resume_tailor.infra import secret_store
            from resume_tailor.model_selection import legacy_routing

            profile, overrides, effort = legacy_routing(defaults)
            with config.pinned(profile, overrides=overrides, effort=effort):
                key = config.api_key_for("rewrite")
            spec = models.light.spec("light")
            assert isinstance(spec, dict)
            name = spec["credential_ref"]
            if key and not config.credential(name):
                secret_store.set(f"api_key:{name}", key)
    except ValueError:
        # An invalid legacy profile must remain editable in Settings.
        if path().exists():
            return False
    save(current)
    return True
