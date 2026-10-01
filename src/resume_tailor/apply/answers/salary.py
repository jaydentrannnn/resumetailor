"""Deterministic salary answers for application forms — pure, no LLM.

The applicant's range lives on ``ApplicantProfile`` (hourly and yearly min/max). A
posting's stated pay comes from the listing's salary column or the saved JD text. The
answer is ``min(posted top, applicant top)`` in the posting's unit: below the range it is
the posting's top, overlapping it is the highest number both allow, above it is the
applicant's own top. With no stated pay the applicant's top is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Unit = Literal["hour", "year"]

#: Full-time hours in a year, for hourly ↔ yearly conversion.
HOURS_PER_YEAR = 2080

_AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?"
#: "$18 - $20", "$18 to $20", and "Minimum $18.00 - Maximum $20.00" (Excellus).
_DASH = r"\s*(?:-|–|—|to)\s*(?:(?:maximum|max\.?|up to)\s*:?\s*)?"
_RANGE = re.compile(r"\$\s?" + _AMOUNT + r"(?:\s?USD)?" + _DASH + r"\$?\s?" + _AMOUNT, re.I)
_SINGLE = re.compile(r"\$\s?" + _AMOUNT)
_HOUR = re.compile(r"/\s?(?:hr|hour)\b|\bper hour\b|\bhourly\b|\ban hour\b|\bph\b", re.I)
_YEAR = re.compile(r"/\s?(?:yr|year)\b|\bper (?:year|annum)\b|\bannual(?:ly)?\b|\byearly\b|\ba year\b", re.I)
_SCALE = re.compile(r"^\s?(?:million|billion|m\b|b\b|bn\b)", re.I)
_EARLY_CAREER = re.compile(r"\bintern(?:ship)?s?\b|\bco-?op\b|\bapprentice", re.I)


@dataclass(frozen=True)
class Pay:
    """One stated pay figure or range in a single unit."""

    low: float
    high: float
    unit: Unit


def _number(digits: str, k: str | None) -> float:
    value = float(digits.replace(",", ""))
    return value * 1000 if k else value


def _unit(text: str, start: int, end: int, high: float) -> Unit | None:
    after = text[end : end + 40]
    before = text[max(0, start - 40) : start]
    for window in (after, before):
        hour, year = _HOUR.search(window), _YEAR.search(window)
        if hour and (not year or hour.start() < year.start()):
            return "hour"
        if year:
            return "year"
    if 7 <= high <= 300:
        return "hour"
    if 15_000 <= high <= 1_000_000:
        return "year"
    return None


def parse_pay(text: str) -> list[Pay]:
    """Every dollar pay figure in ``text`` with a known unit, in order of appearance."""
    found: list[tuple[int, Pay]] = []
    taken: list[tuple[int, int]] = []
    for match in _RANGE.finditer(text):
        if _SCALE.match(text[match.end() :]):
            continue
        low = _number(match.group(1), match.group(2))
        high = _number(match.group(3), match.group(4))
        if match.group(4) and not match.group(2) and low < 1000:
            low *= 1000  # "$60-80k"
        if high < low:
            low, high = high, low
        unit = _unit(text, match.start(), match.end(), high)
        if unit:
            found.append((match.start(), Pay(low, high, unit)))
            taken.append(match.span())
    for match in _SINGLE.finditer(text):
        if any(start <= match.start() < end for start, end in taken):
            continue
        if _SCALE.match(text[match.end() :]):
            continue
        value = _number(match.group(1), match.group(2))
        unit = _unit(text, match.start(), match.end(), value)
        if unit:
            found.append((match.start(), Pay(value, value, unit)))
    return [pay for _pos, pay in sorted(found, key=lambda item: item[0])]


def profile_ranges(text: str) -> dict[Unit, tuple[float, float]]:
    """The first hourly and first yearly range in a free-text salary expectation."""
    ranges: dict[Unit, tuple[float, float]] = {}
    for pay in parse_pay(text):
        ranges.setdefault(pay.unit, (pay.low, pay.high))
    return ranges


def posted_pay(listing_salary: str, jd_text: str) -> Pay | None:
    """The posting's stated pay: the listing column first, else the JD text."""
    for text in (listing_salary or "", jd_text or ""):
        pays = parse_pay(text)
        if pays:
            return pays[0]
    return None


