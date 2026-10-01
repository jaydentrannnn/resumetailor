"""First-page PNG thumbnails for the Template gallery.

A thumbnail shows a template's *design*: its baseline export converted to PDF by the
configured engine (`convert.py`), then page one rasterised with pdfium. Nothing here
touches template tags or the master resume. The PNG is cached next to its source and
rebuilt only when the source is newer.
"""

from __future__ import annotations

import os
import struct
import tempfile
import zlib
from pathlib import Path

from resume_tailor.document import convert

#: Rendered width in pixels. Cards show it at about half this, so it stays sharp on
#: high-density screens.
WIDTH = 480


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    """Encode 8-bit RGB rows as a PNG (no Pillow needed for one flat image)."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(
            ">I", zlib.crc32(kind + body) & 0xFFFFFFFF
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 on every row
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def pdf_first_page_png(pdf_path: Path, out: Path, *, width: int = WIDTH) -> Path:
    """Rasterise page one of ``pdf_path`` to ``out`` (PNG, ``width`` pixels wide)."""
    import pypdfium2 as pdfium  # imported lazily: only the gallery needs it

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if len(doc) == 0:
            raise ValueError(f"{pdf_path.name} has no pages")
        page = doc[0]
        bitmap = page.render(
            scale=width / page.get_width(), rev_byteorder=True, fill_color=(255, 255, 255, 255)
        )
        channels = bitmap.n_channels
        buffer = bytes(bitmap.buffer)
        rows = []
        for y in range(bitmap.height):
            line = buffer[y * bitmap.stride : y * bitmap.stride + bitmap.width * channels]
            if channels == 4:  # RGBx: drop the padding byte
                line = b"".join(line[i : i + 3] for i in range(0, len(line), 4))
            rows.append(line)
        tmp = out.with_suffix(".tmp.png")
        tmp.write_bytes(_png(bitmap.width, bitmap.height, rows))
        os.replace(tmp, out)
    finally:
        doc.close()
    return out


def docx_thumbnail(docx_path: Path, out: Path, *, width: int = WIDTH) -> Path:
    """Cached PNG of page one of ``docx_path``; raises `RuntimeError` with no PDF engine."""
    if not docx_path.exists():
        raise FileNotFoundError(docx_path)
    if out.exists() and out.stat().st_mtime >= docx_path.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rt_thumb_") as tmp:
        pdf = Path(tmp) / "page.pdf"
        convert.convert(docx_path, pdf)
        return pdf_first_page_png(pdf, out, width=width)
