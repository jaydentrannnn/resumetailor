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
    "model",
    "model_name",
    "ollama_model",
    "gemini_model",
    "effort",
    "extract_runs",
    "max_concurrent_jobs",
)
#: `JobSettings.apply` keys that are app-wide (the Autofill model).
APPLY_KEYS = ("model_provider", "model_name")

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
    if path().exists():
        return False
    save(_pick(defaults))
    return True
