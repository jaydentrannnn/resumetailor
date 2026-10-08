"""Completed education: profile choices and conservative form semantics. No LLM."""

from __future__ import annotations

import re
import unicodedata

KEY = "highest_education_obtained"
MIXED_KEY = "education_completed_or_pursuing"
DETAIL_KEY = "completed_education_other"
RESERVED_KEYS = frozenset({KEY, MIXED_KEY, DETAIL_KEY})

LEVELS = (
    "Less than high school",
    "High school diploma",
    "GED or equivalent",
    "Some college—no degree",
    "Vocational/technical certificate or diploma",
    "Associate's degree",
    "Bachelor's degree",
    "Master's degree",
    "Professional degree",
    "Doctorate",
)


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", plain).split())


_ALIASES = (
    ("less than high school", "below high school", "no high school diploma"),
    ("high school diploma", "high school", "hs", "secondary school diploma"),
    ("ged or equivalent", "ged", "general educational development", "high school equivalency"),
    ("some college no degree", "some college", "college coursework no degree"),
    (
        "vocational technical certificate or diploma",
        "vocational certificate",
        "technical diploma",
        "trade school diploma",
    ),
    (
        "associate s degree",
        "associate s",
        "associate degree",
        "associates degree",
        "associates",
        "associate",
    ),
    (
        "bachelor s degree",
        "bachelor s",
        "bachelor degree",
        "bachelors degree",
        "bachelors",
        "bachelor",
    ),
    ("master s degree", "master s", "master degree", "masters degree", "masters", "master"),
    ("professional degree", "professional doctorate"),
    ("doctorate", "doctoral degree", "doctorate degree", "doctoral"),
)
LEVEL_BY_ALIAS = {
    alias: level for level, aliases in zip(LEVELS, _ALIASES, strict=True) for alias in aliases
}

HIGHEST_PATTERN = (
    r"\bhighest\s+(?:completed\s+)?(?:(?:level of|level|educational)\s+)?"
    r"(?:education|qualification|degree)\b(?!\s+of\b(?!\s+education\b))"
    r"|\b(?:level of education|education level|educational attainment)\b"
)
COMPLETED_PATTERN = (
    r"\b(?:education|degree|qualification)\b.{0,50}\b(?:completed|obtained|attained|earned|held)\b"
    r"|\b(?:completed|earned|obtained)\s+(?:education|degree|qualification)\b"
)
PURSUING_PATTERN = (
    r"\b(?:degree|education|qualification)\b.{0,90}\b(?:pursuing|in progress|working toward)\b"
    r"|\b(?:pursuing|in progress|working toward)\b.{0,50}\bdegree\b"
    r"|\bcurrent\s+(?:or most recently completed\s+)?degree\b"
)
# Shared with the standalone DOM fill fallback through ats_hints.SYNONYMS.
MIXED_PATTERN = rf"(?=.*(?:{HIGHEST_PATTERN}|{COMPLETED_PATTERN}))(?=.*(?:{PURSUING_PATTERN})).+"
DETAIL_PATTERN = (
    r"^if (?:other|you .{0,30}other)\b(?!.*\bschool\b).*"
    r"\b(?:degree|qualification|education level)\b"
)


def level(text: str) -> str | None:
    """A known broad level; specific credentials and unfamiliar text stay custom."""
    return LEVEL_BY_ALIAS.get(normalize(text))


def equivalent(option: str, value: str) -> bool:
    """An equivalent level, including explicit grouped options; never a rank fallback."""
    wanted = level(value)
    if wanted is None:
        return False
    if level(option) == wanted:
        return True
    parts = re.split(r"\s+or\s+|\s*[/;]\s*", option, flags=re.I)
    return any(level(part) == wanted for part in parts) if len(parts) > 1 else False


def not_education(text: str) -> bool:
    """'Highest degree of integrity' is not an academic qualification."""
    return bool(re.search(r"\bhighest\s+degree\s+of\s+(?!education\b)", text, re.I))


def compound(text: str) -> bool:
    """A level alone cannot answer a question also requesting a major or institution."""
    return bool(
        re.search(
            r"\band\b.{0,30}\b(?:major|field of study|school|institution)\b",
            text,
            re.I,
        )
    )


def question_key(text: str, help_text: str = "") -> str | None:
    """Only education-level questions, not degree eligibility or school follow-ups."""
    low = " ".join(f"{text} {help_text}".casefold().split())
    if not_education(text):
        return None
    if re.search(DETAIL_PATTERN, low):
        return DETAIL_KEY
    if low.startswith("if "):
        return None
    # A group's shared description also appears beside School and dates.
    if not re.search(r"\b(?:degree|qualification)\b", text, re.I) and not re.search(
        HIGHEST_PATTERN,
        text,
        re.I,
    ):
        return None
    if re.search(r"\b(?:graduation|graduate|degree).{0,60}\bby\b", low):
        return None
    highest = bool(re.search(HIGHEST_PATTERN, low))
    completed = bool(re.search(COMPLETED_PATTERN, low))
    pursuing_text = re.sub(
        r"\b(?:do not|don't|not|exclude|excluding)\b.{0,45}"
        r"\b(?:pursuing|in progress|working toward)\b(?:\s+degrees?)?",
        "",
        low,
    )
    pursuing = bool(re.search(PURSUING_PATTERN, pursuing_text))
    if pursuing:
        return MIXED_KEY if highest or completed else "degree_level"
    return KEY if highest or completed else None


def refresh_fields(fields: dict[str, str], value: str) -> None:
    """Overlay the current profile, including clearing values from old packets."""
    fields.pop(KEY, None)
    fields.pop(DETAIL_KEY, None)
    value = value.strip()
    if value:
        fields[KEY] = value
        if level(value) is None:
            fields[DETAIL_KEY] = value
