"""Tag suggestions for one bullet: which known skills its text already names.

Pure string matching, no model call. The candidates are the resume's own tag vocabulary
plus every alias and canonical tag in the active vocabulary packs (`config.TAG_ALIASES`),
so "Built DCF models in Excel" suggests `discounted cash flow` and `excel` when the finance
pack is enabled. A suggestion is only ever a tag the student adds with a click; tags are
the fabrication guard's whitelist, so nothing here is applied automatically.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

#: Most suggestions returned for one bullet.
LIMIT = 8


def _pattern(phrase: str) -> re.Pattern[str]:
    # Whole-word-ish: no letter or digit on either side, so "go" never matches "google"
    # while "c++" and "node.js" still match with their punctuation.
    return re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])")


def suggest_tags(
    text: str,
    existing: Iterable[str],
    vocabulary: Iterable[str],
    aliases: Mapping[str, str],
    canonical=lambda raw: raw.strip().lower(),
) -> list[dict[str, str]]:
    """Tags whose name (or an alias of it) appears in ``text`` and isn't tagged yet.

    Returns ``[{"tag", "matched"}]`` in the order the text mentions them. Longer phrases
    win over the shorter phrases inside them ("machine learning" over "learning"). One-
    and two-letter names ("r", "c", "go") only match when written in capitals ("R", "C",
    "GO"), since in lowercase they are ordinary words or fragments.
    """
    lower = text.lower()
    have = {canonical(tag) for tag in existing}
    phrases: dict[str, str] = {}
    for tag in vocabulary:
        key = tag.strip().lower()
        if key:
            phrases.setdefault(key, canonical(tag))
    for alias, target in aliases.items():
        for key in (alias.strip().lower(), target.strip().lower()):
            if key:
                phrases.setdefault(key, canonical(target))
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for phrase in sorted(phrases, key=len, reverse=True):
        tag = phrases[phrase]
        if tag in have or tag in seen:
            continue
        for match in _pattern(phrase).finditer(lower):
            start, end = match.span()
            if len(phrase) <= 2 and text[start:end] != phrase.upper():
                continue
            if any(start < b and a < end for a, b in taken):
                continue
            taken.append((start, end))
            found.append((start, tag, text[start:end]))
            seen.add(tag)
            break
    found.sort()
    return [{"tag": tag, "matched": matched} for _, tag, matched in found[:LIMIT]]
