"""What was sent: a read-only copy of an application's files each time it goes out.

`store.set_status` calls `on_status` on every status change. A row moving into
``submitted`` or ``submit_unconfirmed`` from a status that was not already sent gets a
new `SubmissionAttempt`: the resume and cover letter (PDF and Word), the packet, the
final bullets, requirements and coverage, the saved JD and ``fill.json`` from the
application folder, and under ``attached/<purpose>/`` the exact files the app attached
(its fill's pinned copies, `fill_files`), copied to
``APPLICATIONS_OUTPUT_DIR/<source_job_id>/attempts/<n>/``, hashed and marked read-only.
The run files come from the fill folder of the resume (or cover letter) the app
attached, so they describe that document; the run folder only when the app attached
neither. Interview prep and follow-ups read this copy, never the run folder a later
Prepare overwrites.

``confirmed`` says these exact files reached the employer: an automatic submit that saw
its confirmation, or a submit the monitor saw in the tab the app filled. A manual mark
records the prepared files; what the student actually uploaded is unconfirmed. A
``submit_unconfirmed`` row that is confirmed later updates the same attempt. Undoing a
submitted mark voids the latest attempt and keeps its files.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config
from resume_tailor.apply.forms.submit_guard import AUTO_NOTE

from . import fill_files, store_models

#: The status note `submission_monitor` writes when it sees a manual submit.
MONITOR_NOTE = "Manual submission confirmed in the recorded application tab"

SENT_STATUSES = frozenset({"submitted", "submit_unconfirmed"})
#: Statuses that mean the employer (probably) already has this attempt.
_APPLIED = frozenset({"submitted", "submit_unconfirmed", "interview", "rejected", "ghosted"})
#: Copied from the run folder (``OUTPUT_DIR/jobs/<job_id>``) when present.
RUN_FILES = (
    "tailored.pdf", "tailored.docx", "cover.pdf", "cover.docx", "cover.json",
    "packet.json", "bullets.json", "requirements.json", "coverage.json",
)

Method = Literal["auto", "manual", "monitor"]


def method_for(note: str) -> Method:
    if note == AUTO_NOTE:
        return "auto"
    if note == MONITOR_NOTE:
        return "monitor"
    return "manual"


def latest(app: store_models.Application) -> store_models.SubmissionAttempt | None:
    """The newest attempt that was not voided."""
    return next((a for a in reversed(app.attempts) if a.voided_at is None), None)


def on_status(
    app: store_models.Application, previous: str, new_status: str, note: str
) -> None:
    """Record or confirm an attempt for a status change; never raises for file errors."""
    if new_status not in SENT_STATUSES:
        return
    method = method_for(note)
    confirmed = new_status == "submitted" and method != "manual"
    current = latest(app)
    if current is not None and previous in _APPLIED:
        if confirmed and not current.confirmed:
            current.confirmed = True
        return
    if previous == new_status:
        return
    record(app, method=method, confirmed=confirmed)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sources(app: store_models.Application) -> list[tuple[Path, str]]:
    """``(source, name in the attempt folder)`` for every file that exists. A resume or
    cover letter the app attached brings the run files that go with it from its fill
    folder (`fill_files`), never the run folder a later Prepare rewrote."""
    uploads = _attached_uploads(app)
    sources: list[tuple[Path | None, str]] = []
    if app.job_id:
        run_dir = config.OUTPUT_DIR / "jobs" / app.job_id
        fills = _fill_folders(uploads)
        sources.extend((_run_file(run_dir, fills, name), name) for name in RUN_FILES)
    app_dir = config.APPLICATIONS_OUTPUT_DIR / app.source_job_id
    jd = Path(app.jd_text_path) if app.jd_text_path else app_dir / "jd.txt"
    sources += [(jd, "jd.txt"), (app_dir / "fill.json", "fill.json")]
    sources += _attached(uploads)
    return [(path, name) for path, name in sources if path is not None and path.is_file()]


#: Where an attempt keeps the files the app attached.
ATTACHED = "attached/"
#: Where a fill folder keeps each run document (`packet._artifact_paths` kinds); the
#: run's JSON files are under ``fill_files.RUN``.
_PINNED_AS = {
    "tailored.pdf": "resume_pdf", "tailored.docx": "resume_docx",
    "cover.pdf": "cover_pdf", "cover.docx": "cover_docx",
}


def _attached_uploads(app: store_models.Application) -> list[dict[str, Any]]:
    """The uploads this row's fill verified as attached from a pinned copy."""
    fill = store_models.FillResult.model_validate(app.fill) if app.fill else None
    return [
        upload for upload in (fill.uploads if fill else [])
        if upload.get("artifact_path") and upload.get("uploaded_by_app")
        and upload.get("verified")
    ]


