"""Student and recent-graduate facts from dated education, without a model."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from resume_tailor.content import dates


def bounds(value: str) -> tuple[date, date] | None:
    parsed = dates.parse(value)
    if parsed is None or parsed[1] is None:
        return None
    year, month, day = parsed
    if day is not None:
        exact = date(year, month, day)
        return exact, exact
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def facts(education: list[Any], today: date | None = None) -> dict[str, str]:
    today = today or date.today()
    month_index = today.year * 12 + today.month - 1 - 6
    year, month = divmod(month_index, 12)
    cutoff = date(year, month + 1, min(today.day, calendar.monthrange(year, month + 1)[1]))
    enrolled, recent, unknown = False, False, False
    for entry in education:
        start, end = bounds(entry.start), bounds(entry.end)
        if start is not None and end is not None:
            enrolled |= start[0] <= today <= end[1]
        else:
            unknown = True
        if end is not None:
            recent |= end[0] <= today and end[1] >= cutoff
    return {
        "currently_enrolled": "Yes"
        if enrolled
        else "Unknown"
        if unknown or not education
        else "No",
        "recent_graduate_or_student": "Yes"
        if enrolled or recent
        else "Unknown"
        if unknown or not education
        else "No",
    }
