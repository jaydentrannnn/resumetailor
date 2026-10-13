"""The printed degree line from structured parts, and the reverse guess.

Pure string work, no model call: `compose` is what a "generated" education entry
prints (`Education.degree_mode`); `detect` pre-fills the structured fields from an
existing typed line when the person asks for it in the editor, never on its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

#: `Education.degree_format` -> the text between the major part and the minor part.
SEPARATORS = {"semicolon": "; ", "comma": ", ", "pipe": " | "}

_MINOR_RE = re.compile(r"\s*(?:[;,|]|\band\b)?\s*\bminors?\s+in\s+(.+)$", re.IGNORECASE)
_IN_RE = re.compile(r"^(.+?)\s+in\s+(.+)$")
#: A leading abbreviation with no "in": "BS Computer Science", "B.A. Economics".
_ABBREV_RE = re.compile(r"^((?:[A-Z]\.?){1,4}[A-Za-z]?\.?)\s+(.+)$")
_SPLIT_RE = re.compile(r"\s*(?:,|&|\band\b)\s*")


def join_names(names: list[str]) -> str:
    """"X", "X and Y", "X, Y and Z"."""
    names = [n.strip() for n in names if n.strip()]
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def compose(
    degree_type: str,
    majors: list[str],
    minors: list[str],
    fmt: str = "semicolon",
    *,
    major_entries: Iterable[Any] | None = None,
) -> str:
    """Combine shared credentials; retain the first display label for each type.

    The positional interface remains valid for legacy callers. Structured entries can
    be model instances or mappings (such as editor JSON).
    """
    separator = SEPARATORS.get(fmt, "; ")
    groups: dict[str, tuple[str, list[str]]] = {}
    entries = major_entries if major_entries is not None else (
        {"name": name, "degree_type": degree_type} for name in (majors or [""])
    )
    for entry in entries:
        kind = str(_entry_value(entry, "degree_type") or "").strip()
        name = str(_entry_value(entry, "name") or "").strip()
        key = _credential_key(kind)
        _label, group_names = groups.setdefault(key, (kind, []))
        if name:
            group_names.append(name)
    clauses: list[str] = []
    for kind, names in groups.values():
        fields = join_names(names)
        clause = f"{kind} in {fields}" if kind and fields else kind or fields
        if clause:
            clauses.append(clause)
    head = separator.join(clauses)
    minor_names = [m for m in minors if m.strip()]
    if not minor_names:
        return head
    minor = f"{'Minors' if len(minor_names) > 1 else 'Minor'} in {join_names(minor_names)}"
    return f"{head}{separator}{minor}" if head else minor


def _entry_value(entry: Any, key: str) -> Any:
    return entry.get(key, "") if isinstance(entry, Mapping) else getattr(entry, key, "")


def _credential_key(label: str) -> str:
    """Match common abbreviations without combining different earned credentials."""
    normalized = re.sub(r"[^a-z0-9]", "", label.casefold())
    aliases = {
        "bsc": "bs",
        "msc": "ms",
        "bachelorofscience": "bs",
        "bachelorscience": "bs",
        "bachelorsdegreeinscience": "bs",
        "bachelorofarts": "ba",
        "bachelorarts": "ba",
        "bachelorsdegreeinarts": "ba",
        "masterofscience": "ms",
        "masterofarts": "ma",
        "associateofscience": "as",
        "associateofarts": "aa",
        "doctorofphilosophy": "phd",
    }
    return aliases.get(normalized, normalized)


def detect(degree: str) -> tuple[str, list[str], list[str]]:
    """Best guess at `(degree_type, majors, minors)` in a typed degree line."""
    text = re.sub(r"\s*\|\s*GPA:.*$", "", degree.strip(), flags=re.IGNORECASE)
    minors: list[str] = []
    minor = _MINOR_RE.search(text)
    if minor:
        minors = _split(minor.group(1))
        text = text[: minor.start()].strip(" ;,|")
    found = _IN_RE.match(text) or _ABBREV_RE.match(text)
    if found:
        return found.group(1).strip(), _split(found.group(2)), minors
    return "", _split(text), minors


def _split(text: str) -> list[str]:
    return [part for part in _SPLIT_RE.split(text.strip(" ;,|.")) if part]
