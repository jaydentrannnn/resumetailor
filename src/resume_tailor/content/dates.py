"""Date values the profile and resume store: ``YYYY-MM-DD``, ``YYYY-MM``, ``YYYY``.

Everything the user types or an older file held ("June 14, 2027", "6/14/2027", "Jun 2027")
is read into those shapes; text that names no date ("ASAP", "Present") is passed through
untouched, so a hand-written value is never lost or invented.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

Precision = Literal["day", "month", "year"]

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)  # fmt: skip
_BY_NAME = {name.casefold(): index for index, name in enumerate(MONTH_NAMES, start=1)}
_BY_NAME.update({name[:3].casefold(): index for index, name in enumerate(MONTH_NAMES, start=1)})
_BY_NAME["sept"] = 9

_ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
_US_DAY = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$")
_US_MONTH = re.compile(r"^(\d{1,2})[/.](\d{4})$")
_WORD_DAY = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
_WORD_MONTH = re.compile(r"^([A-Za-z]{3,9})\.?,?\s+(\d{4})$")
_YEAR = re.compile(r"^(\d{4})$")


def parse(text: str) -> tuple[int, int | None, int | None] | None:
    """``(year, month, day)`` the text states (month/day None when absent), else None."""
    value = text.strip()
    month_of = lambda word: _BY_NAME.get(word.casefold())  # noqa: E731
    candidates: list[tuple[int, int | None, int | None]] = []
    if m := _ISO_DAY.match(value):
        candidates.append((int(m[1]), int(m[2]), int(m[3])))
    elif m := _ISO_MONTH.match(value):
        candidates.append((int(m[1]), int(m[2]), None))
    elif m := _US_DAY.match(value):
        candidates.append((int(m[3]), int(m[1]), int(m[2])))
    elif m := _US_MONTH.match(value):
        candidates.append((int(m[2]), int(m[1]), None))
    elif (m := _WORD_DAY.match(value)) and month_of(m[1]):
        candidates.append((int(m[3]), month_of(m[1]), int(m[2])))
    elif (m := _WORD_MONTH.match(value)) and month_of(m[1]):
        candidates.append((int(m[2]), month_of(m[1]), None))
    elif m := _YEAR.match(value):
        candidates.append((int(m[1]), None, None))
    if not candidates:
        return None
    year, month, day = candidates[0]
    if not 1950 <= year <= 2100 or (month is not None and not 1 <= month <= 12):
        return None
    if day is not None:
        try:
            date(year, month or 1, day)
        except ValueError:
            return None
    return year, month, day


def format_iso(year: int, month: int | None, day: int | None, precision: Precision) -> str:
    """The stored string at ``precision``; never invents a part the source lacked."""
    if precision == "year" or month is None:
        return f"{year:04d}"
    if precision == "month" or day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def normalize(text: str, precision: Precision = "month") -> str:
    """Read ``text`` into ``precision`` ("2027-06-14" for "June 14, 2027"), else unchanged."""
    parsed = parse(text)
    return text if parsed is None else format_iso(*parsed, precision)


_ONGOING = re.compile(r"^(present|current|now|ongoing|today)$", re.IGNORECASE)
_SPAN_SPLIT = re.compile(r"\s*[–—]\s*|\s+-\s+|(?<=\d)-(?=[A-Za-z])")


def read_span(text: str) -> tuple[str, str] | None:
    """``("2025-03", "2025-05")`` for "Mar 2025 - May 2025"; ``("2025-03", "")`` for one date.

    ``Present`` (and "current", "ongoing") reads as ``"Present"``. None when any part is
    not a date, so free text such as "Spring 2025" is left for the caller to keep as written.
    """
    value = text.strip()
    if not value:
        return None
    if parse(value) is not None:
        return normalize(value, "month"), ""
    parts = _SPAN_SPLIT.split(value)
    if len(parts) != 2:
        return None
    read: list[str] = []
    for part in parts:
        part = part.strip()
        if _ONGOING.match(part):
            read.append("Present")
        elif parse(part) is not None:
            read.append(normalize(part, "month"))
        else:
            return None
    return read[0], read[1]


def month_name(month: int) -> str:
    """``6`` -> "June"."""
    return MONTH_NAMES[month - 1]


def display(text: str) -> str:
    """Readable form of a stored date ("2027-06-14" -> "June 14, 2027"), else unchanged."""
    parsed = parse(text)
    if parsed is None:
        return text
    year, month, day = parsed
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{month_name(month)} {year:04d}"
    return f"{month_name(month)} {day}, {year:04d}"
