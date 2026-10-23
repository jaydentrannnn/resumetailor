"""Spoken-language requirements in a posting, checked against the profile — pure, no LLM.

A posting that requires a language the profile does not list is screened out. One that
asks for fluency in a language the profile lists as not fluent, or for any language when
the profile lists none, is only flagged: the user decides. English is assumed unless the
profile lists it as not fluent. Optional wording ("a plus", "preferred", a "Preferred
qualifications" heading) never counts as a requirement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from resume_tailor.apply.funnel.screen import sentence_around


class Spoken(Protocol):
    """One profile language (`profile.LanguageEntry`)."""

    language: str
    fluent: bool


#: Languages a posting may require, as written → the key the check compares.
_NAMES = {
    name: name.lower()
    for name in (
        "English", "Spanish", "French", "German", "Italian", "Portuguese", "Dutch",
        "Swedish", "Norwegian", "Danish", "Finnish", "Icelandic", "Polish", "Czech",
        "Slovak", "Hungarian", "Romanian", "Bulgarian", "Greek", "Russian", "Ukrainian",
        "Serbian", "Croatian", "Bosnian", "Slovenian", "Albanian", "Estonian", "Latvian",
        "Lithuanian", "Turkish", "Arabic", "Hebrew", "Persian", "Dari", "Pashto",
        "Kurdish", "Armenian", "Hindi", "Urdu", "Bengali", "Punjabi", "Gujarati",
        "Marathi", "Tamil", "Telugu", "Kannada", "Malayalam", "Nepali", "Sinhala",
        "Chinese", "Mandarin", "Cantonese", "Japanese", "Korean", "Vietnamese", "Thai",
        "Khmer", "Burmese", "Indonesian", "Malay", "Tagalog", "Hmong", "Swahili",
        "Amharic", "Somali", "Tigrinya", "Yoruba", "Igbo", "Hausa", "Zulu", "Afrikaans",
        "Haitian Creole", "Catalan", "Basque", "Welsh", "Mongolian", "Uzbek", "Kazakh",
        "Azerbaijani", "Yiddish",
    )
} | {
    "Farsi": "persian",
    "Filipino": "tagalog",
    "Bangla": "bengali",
    "ASL": "asl",
    "American Sign Language": "asl",
}

#: What satisfies a required key, where it is not just itself.
_SATISFIED_BY = {
    "chinese": {"chinese", "mandarin", "cantonese"},
    "mandarin": {"mandarin", "chinese"},
    "cantonese": {"cantonese", "chinese"},
}


def _alternation(names: Iterable[str]) -> str:
    return "|".join(sorted(map(re.escape, names), key=len, reverse=True))


# Capitalised names only in a posting, so "polish the UI" is never Polish; a profile
# entry is matched in any case ("spanish (native)").
_POSTING_NAME = re.compile(rf"\b(?:{_alternation(_NAMES)})\b")
_PROFILE_NAME = re.compile(rf"\b(?:{_alternation(_NAMES)})\b", re.IGNORECASE)
_KEY_BY_LOWER = {name.lower(): key for name, key in _NAMES.items()}
#: "Polish the UI" at the start of a sentence is the verb.
_VERB = re.compile(r"Polish\s+(?:the|a|an|and|our|your|their|its?|up|off|existing|final)\b")
#: The lowercase word after a name, when there is one.
_NEXT_WORD = re.compile(r"\s+([a-z]+)")
#: Words that may follow a name used as a language; any other lowercase word makes it
#: the adjective ("a Dutch university", "Japanese clients").
_LANGUAGE_FOLLOWERS = frozenset(
    (
        "and", "or", "is", "are", "as", "at", "to", "in", "with", "both", "also", "plus",
        "would", "will", "must", "language", "languages", "speaker", "speakers", "speaking",
        "skill", "skills", "communication", "fluency", "fluent", "fluently", "proficiency",
        "proficient", "level", "business", "professional", "native", "written", "spoken",
        "verbal", "oral", "reading", "writing", "required", "preferred", "mandatory",
        "essential",
    )
)

#: A clause: sentences, plus semicolons and bullet marks inside one line.
_CLAUSE_END = re.compile(r"\n|;|•|(?<!\b[A-Za-z])[.?!](?=\s)")
#: How far from the language name a cue may sit.
_WINDOW = 80

#: Wording that asks for a level: a profile entry marked not fluent is then flagged.
_LEVEL = re.compile(
    r"\bfluen(?:t|cy|tly)\b|\bbilingual\b|\bnear[- ]native\b|\bmother tongue\b"
    r"|\bnative[- ](?:speaker|level|language|fluency|proficiency|or near)"
    r"|\bbusiness[- ](?:level|fluen\w*|proficien\w*)|\bprofessional (?:working )?proficiency\b"
    r"|\b[Cc][12]\b|\bJLPT\s*N[12]\b|\bHSK\s*[56]\b",
    re.IGNORECASE,
)
#: Wording that makes a language a requirement at any level.
_REQUIRED = re.compile(
    r"\brequired\b|\brequirement\b|\bmust\b|\bmandatory\b|\bessential\b|\bproficien(?:t|cy)\b"
    r"|\bability to (?:speak|read|write|communicate|converse)\b"
    r"|\bcommunicat\w* (?:\w+ ){0,2}in\b"
    r"|\b(?:written|verbal|spoken|oral)\s+(?:and|&)\s+(?:written|verbal|spoken|oral)\b",
    re.IGNORECASE,
)
#: Wording that makes the whole clause optional.
_OPTIONAL = re.compile(
    r"\bplus\b|\bprefer(?:red|ably|ence)\b|\bbonus\b|\bnice[- ]to[- ]have\b|\bdesir(?:ed|able)\b"
    r"|\bideally\b|\basset\b|\badvantage(?:ous)?\b|\bbeneficial\b|\bhelpful\b|\bwelcome[ds]?\b"
    r"|\bencouraged\b|\boptional\b|\bappreciated\b"
    r"|\bnot (?:a )?(?:required|requirement|necessary|mandatory)\b",
    re.IGNORECASE,
)
#: Wording that makes the clause's languages alternatives ("Spanish or Portuguese",
#: "a second language such as French").
_ANY_OF = re.compile(
    r"\bor\b|\beither\b|\bsuch as\b|\be\.g\.|\bany\b|\bone of\b|\bat least one\b"
    r"|\banother\b|\bsecond\b|\bforeign\b",
    re.IGNORECASE,
)
#: Section headings, read upward from a clause: an optional one makes it optional.
_OPTIONAL_HEADING = re.compile(
    r"^\W*(?:preferred|desired|bonus|nice[- ]to[- ]haves?|pluses|extra credit)\b", re.IGNORECASE
)
_REQUIRED_HEADING = re.compile(
    r"^\W*(?:required|minimum|basic|must[- ]haves?|requirements|qualifications"
    r"|what you(?:'|’)?ll (?:need|bring)|responsibilities|about (?:you|the role))\b",
    re.IGNORECASE,
)


def _clauses(text: str) -> Iterable[tuple[int, int]]:
    start = 0
    for match in _CLAUSE_END.finditer(text):
        yield start, match.start()
        start = match.end()
    yield start, len(text)


def _as_language(clause: str, match: re.Match[str]) -> bool:
    """Whether a name is the language, not the verb or a nationality adjective."""
    if _VERB.match(clause, match.start()):
        return False
    after = _NEXT_WORD.match(clause, match.end())
    return after is None or after.group(1) in _LANGUAGE_FOLLOWERS


def _heading(line: str) -> bool:
    words = line.split()
    return bool(words) and (len(words) <= 4 or (len(words) <= 6 and line.endswith(":")))


def _under_optional_heading(text: str, pos: int) -> bool:
    for line in reversed(text[:pos].splitlines()):
        line = line.strip()
        if not _heading(line):
            continue
        if _OPTIONAL_HEADING.match(line):
            return True
        if _REQUIRED_HEADING.match(line):
            return False
    return False


def _held(languages: Iterable[Spoken]) -> dict[str, bool]:
    """Profile language key → fluent, with English assumed fluent unless listed."""
    held: dict[str, bool] = {}
    for entry in languages:
        for match in _PROFILE_NAME.finditer(entry.language or ""):
            key = _KEY_BY_LOWER[match.group().lower()]
            held[key] = held.get(key, False) or bool(entry.fluent)
    return held


def _verdict(keys: list[str], level: bool, held: dict[str, bool], listed: bool) -> str:
    """``ok``, ``level`` (held but not fluent), ``unlisted`` or ``reason``."""
    have = [
        fluent
        for key in keys
        for name, fluent in held.items()
        if name in _SATISFIED_BY.get(key, {key})
    ]
    if any(have) or (have and not level):
        return "ok"
    if have:
        return "level"
    return "unlisted" if not listed else "reason"


def check(
    jd_text: str, languages: Iterable[Spoken] | None
) -> tuple[list[str], list[str], list[str]]:
    """``(reasons, flags, evidence)`` for the posting's language requirements.

    ``languages`` None skips the check (no profile could be read). A reason is
    ``language_required:<name>``; flags are ``language_level:<name>`` (listed, not
    fluent, and the posting asks for fluency) and ``language_unlisted:<name>`` (the
    profile lists no languages). Evidence is the posting sentence behind each reason.
    """
    if languages is None:
        return [], [], []
    held = _held(languages)
    listed = bool(held)
    held.setdefault("english", True)
    reasons: list[str] = []
    flags: list[str] = []
    evidence: list[str] = []
    for start, end in _clauses(jd_text):
        clause = jd_text[start:end]
        mentions = [m for m in _POSTING_NAME.finditer(clause) if _as_language(clause, m)]
        if not mentions or _OPTIONAL.search(clause) or _under_optional_heading(jd_text, start):
            continue
        cued = [
            m
            for m in mentions
            if (window := clause[max(0, m.start() - _WINDOW) : m.end() + _WINDOW])
            and (_LEVEL.search(window) or _REQUIRED.search(window))
        ]
        if not cued:
            continue
        level = bool(_LEVEL.search(clause))
        names = list(dict.fromkeys(m.group() for m in cued))
        groups = [names] if _ANY_OF.search(clause) else [[name] for name in names]
        for group in groups:
            verdict = _verdict([_NAMES[name] for name in group], level, held, listed)
            if verdict == "ok":
                continue
            label = " or ".join(group)
            if verdict == "reason":
                code = f"language_required:{label}"
                if code not in reasons:
                    reasons.append(code)
                    first = next(m for m in cued if m.group() == group[0])
                    evidence.append(
                        sentence_around(jd_text, start + first.start(), start + first.end())
                    )
            else:
                code = f"language_{verdict}:{label}"
                if code not in flags:
                    flags.append(code)
    return reasons, flags, evidence
