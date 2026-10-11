"""The font families installed where PDFs are made, for Quick adjustments' font box.

Fonts are listed from this machine, never the browser's: Word (or LibreOffice) draws the
PDF here, and a font only the browser has would print as a substitute and throw off
page fit. Windows reads the registered font files, macOS scans its font folders, and
Linux/Docker asks fontconfig. Each file's family is read from its OpenType `name` table
(name ID 1: the name Word's font box and `w:rFonts` use). No dependencies, no LLM.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

#: The fonts the box offers first, when installed (the old fixed list).
COMMON = ("Arial", "Calibri", "Cambria", "Garamond", "Georgia", "Helvetica",
          "Times New Roman", "Verdana")  # fmt: skip
_FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
_cache: dict[tuple, list[str]] = {}


def _decode(platform: int, raw: bytes) -> str | None:
    try:
        return raw.decode("utf-16-be") if platform in (0, 3) else raw.decode("mac_roman")
    except UnicodeDecodeError:
        return None


def _read(handle, offset: int, size: int) -> bytes:
    handle.seek(offset)
    data = handle.read(size)
    if len(data) < size:
        raise struct.error("truncated font file")
    return data


def _family_at(handle, offset: int) -> str | None:
    """Name ID 1 of the font whose table directory starts at `offset`. Reads only the
    directory and the `name` table, never the glyphs (some fonts run to tens of MB)."""
    (num_tables,) = struct.unpack(">H", _read(handle, offset + 4, 2))
    directory = _read(handle, offset + 12, 16 * num_tables)
    for i in range(num_tables):
        tag, _sum, table, length = struct.unpack_from(">4sIII", directory, 16 * i)
        if tag != b"name":
            continue
        data = _read(handle, table, length)
        _fmt, count, strings = struct.unpack_from(">HHH", data, 0)
        best: tuple[int, str] | None = None
        for r in range(count):
            platform, _enc, lang, name_id, size, off = struct.unpack_from(
                ">HHHHHH", data, 6 + 12 * r
            )
            if name_id != 1:
                continue
            text = _decode(platform, data[strings + off : strings + off + size])
            if not text:
                continue
            # English Windows names first, then any Windows name, then Mac Roman.
            rank = 0 if (platform, lang) == (3, 0x409) else 1 if platform == 3 else 2
            if best is None or rank < best[0]:
                best = (rank, text.strip())
        return best[1] if best else None
    return None


def families_in(path: Path) -> list[str]:
    """Every family name in one font file (a collection holds several)."""
    try:
        with path.open("rb") as handle:
            if _read(handle, 0, 4) == b"ttcf":
                (count,) = struct.unpack(">I", _read(handle, 8, 4))
                offsets = struct.unpack(f">{count}I", _read(handle, 12, 4 * count))
            else:
                offsets = (0,)
            names = [_family_at(handle, o) for o in offsets]
    except (OSError, struct.error, IndexError):
        return []
    return [n for n in names if n and not n.startswith("@")]


def _windows_files() -> list[Path]:
    import winreg  # noqa: PLC0415

    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    files: list[Path] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key) as handle:
                for i in range(winreg.QueryInfoKey(handle)[1]):
                    _name, value, _type = winreg.EnumValue(handle, i)
                    path = Path(value)
                    files.append(path if path.is_absolute() else windir / path)
        except OSError:
            continue
    return files


def _mac_files() -> list[Path]:
    roots = [Path("/System/Library/Fonts"), Path("/Library/Fonts"),
             Path.home() / "Library" / "Fonts"]  # fmt: skip
    return [p for root in roots if root.is_dir() for p in root.rglob("*")]


def _fontconfig() -> list[str]:
    if shutil.which("fc-list") is None:
        return []
    try:
        out = subprocess.run(
            ["fc-list", ":", "family"], capture_output=True, text=True, timeout=20, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split(",")[0].strip() for line in out.splitlines() if line.strip()]


def _stamp() -> tuple:
    """Changes when fonts are installed or removed (the cache key)."""
    if sys.platform == "win32":
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    elif sys.platform == "darwin":
        dirs = [Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]
    stamps = []
    for d in dirs:
        try:
            stamps.append((str(d), d.stat().st_mtime_ns))
        except OSError:
            stamps.append((str(d), None))
    return (sys.platform, *stamps)


def installed() -> list[str]:
    """Every installed family, sorted case-insensitively (cached until fonts change)."""
    key = _stamp()
    if key in _cache:
        return _cache[key]
    if sys.platform == "win32":
        names = [n for f in _windows_files() for n in families_in(f)]
    elif sys.platform == "darwin":
        names = [n for f in _mac_files() if f.suffix.lower() in _FONT_SUFFIXES
                 for n in families_in(f)]  # fmt: skip
    else:
        names = _fontconfig()
    found = sorted(set(names), key=str.casefold)
    _cache.clear()
    _cache[key] = found
    return found


def common(families: list[str]) -> list[str]:
    """`COMMON`, kept to the ones installed (all of it when nothing could be listed)."""
    if not families:
        return list(COMMON)
    have = {f.casefold() for f in families}
    return [f for f in COMMON if f.casefold() in have]
