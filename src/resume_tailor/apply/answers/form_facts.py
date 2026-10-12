"""Deterministic facts for education, skill checklists and routine notices."""

from __future__ import annotations

import re
from collections.abc import Iterable

HIGH_SCHOOL = "high_school_graduation_year"
SKILLS = "programming_languages"
ACKNOWLEDGEMENT = "routine_acknowledgement"
TALENT_POOL = "talent_pool_consent"
TYPED_CONSENT = "typed_consent"
PROTECTED_KEYS = frozenset({
    HIGH_SCHOOL, SKILLS, ACKNOWLEDGEMENT, TALENT_POOL, TYPED_CONSENT, "relatives_at_company",
})

#: Consent to keep the applicant's data for OTHER openings (a talent pool), as opposed to
#: processing it for this application. The applicant declines these (2026-10-12).
_TALENT_POOL = re.compile(
    r"(?:consent|agree|permission|allow|may we|keep|retain|store).{0,160}"
    r"(?:(?:other|future|additional|similar)\s+(?:job|career|employment|work)?\s*"
    r"(?:opportunit|opening|position|role|vacanc)|talent (?:pool|community|network))",
    re.S,
)


def talent_pool(text: str) -> bool:
    """A question asking to keep the applicant's data for other job opportunities."""
    return bool(_TALENT_POOL.search(text.casefold()))


#: A notice, consent or declaration the applicant is asked to accept.
_NOTICE = re.compile(
    r"acknowledg|confirm|\bi agree\b|\bagree (?:to|with) (?:the|these|this|our|all|its)\b"
    r"|understand and (?:agree|accept|acknowledge)|\bconsent|privacy|personal information policy"
    r"|read.{0,35}(?:statement|notice|policy)|certif|attest|signature"
    r"|terms (?:and|&) conditions|\bi authori[sz]e\b|\bdeclar(?:e|ation)\b"
)
#: A declaration that states a fact about the applicant ("I confirm that I am legally
#: authorized to work..."): answered from that fact, never agreed to blindly.
_FACT_CLAIM = re.compile(
    r"\b(?:i|you)\s+(?:am|are|'m|'re|was|were|hold|possess|do\s+not|don'?t"
    r"|have\s+(?!read|reviewed|answered|understood|carefully|provided|completed this)"
    r"|(?:will\s+(?:not\s+)?|currently\s+)?(?:require|need))\b"
    r".{0,120}?(?:authori[sz]ed\s+to\s+work|citizen|permanent\s+resident|green\s+card"
    r"|sponsor|\bvisa\b|non[- ]?compet|non[- ]?solicit|convict|felon|criminal|\b18\b"
    r"|years\s+of\s+age|clearance)"
)
#: Optional opt-ins the applicant declines (marketing, alerts, texts, talent pools).
_OPT_IN = re.compile(
    r"marketing|newsletter|promotional|job alerts?|text messages?|\bsms\b"
    r"|talent (?:community|network|pool)"
)


#: A text box the applicant fills to accept a notice: an e-signature, today's date beside
#: it, or a word the instruction quotes ("Type 'I agree' to continue").
_TYPE_TOKEN = re.compile(
    r"\b(?:type|enter|write|select|choose|(?:answer|respond|reply)(?:\s+with)?)\s+"
    r"(?:the\s+(?:word|phrase|text)\s+)?[\"'“‘]([^\"'”’]{1,30})[\"'”’]",
    re.I,
)
_SIGNATURE = re.compile(
    r"\be-?signature\b|\bsignature\b(?!\s*date)|electronic(?:ally)?\s+sign"
    r"|\b(?:type|enter)\s+your\s+(?:full\s+|legal\s+)*name\b.{0,40}\b(?:sign|signature|acknowledg|agree)"
)
_SIGNED_DATE = re.compile(r"^(?:today'?s\s+)?date$|signature\s+date|date\s+signed|^today'?s\s+date")


def typed_consent(text: str, help_text: str = "") -> str:
    """What to type into a consent text box: the quoted word, "full_name" for a
    signature, "today" for its date; "" when ``text`` is not such a box."""
    context = f"{text} {help_text}"
    token = _TYPE_TOKEN.search(context)
    # Only a notice's token ("Type 'I agree'"), never "Enter 'N/A' if none" or a quoted
    # word that would assert a fact about the applicant.
    if token and acknowledgement(context) == "routine":
        return token.group(1).strip()
    label = re.sub(r"[*:]\s*$", "", text.strip()).strip().casefold()
    if _SIGNED_DATE.search(label):
        return "today"
    if _SIGNATURE.search(context.casefold()):
        return "full_name"
    return ""


def acknowledgement(text: str) -> str:
    """What kind of notice ``text`` is, using the whole question, not a box's caption:
    "routine" (a notice, process or declaration of accuracy to agree to: privacy,
    background check, screening, terms, arbitration, signature), "fact" (it asserts
    something about the applicant), "optional" (an opt-in to decline), else ""."""
    low = text.casefold()
    if not _NOTICE.search(low):
        return ""
    if _FACT_CLAIM.search(low):
        return "fact"
    if _OPT_IN.search(low):
        return "optional"
    return "routine"


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
    # "Are you related to a current Workday employee?" too; ties to a customer, supplier,
    # competitor or official are a conflict of interest instead (`ats_hints`).
    if (
        re.search(r"\brelatives?\b|\bfamily members?\b|\brelated to\b", low)
        and re.search(r"work|employ|company|management committee", low)
        and not re.search(
            r"\bcompetitor|\bother compan|\bcustomer|\bsupplier|\bvendor|\bofficial"
            r"|conflict of interest",
            low,
        )
    ):
        return "relatives_at_company"
    if talent_pool(text):
        return TALENT_POOL
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