def _convert(value: float, source: Unit, target: Unit) -> float:
    if source == target:
        return value
    return value * HOURS_PER_YEAR if target == "year" else value / HOURS_PER_YEAR


def question_unit(label: str) -> Unit | None:
    """The unit a salary question asks for, when its wording names one."""
    if _HOUR.search(label) or re.search(r"\bhour", label, re.I):
        return "hour"
    if _YEAR.search(label) or re.search(r"\b(?:year|annual)", label, re.I):
        return "year"
    return None


def answer_value(
    unit: Unit,
    posted: Pay | None,
    my_max: dict[Unit, float | None],
) -> float | None:
    """``min(posted top, my top)`` in ``unit``; my top alone with no posted pay."""
    mine = my_max.get(unit)
    if mine is None:
        other: Unit = "year" if unit == "hour" else "hour"
        if my_max.get(other) is None:
            return None
        mine = _convert(float(my_max[other]), other, unit)  # type: ignore[arg-type]
    if posted is None:
        return float(mine)
    return min(_convert(posted.high, posted.unit, unit), float(mine))


def format_value(value: float, unit: Unit, *, numeric: bool) -> str:
    """``"45"`` / ``"80000"`` for number inputs, ``"$45/hour"`` / ``"$80,000/year"`` otherwise."""
    rounded = round(value, 2) if unit == "hour" else round(value)
    number = f"{rounded:.2f}".rstrip("0").rstrip(".") if unit == "hour" else str(int(rounded))
    if numeric:
        return number
    if unit == "hour":
        shown = f"{rounded:,.0f}" if float(rounded).is_integer() else f"{rounded:,.2f}"
    else:
        shown = f"{int(rounded):,}"
    return f"${shown}/{unit}"


def _low_value(unit: Unit, my_min: dict[Unit, float | None], top: float) -> float | None:
    """The applicant's bottom in ``unit`` (converted from the other unit if needed), never above ``top``."""
    mine = my_min.get(unit)
    if mine is None:
        other: Unit = "year" if unit == "hour" else "hour"
        if my_min.get(other) is None:
            return None
        mine = _convert(float(my_min[other]), other, unit)  # type: ignore[arg-type]
    return min(float(mine), top)


def salary_fields(
    *,
    role: str,
    listing_salary: str,
    jd_text: str,
    hourly_max: float | None,
    yearly_max: float | None,
    hourly_min: float | None = None,
    yearly_min: float | None = None,
) -> dict[str, str]:
    """Packet keys for salary questions, or ``{}`` when the applicant set no range.

    ``salary_expectation[_number]`` answer in the default unit (the posting's, else
    hourly for intern/co-op titles and yearly otherwise); ``salary_hourly[_number]`` and
    ``salary_yearly[_number]`` answer a question that names its unit. With a minimum,
    ``<key>_low_number`` is the bottom of the applicant's range in that unit, for a
    question that offers ranges (`pick_range`).
    """
    my_max: dict[Unit, float | None] = {"hour": hourly_max, "year": yearly_max}
    my_min: dict[Unit, float | None] = {"hour": hourly_min, "year": yearly_min}
    posted = posted_pay(listing_salary, jd_text)
    default: Unit = posted.unit if posted else ("hour" if _EARLY_CAREER.search(role or "") else "year")
    fields: dict[str, str] = {}
    for key, unit in (("salary_expectation", default), ("salary_hourly", "hour"), ("salary_yearly", "year")):
        value = answer_value(unit, posted, my_max)  # type: ignore[arg-type]
        if value is None:
            continue
        fields[key] = format_value(value, unit, numeric=False)  # type: ignore[arg-type]
        fields[f"{key}_number"] = format_value(value, unit, numeric=True)  # type: ignore[arg-type]
        low = _low_value(unit, my_min, value)  # type: ignore[arg-type]
        if low is not None:
            fields[f"{key}_low_number"] = format_value(low, unit, numeric=True)  # type: ignore[arg-type]
    return fields


