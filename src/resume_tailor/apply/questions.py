"""What a form question asks and what the applicant's answer is: one decision layer.

Every fill path observes questions its own way (``filler.js``, ``dom_scan.js``, the
SmartRecruiters and Workday flows), then asks this module three things:

- :func:`classify` — which applicant fact a question asks for (a canonical key, plus a
  parameter such as a date or a place the question names). Stem rules for questions
  whose answer is *derived* come first; then the shared label synonyms
  (``ats_hints.SYNONYMS``), behind two gates: a long question never maps to a short
  identity field ("Have you uploaded your most recent College Transcript?" is not the
  School field), and a key must suit the control (a Yes/No question is never a GPA or a
  Phone). A question no rule covers is unkeyed, never guessed.
- :func:`answers` — the answers to try, most specific first, from the packet's profile
  facts or computed from them (enrolled now, degree finished by a date, GPA at least a
  threshold, located in or willing to move to a place, ...). No fact, no answer.
- :func:`choose` — the exact option of a choice control that says that answer.

The rules here are pure and deterministic; a model never picks an answer value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Literal

from resume_tailor.apply import ats_hints, field_matcher, salary

if TYPE_CHECKING:
    from resume_tailor.apply.packet import Packet

Kind = Literal["text", "textarea", "choice", "multi", "typeahead", "date", "checkbox"]

MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)


@dataclass(frozen=True)
class Question:
    """One question as a form shows it, whichever control asks it."""

    text: str
    kind: Kind = "text"
    options: tuple[str, ...] = ()
    #: For one box of a split date: "month", "year" or "day".
    part: str = ""
    #: The enclosing group's heading ("Education", "Start Date"), for split dates.
    section: str = ""


@dataclass(frozen=True)
class Match:
    """The fact a question asks for; ``param`` is what the question names (a date, a place)."""

    key: str
    param: str = ""


@dataclass(frozen=True)
class Facts:
    """What answers are computed from: the packet's fields and a little context."""

    fields: dict[str, str]
    today: date = field(default_factory=date.today)
    company: str = ""
    role: str = ""
    employers: tuple[str, ...] = ()
    experience_titles: tuple[str, ...] = ()


# --- classify -------------------------------------------------------------------------

#: Keys whose answer is a short identity/contact/education value: never the key of a long
#: question that merely mentions "school", "phone" or "city" (mirrors ``filler.js``).
SHORT_FIELD_KEYS = frozenset({
    "first_name", "middle_name", "last_name", "preferred_name", "full_name", "email", "phone",
    "address_line1", "address_line2", "city", "state", "postal_code", "country", "school",
    "major", "degree_level", "gpa", "website", "current_company", "current_title",
    "linkedin_url", "github_url", "portfolio_url", "school_email", "pronouns",
})

#: Keys answered by typing, never by picking Yes/No.
TEXT_ONLY_KEYS = frozenset({
    "first_name", "middle_name", "last_name", "preferred_name", "full_name", "email", "phone",
    "phone_extension", "address_line1", "address_line2", "postal_code", "linkedin_url",
    "github_url", "portfolio_url", "website", "school_email", "gpa",
})

#: Keys whose answer is Yes or No (a Yes/No question may only take one of these).
YES_NO_KEYS = frozenset({
    "authorized_to_work", "requires_sponsorship", "requires_sponsorship_future",
    "requires_sponsorship_any", "f1_opt_eligible", "over_18", "willing_to_relocate",
    "noncompete", "drivers_license", "has_preferred_name", "previous_worker",
    "work_authorization", "relatives_at_company",
    "currently_enrolled", "degree_by", "returning_to_school", "gpa_at_least",
    "located_or_relocate", "has_prior_internship",
}) | field_matcher.EEO_KEYS

_MONTH_RE = "|".join(month.lower() for month in MONTHS)
_BY_DATE = re.compile(
    rf"\bby\s+(?:the\s+end\s+of\s+)?(?P<month>{_MONTH_RE})?\s*(?:of\s+)?(?:(?P<year>\d{{4}})"
    r"|(?P<relative>(?:the\s+)?(?:next|upcoming|following|coming)\s+year|this\s+year))?",
)
_AREA = re.compile(
    r"\b(?:located|living|live|reside|residing|based)\s+(?:in|near|within)\s+(?:the\s+)?"
    r"(?P<area>.+?)(?:,|\s+or\b|\s+and\b|\?|$)",
)
_THRESHOLD = re.compile(r"(\d\.\d{1,2})")

