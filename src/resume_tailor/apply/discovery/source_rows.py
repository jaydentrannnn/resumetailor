"""README posting rows: the row model, its flags and posted-age parsing."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

US_CITIZEN_FLAG = "🇺🇸"

NO_SPONSOR_FLAG = "🛂"

GRAD_FLAG = "🎓"

FAANG_FLAG = "🔥"

SponsorshipOk = Literal["Unknown", "No"]

#: Posted-age token: optional spaces between the number and unit.
_AGE_RE = re.compile(
    r"^(\d+)\s*(m|min|h|hr|d|w|mo)$",
    re.IGNORECASE,
)

class SourceRow(BaseModel):
    """One parsed posting row from a category section."""

    company: str
    role: str
    location: str
    age: str
    age_days: int | None = None
    #: ISO date the posting was published, when the source states one ("" otherwise).
    posted_at: str = ""
    job_id: str | None = None
    application_link: str | None = None
    sponsorship_ok: SponsorshipOk = "Unknown"
    citizenship_required: str = "No"
    notes: str = ""
    advanced_degree: bool = False
    source_id: str = ""
    salary: str = ""
    flags: list[str] = Field(default_factory=list)

class FilterResult(BaseModel):
    """Outcome of ``filter_rows`` with dedupe and exclusion counts."""

    new_rows: list[SourceRow] = Field(default_factory=list)
    total_candidates: int = 0
    age_filtered_count: int = 0
    excluded_citizenship: int = 0
    excluded_advanced_degree: int = 0
    excluded_no_sponsorship: int = 0
    excluded_title: int = 0
    already_known: int = 0

def parse_age(text: str) -> int | None:
    """Convert a README age token into whole days, or ``None`` when unparseable.

    Minutes and hours collapse to 0 (same calendar day). Weeks are 7 days;
    months are approximated as 30 days.
    """
    cleaned = text.strip().lower()
    if not cleaned:
        return None
    match = _AGE_RE.match(cleaned)
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit in {"m", "min", "h", "hr"}:
        return 0
    if unit == "d":
        return amount
    if unit == "w":
        return amount * 7
    if unit == "mo":
        return amount * 30
    return None
