"""Deterministic facts for education, skill checklists and routine notices."""

from __future__ import annotations

import re
from collections.abc import Iterable

HIGH_SCHOOL = "high_school_graduation_year"
SKILLS = "programming_languages"
ACKNOWLEDGEMENT = "routine_acknowledgement"
PROTECTED_KEYS = frozenset({HIGH_SCHOOL, SKILLS, ACKNOWLEDGEMENT, "relatives_at_company"})


def acknowledgement(text: str) -> str:
    """routine/manual/empty, using the whole question rather than a box's caption."""
    low = text.casefold()
    if not re.search(
        r"acknowledge|confirm|i agree|consent|privacy|personal information policy|"
        r"read.{0,35}statement|certif|attest|signature|terms (?:and|&) conditions",
        low,
    ):
        return ""
    if re.search(
        r"certif|attest|accurac|truth|signature|arbitration|background check|marketing|"
        r"newsletter|text messages|sms|code of conduct|\bstatements\b",
        low,
    ):
        return "manual"
    if re.search(
        r"privacy|personal information policy|data (?:processing|protection)|"
        r"read.{0,35}(?:statement|notice)|reasonable accommodation",
        low,
    ):
        return "routine"
    return "manual"


def semantic_key(text: str, help_text: str = "") -> str:
    low = text.casefold()
    if re.search(r"\bhigh school\b|\bsecondary school\b", low) and re.search(
        r"graduat|complet|finish", low
    ):
        return HIGH_SCHOOL
    if re.search(r"\bprogramming languages?\b", low):
        return SKILLS
    if re.search(r"\b(?:current )?grade level\b", low):
        return "class_year"
    if (
        re.search(r"\brelatives?\b|\bfamily members?\b", low)
        and re.search(r"work|employ|company|management committee", low)
        and not re.search(r"\bcompetitor|\bother compan", low)
    ):
        return "relatives_at_company"
    if acknowledgement(f"{text} {help_text}"):
        return ACKNOWLEDGEMENT
    return ""


def year_option(options: Iterable[str], year: str) -> str | None:
    if not re.fullmatch(r"\d{4}", year):
        return None
    wanted = int(year)
    hits = []
    for option in options:
        years = [int(x) for x in re.findall(r"\b\d{4}\b", option)]
        if not years:
            continue
        low = option.casefold()
        if len(years) == 2:
            matches = years[0] <= wanted <= years[1]
        elif re.search(r"or (?:earlier|before)|and (?:earlier|before)", low):
            matches = wanted <= years[0]
        elif re.search(r"or (?:later|after)|and (?:later|after)", low):
            matches = wanted >= years[0]
        elif "before" in low:
            matches = wanted < years[0]
        elif "after" in low:
            matches = wanted > years[0]
        else:
            matches = wanted == years[0]
        if matches:
            hits.append(option)
    return hits[0] if len(hits) == 1 else None


def skill_options(options: Iterable[str], skills: Iterable[str]) -> list[str]:
    """Exact names and explicit aliases; punctuation is significant (C/C++/C#)."""

    def canonical(value: str) -> str:
        value = re.sub(r"\s*\(programming language\)\s*$", "", value.casefold()).strip()
        return {
            "cpp": "c++",
            "c plus plus": "c++",
            "c sharp": "c#",
            "csharp": "c#",
            "js": "javascript",
            "ts": "typescript",
        }.get(value, value)

    known = {canonical(skill) for skill in skills}
    return [option for option in options if canonical(option) in known]


def high_school_year(education: Iterable[object]) -> str:
    starts = [
        str(getattr(row, "start", ""))[:4]
        for row in education
        if re.search(r"bachelor|associate", str(getattr(row, "degree_level", "")), re.I)
        and re.match(r"\d{4}", str(getattr(row, "start", "")))
    ]
    return min(starts, default="")
