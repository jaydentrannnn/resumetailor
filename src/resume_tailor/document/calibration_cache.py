"""Retain page-fit measurements by their exact template/resume/backend inputs."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from resume_tailor import config


def input_digest(*, paths: dict[str, Path] | None = None, backend: str | None = None) -> str:
    digest = hashlib.sha256((backend or config.PDF_BACKEND).encode())
    for name in ("DEFAULT_TEMPLATE_PATH", "TEMPLATE_PROFILE_PATH", "MASTER_RESUME_PATH"):
        path = paths[name] if paths is not None else getattr(config, name)
        digest.update(path.name.encode())
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    return digest.hexdigest()


def _path() -> Path:
    return config.CALIBRATION_DIR / f"{config.PDF_BACKEND}.json"


def remember() -> None:
    """Call under the template lock, before replacing any live template inputs."""
    path = _path()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text("utf-8"))
        digest = input_digest()
        if raw.get("input_digest") != digest:
            return
        cached = config.CALIBRATION_DIR / "templates" / f"{digest}.json"
        cached.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, cached)
    except (OSError, ValueError):
        return


def activate() -> None:
    """Restore matching measurements, otherwise stop using the preceding template's."""
    path = _path()
    digest = input_digest()
    cached = config.CALIBRATION_DIR / "templates" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if cached.is_file():
        try:
            raw = json.loads(cached.read_text("utf-8"))
            if raw.get("input_digest") == digest and raw.get("backend") == config.PDF_BACKEND:
                shutil.copy2(cached, path)
                config.reload_calibration()
                return
        except (OSError, ValueError):
            pass
    if path.is_file():
        # Keep unverified legacy measurements available for inspection/recovery.
        backup = (
            config.CALIBRATION_DIR
            / "templates"
            / f"unverified-{hashlib.sha256(path.read_bytes()).hexdigest()}.json"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        path.unlink()
    config.reload_calibration()