def _fill_folders(uploads: list[dict[str, Any]]) -> dict[str, Path]:
    """purpose → the fill folder its attached copy came from, for folders that kept the
    run files with it (fills from before that keep none, and read the run folder)."""
    folders: dict[str, Path] = {}
    for upload in uploads:
        folder = Path(str(upload["artifact_path"])).parent.parent
        if (folder / fill_files.RUN).is_dir():
            folders.setdefault(str(upload.get("purpose") or ""), folder)
    return folders


def _run_file(run_dir: Path, fills: dict[str, Path], name: str) -> Path | None:
    """Where ``name`` comes from: the fill folder of the document it goes with (the cover
    letter's for ``cover.*``, else the resume's), or the run folder when the app attached
    neither. None when that fill had no such file: the run's newer one is not it."""
    folder = fills.get("cover_letter") if name.startswith("cover") else None
    folder = folder or fills.get("resume")
    if folder is None:
        return run_dir / name
    kept = folder / _PINNED_AS.get(name, fill_files.RUN) / name
    return kept if kept.is_file() else None


def _attached(uploads: list[dict[str, Any]]) -> list[tuple[Path, str]]:
    """The attached pinned files, once each, named by purpose: a transcript and a
    portfolio can both be ``document.pdf``."""
    found: dict[str, Path] = {}
    for upload in uploads:
        path = Path(str(upload["artifact_path"]))
        if path in found.values():
            continue
        purpose = re.sub(r"[^a-z_]", "", str(upload.get("purpose") or "").lower()) or "file"
        name, number = f"{ATTACHED}{purpose}/{path.name}", 2
        while name in found:
            name, number = f"{ATTACHED}{purpose}/{number}-{path.name}", number + 1
        found[name] = path
    return [(path, name) for name, path in found.items()]


def record(
    app: store_models.Application, *, method: Method, confirmed: bool
) -> store_models.SubmissionAttempt:
    """Copy the row's files into a new numbered attempt folder and append the attempt."""
    number = len(app.attempts) + 1
    folder = config.APPLICATIONS_OUTPUT_DIR / app.source_job_id / "attempts" / str(number)
    attempt = store_models.SubmissionAttempt(
        id=uuid.uuid4().hex[:12],
        number=number,
        submitted_at=store_models._now_iso(),
        method=method,
        confirmed=confirmed,
        snapshot_dir=str(folder),
    )
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for source, name in _sources(app):
            target = folder / name
            if target.exists():  # a folder left by an attempt whose row was never saved
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            attempt.files[name] = _sha256(target)
            if name.startswith(ATTACHED):
                attempt.attached[name] = attempt.files[name]
            os.chmod(target, stat.S_IREAD)
    except OSError as exc:
        attempt.error = f"Could not copy every file: {exc}"
    attempt.packet_digest = attempt.files.get("packet.json", "")
    attempt.jd_sha256 = attempt.files.get("jd.txt", "")
    app.attempts.append(attempt)
    return attempt


def void_latest(app: store_models.Application) -> None:
    """Void the newest attempt (a submitted mark was undone); its files stay."""
    current = latest(app)
    if current is not None:
        current.voided_at = store_models._now_iso()
