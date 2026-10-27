"""The exact files one fill uploads: read-only copies taken when it starts (audit #10).

A fill uploads from ``APPLICATIONS_OUTPUT_DIR/<id>/fills/<n>/<kind>/``, never the run
folder, so a resume re-rendered, a cover letter rewritten or a Prepare run while the
fill works never changes what it sends. Each copy is checked against the hash its
packet's preparation manifest recorded (`Changed` when the file moved on in between);
`attempts` keeps the copies a fill actually attached (audit #11).
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
    for kind, source in list(pkt.artifacts.items()):
        pkt.artifacts[kind] = str(_copy(Path(source), folder / kind, recorded.get(kind)))
    pkt.pinned_dir = str(folder)
    return folder


def pin_more(pkt: Packet, kinds: Iterable[str]) -> None:
    """Pin artifacts added to ``pkt`` during its fill (a cover letter written on demand)."""
    pinned = getattr(pkt, "pinned_dir", "")
    if not pinned:
        return
    folder = Path(pinned)
    for kind in kinds:
        source = pkt.artifacts.get(kind)
        if source and not Path(source).is_relative_to(folder):
            pkt.artifacts[kind] = str(_copy(Path(source), folder / kind, None))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(source: Path, folder: Path, expected: str | None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    shutil.copyfile(source, target)
    if expected and sha256(target) != expected:
        target.unlink()
        raise Changed(f"{source.name} changed while the fill was starting")
    os.chmod(target, stat.S_IREAD)
    return target
