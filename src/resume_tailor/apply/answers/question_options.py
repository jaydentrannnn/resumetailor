"""Choice lists that say a profile fact in their own shape: a graduation term
("Spring 2027"), a GPA range ("3.5 - 3.79"), a class standing ("Junior") or a class year
("2027").

Each picker returns the one option the fact fits, or None when none or several do (a June
graduation fits both "Spring 2027" and "Summer 2027"; a 3.6 GPA fits both "3.0+" and
"3.5+"), so an unclear list is left for the applicant. Pure: no page, no model.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_YEAR = re.compile(r"\b(20\d{2}|19\d{2})\b")

#: The months a term can name. Spring and summer share June; fall and winter share
#: December: a graduation in either month fits both, so a list offering both is unclear.
_TERMS = {
    "winter": {12, 1, 2},
    "spring": {3, 4, 5, 6},
    "summer": {6, 7, 8},
    "fall": {9, 10, 11, 12},
    "autumn": {9, 10, 11, 12},
}
_TERM = re.compile(r"\b(" + "|".join(_TERMS) + r")\b", re.I)


def _term_year(option: str) -> tuple[str, int] | None:
    term, year = _TERM.search(option), _YEAR.search(option)
    if not term or not year:
        return None
    return term.group(1).casefold(), int(year.group(1))


def term_options(options: Sequence[str]) -> bool:
    """Whether the options are academic terms with years ("Spring 2027", "Fall 2027")."""
    return sum(1 for option in options if _term_year(option)) >= 2


def term_option(options: Sequence[str], year: int, month: int) -> str | None:
    """The one "<term> <year>" option a ``year``/``month`` date falls in."""
    fits = []
    for option in options:
        parsed = _term_year(option)
        if parsed and parsed[1] == year and month in _TERMS[parsed[0]]:
            fits.append(option)
    return fits[0] if len(fits) == 1 else None


_NUMBER = r"(\d(?:\.\d{1,2})?)"
_GPA_BETWEEN = re.compile(rf"^\D*{_NUMBER}\s*(?:-|–|—|to)\s*{_NUMBER}\D*$")
_GPA_ABOVE = re.compile(
    rf"^\D*{_NUMBER}\s*(?:\+|or\s+(?:above|higher|greater|more)|and\s+(?:above|higher|up))\D*$"
    rf"|^\s*(?:at\s+least|minimum(?:\s+of)?|no\s+less\s+than)\s+{_NUMBER}\D*$"
    rf"|^\s*(?:above|over|greater\s+than|more\s+than|higher\s+than)\s+{_NUMBER}\D*$",
    re.I,
)
_GPA_BELOW = re.compile(
    rf"^\s*(?:below|under|less\s+than|lower\s+than)\s+{_NUMBER}\D*$"
    rf"|^\D*{_NUMBER}\s+or\s+(?:below|lower|less)\D*$"
    rf"|^\s*(?:at\s+most|up\s+to|no\s+more\s+than|maximum(?:\s+of)?)\s+{_NUMBER}\D*$",
    re.I,
)
#: A GPA scale tops out at 5 (some schools weight to 5.0); a larger number is not a GPA.
_GPA_MAX = 5.0


def _gpa_range(option: str) -> tuple[float, bool, float, bool] | None:
    """(low, low_inclusive, high, high_inclusive) for a GPA range option; None for
    anything else. "3.0+" and "At least 3.0" hold 3.0; "Above 3.0" and "Below 3.0" do
    not."""
    text = option.strip()
    found = _GPA_BETWEEN.match(text)
    if found:
        low, high = float(found.group(1)), float(found.group(2))
        return (low, True, high, True) if low < high <= _GPA_MAX else None
    found = _GPA_ABOVE.match(text)
    if found:
        low = float(found.group(1) or found.group(2) or found.group(3))
        inclusive = found.group(3) is None
        return (low, inclusive, _GPA_MAX, True) if low <= _GPA_MAX else None
    found = _GPA_BELOW.match(text)
    if found:
        high = float(found.group(1) or found.group(2) or found.group(3))
        inclusive = found.group(1) is None
        return (0.0, True, high, inclusive) if high <= _GPA_MAX else None
    return None


def gpa_options(options: Sequence[str]) -> bool:
    """Whether the options are GPA ranges ("Below 3.0", "3.0 - 3.49", "3.5+")."""
    return sum(1 for option in options if _gpa_range(option)) >= 2


def gpa_option(options: Sequence[str], gpa: float) -> str | None:
    """The one range option holding ``gpa`` (a GPA in a gap, or in two ranges: None)."""
    fits = []
    for option in options:
        found = _gpa_range(option)
        if not found:
            continue
        low, low_inclusive, high, high_inclusive = found
        if (low < gpa or (low_inclusive and gpa == low)) and (
            gpa < high or (high_inclusive and gpa == high)
        ):
            fits.append(option)
    return fits[0] if len(fits) == 1 else None


_STANDING = re.compile(r"\b(?:freshman|freshmen|sophomore|junior|senior)\b", re.I)


def standing_options(options: Sequence[str]) -> bool:
    """Whether the options are class standings (Freshman, Sophomore, Junior, Senior)."""
    found = {m.group(0).casefold() for m in map(_STANDING.search, options) if m}
    return len(found) >= 2


def year_options(options: Sequence[str]) -> bool:
    """Whether most options are bare years ("2026", "2027")."""
    named = [option for option in options if option.strip()]
    years = [option for option in named if re.fullmatch(r"\s*(?:19|20)\d{2}\s*", option)]
    return len(years) >= 2 and len(years) >= len(named) - 1
