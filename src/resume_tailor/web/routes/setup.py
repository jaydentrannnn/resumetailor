"""`GET /api/setup-status`: the header's "Ready / N setup steps left" checklist.

Each item says whether one prerequisite is met and where to fix it. The model check
never makes a paid call: a missing key is a gap (`config.credential_gaps`), and a local
server (Ollama, LM Studio) is probed with a 2 s ``GET <base>/models``, cached for
`_PROBE_TTL` seconds so the header can poll this freely.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter

from resume_tailor import config, workspace
from resume_tailor.apply.answers import profile as apply_profile
from resume_tailor.content import data
from resume_tailor.web.job_routing import model_routing
from resume_tailor.web.schemas import JobSettings

router = APIRouter()

_PROBE_TTL = 60.0
_LOCAL_ORIGINS = frozenset({"ollama", "lmstudio"})
_probe_cache: dict[str, tuple[float, str | None]] = {}


def probe_local_server(base_url: str) -> str | None:
    """None when ``base_url`` answers, else a short reason. Cached per URL."""
    now = time.monotonic()
    hit = _probe_cache.get(base_url)
    if hit is not None and now - hit[0] < _PROBE_TTL:
        return hit[1]
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=2.0)
        problem = None if response.status_code < 500 else f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        problem = type(exc).__name__
    _probe_cache[base_url] = (now, problem)
    return problem


#: A hosted endpoint's answer that means the key, not the service, is the problem.
KEY_REJECTED = "key rejected"


def probe_remote_server(base_url: str, api_key: str) -> str | None:
    """Like ``probe_local_server`` for a hosted endpoint (Ollama Cloud): sends the key,
    waits longer, and reports a 401/403 as ``KEY_REJECTED``. Cached per URL and key."""
    cache_key = f"{base_url}\0{hash(api_key)}"
    now = time.monotonic()
    hit = _probe_cache.get(cache_key)
    if hit is not None and now - hit[0] < _PROBE_TTL:
        return hit[1]
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=5.0)
        if response.status_code in (401, 403):
            problem: str | None = KEY_REJECTED
        else:
            problem = None if response.status_code < 500 else f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        problem = type(exc).__name__
    _probe_cache[cache_key] = (now, problem)
    return problem


def clear_probe_cache() -> None:
    """Forget every probe result, e.g. after "Test connection" succeeded."""
    _probe_cache.clear()


def _item(
    item_id: str, label: str, ok: bool, detail: str, fix: str, to: str, *, optional: bool = False
) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "ok": ok,
        "detail": detail,
        "fix": {"label": fix, "to": to},
        "optional": optional,
    }


def _model_item() -> dict[str, Any]:
    settings = JobSettings.model_validate(workspace.load_settings()["defaults"])
    profile, overrides, effort = model_routing(settings)
    gaps = config.credential_gaps(profile, overrides)
    if gaps:
        return _item(
            "model", "AI model", False, f"An API key is missing ({gaps[0]}).",
            "Add your key", "/settings",
        )
    with config.pinned(profile, overrides=overrides, effort=effort):
        backends = {config.backend_for(p) for p in ("extract", "rewrite")}
        # Only hosted Ollama/LM Studio endpoints need the key for the probe below;
        # `api_key_for` raises for a missing Anthropic key, which is reported above.
        keys = {
            config.backend_for(p): config.api_key_for(p)
            for p in ("extract", "rewrite")
            if (config.backend_for(p).origin or "") in _LOCAL_ORIGINS
        }
    # `credential_gaps` covers only origins whose key `llm.py` checks up front; the
    # Anthropic key is enforced later, by `config.anthropic_api_key`.
    if any(b.provider == "anthropic" for b in backends) and not config.credential(
        "ANTHROPIC_API_KEY"
    ):
        return _item(
            "model", "AI model", False, "An API key is missing (ANTHROPIC_API_KEY).",
            "Add your key", "/settings",
        )
    for backend in backends:
        origin = backend.origin or backend.provider
        if origin not in _LOCAL_ORIGINS or not backend.base_url:
            continue
        name = "Ollama" if origin == "ollama" else "LM Studio"
        if config.is_local_url(backend.base_url):
            problem = probe_local_server(backend.base_url)
            if problem is not None:
                return _item(
                    "model", "AI model", False,
                    f"{name} is not answering at {backend.base_url} ({problem}). "
                    "Start it, then check again.",
                    "Model settings", "/settings",
                )
            continue
        # A hosted endpoint (Ollama Cloud): nothing to "start", and it wants the key.
        problem = probe_remote_server(backend.base_url, keys.get(backend, ""))
        if problem == KEY_REJECTED:
            return _item(
                "model", "AI model", False,
                f"{backend.base_url} rejected the API key. Check OLLAMA_API_KEY in Settings.",
                "Model settings", "/settings",
            )
        if problem is not None:
            return _item(
                "model", "AI model", False,
                f"Can't reach {backend.base_url} ({problem}). Check your internet connection, "
                "then test the connection in Settings.",
                "Model settings", "/settings",
            )
    models = ", ".join(sorted({f"{b.origin or b.provider}:{b.model}" for b in backends}))
    return _item("model", "AI model", True, f"Using {models}.", "Model settings", "/settings")


@router.get("/api/setup-status")
def setup_status() -> dict[str, Any]:
    items = [_model_item()]

    template_ok = config.DEFAULT_TEMPLATE_PATH.exists()
    items.append(_item(
        "template", "Resume template", template_ok,
        "Installed." if template_ok else "Upload your resume or pick a default template.",
        "Set up template", "/template",
    ))
    calibrated = config.CALIBRATION_SOURCE != "fallback"
    items.append(_item(
        "calibration", "Page fit tuned for your template", calibrated,
        "Measured." if calibrated else "Using estimates; tune it once for exact page fit.",
        "Tune page fit", "/template", optional=True,
    ))

    try:
        resume = data.load()
        entries = sum(len(s.entries) for s in resume.entry_sections)
        resume_ok, resume_detail = entries > 0, f"{entries} entries."
    except (FileNotFoundError, ValueError):
        resume_ok, resume_detail = False, "No master resume yet."
    items.append(_item(
        "resume", "Your experience", resume_ok,
        resume_detail if resume_ok else "Import your resume or add an entry.",
        "Open editor", "/profile/resume",
    ))

    try:
        profile, _seeded = apply_profile.load_profile()
        basics = bool(profile.first_name.strip() and profile.email.strip())
    except Exception:  # noqa: BLE001 - an unreadable profile is simply "not filled"
        basics = False
    items.append(_item(
        "profile", "Application basics", basics,
        "Filled." if basics else "Name and email for application forms (only needed to apply).",
        "Fill in profile", "/profile/application", optional=True,
    ))
    remaining = sum(1 for i in items if not i["ok"] and not i["optional"])
    return {"items": items, "ready": remaining == 0, "remaining": remaining}
