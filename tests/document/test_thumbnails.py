"""Template gallery thumbnails: pdfium rasterising and the mtime cache (no PDF engine)."""

from __future__ import annotations

import os
import struct
import zlib

from pypdf import PdfWriter

from resume_tailor.document import thumbnails


def _blank_pdf(path, width=612, height=792):
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_first_page_png_is_a_valid_scaled_png(tmp_path):
    out = thumbnails.pdf_first_page_png(_blank_pdf(tmp_path / "a.pdf"), tmp_path / "a.png", width=200)
    data = out.read_bytes()
    width, height = _png_size(data)
    assert width == 200 and height == round(200 * 792 / 612)
    # The IDAT stream decodes to one filter byte plus RGB per pixel, per row.
    idat_len = struct.unpack(">I", data[33:37])[0]
    raw = zlib.decompress(data[41 : 41 + idat_len])
    assert len(raw) == height * (1 + width * 3)
    assert raw[1:4] == b"\xff\xff\xff"  # a blank page renders white


def test_docx_thumbnail_converts_once_until_the_source_changes(tmp_path, monkeypatch):
    calls = []

    def fake_convert(docx_path, pdf_path, **_):
        calls.append(docx_path)
        return _blank_pdf(pdf_path)

    monkeypatch.setattr(thumbnails.convert, "convert", fake_convert)
    source = tmp_path / "baseline.docx"
    source.write_bytes(b"docx")
    out = tmp_path / "thumb.png"
    thumbnails.docx_thumbnail(source, out)
    thumbnails.docx_thumbnail(source, out)
    assert len(calls) == 1
    later = out.stat().st_mtime + 10
    os.utime(source, (later, later))
    thumbnails.docx_thumbnail(source, out)
    assert len(calls) == 2