#: Questions whose answer is computed from profile facts, by what they ask. Matched on
#: the casefolded question before any label synonym.
_DERIVED: tuple[tuple[str, str], ...] = (
    (
        r"\bgpa\b.{0,80}?\d\.\d{1,2}\s*(?:or\s+(?:above|higher|greater|more|better)|\+|and\s+above)"
        r"|\bgpa\b.{0,40}\b(?:at least|above|greater than|higher than|minimum(?: of)?)"
        r"\s*(?:a\s+)?\d\.\d",
        "gpa_at_least",
    ),
    (
        r"\b(?:currently|presently)\s+(?:be\s+)?enrolled\b"
        r"|\bare you (?:currently )?(?:an? )?(?:enrolled |full[- ]time )?student\b",
        "currently_enrolled",
    ),
    (
        r"\b(?:obtain|obtained|complete|completed|receive|received|earn|earned|finish|finished"
        r"|conferred)\b.{0,60}\bdegree\b.{0,60}\bby\b"
        r"|\bgraduat\w*\b.{0,40}\bby\s+(?:" + _MONTH_RE + r"|the end|\d{4})",
        "degree_by",
    ),
    (
        r"\breturn(?:ing)?\s+to\s+(?:school|college|university|campus)\b"
        r"|\bcontinue\s+(?:your\s+)?academic\s+studies\b",
        "returning_to_school",
    ),
    (
        r"\b(?:located|living|live|reside|residing|based)\s+(?:in|near|within)\b.{0,120}"
        r"\bwilling\s+to\s+relocate\b",
        "located_or_relocate",
    ),
    (
        r"\b(?:completed|had|done|have)\b.{0,40}\b(?:internships?|co-?ops?)\b",
        "has_prior_internship",
    ),
    (
        r"\bhave you (?:ever )?(?:previously )?(?:worked|been employed)\s+(?:at|for|by|with)\b"
        r"|previous(?:ly)?\s+(?:worked|employed)|ever\s+(?:been\s+)?(?:worked|employed)"
        r"|former\s+employee|current\s+or\s+former|worked\s+(?:for|at)\s+.{0,40}before",
        "previous_worker",
    ),
)

#: The profile field a derived answer comes from: the field to fill in when it is blank.
SOURCE_FIELD = {
    "currently_enrolled": "graduation_month",
    "degree_by": "graduation_month",
    "returning_to_school": "graduation_month",
    "gpa_at_least": "gpa",
    "located_or_relocate": "willing_to_relocate",
}


def profile_field(key: str) -> str:
    """The profile field behind ``key`` (itself, unless its answer is derived)."""
    return SOURCE_FIELD.get(key, key)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def yes_no_options(options: Sequence[str]) -> bool:
    """Whether a choice's options are Yes/No answers ("Yes - I consent", "No")."""
    heads = {_yes_no_head(option) for option in options if _clean(option)}
    return {"yes", "no"} <= heads


def _yes_no_head(option: str) -> str:
    words = field_matcher.normalize(option).split()
    return words[0] if words and words[0] in {"yes", "no"} else ""


def _compatible(key: str, question: Question) -> bool:
    if question.kind in {"choice", "multi", "checkbox"}:
        if key in TEXT_ONLY_KEYS:
            return False
        if question.options and yes_no_options(question.options) and key not in YES_NO_KEYS:
            return False
    return True


def _sponsorship_key(low: str) -> str | None:
    """A question about *needing* sponsorship, whatever else it names ("work authorization",
    "visa status"): now, in the future, or either."""
    if not (re.search(r"\bsponsor", low) and re.search(r"\b(?:require|need|seek)", low)):
        return None
    future = "future" in low
    now = re.search(r"\bnow\b|\bcurrent", low)
    if future and now:
        return "requires_sponsorship_any"
    return "requires_sponsorship_future" if future else "requires_sponsorship"


def _synonym_key(text: str) -> str | None:
    low = text.casefold()
    sponsorship = _sponsorship_key(low)
    if sponsorship:
        return sponsorship
    for pattern, key in ats_hints.SYNONYMS:
        if len(text) > 60 and key in SHORT_FIELD_KEYS:
            continue
        if re.search(pattern, low, re.I):
            return key
    return None


