"""The exact files one fill uploads: read-only copies taken when it starts (audit #10).

A fill uploads from ``APPLICATIONS_OUTPUT_DIR/<id>/fills/<n>/<kind>/``, never the run
folder, so a resume re-rendered, a cover letter rewritten or a Prepare run while the
fill works never changes what it sends. Each copy is checked against the hash its
packet's preparation manifest recorded (`Changed` when the file moved on in between);
`attempts` keeps the copies a fill actually attached (audit #11). Beside them, ``run/``
keeps what goes with those documents: the run's bullets, requirements, coverage and
cover-letter text, and the packet as the fill built it, so interview prep reads the
bullets of the resume that was attached, not a later Prepare's. The documents and those
files are copied as one revision: under the run folder's lock (`infra.run_lock`, held by
a re-render or a regenerated cover letter while it rewrites them), and the documents are
checked again once everything is copied.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Callable, Iterable
from pathlib import Path

from resume_tailor import config
from resume_tailor.apply.funnel.packet_models import Packet
from resume_tailor.infra import run_lock


#: The fill folder's copy of the run files that go with its documents.
RUN = "run"
#: Run files kept in ``run/`` (the packet is written as the fill built it).
SUPPORTING = ("bullets.json", "requirements.json", "coverage.json", "cover.json")


class Changed(RuntimeError):
    """A prepared file no longer matches the hash its packet recorded."""


def pinned_packet(
    build: Callable[[], Packet], application_id: str,
    *, progress: Callable[[str], None] | None = None,
) -> Packet:
    """``build()`` a packet and pin its files. A file that changed in between (a Prepare
    finishing) rebuilds it once; a second change fails the fill's start."""
    pkt = build()
    try:
        pin(pkt, application_id)
    except Changed:
        if progress is not None:
            progress("a prepared file changed; rebuilding the packet")
        pkt = build()
        pin(pkt, application_id)
    return pkt


def pin(pkt: Packet, application_id: str) -> Path:
    """Copy every artifact of ``pkt`` into a new numbered fill folder and point
    ``pkt.artifacts`` at the copies; returns the folder."""
    root = config.APPLICATIONS_OUTPUT_DIR / application_id / "fills"
    root.mkdir(parents=True, exist_ok=True)
    numbers = [int(child.name) for child in root.iterdir() if child.name.isdigit()]
    folder = root / str(max(numbers, default=0) + 1)
    folder.mkdir()
    recorded = {item.purpose: item.sha256 for item in pkt.preparation.artifacts}
    sources = dict(pkt.artifacts)
    with run_lock.of(_run_dir(pkt)):
        for kind, source in sources.items():
            pkt.artifacts[kind] = str(_copy(Path(source), folder / kind, recorded.get(kind)))
        pkt.pinned_dir = str(folder)
        _keep_run_files(pkt, folder, SUPPORTING)
        # A writer that does not take the lock may have moved a document on meanwhile.
        for kind, source in sources.items():
            if recorded.get(kind) and _sha_or_none(Path(source)) != recorded[kind]:
                raise Changed(f"{Path(source).name} changed while the fill was starting")
    return folder


def pin_more(pkt: Packet, kinds: Iterable[str]) -> None:
    """Pin artifacts added to ``pkt`` during its fill (a cover letter written on demand)."""
    pinned = getattr(pkt, "pinned_dir", "")
    if not pinned:
        return
    folder = Path(pinned)
    kinds = list(kinds)
    with run_lock.of(_run_dir(pkt)):
        for kind in kinds:
            source = pkt.artifacts.get(kind)
            if source and not Path(source).is_relative_to(folder):
                pkt.artifacts[kind] = str(_copy(Path(source), folder / kind, None))
        covers = ("cover.json",) if any(kind.startswith("cover") for kind in kinds) else ()
        _keep_run_files(pkt, folder, covers)


def _run_dir(pkt: Packet) -> Path:
    return config.OUTPUT_DIR / "jobs" / pkt.job_id


def _keep_run_files(pkt: Packet, folder: Path, names: Iterable[str]) -> None:
    """Copy ``names`` from the run folder into ``folder/run/`` and write the packet there."""
    kept = folder / RUN
    kept.mkdir(exist_ok=True)
    run_dir = _run_dir(pkt)
    for name in names:
        if (run_dir / name).is_file():
            _copy(run_dir / name, kept, None)
    _writable(kept / "packet.json")
    (kept / "packet.json").write_text(pkt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.chmod(kept / "packet.json", stat.S_IREAD)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha_or_none(path: Path) -> str | None:
    return sha256(path) if path.is_file() else None


def _writable(path: Path) -> None:
    if path.exists():
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def _copy(source: Path, folder: Path, expected: str | None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    _writable(target)
    shutil.copyfile(source, target)
    if expected and sha256(target) != expected:
        target.unlink()
        raise Changed(f"{source.name} changed while the fill was starting")
    os.chmod(target, stat.S_IREAD)
    return target
