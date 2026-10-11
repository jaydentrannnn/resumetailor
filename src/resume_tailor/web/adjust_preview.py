"""Quick adjustments' live preview: the master resume through the adjusted template,
as one PNG per page, without installing anything.

Same steps as Apply, stopped short: the adjustments go onto the live layout file, it is
read back, the read-back is built into a staged template (`template_preview` does the
same for the wizard's draft), and the resume is rendered through it. Images, not a PDF
frame: the page beside it may hold the resume's own PDF frame, and Chrome/Edge run one
PDF plugin. Conversion runs outside `template_ops.LOCK` on `convert_warm`'s thread, so
Word stays open between previews. A newer request supersedes an older one before its
conversion starts; results are cached by everything that shapes them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
from pathlib import Path

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import (
    convert_warm,
    render,
    skeleton_parse,
    template_build,
    template_profile,
    thumbnails,
)
from resume_tailor.document.template_adjust import Adjustments

from . import template_edit, template_ops

#: Wide enough to read at the document column's width on a high-density screen.
WIDTH = 1100
#: Previews kept on disk; older ones are removed as new ones are made.
_KEEP = 12
_TICKET = {"latest": 0}
_TICKET_LOCK = threading.Lock()


class Superseded(Exception):
    """A newer preview request arrived; this one stopped before converting."""


class PreviewError(Exception):
    """The adjusted layout couldn't be read back or built (the message says why)."""


def _directory() -> Path:
    return config.CACHE_DIR / "adjust_preview"


def _take_ticket() -> int:
    with _TICKET_LOCK:
        _TICKET["latest"] += 1
        return _TICKET["latest"]


def _check(ticket: int) -> None:
    if ticket != _TICKET["latest"]:
        raise Superseded


def _prune(keep: Path) -> None:
    dirs = sorted((d for d in _directory().iterdir() if d.is_dir() and d != keep),
                  key=lambda d: d.stat().st_mtime, reverse=True)  # fmt: skip
    for old in dirs[_KEEP - 1 :]:
        shutil.rmtree(old, ignore_errors=True)


def _key(adj: Adjustments) -> str:
    """Everything the preview shows: the adjustments, the live template and the resume
    (the layout file itself is regenerated each time, with fresh zip timestamps)."""
    digest = hashlib.sha256(adj.model_dump_json().encode())
    digest.update(config.PDF_BACKEND.encode())
    for path in (config.MASTER_RESUME_PATH, config.BASELINE_TEMPLATE_PATH,
                 config.DEFAULT_TEMPLATE_PATH, config.TEMPLATE_PROFILE_PATH):  # fmt: skip
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    return digest.hexdigest()[:24]


def _pages(directory: Path) -> int | None:
    marker = directory / "pages.json"
    if not marker.is_file():
        return None
    return int(json.loads(marker.read_text(encoding="utf-8"))["pages"])


def preview(adj: Adjustments) -> tuple[str, int]:
    """(key, page count) of the preview for `adj`. Raises `Superseded`, `PreviewError`,
    `template_edit.EditSessionError` (no template) or `RuntimeError` (no PDF engine)."""
    ticket = _take_ticket()
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError) as exc:
        raise PreviewError("Add your resume content first: the preview shows it.") from exc
    with template_ops.LOCK:
        key = _key(adj)
        directory = _directory() / key
        pages = _pages(directory)
        if pages is not None:
            return key, pages
        _check(ticket)
        raw, meta = template_edit.adjusted(adj)
        parsed = skeleton_parse.parse_skeleton(raw, meta, resume)
        profile = parsed.result.suggested_profile
        if profile is None or not parsed.result.ready:
            blocking = [i.message for i in parsed.result.issues if i.blocking]
            raise PreviewError(blocking[0] if blocking else "The adjusted layout couldn't be read.")
        stage = Path(tempfile.mkdtemp(prefix="rt_adjust_"))
        try:
            src, tagged = stage / "baseline.docx", stage / "main_template.docx"
            src.write_bytes(parsed.raw)
            try:
                template_build.build_from_profile(src, tagged, profile)
            except Exception as exc:  # noqa: BLE001 - every mapping problem is a RuntimeError
                raise PreviewError(f"The adjusted template couldn't be built: {exc}") from exc
            docx_path = stage / "preview.docx"
            render.render(resume, template=tagged, out=docx_path,
                          layout=template_profile.active_layout(profile))  # fmt: skip
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
    try:
        _check(ticket)
        pdf_path = stage / "preview.pdf"
        convert_warm.to_pdf(docx_path, pdf_path)
        directory.mkdir(parents=True, exist_ok=True)
        pages = thumbnails.pdf_pages_png(pdf_path, directory, width=WIDTH)
        (directory / "pages.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
        _prune(directory)
        return key, pages
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def page_path(key: str, page: int) -> Path:
    """A rendered page's PNG; `FileNotFoundError` once it has been pruned."""
    if not (len(key) == 24 and all(c in "0123456789abcdef" for c in key)) or page < 1:
        raise FileNotFoundError(key)
    path = _directory() / key / f"{page}.png"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path
