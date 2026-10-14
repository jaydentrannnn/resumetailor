"""Desktop appearance shared by the startup shell and the served app."""

import json
import os
from pathlib import Path
from typing import Literal

from resume_tailor import config
from resume_tailor.infra.atomic import write_text

ThemePreference = Literal["system", "light", "dark"]


def theme_path() -> Path:
    # The shell supplies one stable path, independent of data-folder overrides in .env.
    override = os.environ.get("RESUME_TAILOR_THEME_PATH")
    return Path(override) if override else config.DATA_ROOT / "theme.json"


def load_theme() -> ThemePreference | None:
    try:
        preference = json.loads(theme_path().read_text("utf-8"))["preference"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return preference if preference in ("system", "light", "dark") else None


def save_theme(preference: ThemePreference) -> None:
    target = theme_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text(target, json.dumps({"preference": preference}) + "\n")
