"""Structured start/end months for Education entries (plan P3-E).

The printed `Education.dates` string stays whatever the student wrote ("Expected May
2027", "Fall 2022 – Spring 2026"). Application forms want months, so `months()` reads
a `YYYY-MM` start and end out of it. It returns "" for anything it can't pin to a
month: a bare year, "Present", or free text. That way a month is never invented. The
editor shows the result as month pickers the student can correct.

Seasons map to the month a term usually starts or a class usually graduates. That is a
convention, not a fact from the resume, so it is shown and editable like any other
derived value.
"""

from __future__ import annotations

import re

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip

#: Season → (month when a term starts, month when a class graduates).
_SEASONS = {
    "spring": (1, 5),
    "summer": (6, 8),
    "fall": (9, 12),
    "autumn": (9, 12),
    "winter": (1, 3),
}

_NAMES = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r"|spring|summer|fall|autumn|winter"
)

#: One date on the line, in reading order: ``2022-09``, ``09/2022``, ``Sep 2022``,
#: ``Fall 2022``, ``May '27``, or an open end ("Present").
_TOKEN_RE = re.compile(
    r"(?P<iso>\b\d{4}-\d{1,2})(?!\d)"
    r"|(?P<numeric>\b\d{1,2}\s*[/.]\s*\d{4})\b"
    r"|(?P<word>\b(?:" + _NAMES + r")\.?,?\s+'?\d{2,4})\b"
    r"|(?P<open>\b(?:present|current|now|ongoing)\b)",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"^([A-Za-z]+)\.?,?\s+'?(\d{4}|\d{2})$")
_NUMERIC_RE = re.compile(r"^(\d{1,2})\s*[/.]\s*(\d{4})$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _year(text: str) -> int | None:
    value = int(text)
    if len(text) == 2:
        value += 2000
    return value if 1950 <= value <= 2100 else None


def _month(part: str, *, end: bool) -> str:
    """One side of a range as ``YYYY-MM``, or "" when it isn't a month."""
    part = part.strip().strip(",")
    if not part:
        return ""
    if m := _ISO_RE.match(part):
        month = int(m.group(2))
        return f"{m.group(1)}-{month:02d}" if 1 <= month <= 12 else ""
    if m := _NUMERIC_RE.match(part):
        month = int(m.group(1))
        year = _year(m.group(2))
        return f"{year}-{month:02d}" if year and 1 <= month <= 12 else ""
    if m := _WORD_RE.match(part):
        word = m.group(1).lower()
        year = _year(m.group(2))
        if year is None:
            return ""
        if word in _SEASONS:
            return f"{year}-{_SEASONS[word][1 if end else 0]:02d}"
        month = _MONTHS.get(word[:3])
        return f"{year}-{month:02d}" if month else ""
    return ""


def months(dates: str) -> tuple[str, str]:
    """``(start, end)`` as ``YYYY-MM`` strings ("" where the text gives no month).

    Dates are read in order: two give a start and an end, one is the graduation (end)
    date. On an education line a single date almost always is ("May 2027", "Expected
    June 2027"). Bare years and other words ("Class of 2027") are not dates here.
    """
    tokens = []
    for match in _TOKEN_RE.finditer(dates or ""):
        if match.lastgroup == "open":
            tokens.append("")
            continue
        tokens.append(match.group(0))
    if len(tokens) >= 2:
        return _month(tokens[0], end=False), _month(tokens[1], end=True)
    if tokens:
        return "", _month(tokens[0], end=True)
    return "", ""


def fill(education) -> None:
    """Set an entry's empty ``start``/``end`` from its printed ``dates`` (in place)."""
    start, end = months(education.dates)
    if not education.start and start:
        education.start = start
    if not education.end and end:
        education.end = end
