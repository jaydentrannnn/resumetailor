"""Stable chronological order for dated sections; never changes printed dates."""

from __future__ import annotations

import re
from collections.abc import Mapping

from . import dates, edu_dates

_TOKEN = re.compile(
    r"\b(?:present|current|now|ongoing|today)\b"
    r"|\b\d{4}-\d{1,2}(?:-\d{1,2})?(?!\d)"
    r"|\b\d{1,2}[/.]\d{4}\b"
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r"|spring|summer|fall|autumn|winter)\.?,?\s+'?\d{2,4}\b"
    r"|\b\d{4}\b",
    re.IGNORECASE,
)
_ONGOING = re.compile(r"^(present|current|now|ongoing|today)$", re.IGNORECASE)


def _month(token: str, *, end: bool) -> int:
    if _ONGOING.fullmatch(token):
        return 999999
    parsed = dates.parse(token)
    if parsed:
        year, month, _ = parsed
        return year * 12 + (month or 12)
    if not re.match(r"^[A-Za-z]", token):
        return 0
    start, finish = edu_dates.months(f"{token} – {token}")
    value = finish if end else start
    return int(value[:4]) * 12 + int(value[5:]) if value else 0


def _span(text: str) -> tuple[int, int]:
    tokens = [m.group() for m in _TOKEN.finditer(text)]
    if not tokens:
        return 0, 0
    return _month(tokens[0], end=False), _month(tokens[-1], end=True)


def entry_date_key(entry: object) -> tuple[int, int]:
    """(effective end, start), descending; zero is an unknown date."""
    def value(name: str) -> str:
        raw = entry.get(name, "") if isinstance(entry, Mapping) else getattr(entry, name, "")
        return str(raw or "")

    fallback_start, fallback_end = _span(value("dates") or value("date"))
    start = _span(value("start"))[0]
    finish = _span(value("end"))[1]
    # A project with structured dates prints those, ignoring its old free-text date.
    if not value("dates") and (start or finish):
        return finish or start, start
    start = start or fallback_start
    finish = finish or fallback_end or start
    return finish, start


def sort_dated_sections(sections) -> None:
    """Normalize validated sections in place, preserving identities and stable ties."""
    for section in sections:
        if section.kind in {"experience", "project", "education"}:
            section.entries.sort(key=entry_date_key, reverse=True)