def _param(key: str, text: str) -> str:
    low = text.casefold()
    if key == "gpa_at_least":
        found = _THRESHOLD.search(low)
        return found.group(1) if found else ""
    if key == "located_or_relocate":
        found = _AREA.search(low)
        return found.group("area").strip() if found else ""
    if key == "degree_by":
        found = _by_match(low)
        return found.group(0) if found else ""
    if key == "has_prior_internship":
        work = re.search(r"\bwork experience|\brelated experience|\bwork history", low)
        return "work" if work else ""
    if key == "previous_worker":
        return low
    return ""


def _by_match(text: str) -> re.Match[str] | None:
    """The first "by <month> <year>" phrase that names a date ("by AbbVie" does not)."""
    for found in _BY_DATE.finditer(text):
        if found.group("month") or found.group("year") or found.group("relative"):
            return found
    return None


def classify(question: Question) -> Match | None:
    """The fact ``question`` asks for, or None when no rule covers it."""
    text = _clean(question.text)
    if not text:
        return None
    low = text.casefold()
    for pattern, key in _DERIVED:
        if re.search(pattern, low) and _compatible(key, question):
            return Match(key, _param(key, text))
    if question.part in {"month", "year"}:
        context = f"{question.section} {text}".casefold()
        if re.search(r"\bend\b|graduat|complet|finish", context):
            return Match("graduation_month")
        if re.search(r"\bstart\b|\bbegin|\bfrom\b|enroll", context):
            return Match("education_start_month")
    key = _synonym_key(text)
    if key is None or not _compatible(key, question):
        return None
    return Match(key)


# --- answers --------------------------------------------------------------------------


def _year_month(value: str) -> tuple[int, int] | None:
    found = re.search(r"(\d{4})(?:-(\d{1,2}))?", value or "")
    if not found:
        return None
    month = int(found.group(2)) if found.group(2) else 12
    return int(found.group(1)), month if 1 <= month <= 12 else 12


def by_date(param: str, today: date) -> tuple[int, int] | None:
    """The (year, month) a "by June of the upcoming year" phrase names."""
    found = _by_match(param.casefold())
    if not found:
        return None
    month_name, year, relative = found.group("month"), found.group("year"), found.group("relative")
    month = MONTHS.index(month_name.capitalize()) + 1 if month_name else 12
    if year:
        return int(year), month
    if relative:
        return (today.year if relative.startswith("this") else today.year + 1), month
    if month_name:
        return (today.year if month >= today.month else today.year + 1), month
    return None


def _yes(value: bool | None) -> list[str]:
    return [] if value is None else ["Yes" if value else "No"]


def _located_in(area: str, fields: dict[str, str]) -> bool | None:
    area = area.casefold()
    if not area:
        return None
    city = fields.get("city", "").strip().casefold()
    state = fields.get("state", "").strip().casefold()
    if not city and not state:
        return None
    if city and re.search(rf"\b{re.escape(city)}\b", area):
        return True
    return bool(state and len(state) > 2 and re.search(rf"\b{re.escape(state)}\b", area))


def _internship_end(facts: Facts) -> tuple[int, int]:
    """The end of the summer the posting's internship runs in (its year, else the next one)."""
    found = re.search(r"\b(20\d{2})\b", facts.role)
    if found:
        return int(found.group(1)), 9
    return (facts.today.year if facts.today.month <= 8 else facts.today.year + 1), 9


def _derived(match: Match, facts: Facts) -> list[str]:
    fields = facts.fields
    graduation = _year_month(fields.get("graduation_month", ""))
    now = (facts.today.year, facts.today.month)
    if match.key == "currently_enrolled":
        return _yes(None if graduation is None else graduation >= now)
    if match.key == "degree_by":
        target = by_date(match.param, facts.today)
        return _yes(None if graduation is None or target is None else graduation <= target)
    if match.key == "returning_to_school":
        return _yes(None if graduation is None else graduation > _internship_end(facts))
    if match.key == "gpa_at_least":
        gpa = re.search(r"\d+(?:\.\d+)?", fields.get("gpa", ""))
        threshold = match.param
        return _yes(None if not gpa or not threshold else float(gpa.group(0)) >= float(threshold))
    if match.key == "located_or_relocate":
        if _located_in(match.param, fields):
            return ["Yes"]
        return [fields["willing_to_relocate"]] if fields.get("willing_to_relocate") else []
    if match.key == "has_prior_internship":
        titles = [title.casefold() for title in facts.experience_titles]
        if any(re.search(r"\bintern|\bco-?op", title) for title in titles):
            return ["Yes"]
        if match.param == "work" and titles:
            return ["Yes"]
        return [] if titles else ["No"]
    if match.key == "previous_worker":
        return _yes(_named_employer(facts, match.param))
    return []


