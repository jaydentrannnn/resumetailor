"""PDF converter strategy — no Word, no LibreOffice required.

Stubs the two backends so the dispatch, error wrapping, and missing-file checks stay
exercised without a rendering engine on the machine running the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor import convert


def test_convert_dispatches_to_named_backend(tmp_path, monkeypatch):
    """Passing backend= selects the implementation; keep_active is forwarded."""
    docx = tmp_path / "in.docx"
    pdf = tmp_path / "out.pdf"
    docx.write_bytes(b"docx")
    seen: dict[str, object] = {}

    def fake_word(src: Path, dst: Path, *, keep_active: bool) -> None:
        seen["src"] = src
        seen["dst"] = dst
        seen["keep_active"] = keep_active
        dst.write_bytes(b"%PDF")

    monkeypatch.setitem(convert._BACKENDS, "word", fake_word)
    result = convert.convert(docx, pdf, keep_active=True, backend="word")

    assert result == pdf
    assert pdf.exists()
    assert seen["keep_active"] is True
    assert seen["src"] == docx


def test_convert_unknown_backend_raises(tmp_path):
    """An unknown backend name fails before any subprocess is launched."""
    docx = tmp_path / "in.docx"
    docx.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="Unknown PDF backend"):
        convert.convert(docx, tmp_path / "out.pdf", backend="ghostscript")


def test_convert_wraps_backend_exceptions(tmp_path, monkeypatch):
    """Any exception from a backend becomes RuntimeError with the engine name."""
    docx = tmp_path / "in.docx"
    docx.write_bytes(b"x")

    def boom(src, dst, *, keep_active):
        raise OSError("COM refused")

    monkeypatch.setitem(convert._BACKENDS, "word", boom)
    with pytest.raises(RuntimeError, match="word could not convert"):
        convert.convert(docx, tmp_path / "out.pdf", backend="word")


def test_convert_requires_produced_file(tmp_path, monkeypatch):
    """A backend that returns without writing is still a failure."""
    docx = tmp_path / "in.docx"
    docx.write_bytes(b"x")

    def silent(src, dst, *, keep_active):
        return None

    monkeypatch.setitem(convert._BACKENDS, "soffice", silent)
    with pytest.raises(RuntimeError, match="was not created"):
        convert.convert(docx, tmp_path / "out.pdf", backend="soffice")


def test_render_to_pdf_delegates(tmp_path, monkeypatch):
    """render.to_pdf is a thin wrapper over convert.convert."""
    from resume_tailor import render

    docx = tmp_path / "tailored.docx"
    docx.write_bytes(b"docx")
    called: list[tuple] = []

    def fake_convert(src, dst, *, keep_active=False, backend=None):
        called.append((src, dst, keep_active))
        dst.write_bytes(b"%PDF")
        return dst

    monkeypatch.setattr(render.convert, "convert", fake_convert)
    out = render.to_pdf(docx, keep_active=True)
    assert out == docx.with_suffix(".pdf")
    assert called == [(docx, out, True)]
