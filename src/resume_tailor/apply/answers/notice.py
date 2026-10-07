"""Notice period: parse, format and convert between the units a form may ask for.

Deterministic on purpose: the decision layer never lets a model pick a value
(`questions.py`), so "2 weeks" becoming "Less than 1 month" or "14" is plain arithmetic.
"""

from __future__ import annotations

import re

UNITS: tuple[str, ...] = ("day", "week", "month")
_DAYS = {"day": 1, "week": 7, "month": 30}
_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
}  # fmt: skip
_NOW = re.compile(r"\b(immediate(ly)?|none|no notice|zero|asap|right away)\b", re.I)
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?|" + "|".join(_WORDS) + r")\s*[- ]?\s*(day|week|wk|month|mo)s?\b", re.I)


def _unit(word: str) -> str:
    word = word.lower()
    return "week" if word in {"week", "wk"} else "month" if word in {"month", "mo"} else "day"


def _number(text: str) -> float:
    return float(_WORDS[text.lower()]) if text.lower() in _WORDS else float(text)


def parse(text: str) -> tuple[int, str] | None:
    """``(value, unit)`` a free-text notice period states, else None ("negotiable")."""
    if not text or not text.strip():
        return None
    found = _AMOUNT.search(text)
    if found:
        number = _number(found.group(1))
        return (int(number) if number == int(number) else round(number), _unit(found.group(2)))
    return (0, "day") if _NOW.search(text) else None


def label(value: int | None, unit: str) -> str:
    """Display string ("2 weeks"); blank when there is no value."""
    if value is None:
        return ""
    if value == 0:
        return "Immediately"
    return f"{value} {unit}{'' if value == 1 else 's'}"


def to_days(value: int, unit: str) -> int:
    return value * _DAYS.get(unit, 1)


def for_label(question: str, value: int, unit: str) -> str:
    """The answer to type into a text box, in the unit the question names, else as stated."""
    text = question.casefold()
    for target, pattern in (("day", r"\bdays?\b"), ("week", r"\bweeks?\b"), ("month", r"\bmonths?\b")):
        if re.search(pattern, text):
            days = to_days(value, unit)
            amount = days / _DAYS[target]
            return str(int(amount)) if amount == int(amount) else f"{amount:.1f}".rstrip("0").rstrip(".")
    return label(value, unit)


_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:[-–—]|to)\s*(\d+(?:\.\d+)?)\s*(day|week|wk|month|mo)s?\b", re.I
)
_LESS_EXCL = re.compile(r"\b(less than|under|fewer than|below|<)\s*(\d+(?:\.\d+)?)\s*(day|week|wk|month|mo)s?\b", re.I)
_LESS_INCL = re.compile(
    r"\b(up to|within|at most|maximum|max)\s*(\d+(?:\.\d+)?)\s*(day|week|wk|month|mo)s?\b"
    r"|\b(\d+(?:\.\d+)?)\s*(day|week|wk|month|mo)s?\s*(?:or (?:less|fewer|under))\b",
    re.I,
)
_MORE = re.compile(
    r"\b(more than|over|at least|minimum|min)\s*(\d+(?:\.\d+)?)\s*(day|week|wk|month|mo)s?\b"
    r"|\b(\d+(?:\.\d+)?)\s*(day|week|wk|month|mo)s?\s*(?:\+|or (?:more|longer|greater))"
    r"|\b(\d+(?:\.\d+)?)\s*\+\s*(day|week|wk|month|mo)s?\b",
    re.I,
)


def option_range(option: str) -> tuple[float, float] | None:
    """Inclusive ``(low, high)`` days an option stands for; ``inf`` for open-ended."""
    text = option.strip()
    if not text:
        return None
    if _NOW.search(text) and not _AMOUNT.search(text):
        return 0.0, 0.0
    found = _RANGE.search(text)
    if found:
        scale = _DAYS[_unit(found.group(3))]
        return float(found.group(1)) * scale, float(found.group(2)) * scale
    found = _LESS_EXCL.search(text)
    if found:
        return 0.0, float(found.group(2)) * _DAYS[_unit(found.group(3))] - 1
    found = _LESS_INCL.search(text)
    if found:
        number, word = (found.group(2), found.group(3)) if found.group(2) else (found.group(4), found.group(5))
        return 0.0, float(number) * _DAYS[_unit(word)]
    found = _MORE.search(text)
    if found:
        if found.group(2):
            number, word = found.group(2), found.group(3)
        elif found.group(4):
            number, word = found.group(4), found.group(5)
        else:
            number, word = found.group(6), found.group(7)
        low = float(number) * _DAYS[_unit(word)]
        return (low + 1 if found.group(1) and found.group(1).lower() in {"more than", "over"} else low), float("inf")
    exact = _AMOUNT.search(text)
    if exact and exact.group(0).strip().casefold() == text.casefold().strip(" ."):
        days = _number(exact.group(1)) * _DAYS[_unit(exact.group(2))]
        return days, days
    return None


def pick_option(options: list[str], value: int, unit: str) -> int | None:
    """Index of the option whose range holds the notice; the narrowest range wins.

    An exact "2 weeks" option beats "1-3 weeks"; two equally narrow candidates are a tie
    (None), left for review rather than guessed.
    """
    days = float(to_days(value, unit))
    fits: list[tuple[float, float, int]] = []
    for index, option in enumerate(options):
        span = option_range(option)
        if span and span[0] <= days <= span[1]:
            # Open-ended ranges tie on width; the one starting latest is the tighter fit.
            fits.append((span[1] - span[0], -span[0], index))
    if not fits:
        return None
    fits.sort()
    if len(fits) > 1 and fits[0][:2] == fits[1][:2]:
        return None
    return fits[0][2]
