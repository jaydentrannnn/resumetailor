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


def _block_hit(pattern: str, text: str) -> bool:
    """Whether a user block entry matches ``text``, case-insensitively.

    Entries are regexes, but the Job sources page saves plain words, so one that is not a
    valid regex ("C++") is matched literally instead of raising.
    """
    try:
        return re.search(pattern, text, re.I) is not None
    except re.error:
        return re.search(re.escape(pattern), text, re.I) is not None


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
    r"|baccalaureate"
    r"|associate(?:'s|s)?\s+degree"
    r"|four-?\s?year\s+degree"
    r"|(?:college|university)\s+degree"
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

# A years match only counts when "experience" follows within this many characters
# ("3+ years of professional experience"), so company boilerplate like "over 40 years
# of excellence" never reads as a requirement.
_EXPERIENCE_AFTER = re.compile(r".{0,40}?\bexp(?:erience[ds]?)?\b", re.I | re.S)

# Sources are intern / new-grad boards, so a larger floor is a misparse, not a real ask.
MAX_PLAUSIBLE_YEARS = 5

_YEARS_SOFT = re.compile(
    r"intern|internship|new grad|entry|student",
    re.I,
)

_RETURN_INTERN = re.compile(
    r"previous(?:ly)?\s+intern|returning\s+intern|return\s+offer",
    re.I,
)


#: Business-track entry titles (plan P4-D3). Banks hire undergraduates as "Summer
#: Analyst", and corporates run analyst, rotational and development programs. A bare
#: "Analyst" or "Associate" is not enough: those titles also name experienced roles, so
#: the posting's years requirement decides (they still pass `check_title`). These words
#: only count without a senior word or a level token ("Summer Analyst II" is not entry).
_BUSINESS_ENTRY = re.compile(
    r"\b(?:summer\s+(?:analyst|associate)|(?:analyst|associate)\s+(?:program|class)"
    r"|rotational|rotation\s+program|(?:leadership\s+)?development\s+program"
    r"|early\s+(?:career|talent))\b",
    re.I,
)

#: A senior word that is part of an entry-level title rather than a seniority marker:
#: "Associate Product Manager", "Assistant Project Manager".
_JUNIOR_MANAGER = re.compile(
    r"\b(?:associate|assistant|junior|jr\.?)\s+(?:\w+\s+){0,2}manager\b", re.I
)
_SENIOR_ONLY = re.compile(
    r"\b(?:senior|sr\.?|staff|principal|director|head\s+of|vp|vice\s+president)\b", re.I
)


def is_early_career_title(role: str) -> bool:
    """True for an intern / new-grad / entry / student title, or a business entry title."""
    if _YEARS_SOFT.search(role) is not None:
        return True
    return (
        _BUSINESS_ENTRY.search(role) is not None
        and _TITLE_SENIOR.search(_JUNIOR_MANAGER.sub(" ", role)) is None
        and _TITLE_LEVEL_FLAG.search(role) is None
    )


def _senior_title(role: str) -> bool:
    """A seniority word that makes the title more than entry level.

    "Product Manager Intern" and "Associate Product Manager" are entry-level: for an
    intern / new-grad title, or a junior manager title, only unambiguous seniority
    ("Senior", "Director", "VP", …) counts.
    """
    if _YEARS_SOFT.search(role) or _JUNIOR_MANAGER.search(role):
        return _SENIOR_ONLY.search(role) is not None
    return _TITLE_SENIOR.search(role) is not None


def has_advanced_degree_requirement(text: str) -> bool:
    """True when the text mentions a master's/PhD-level degree requirement."""
    return _ADVANCED.search(text) is not None


def has_bachelor_alternative(text: str) -> bool:
    """True when the text also names a bachelor's / undergraduate path."""
    return _BACHELOR.search(text) is not None


def min_required_years(text: str) -> int | None:
    """Smallest year floor found, ignoring soft/intern/preferred contexts.

    A match counts only when "experience" follows it and its number is at most
    ``MAX_PLAUSIBLE_YEARS``.
    """
    best: int | None = None
    for match in _YEARS.finditer(text):
        start, end = match.span()
        if not _EXPERIENCE_AFTER.match(text, end):
            continue
        window = text[max(0, start - 60) : min(len(text), end + 60)]
        if _YEARS_SOFT.search(window):
            continue
        value = int(match.group(1))
        if value > MAX_PLAUSIBLE_YEARS:
            continue
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
    if _senior_title(role):
        reasons.append("title_senior")
    if _TITLE_LEVEL_FLAG.search(role):
        flags.append("title_level_token")
    for pattern in settings.extra_title_block:
        if _block_hit(pattern, role):
            reasons.append(f"title_block:{pattern}")
    return Eligibility(passed=not reasons, reasons=reasons, flags=flags)


def check_text(
    jd_text: str,
    settings: EligibilitySettings | None = None,
    *,
    role: str = "",
) -> Eligibility:
    """Apply degree, years, and return-intern rules to JD body text.

    When ``role`` is an intern / new-grad / entry title, a years floor is only flagged,
    never a hard reject — the title is stronger evidence than a regex hit in the body.
    """
    settings = settings or EligibilitySettings()
    reasons: list[str] = []
    flags: list[str] = []

    if has_advanced_degree_requirement(jd_text) and not has_bachelor_alternative(
        jd_text
    ):
        reasons.append("advanced_degree_without_bachelor")

    years = min_required_years(jd_text)
    if years is not None:
        if years >= settings.hard_reject_years and not is_early_career_title(role):
            reasons.append(f"requires_{years}_years")
        elif years >= settings.flag_years:
            flags.append(f"years_{years}")

    if _RETURN_INTERN.search(jd_text):
        flags.append("return_intern_wording")

    for pattern in settings.extra_text_block:
        if _block_hit(pattern, jd_text):
            reasons.append(f"text_block:{pattern}")

    return Eligibility(passed=not reasons, reasons=reasons, flags=flags)
