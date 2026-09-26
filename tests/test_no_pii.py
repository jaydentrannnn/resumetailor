"""Guard against personal data creeping back into tracked files.

The deny-list lives in an untracked file (``data/pii_denylist.txt``, one literal per
line) so the guard itself never republishes what it protects. Without that file the
test is skipped — CI on a fresh clone has nothing to check against.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DENYLIST = ROOT / "data" / "pii_denylist.txt"
#: The MIT copyright notice names the owner on purpose. Only its line is exempt, and
#: only in these files; everything else in them is still checked.
_COPYRIGHT_FILES = {"LICENSE", "desktop/src-tauri/tauri.conf.json"}
_COPYRIGHT_LINE = re.compile(r"copyright \(c\) \d{4} ", re.IGNORECASE)


def _checked_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.relative_to(ROOT).as_posix() in _COPYRIGHT_FILES:
        text = "\n".join(line for line in text.splitlines() if not _COPYRIGHT_LINE.search(line))
    return text.casefold()


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [ROOT / name for name in out if not name.endswith((".docx", ".pdf", ".png", ".ttf", ".otf", ".woff2"))]


def test_no_denylisted_strings_in_tracked_files() -> None:
    if not DENYLIST.is_file():
        pytest.skip("no data/pii_denylist.txt on this machine")
    needles = [
        line.strip().casefold()
        for line in DENYLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    hits: list[str] = []
    for path in _tracked_text_files():
        try:
            text = _checked_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        hits.extend(f"{path.relative_to(ROOT)}: {n}" for n in needles if n in text)
    assert not hits, "personal data in tracked files:\n" + "\n".join(hits)


def test_default_cover_style_names_no_candidate() -> None:
    from resume_tailor import coverletter, style

    for text in (style.DEFAULT_COVER_STYLE, coverletter._SYSTEM):
        assert "Goes by" not in text
        assert "Candidate positioning" in text


def test_only_the_copyright_line_is_exempt() -> None:
    license_path = ROOT / "LICENSE"
    checked = _checked_text(license_path)
    assert "copyright (c)" not in checked
    assert "permission is hereby granted" in checked
    readme = ROOT / "README.md"
    assert _checked_text(readme) == readme.read_text(encoding="utf-8").casefold()