# --- range options ("$60,000 - $79,999", "Less than $40,000", "$100,000+") -------------

_OPTION_NUMBER = re.compile(r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?(?![\w.])")
_OPEN_BELOW = re.compile(r"\b(?:less than|under|below|up to|no more than)\b|<|\bor (?:less|below|under)\b", re.I)
_OPEN_ABOVE = re.compile(
    r"\+|>|\b(?:above|over|more than|greater than|at least)\b|\b(?:or|and) (?:more|above|higher|over|up)\b", re.I,
)
#: "$18 - $20 per hour" / "$60k to $80k": a range question's spec, as `range_spec` writes it.
_SPEC = re.compile(r"^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)/(hour|year)$")


def option_range(label: str) -> tuple[float, float, Unit | None] | None:
    """(low, high, unit) of one range option; open ends are 0 / infinity. None when the
    option names no amount ("Prefer not to say")."""
    found = [(_number(digits, k), bool(k)) for digits, k in _OPTION_NUMBER.findall(label)]
    if not found:
        return None
    if len(found) >= 2:
        (low, low_k), (high, high_k) = found[0], found[1]
        if high_k and not low_k and low < 1000:
            low *= 1000  # "$60-80k"
        low, high = min(low, high), max(low, high)
    elif _OPEN_BELOW.search(label):
        low, high = 0.0, found[0][0]
    elif _OPEN_ABOVE.search(label):
        low, high = found[0][0], float("inf")
    else:
        low = high = found[0][0]
    hour, year = _HOUR.search(label), _YEAR.search(label)
    top = low if high == float("inf") else high
    unit: Unit | None = "hour" if hour and not year else "year" if year and not hour else (
        "hour" if 7 <= top <= 300 else "year" if top >= 15_000 else None
    )
    return low, high, unit


def range_spec(low: float, high: float, unit: Unit) -> str:
    """The applicant's range as one string a select call can carry ("60000-80000/year")."""
    return f"{low:g}-{high:g}/{unit}"


def pick_range(options: list[str], spec: str) -> str | None:
    """The option whose range best covers the applicant's (`range_spec`).

    Most overlap wins; an applicant's single figure counts inside a range that holds it;
    with no overlap the nearest range wins. On a tie the range holding the applicant's
    top wins ($60k-80k against "$60,000 - $70,000" / "$70,000 - $80,000", American
    Century 2026-09: the top is the answer everywhere else), then the first listed. None
    unless at least two options read as ranges, so a dropdown that is not a range list is
    never matched this way.
    """
    parsed = _SPEC.match(spec.strip())
    if not parsed:
        return None
    want_low, want_high, want_unit = float(parsed.group(1)), float(parsed.group(2)), parsed.group(3)
    ranges = [(label, found) for label in options if (found := option_range(label))]
    if len(ranges) < 2:
        return None
    best: tuple[tuple[float, bool], str] | None = None
    for label, (low, high, unit) in ranges:
        target = unit or want_unit
        lo = _convert(want_low, want_unit, target)  # type: ignore[arg-type]
        hi = _convert(want_high, want_unit, target)  # type: ignore[arg-type]
        # Negative when the ranges do not meet: minus the gap to the nearest end.
        score = (min(high, hi) - max(low, lo), low <= hi <= high)
        if best is None or score > best[0]:
            best = (score, label)
    return best[1] if best else None
