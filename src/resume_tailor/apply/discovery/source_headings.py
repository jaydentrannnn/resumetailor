"""Markdown heading ranges in a README (deterministic)."""

from __future__ import annotations

import re


def _normalize_heading_name(raw: str) -> str:
    """Strip emoji / shortcodes and keep word characters for section matching."""
    cleaned = re.sub(r":[a-z_]+:", "", raw)
    return re.sub(r"[^\w,&\s]", "", cleaned).strip()

#: ``## Heading`` through ``#### Heading``.
_MD_HEADING_RE = re.compile(r"^(#{2,4})\s+(.*)$")

#: A collapsible section title, e.g. zapplyjobs'
#: ``<summary><h3>💻 <strong>SWE</strong></h3></summary>``.
_SUMMARY_HEADING_RE = re.compile(r"<summary>\s*<h([2-4])[^>]*>(.*?)</h\1>", re.IGNORECASE)

def _heading(line: str) -> tuple[int, str] | None:
    """``(level, cleaned_name)`` when ``line`` is a section heading, else None."""
    match = _MD_HEADING_RE.match(line)
    if match:
        level, raw = len(match.group(1)), match.group(2)
    else:
        match = _SUMMARY_HEADING_RE.search(line)
        if not match:
            return None
        level, raw = int(match.group(1)), re.sub(r"<[^>]+>", "", match.group(2))
    name = _normalize_heading_name(raw)
    return (level, name) if name else None

def list_sections(text: str) -> list[tuple[int, str]]:
    """Return ``(heading_level, cleaned_name)`` for every ``##``–``####`` header.

    A ``<summary><h3>…</h3></summary>`` title counts as a heading of that level.
    """
    return [found for line in text.splitlines() if (found := _heading(line))]

def _depth_sections(lines: list[str]) -> list[tuple[int, str, int, int]]:
    """Build ``(level, name, start, end)`` ranges for depth-aware headers."""
    headers: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        found = _heading(line)
        if found:
            headers.append((found[0], found[1], index))
    ranges: list[tuple[int, str, int, int]] = []
    for index, (level, name, start) in enumerate(headers):
        end = len(lines)
        for later_level, _later_name, later_start in headers[index + 1 :]:
            if later_level <= level:
                end = later_start
                break
        ranges.append((level, name, start, end))
    return ranges
