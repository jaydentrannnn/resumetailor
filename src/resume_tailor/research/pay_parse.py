"""Pay ranges a posting states, with their currency and pay period. Pure, no LLM.

Separate from `apply/answers/salary.parse_pay`, which answers application forms in
dollars per hour or year and stays as it is. This reader is for benchmarks: it keeps the
currency (USD, CAD, GBP, EUR, AUD) and the period (hour, week, month, year) exactly as
stated, never converts one into another, and keeps the sentence it read each figure from.

It skips figures about something other than base pay (bonuses, equity, relocation or
housing money, funding and revenue, per-mile rates) and figures in millions. A figure
with no period word gets one only when its size leaves no doubt (7 to 300 an hour, 15,000
to 1,000,000 a year); anything else is left out rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Currency = Literal["USD", "CAD", "GBP", "EUR", "AUD"]
Period = Literal["hour", "week", "month", "year"]

#: Characters of context kept around a figure, for the student to check it.
EXCERPT_CHARS = 180

_CODE = r"USD|CAD|GBP|EUR|AUD"
_MARK = r"CA\$|C\$|AU\$|A\$|US\$|\$|£|€"
_DIGITS = r"\d{1,3}(?:\.\d{3})+,\d{2}(?!\d)|\d{1,3}(?:[,.]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"


def _figure(n: str) -> str:
    """A figure with a currency code and/or mark before it; groups prefixed ``n``."""
    return (
        rf"(?:(?P<{n}code>{_CODE})\s?(?P<{n}mark1>{_MARK})?|(?P<{n}mark>{_MARK}))\s?"
        rf"(?P<{n}num>{_DIGITS})\s?(?P<{n}k>[kK](?![a-z]))?"
    )


_UNIT_SUFFIX = r"(?:\s?(?:/|per)\s?(?:hr|hour|yr|year|annum|wk|week|mo|month)\b\.?)?"
_RANGE = re.compile(
    _figure("lo") + rf"(?:\s?(?P<locode2>{_CODE})\b)?" + _UNIT_SUFFIX
    + r"(?:\s*(?:-|–|—|to|and)\s*(?:(?:maximum|max\.?|up to)\s*:?\s*)?"
    + rf"(?:{_figure('hi')}|(?P<bare>{_DIGITS})\s?(?P<barek>[kK](?![a-z]))?))?"
    + rf"(?:\s?(?P<hicode2>{_CODE})\b)?",
    re.I,
)
_PERIODS: tuple[tuple[Period, re.Pattern[str]], ...] = (
    ("hour", re.compile(r"/\s?(?:hr|hour)\b|\bper hour\b|\bhourly\b|\ban hour\b|\bp/?h\b", re.I)),
    ("week", re.compile(r"/\s?(?:wk|week)\b|\bper week\b|\bweekly\b|\ba week\b", re.I)),
    ("month", re.compile(r"/\s?(?:mo|month)\b|\bper month\b|\bmonthly\b|\ba month\b", re.I)),
    ("year", re.compile(
        r"/\s?(?:yr|year)\b|\bper (?:year|annum)\b|\bannual(?:ly)?\b|\byearly\b|\ba year\b|"
        r"\bp\.?a\.?(?!\w)",
        re.I)),
)
#: A figure outside these bounds for its period is a misread, not pay.
_BOUNDS: dict[Period, tuple[float, float]] = {
    "hour": (5, 1_000), "week": (100, 20_000), "month": (300, 100_000),
    "year": (5_000, 5_000_000),
}
#: Words between two single figures that make the second the top of one range
#: ("Compensation Minimum: $25.00 Compensation Maximum: $39.00", "Pay Range - End: $30").
_TOP = re.compile(r"\b(?:max(?:imum)?|end|high(?:est)?|top|upper)\b", re.I)
#: Words just before a figure that make it something other than base pay.
_NOT_PAY = re.compile(
    r"\b(?:bonus(?:es)?|equity|stock|rsus?|sign[- ]?on|signing|relocation|housing|moving|"
    r"travel|commut\w*|reimburs\w*|tuition|401\s?\(?k\)?|referral|revenue|funding|raised|"
    r"valuation|series [a-f]|assets|aum|budget|portfolio|loans?|grants?|scholarships?|"
    r"prizes?|donat\w*|fees?|deposit|discount|credit|gift|allowance|per diem|"
    r"commission|tips?|overtime)\b",
    re.I,
)
_SCALE = re.compile(r"^\s?(?:million|billion|mm?\b|bn?\b)", re.I)
_PER_ITEM = re.compile(r"^\s?(?:/|per)\s?(?:mile|mi|load|unit|piece|lead|sale)\b|^\s?cpm\b", re.I)
_SENTENCE = re.compile(r"[.!?;\n](?=\s|$)")
_LABEL_BREAK = re.compile(r":[ \t]*(?:\r?\n[ \t]*)+")
_MARK_CURRENCY: dict[str, Currency] = {
    "$": "USD", "us$": "USD", "ca$": "CAD", "c$": "CAD", "au$": "AUD", "a$": "AUD",
    "£": "GBP", "€": "EUR",
}


@dataclass(frozen=True)
class PostedRange:
    """One stated pay figure or range (``low == high`` for a single figure)."""

    low: float
    high: float
    currency: Currency
    period: Period
    #: False when the period came from the size of the figure, not a word.
    period_stated: bool
    excerpt: str


def _number(digits: str, k: str | None, currency: Currency) -> float:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", digits) or (
        currency == "EUR" and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", digits)
    ):
        digits = digits.replace(".", "").replace(",", ".")  # "£2.625,00", "€50.000"
    try:
        value = float(digits.replace(",", ""))
    except ValueError:
        return 0.0  # "1.234.567" in dollars: not a figure this reads
    return value * 1000 if k else value


def _currency(match: re.Match[str]) -> Currency:
    for group in ("locode", "locode2", "hicode", "hicode2"):
        if code := match.group(group):
            return code.upper()  # type: ignore[return-value]
    mark = match.group("lomark") or match.group("lomark1")
    return _MARK_CURRENCY[mark.casefold()]


def _clause(text: str, start: int, end: int) -> tuple[int, int]:
    """The bounds of the sentence or line around ``start:end``."""
    before = [m.end() for m in _SENTENCE.finditer(text, 0, start)]
    after = _SENTENCE.search(text, end)
    return (before[-1] if before else 0), (after.start() if after else len(text))


def _period(
    text: str, start: int, figure_end: int, end: int, high: float
) -> tuple[Period, bool] | None:
    """The period worded after the first figure (inside the range too), else before it.

    A worded period the figure cannot be ("$145,000 - $195,000 The compensation range or
    hourly rate...") gives way to the figure's size.
    """
    clause_start, clause_end = _clause(text, start, end)
    after = text[figure_end : min(end + 40, clause_end)]
    before = text[max(clause_start, start - 60) : start]
    for window, nearest in ((after, min), (before, max)):
        hits = [(m.start(), period) for period, pattern in _PERIODS
                if (m := pattern.search(window))]
        if hits:
            period = nearest(hits)[1]
            if _BOUNDS[period][0] <= high <= _BOUNDS[period][1]:
                return period, True
            break
    if 7 <= high <= 300:
        return "hour", False
    if 15_000 <= high <= 1_000_000:
        return "year", False
    return None


def _excerpt(text: str, start: int, end: int) -> str:
    clause_start, clause_end = _clause(text, start, end)
    left = max(clause_start, start - EXCERPT_CHARS // 2)
    right = min(clause_end, end + EXCERPT_CHARS // 2)
    snippet = " ".join(text[left:right].split())
    return ("…" if left > clause_start else "") + snippet + ("…" if right < clause_end else "")


def _bounds(match: re.Match[str], currency: Currency) -> tuple[float, float]:
    low = _number(match.group("lonum"), match.group("lok"), currency)
    if match.group("hinum"):
        digits, k_high = match.group("hinum"), match.group("hik")
    elif match.group("bare"):
        digits, k_high = match.group("bare"), match.group("barek")
    else:
        return low, low
    high = _number(digits, k_high, currency)
    if k_high and not match.group("lok") and low < 1000:
        low *= 1000  # "$60-80k"
    if high < low or high > 4 * low:
        return low, low  # "$50,000 and 401(k)": the second number is not the top
    return low, high


@dataclass
class _Found:
    start: int
    end: int
    low: float
    high: float
    currency: Currency
    period: Period
    stated: bool


def _figures(text: str) -> list[_Found]:
    found: list[_Found] = []
    for match in _RANGE.finditer(text):
        tail = text[match.end() :]
        if _SCALE.match(tail) or _PER_ITEM.match(tail):
            continue
        clause_start, _end = _clause(text, match.start(), match.end())
        if _NOT_PAY.search(text[max(clause_start, match.start() - 50) : match.start()]):
            continue
        currency = _currency(match)
        low, high = _bounds(match, currency)
        figure_end = match.end("lok") if match.group("lok") else match.end("lonum")
        period = _period(text, match.start(), figure_end, match.end(), high)
        if period is None:
            continue
        floor, ceiling = _BOUNDS[period[0]]
        if floor <= low <= high <= ceiling:
            found.append(_Found(match.start(), match.end(), low, high, currency, *period))
    return found


def _pair_min_max(text: str, found: list[_Found]) -> list[_Found]:
    """Join a single minimum and the single maximum stated just after it."""
    joined: list[_Found] = []
    for item in found:
        last = joined[-1] if joined else None
        if (
            last is not None and last.low == last.high and item.low == item.high
            and (last.currency, last.period) == (item.currency, item.period)
            and last.low < item.low <= 4 * last.low
            and item.start - last.end <= 60
            and _TOP.search(text[last.end : item.start])
        ):
            last.high, last.end = item.low, item.end
            continue
        joined.append(item)
    return joined


def posted_ranges(text: str) -> list[PostedRange]:
    """Every base-pay figure or range ``text`` states, once each, in order of appearance."""
    # A label line ("The weekly pay range for this role is:") belongs to the line after it.
    text = _LABEL_BREAK.sub(": ", text or "")
    ranges: list[PostedRange] = []
    seen: set[tuple[float, float, str, str]] = set()
    for item in _pair_min_max(text, _figures(text)):
        key = (item.low, item.high, item.currency, item.period)
        if key not in seen:
            seen.add(key)
            ranges.append(PostedRange(item.low, item.high, item.currency, item.period,
                                      item.stated, _excerpt(text, item.start, item.end)))
    return ranges
