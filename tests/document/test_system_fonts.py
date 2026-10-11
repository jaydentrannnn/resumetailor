"""Reading a font file's family name, and the common-font shortlist."""

from __future__ import annotations

import struct

from resume_tailor.document import system_fonts


def _name_table(names: list[tuple[int, int, int, str]]) -> bytes:
    """A `name` table with (platform, language, name id, text) records."""
    records, strings = b"", b""
    for platform, lang, name_id, text in names:
        raw = text.encode("utf-16-be" if platform == 3 else "mac_roman")
        records += struct.pack(">HHHHHH", platform, 1 if platform == 3 else 0, lang, name_id,
                               len(raw), len(strings))  # fmt: skip
        strings += raw
    return struct.pack(">HHH", 0, len(names), 6 + len(records)) + records + strings


def _font(names, base: int = 0) -> bytes:
    """One sfnt (table directory + name table) laid out as if it started at `base`."""
    table = _name_table(names)
    header = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    directory = struct.pack(">4sIII", b"name", 0, base + 12 + 16, len(table))
    return header + directory + table


def test_reads_the_english_windows_family_first(tmp_path):
    path = tmp_path / "a.ttf"
    path.write_bytes(_font([
        (1, 0, 1, "Mac Name"), (3, 0x40C, 1, "Nom"), (3, 0x409, 1, "Test Sans"),
        (3, 0x409, 2, "Bold"),
    ]))  # fmt: skip
    assert system_fonts.families_in(path) == ["Test Sans"]


def test_reads_every_font_in_a_collection(tmp_path):
    first = _font([(3, 0x409, 1, "One")], base=20)
    second = _font([(3, 0x409, 1, "Two")], base=20 + len(first))
    header = b"ttcf" + struct.pack(">HHI", 1, 0, 2) + struct.pack(">II", 20, 20 + len(first))
    path = tmp_path / "pair.ttc"
    path.write_bytes(header + first + second)
    assert system_fonts.families_in(path) == ["One", "Two"]


def test_unreadable_and_vertical_fonts_are_skipped(tmp_path):
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"\x00\x01\x00\x00\x00")
    vertical = tmp_path / "v.ttf"
    vertical.write_bytes(_font([(3, 0x409, 1, "@MS Gothic")]))
    assert system_fonts.families_in(broken) == []
    assert system_fonts.families_in(vertical) == []


def test_common_keeps_installed_ones_and_falls_back_when_nothing_was_listed():
    assert system_fonts.common(["georgia", "Zapfino", "Arial"]) == ["Arial", "Georgia"]
    assert system_fonts.common([]) == list(system_fonts.COMMON)
