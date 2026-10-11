"""Retain page-fit measurements by their exact template/backend inputs.

The fingerprint covers the tagged template, its profile and the PDF backend — not the
master resume. Line width, page length and header width are properties of the template:
`calibrate` measures them with synthetic probe bullets, so a resume edit cannot change
them. (The one resume-specific check, the render anchors, keeps its own
`resume_sha256`.) Keeping the resume out means an edit never discards a measurement and
each template's measurement is restored when it becomes active again.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from resume_tailor import config

_INPUT_NAMES = ("DEFAULT_TEMPLATE_PATH", "TEMPLATE_PROFILE_PATH")
#: Files measured before the resume left the fingerprint also hashed it.
_LEGACY_INPUT_NAMES = ("DEFAULT_TEMPLATE_PATH", "TEMPLATE_PROFILE_PATH", "MASTER_RESUME_PATH")


def _digest(names: tuple[str, ...], paths: dict[str, Path] | None, backend: str | None) -> str:
    digest = hashlib.sha256((backend or config.PDF_BACKEND).encode())
    for name in names:
        path = paths[name] if paths is not None else getattr(config, name)
        digest.update(path.name.encode())
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    return digest.hexdigest()


def input_digest(*, paths: dict[str, Path] | None = None, backend: str | None = None) -> str:
    return _digest(_INPUT_NAMES, paths, backend)


def legacy_input_digest(
    *, paths: dict[str, Path] | None = None, backend: str | None = None
) -> str | None:
    """The pre-change fingerprint (template + profile + resume), for upgrading old files.
    `None` when `paths` doesn't name the resume."""
    if paths is not None and "MASTER_RESUME_PATH" not in paths:
        return None
    return _digest(_LEGACY_INPUT_NAMES, paths, backend)


def matches(
    recorded: str, *, paths: dict[str, Path] | None = None, backend: str | None = None
) -> bool:
    """Whether a file's recorded digest describes the current inputs — under the current
    fingerprint, or the legacy one for a file measured before the change."""
    if recorded == input_digest(paths=paths, backend=backend):
        return True
    return recorded == legacy_input_digest(paths=paths, backend=backend)


def upgrade_legacy(
    path: Path, *, paths: dict[str, Path] | None = None, backend: str | None = None
) -> None:
    """Rewrite a calibration file whose digest is the legacy one for the current inputs,
    so a later resume edit no longer invalidates it. Best effort: never raises."""
    try:
        raw = json.loads(path.read_text("utf-8"))
        current = input_digest(paths=paths, backend=backend)
        if raw.get("input_digest") in (None, current):
            return
        if raw["input_digest"] != legacy_input_digest(paths=paths, backend=backend):
            return
        raw["input_digest"] = current
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, ValueError, KeyError):
        return


def _path() -> Path:
    return config.CALIBRATION_DIR / f"{config.PDF_BACKEND}.json"


def remember() -> None:
    """Call under the template lock, before replacing any live template inputs."""
    path = _path()
    if not path.is_file():
        return
    upgrade_legacy(path)
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
    if path.is_file():
        upgrade_legacy(path)
        try:
            if json.loads(path.read_text("utf-8")).get("input_digest") == input_digest():
                # Already this template's measurement (e.g. a re-activation).
                config.reload_calibration()
                return
        except (OSError, ValueError):
            pass
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
