"""Regexes and section-title tables the PDF importer matches against."""

from __future__ import annotations

import re
from typing import Literal

_BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi", re.I)

_ITALIC_RE = re.compile(r"italic|oblique", re.I)

_PUA_RE = re.compile("[\ue000-\uf8ff]")

#: A bullet glyph at the start of a line. Hyphen, dash and asterisk count only when
#: followed by a space, so "-5% churn" or "*Expected" stay text.
_BULLET_RE = re.compile(
    "^\\s*(?:[\u2022\u25aa\u25e6\u25cf\u2023\u2043\u2219\u00b7\u25cb\u25a0\u25a1\u25ba"
    "\u25b6\u27a2\u27a4\u2713\u2714\u2756\u25c6\u25c7\ue000-\uf8ff]\\s*|[-\u2013\u2014*]\\s+)"
)

_PAGE_NUMBER_RE = re.compile(r"(?i)^(?:page\s*)?\d{1,3}(?:\s*(?:of|/)\s*\d{1,3})?$")

_SEPARATORS_RE = re.compile(r"\s+(?:\||\u2022|\u00b7|\u25aa)\s+")

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"

_SEASON = r"(?:spring|summer|fall|autumn|winter)"

_YEAR = r"(?:(?:19|20)\d{2}|['\u2019]\d{2})"

_POINT = rf"(?:(?:{_MONTH}|{_SEASON}),?\s+{_YEAR}|\d{{1,2}}/(?:19|20)?\d{{2}}|{_YEAR})"

_END = rf"(?:{_POINT}|present|current|now|ongoing)"

_DATE_SPAN = (
    rf"(?:(?:expected|anticipated|exp\.)\s+)?{_POINT}(?:\s*(?:-|\u2013|\u2014|to)\s*{_END})?"
    r"|present"
)

_DATE_FULL_RE = re.compile(rf"(?i)^\(?(?:{_DATE_SPAN})\)?$")

_DATE_TAIL_RE = re.compile(rf"(?i)[\s,|\u2013\u2014-]*\(?({_DATE_SPAN})\)?\s*$")

_LOCATION_RE = re.compile(
    r"^(?:remote|hybrid|[A-Z][A-Za-z.'\- ]{1,30},\s*(?:[A-Z]{2}|[A-Z][A-Za-z .'-]{2,30})"
    r"(?:\s+\d{5})?(?:\s*\((?:remote|hybrid)\))?)$",
    re.I,
)

_SCHOOL_RE = re.compile(r"(?i)\b(university|college|institute|school|academy|polytechnic)\b")

_GPA_RE = re.compile(r"(?i)[,|\s]*\(?\bGPA\b[:\s]*([0-9]\.[0-9]{1,2}(?:\s*/\s*[0-9.]+)?)\)?")

_COURSEWORK_RE = re.compile(r"(?i)^(?:relevant\s+)?course\s*work\s*:\s*(.+)$")

_LINK_RES = {
    "linkedin": re.compile(r"(?i)(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%.]+/?"),
    "github": re.compile(r"(?i)(?:https?://)?(?:www\.)?github\.com/[\w\-.]+/?"),
}

_URL_RE = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s|,]+|\b[\w-]+\.(?:com|io|dev|me|net|org)/[^\s|,]*"
)

_SUMMARY_TITLES = {
    "summary",
    "professional summary",
    "profile",
    "professional profile",
    "objective",
    "career objective",
    "about me",
}

_LIST_TITLES = {
    "certifications",
    "certificates",
    "licenses & certifications",
    "licenses and certifications",
    "awards",
    "honors",
    "honors & awards",
    "honors and awards",
    "awards & honors",
    "awards and honors",
    "publications",
    "languages",
    "interests",
    "relevant coursework",
    "coursework",
}

#: Headings whose section kind depends on its body: entries with bullets read as
#: experience, one-line items as a list.
_SHAPED_TITLES = {
    "leadership",
    "activities",
    "involvement",
    "campus involvement",
    "extracurricular activities",
    "extracurriculars",
    "volunteering",
    "volunteer",
    "community service",
    "research",
    "leadership & activities",
    "leadership and activities",
}

SectionKind = Literal["experience", "project", "education", "skills", "list", "summary"]
