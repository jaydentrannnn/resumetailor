"""Bachelor-only eligibility prefilter — pure regex, no LLM.

Hard-rejects postings that require a graduate degree without naming a
bachelor's alternative, senior titles, and high year floors. Ambiguous
signals become flags rather than silent drops.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class EligibilitySettings(BaseModel):
    """Tunable thresholds and extra block patterns for ``check_*``."""

    hard_reject_years: int = 4
    flag_years: int = 2
    extra_title_block: list[str] = Field(default_factory=list)
    extra_text_block: list[str] = Field(default_factory=list)


class Eligibility(BaseModel):
    """Outcome of a title or JD-text eligibility check."""

    passed: bool
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


_ADVANCED = re.compile(
    r"\b("
    r"ph\.?\s?d\.?"
    r"|doctora(?:l|te)"
    r"|dphil"
    r"|master(?:'s|s)?(?:\s+degree)?"
    r"|m\.?s\.?(?!\s*(?:office|word|excel|sql|teams|azure|windows|dynamics))"
    r"(?=[\s,/)\.]|$)"
    r"|m\.?eng\b"
    r"|mba"
    r"|graduate\s+(?:student|degree|program)"
    r"|post-?doc(?:toral)?"
    r")\b",
    re.I,
)

_BACHELOR = re.compile(
    r"\b("
    r"bachelor(?:'s|s)?"
    r"|b\.?s\.?(?=[\s,/)\.]|$)"
    r"|b\.?a\.?(?=[\s,/)\.]|$)"
    r"|b\.?eng\b"
    r"|b\.?sc\b"
    r"|undergrad(?:uate)?s?"
    r"|or\s+equivalent(?:\s+experience)?"
    r")\b",
    re.I,
)

_TITLE_HARD = re.compile(
    r"\b("
    r"ph\.?\s?d"
    r"|doctoral"
    r"|dphil"
    r"|post-?doc"
    r"|mba"
    r"|master(?:'s|s)?\s+(?:intern|student|program)"
    r"|graduate\s+(?:student\s+)?researcher"
    r")\b",
    re.I,
)

_TITLE_SENIOR = re.compile(
    r"\b("
    r"senior|sr\.?"
    r"|staff|principal|lead|manager|director"
    r"|head\s+of|vp|vice\s+president|architect"
    r")\b",
    re.I,
)

_TITLE_LEVEL_FLAG = re.compile(r"\b(II|III|IV|L[3-9]|E[3-9])\b")

_YEARS = re.compile(
    r"(?<!\d)(\d{1,2})(?!\d)\s*\+?\s*(?:-|–|to)?\s*(?<!\d)(\d{1,2})?(?!\d)\s*\+?\s*"
    r"(?:years?|yrs?)\b(?:\s+of)?",
    re.I,
)

_YEARS_SOFT = re.compile(
    r"intern|internship|new grad|entry|student",
    re.I,
)

_RETURN_INTERN = re.compile(
    r"previous(?:ly)?\s+intern|returning\s+intern|return\s+offer",
    re.I,
)


def has_advanced_degree_requirement(text: str) -> bool:
    """True when the text mentions a master's/PhD-level degree requirement."""
    return _ADVANCED.search(text) is not None


def has_bachelor_alternative(text: str) -> bool:
    """True when the text also names a bachelor's / undergraduate path."""
    return _BACHELOR.search(text) is not None


def min_required_years(text: str) -> int | None:
    """Smallest year floor found, ignoring soft/intern/preferred contexts."""
    best: int | None = None
    for match in _YEARS.finditer(text):
        start, end = match.span()
        window = text[max(0, start - 60) : min(len(text), end + 60)]
        if _YEARS_SOFT.search(window):
            continue
        value = int(match.group(1))
        if best is None or value < best:
            best = value
    return best


def check_title(
    role: str,
    settings: EligibilitySettings | None = None,
) -> Eligibility:
    """Hard-reject advanced-degree / senior titles; flag level tokens."""
    settings = settings or EligibilitySettings()
    reasons: list[str] = []
    flags: list[str] = []
    if _TITLE_HARD.search(role):
        reasons.append("title_advanced_degree")
    if _TITLE_SENIOR.search(role):
        reasons.append("title_senior")
    if _TITLE_LEVEL_FLAG.search(role):
        flags.append("title_level_token")
    for pattern in settings.extra_title_block:
        if re.search(pattern, role, re.I):
            reasons.append(f"title_block:{pattern}")
    return Eligibility(passed=not reasons, reasons=reasons, flags=flags)


def check_text(
    jd_text: str,
    settings: EligibilitySettings | None = None,
) -> Eligibility:
    """Apply degree, years, and return-intern rules to JD body text."""
    settings = settings or EligibilitySettings()
    reasons: list[str] = []
    flags: list[str] = []

    if has_advanced_degree_requirement(jd_text) and not has_bachelor_alternative(
        jd_text
    ):
        reasons.append("advanced_degree_without_bachelor")

    years = min_required_years(jd_text)
    if years is not None:
        if years >= settings.hard_reject_years:
            reasons.append(f"requires_{years}_years")
        elif years >= settings.flag_years:
            flags.append(f"years_{years}")

    if _RETURN_INTERN.search(jd_text):
        flags.append("return_intern_wording")

    for pattern in settings.extra_text_block:
        if re.search(pattern, jd_text, re.I):
            reasons.append(f"text_block:{pattern}")

    return Eligibility(passed=not reasons, reasons=reasons, flags=flags)
