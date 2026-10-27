"""Cover letters for Apply, by `ApplySettings.cover_letter_mode`.

``every`` writes one during Prepare for every application (`daily_rows._job_settings`).
The other modes write none in Prepare: most applications never ask, and on a
one-request-at-a-time model plan each letter is calls the whole batch waits on. Whether a
posting asks is only known inside its form (Workday shows it pages in), so Fill decides
per cover-letter field, upload or text box (`plan`): ``required`` writes one for a
required field, ``optional`` for any; ``off`` never writes one. An optional field the
mode does not cover is left empty.

The letter is the same one the job page's Regenerate writes
(`job_followups.regenerate_cover_letter`): the run's saved bullets, requirements,
guidance and model connections, the same guard, rendered beside the resume.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Literal

from resume_tailor import config
from resume_tailor.apply.funnel import packet as packet_mod
from resume_tailor.apply.funnel.packet_models import Packet

_log = logging.getLogger(__name__)

#: Shown beside the upload in the fill summary.
GENERATED_NOTE = "Written during fill for this form"

#: Shown when an optional cover-letter field is left empty.
SKIPPED_NOTE = "Optional cover-letter field left empty"

_COVER_FILES = ("cover.pdf", "cover.docx")

_LOCK = threading.Lock()
#: Letters written while Fill answers the rest of the form (`start`).
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cover-letter")
#: Background letters not finished yet, queued or writing (`busy`).
_RUNNING = 0
_RUNNING_LOCK = threading.Lock()

CoverMode = Literal["off", "required", "optional", "every"]

#: What Fill does with one cover-letter field: leave it empty, fill it with the letter it
#: has, write a letter first, or report that none is available (left for review).
Action = Literal["skip", "use", "write", "missing"]


def plan(mode: CoverMode, *, required: bool, has_letter: bool) -> Action:
    """The decision for one cover-letter field. Pure; `resolve` carries it out."""
    if not required and mode not in ("optional", "every"):
        return "skip"
    if has_letter:
        return "use"
    return "missing" if mode == "off" else "write"


def is_cover_field(label: str) -> bool:
    """A form field asking for the cover letter (an upload or a text box)."""
    text = label.casefold()
    return "cover" in text and "letter" in text


def has_cover(pkt: Packet) -> bool:
    return bool(pkt.artifacts.get("cover_pdf") or pkt.artifacts.get("cover_docx"))


def ensure(pkt: Packet) -> bool:
    """Give `pkt` a cover letter, writing one for its job when none exists yet.

    Updates `pkt` in place (artifacts, letter text, preparation manifest) and persists
    the rebuilt ``packet.json``. Idempotent: a letter already on disk is reused. Never
    raises — a failed draft returns False and the upload reports the missing document.
    """
    if has_cover(pkt):
        return True
    from resume_tailor.web import job_followups

    job_dir = config.OUTPUT_DIR / "jobs" / pkt.job_id
    try:
        with _LOCK:
            if not any((job_dir / name).is_file() for name in _COVER_FILES):
                job_followups.regenerate_cover_letter(pkt.job_id)
            fresh = packet_mod.write_packet(pkt.job_id)
    except Exception:  # noqa: BLE001 - the fill continues; the upload names what is missing
        _log.warning("Could not write a cover letter for job %s", pkt.job_id, exc_info=True)
        return False
    for kind in ("cover_pdf", "cover_docx"):
        if kind in fresh.artifacts:
            pkt.artifacts[kind] = fresh.artifacts[kind]
    from resume_tailor.apply.funnel import fill_files  # noqa: PLC0415

    try:
        fill_files.pin_more(pkt, ("cover_pdf", "cover_docx"))
    except OSError:
        _log.warning("Could not pin the cover letter for job %s", pkt.job_id, exc_info=True)
        return False
    pkt.cover_letter = fresh.cover_letter
    pkt.preparation = fresh.preparation
    return has_cover(pkt)


def start(pkt: Packet) -> Future[bool]:
    """`ensure` in the background, in the caller's context (its model routing): the
    letter and its PDF take about a minute, which the form's other answers need not
    wait for (Twitch, 2026-10). Touches no browser.

    A fill that runs out of time stops waiting, but the letter keeps going. It stays
    pinned to the profile it started in, and `busy` holds a profile switch until it is
    done: v1.24.0 read the live profile's paths, so a switch in between wrote the packet
    into the other profile's output folder."""
    global _RUNNING
    # Outside a run, paths come from the process default, which a switch rebinds.
    pinned = None if config.in_run_context() else config.default_context()
    with _RUNNING_LOCK:
        _RUNNING += 1
    try:
        return config.submit_in_context(_POOL, _ensure_pinned, pkt, pinned)
    except BaseException:
        _finished()
        raise


def busy() -> bool:
    """Whether a background letter is still queued or being written."""
    with _RUNNING_LOCK:
        return _RUNNING > 0


def _ensure_pinned(pkt: Packet, pinned: config.RunContext | None) -> bool:
    try:
        if pinned is None:
            return ensure(pkt)
        with config.use_context(pinned):
            return ensure(pkt)
    finally:
        _finished()


def _finished() -> None:
    global _RUNNING
    with _RUNNING_LOCK:
        _RUNNING -= 1


def resolve(pkt: Packet, mode: CoverMode, *, required: bool) -> tuple[Action, bool]:
    """Carry out `plan` for one field: ``(action, written)``. ``action`` is ``use`` when
    `pkt` now has a letter, ``written`` true when it was written just now; a failed
    write comes back as ``missing``."""
    action = plan(mode, required=required, has_letter=has_cover(pkt))
    if action != "write":
        return action, False
    return ("use", True) if ensure(pkt) else ("missing", False)
