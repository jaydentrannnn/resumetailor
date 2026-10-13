"""Deterministic, user-selected experience totals from the full resume store.

All chosen dated sections contribute to one union of calendar intervals. The value
stays fractional until a form explicitly requires completed whole years.
"""

from __future__ import annotations

import calendar
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Literal

from resume_tailor.content import dates, edu_dates

BASIS = Literal["experience", "experience_projects", "experience_projects_education", "custom"]
_KINDS = {
    "experience": frozenset({"experience"}),
    "experience_projects": frozenset({"experience", "project"}),
    "experience_projects_education": frozenset({"experience", "project", "education"}),
}
_ONGOING = frozenset({"present", "current", "now", "ongoing", "today"})
_DAYS_PER_YEAR = 365.2425


def _get(value: Any, key: str, default: Any = "") -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _boundary(text: str, *, end: bool = False) -> date | None:
    parsed = dates.parse(text)
    if parsed is None or parsed[1] is None:
        return None
    year, month, day = parsed
    if day is None:
        day = calendar.monthrange(year, month)[1] if end else 1
    return date(year, month, day)


def _span(entry: Any, kind: str, today: date) -> tuple[tuple[date, date] | None, str]:
    """Inclusive source endpoints become an exclusive upper endpoint for unioning."""
    start_text = str(_get(entry, "start") or "").strip()
    end_text = str(_get(entry, "end") or "").strip()
    if kind == "education":
        derived_start, derived_end = edu_dates.months(str(_get(entry, "dates") or ""))
        start_text = start_text or derived_start
        end_text = end_text or derived_end
    start = _boundary(start_text)
    if start is None:
        return None, "Missing or incomplete start date"
    if end_text.casefold() in _ONGOING:
        end = today
    elif not end_text and kind == "project":
        end = _boundary(start_text, end=True)
    else:
        end = _boundary(end_text, end=True)
    if end is None:
        return None, "Missing or incomplete end date"
    # A future ongoing entry has zero accrued time, not a reversed-date error.
    if end < start and end_text.casefold() not in _ONGOING:
        return None, "End date precedes start date"
    upper = min(end, today) + timedelta(days=1)
    return (start, max(start, upper)), ""


def _label(entry: Any, kind: str) -> str:
    if kind == "experience":
        return " — ".join(str(_get(entry, key)) for key in ("title", "company") if _get(entry, key))
    return str(_get(entry, "school" if kind == "education" else "name") or kind.title())


def _union_days(intervals: list[tuple[date, date]]) -> int:
    total = 0
    left: date | None = None
    right: date | None = None
    for start, end in sorted(intervals):
        if left is None or right is None:
            left, right = start, end
        elif start <= right:
            right = max(right, end)
        else:
            total += (right - left).days
            left, right = start, end
    return total + ((right - left).days if left is not None and right is not None else 0)


def calculate(
    resume: Any, basis: BASIS, custom_years: float | None = None, today: date | None = None
) -> dict[str, Any]:
    """Return raw years, calculation date, and selected entries lacking usable dates.

    Null means there is no usable dated evidence (or no valid custom value). Future
    dated evidence is usable but contributes zero. Undated evidence is excluded and
    reported while the remaining subtotal stays available.
    """
    today = today or date.today()
    result: dict[str, Any] = {"years": None, "as_of": today.isoformat(), "excluded_entries": []}
    if basis == "custom":
        if (
            isinstance(custom_years, (int, float))
            and not isinstance(custom_years, bool)
            and math.isfinite(custom_years)
            and custom_years >= 0
        ):
            result["years"] = float(custom_years)
        return result
    if basis not in _KINDS:
        raise ValueError(f"Unknown experience basis: {basis}")
    spans = []
    for section in _get(resume, "sections", []):
        kind = _get(section, "kind")
        if kind not in _KINDS[basis]:
            continue
        for entry in _get(section, "entries", []):
            span, reason = _span(entry, kind, today)
            if span is None:
                result["excluded_entries"].append(
                    {"label": _label(entry, kind), "kind": kind, "reason": reason}
                )
            else:
                spans.append(span)
    if spans:
        result["years"] = _union_days(spans) / _DAYS_PER_YEAR
    return result