def _named_employer(facts: Facts, question: str) -> bool:
    """Whether the applicant worked at the posting company or a company the question names."""
    employers = [field_matcher.normalize(name) for name in facts.employers if name.strip()]
    company = field_matcher.normalize(facts.company)
    asked = f" {field_matcher.normalize(question)} "
    return any(
        (company and (name == company or re.search(rf"\b{re.escape(company)}\b", name)))
        or (len(name) > 2 and f" {name} " in asked)
        for name in employers
    )


def _date_part(value: str, part: str) -> str:
    """The part of a "2027-06" (or "June 2027") date a split question asks for; "" when the
    date lacks it."""
    parsed = re.search(r"(\d{4})(?:-(\d{1,2}))?", value or "")
    named = next((m for m in MONTHS if m.casefold() in (value or "").casefold()), "")
    month = named
    if parsed and parsed.group(2) and 1 <= int(parsed.group(2)) <= 12:
        month = MONTHS[int(parsed.group(2)) - 1]
    if part == "year":
        return parsed.group(1) if parsed else ""
    if part == "month":
        return month
    return value


def answers(match: Match | None, question: Question, facts: Facts) -> list[str]:
    """Answers to try for ``question``, most specific first; [] when no fact answers it."""
    if match is None:
        return []
    derived = _derived(match, facts)
    if derived or match.key in {key for _pattern, key in _DERIVED}:
        return derived
    if match.key in {"graduation_month", "education_start_month"}:
        value = facts.fields.get(match.key, "")
        part = question.part or _part_from_text(question.text)
        answer = _date_part(value, part) if value else ""
        return [answer] if answer else []
    if match.key == "salary_expectation":
        # The fill runner precomputes each unit's answer (`apply/salary.py`).
        unit = salary.question_unit(question.text)
        key = {"hour": "salary_hourly", "year": "salary_yearly"}.get(unit or "", match.key)
        value = facts.fields.get(key) or facts.fields.get(match.key, "")
        return [value] if value else []
    return field_matcher.choice_values(match.key, facts.fields)


def _part_from_text(text: str) -> str:
    low = text.casefold()
    if "year" in low and "month" not in low:
        return "year"
    if "month" in low and "year" not in low:
        return "month"
    return ""


def choose(question: Question, key: str, candidates: Iterable[str]) -> str | None:
    """The one option of ``question`` that says the first answer any option says."""
    options = [option for option in question.options if _clean(option)]
    for candidate in candidates:
        wanted = field_matcher.normalize(candidate)
        if wanted in {"yes", "no"} and yes_no_options(options):
            hits = [option for option in options if _yes_no_head(option) == wanted]
            if len(hits) == 1:
                return hits[0]
            continue
        if key in {"graduation_month", "education_start_month"} and question.part == "month":
            hit = _month_option(options, candidate)
            if hit:
                return hit
        hit = field_matcher.closest_option(options, candidate, key=key)
        if hit:
            return hit
    return None


def _month_option(options: list[str], month: str) -> str | None:
    """"June" among "Jun" / "06" / "June" style month lists."""
    if month not in MONTHS:
        return None
    number = MONTHS.index(month) + 1
    for option in options:
        low = option.strip().casefold()
        if low in {month.casefold(), month[:3].casefold()} or low.lstrip("0") == str(number):
            return option
    return None


def facts_from_packet(packet: Packet, *, fields: dict[str, str] | None = None) -> Facts:
    """Facts for the application ``packet`` describes (``fields`` overrides its fields)."""
    return facts_for(
        packet.fields if fields is None else fields,
        company=packet.company, role=packet.role,
        employers=[entry.employer for entry in packet.experience],
        experience_titles=[entry.title for entry in packet.experience],
    )


def facts_for(
    fields: dict[str, str], *, company: str = "", role: str = "",
    employers: Iterable[str] = (), experience_titles: Iterable[str] = (),
    today: date | None = None,
) -> Facts:
    """Facts for one application (``today`` is fixed in tests)."""
    return Facts(
        fields=dict(fields), today=today or date.today(), company=company, role=role,
        employers=tuple(employers), experience_titles=tuple(experience_titles),
    )
