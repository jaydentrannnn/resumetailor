"""A job title's role family and level, from fixed word lists. Pure, no LLM.

Used only to group pay figures ("same family and level"), never to screen or rank
postings. The whole title is read (`identity.normalize_role` would drop a segment such
as "AI Research Engineer" as if it were a location). The first family whose words
appear wins, in a fixed order (security before data before software...); "AI" alone
counts as data only when nothing more specific matched. With no level word, a title is
mid-level.
"""

from __future__ import annotations

import re
from typing import Literal

Family = Literal[
    "security", "data", "hardware", "software", "product", "design", "research",
    "business", "engineering", "other",
]
Level = Literal["intern", "new_grad", "mid", "senior", "staff", "manager"]

FAMILY_LABELS: dict[Family, str] = {
    "security": "Security", "data": "Data and machine learning", "hardware": "Hardware",
    "software": "Software", "product": "Product", "design": "Design", "research": "Research",
    "business": "Business and finance", "engineering": "Engineering (other)", "other": "Other",
}
LEVEL_LABELS: dict[Level, str] = {
    "intern": "Intern or co-op", "new_grad": "New grad or entry", "mid": "Mid-level",
    "senior": "Senior", "staff": "Staff or principal", "manager": "Manager or director",
}

_FAMILIES: tuple[tuple[Family, str], ...] = (
    ("security", r"security|cyber\w*|siem|soc|infosec|penetration"),
    ("data", r"data|analytics?|analysts?|machine learning|ml|mlops|scientists?|science|"
             r"intelligence|visuali[sz]ation|statistics?|statistician|quantitative|quant"),
    ("hardware", r"hardware|firmware|embedded|electrical|asic|fpga|silicon|chip|rf|"
                 r"mechanical|manufacturing|robotics"),
    ("software", r"software|developer|development engineer|swe|sde|backend|back end|"
                 r"frontend|front end|full ?stack|web|mobile|ios|android|devops|sre|"
                 r"site reliability|cloud|platform|programmer|applications?|"
                 r"information technology|it"),
    ("product", r"product manager|product management|product owner|program manager"),
    ("design", r"designer|design|ux|ui"),
    ("research", r"research|researcher"),
    ("business", r"business|strategy|sales|marketing|finance|financial|accounting|tax|"
                 r"consult\w*|operations|revenue|benefits|human resources|hr|people|"
                 r"supply chain|investment|banking|audit|actuarial|economics?"),
    ("data", r"ai|artificial intelligence"),
    ("engineering", r"engineer|engineering"),
)
_FAMILY_PATTERNS = tuple((f, re.compile(rf"\b(?:{words})\b")) for f, words in _FAMILIES)
_LEVELS: tuple[tuple[Level, re.Pattern[str]], ...] = (
    ("intern", re.compile(r"\b(?:intern(?:ship)?s?|co ?op|apprentice\w*|placement|"
                          r"summer (?:associate|analyst)|working student)\b")),
    ("manager", re.compile(r"\b(?:director|head|vp|vice president|chief)\b|"
                           r"(?<!product )(?<!program )(?<!project )(?<!account )\bmanager\b")),
    ("staff", re.compile(r"\b(?:staff|principal|distinguished|architect)\b")),
    ("senior", re.compile(r"\b(?:senior|sr|lead)\b")),
    ("new_grad", re.compile(r"\b(?:new grad\w*|graduate|entry|junior|jr|associate|"
                            r"early careers?|university|i|1)\b")),
)


def _title(role: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", role.casefold()))


def family(role: str) -> Family:
    title = _title(role)
    return next((f for f, pattern in _FAMILY_PATTERNS if pattern.search(title)), "other")


def level(role: str) -> Level:
    title = _title(role)
    return next((lv for lv, pattern in _LEVELS if pattern.search(title)), "mid")