def summaries(resume: Any, today: date | None = None) -> dict[str, dict[str, Any]]:
    """All automatic bases, calculated against one common date."""
    today = today or date.today()
    return {basis: calculate(resume, basis, today=today) for basis in _KINDS}


_GENERAL_WORDS = frozenset(
    [
        "how",
        "many",
        "number",
        "total",
        "overall",
        "years",
        "year",
        "of",
        "hands",
        "on",
        "handson",
        "work",
        "working",
        "professional",
        "relevant",
        "practical",
        "actual",
        "experience",
        "experiences",
        "have",
        "has",
        "had",
        "do",
        "did",
        "does",
        "you",
        "your",
        "possess",
        "please",
        "indicate",
        "enter",
        "provide",
        "specify",
        "the",
        "a",
        "an",
        "is",
        "are",
        "what",
        "amount",
        "much",
        "full",
        "time",
        "part",
        "accumulated",
        "paid",
        "employment",
    ]
)


def question_key(text: str) -> str | None:
    """Recognize aggregate years questions; named technologies stay evidence-based."""
    words = re.findall(r"[a-z]+|\d+", text.casefold())
    if not ({"year", "years"} & set(words)) or not ({"experience", "experiences"} & set(words)):
        return None
    return "experience_years" if set(words) <= _GENERAL_WORDS else None


def years_text(years: float, *, integer: bool = False) -> str:
    """Form text: completed years when integral input is required, otherwise decimal."""
    return str(math.floor(years)) if integer else f"{years:.6f}".rstrip("0").rstrip(".")


_NUMBER = r"\d+(?:\.\d+)?"
_YEAR_SUFFIX = r"(?:\s+years?)?(?:\s+(?:of\s+)?experience)?"


def _option_span(label: str) -> tuple[float, float, bool, bool] | None:
    """Lower/upper values and their inclusivity; reject unrelated numbered choices."""
    text = " ".join(label.casefold().replace("–", "-").replace("—", "-").split())
    if text in {"none", "no experience", "no prior experience", "zero years"}:
        return 0, 0, True, True
    if match := re.fullmatch(rf"({_NUMBER}){_YEAR_SUFFIX}", text):
        value = float(match[1])
        return value, value, True, True
    if match := re.fullmatch(
        rf"(?:between\s+)?({_NUMBER})(?:\s+years?)?\s*(?:-|to|and)\s*({_NUMBER}){_YEAR_SUFFIX}",
        text,
    ):
        low, high = float(match[1]), float(match[2])
        return (low, high, True, True) if low <= high else None
    if match := re.fullmatch(
        rf"(?:under|less than|fewer than|below)\s+({_NUMBER}){_YEAR_SUFFIX}", text
    ):
        return 0, float(match[1]), True, False
    if match := re.fullmatch(rf"({_NUMBER})\s*\+{_YEAR_SUFFIX}", text):
        return float(match[1]), math.inf, True, True
    if match := re.fullmatch(
        rf"({_NUMBER})(?:\s+years?)?\s+(?:or more|and above|and over|or above){_YEAR_SUFFIX}", text
    ):
        return float(match[1]), math.inf, True, True
    if match := re.fullmatch(rf"(?:more than|over)\s+({_NUMBER}){_YEAR_SUFFIX}", text):
        return float(match[1]), math.inf, False, True
    return None


def choose_year_option(options: Sequence[str], years: float) -> str | None:
    """Prefer exact numeric choices, then the lowest matching bucket at shared edges."""
    if not math.isfinite(years) or years < 0:
        return None
    candidates = []
    for index, label in enumerate(options):
        span = _option_span(label)
        if span is None:
            continue
        low, high, include_low, include_high = span
        if (years > low or include_low and years == low) and (
            years < high or include_high and years == high
        ):
            candidates.append((low != high, low, high, index, label))
    return min(candidates)[-1] if candidates else None
