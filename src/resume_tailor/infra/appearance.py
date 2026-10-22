"""Desktop appearance shared by the startup shell and the served app.

``theme.json`` holds the light/dark preference, optional accent hex, and UI scale.
The shell seeds preference and accent into ``index.html`` before paint; scale is
applied by the shell via ``set_zoom``. Browser builds keep preference and accent in
``localStorage`` as well.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config
from resume_tailor.infra.atomic import write_text

ThemePreference = Literal["system", "light", "dark"]

#: Allowed UI scales (percent of 1.0); must match the Appearance tab's choices.
SCALES = (0.9, 1.0, 1.1, 1.25, 1.5)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def theme_path() -> Path:
    """Path to ``theme.json``; the shell may override via ``RESUME_TAILOR_THEME_PATH``."""
    # The shell supplies one stable path, independent of data-folder overrides in .env.
    override = os.environ.get("RESUME_TAILOR_THEME_PATH")
    return Path(override) if override else config.DATA_ROOT / "theme.json"


def load() -> dict[str, Any]:
    """Raw ``theme.json`` contents, or ``{}`` when missing or unreadable."""
    try:
        raw = json.loads(theme_path().read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_theme() -> ThemePreference | None:
    """Saved light/dark preference, or None when unset/invalid."""
    preference = load().get("preference")
    return preference if preference in ("system", "light", "dark") else None


def load_accent() -> str | None:
    """Saved accent hex (``#rrggbb``), or None for the default green."""
    accent = load().get("accent")
    return accent if isinstance(accent, str) and _HEX.match(accent) else None


def load_scale() -> float:
    """Saved UI scale factor; defaults to 1.0."""
    scale = load().get("scale")
    try:
        value = float(scale)
    except (TypeError, ValueError):
        return 1.0
    return value if value in SCALES else 1.0


def save(*, preference: ThemePreference | None = None, accent: str | None | object = ...,
         scale: float | None = None) -> dict[str, Any]:
    """Merge fields into ``theme.json`` and return the saved dict.

    Pass ``accent=None`` to clear a custom accent (default green). Omit ``accent``
    (the sentinel ``...``) to leave the stored value alone.
    """
    data = load()
    if preference is not None:
        data["preference"] = preference
    if accent is not ...:
        if accent is None:
            data.pop("accent", None)
        elif isinstance(accent, str) and _HEX.match(accent):
            data["accent"] = accent
        else:
            raise ValueError("accent must be #rrggbb or null")
    if scale is not None:
        if scale not in SCALES:
            raise ValueError(f"scale must be one of {SCALES}")
        data["scale"] = scale
    target = theme_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text(target, json.dumps(data) + "\n")
    return data


def save_theme(preference: ThemePreference) -> None:
    """Persist the light/dark preference without clearing accent or scale."""
    save(preference=preference)
