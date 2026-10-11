"""Edit layout in Word: write the layout file, open it, notice the save, read it back.

One session per profile, under `<templates>/edit/`: `layout.docx` (the token skeleton,
`document/template_skeleton.py`) and `session.json` (the skeleton's meta plus the file's
size and mtime when it was written). Nothing is applied here — `read_back` parses the
saved file into an ordinary analysis, caches its realised bytes as a prepared upload, and
the template wizard installs it after the person confirms. Desktop only: opening a file
in the person's word processor only makes sense on their own machine.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import (
    docx_normalize,
    skeleton_parse,
    template_adjust,
    template_profile,
    template_skeleton,
)
from resume_tailor.web.schemas import TemplateAnalyzeResponse, TemplateEditStatus

from . import template_ops, template_uploads

LAYOUT_NAME = "layout.docx"
_SESSION_NAME = "session.json"
_MAC_WORD = Path("/Applications/Microsoft Word.app")


class EditSessionError(template_ops.TemplateValidationError):
    """A session request that cannot be met right now (none open, one already open)."""


def _dir() -> Path:
    return config.TEMPLATES_DIR / "edit"


def layout_path() -> Path:
    return _dir() / LAYOUT_NAME


def _session() -> dict | None:
    try:
        return json.loads((_dir() / _SESSION_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_session(session: dict) -> None:
    target = _dir() / _SESSION_NAME
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(session), encoding="utf-8")
    os.replace(temp, target)


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _open_file(path: Path) -> None:
    """Open `path` in the person's word processor (Word, else LibreOffice on macOS).

    Never Pages: it cannot save a .docx back in place, so the save would never arrive.
    """
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        app = "Microsoft Word" if _MAC_WORD.exists() else "LibreOffice"
        subprocess.Popen(["open", "-a", app, str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607


def _editor_open(path: Path) -> bool:
    """Whether a word processor holds the file: Word's `~$` owner file, LibreOffice's
    `.~lock.<name>#`. Word shortens the name to fit, so match on the tail. A lock file
    left behind by a crashed editor still reads as open until it is deleted."""
    tail = path.name[2:]
    for sibling in path.parent.iterdir():
        name = sibling.name
        if name.startswith("~$") and name.endswith(tail):
            return True
        if name == f".~lock.{path.name}#":
            return True
    return False


def status() -> TemplateEditStatus:
    session = _session()
    path = layout_path()
    if session is None or not path.exists():
        return TemplateEditStatus(active=False)
    stamp = _stamp(path)
    changed = stamp is not None and list(stamp) != session["stamp"]
    saved_at = None
    if changed and stamp is not None:
        saved_at = datetime.fromtimestamp(stamp[0] / 1e9, UTC).isoformat()
    editor_open = _editor_open(path)
    if editor_open and not session.get("seen_open"):
        # Remembered so "closed" can be told apart from "not opened yet".
        _write_session({**session, "seen_open": True})
        session["seen_open"] = True
    return TemplateEditStatus(
        active=True,
        changed=changed,
        saved_at=saved_at,
        editor_open=editor_open,
        editor_closed=bool(session.get("seen_open")) and not editor_open,
        started_at=session.get("started_at"),
        path=str(path),
    )


def _resume():
    try:
        return data.load()
    except (FileNotFoundError, ValueError):
        return None


def start() -> TemplateEditStatus:
    """Write the active template's layout file and open it. Refuses a second session."""
    if _session() is not None and layout_path().exists():
        raise EditSessionError(
            "The layout file is already open for editing. Finish or discard that session first."
        )
    skeleton = _live_skeleton()
    directory = _dir()
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    path = layout_path()
    path.write_bytes(skeleton.raw)
    session = {
        "meta": skeleton.meta(),
        "stamp": list(_stamp(path) or (0, 0)),
        "started_at": datetime.now(UTC).isoformat(),
    }
    _write_session(session)
    _open_file(path)
    return status()


def reopen() -> TemplateEditStatus:
    """Open the session's file again (the person closed the window before saving)."""
    session = _session()
    if session is None or not layout_path().exists():
        raise EditSessionError("No layout file is open for editing.")
    _write_session({**session, "seen_open": False})
    _open_file(layout_path())
    return status()


def read_back() -> TemplateAnalyzeResponse:
    """Parse the saved layout file into an analysis the template wizard can install.

    The realised file (tokens swapped for sample text) is cached as an already-prepared
    upload, so the wizard's preview, remap and install steps find it by its hash.
    """
    session = _session()
    if session is None or not layout_path().exists():
        raise EditSessionError("No layout file is open for editing.")
    raw = layout_path().read_bytes()
    if not zipfile.is_zipfile(layout_path()):
        raise EditSessionError(
            "The layout file is still being saved, or isn't a .docx any more. Save it in "
            "Word as a Word document (.docx) and try again."
        )
    # Accept tracked changes and drop comments the same way an upload is cleaned.
    raw, _counts = docx_normalize.normalize(raw)
    return _analysis(raw, session["meta"])


def _analysis(raw: bytes, meta: dict) -> TemplateAnalyzeResponse:
    """Parse a layout file and cache its realised bytes for the wizard's install."""
    try:
        parsed = skeleton_parse.parse_skeleton(raw, meta, _resume())
    except (KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise EditSessionError(f"Couldn't read the layout file: {exc}") from exc
    template_uploads.cache_prepared(parsed.raw)
    return template_uploads._analysis_to_response(parsed.result)


def _live_skeleton() -> template_skeleton.Skeleton:
    profile = template_profile.load_profile()
    if profile is None or not config.DEFAULT_TEMPLATE_PATH.exists():
        raise EditSessionError("Set up a template first: there is no layout to edit yet.")
    return template_skeleton.make_skeleton(config.DEFAULT_TEMPLATE_PATH, profile, _resume())


def adjustment_form() -> tuple[template_adjust.CurrentLayout, bool]:
    """The live template's margins, font and field emphasis, and whether it is a table
    layout (its fixed-width tables do not follow a margin change)."""
    profile = template_profile.load_profile()
    return template_adjust.current(_live_skeleton().raw), bool(
        profile is not None and profile.layout == "table"
    )


def adjust(adj: template_adjust.Adjustments) -> TemplateAnalyzeResponse:
    """Quick adjustments: edit the layout file in code, then read it back like a Word edit."""
    skeleton = _live_skeleton()
    return _analysis(template_adjust.apply(skeleton.raw, adj), skeleton.meta())


def realised(sha: str) -> bytes:
    """The read-back file the wizard installs (`read_back` cached it by `sha`)."""
    return template_uploads._load_cached_upload(sha)


def end() -> None:
    """Close the session and delete its files (the person's word processor may still hold
    the file open; a failed delete is left for the next `start`, which clears it)."""
    shutil.rmtree(_dir(), ignore_errors=True)
