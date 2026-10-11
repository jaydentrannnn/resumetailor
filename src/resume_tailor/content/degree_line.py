"""The printed degree line from structured parts, and the reverse guess.

Pure string work, no model call: `compose` is what a "generated" education entry
prints (`Education.degree_mode`); `detect` pre-fills the structured fields from an
existing typed line when the person asks for it in the editor, never on its own.
"""

from __future__ import annotations

import re

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
    degree_type: str, majors: list[str], minors: list[str], fmt: str = "semicolon"
) -> str:
    """"B.A. in Economics and Math; Minor in Art". Empty parts are left out."""
    kind, fields = degree_type.strip(), join_names(majors)
    head = f"{kind} in {fields}" if kind and fields else kind or fields
    minor_names = [m for m in minors if m.strip()]
    if not minor_names:
        return head
    minor = f"{'Minors' if len(minor_names) > 1 else 'Minor'} in {join_names(minor_names)}"
    return f"{head}{SEPARATORS.get(fmt, '; ')}{minor}" if head else minor


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
