"""Every `CLAUDE.md` has a byte-identical `AGENTS.md` beside it (see the root CLAUDE.md)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parents[2]
_SKIP = {".git", ".venv", "node_modules", "__pycache__", "dist", "build", "output", "data"}


def _claude_files() -> list[Path]:
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
        if "CLAUDE.md" in files:
            found.append(Path(folder) / "CLAUDE.md")
    return found


def test_every_claude_md_has_an_identical_agents_md():
    claude_files = _claude_files()
    assert ROOT / "CLAUDE.md" in claude_files
    drift = []
    for claude in claude_files:
        agents = claude.with_name("AGENTS.md")
        rel = claude.parent.relative_to(ROOT)
        if not agents.is_file():
            drift.append(f"{rel}: AGENTS.md missing")
        elif agents.read_bytes() != claude.read_bytes():
            drift.append(f"{rel}: AGENTS.md differs from CLAUDE.md")
    assert not drift, "Edit CLAUDE.md and AGENTS.md together:\n" + "\n".join(drift)
