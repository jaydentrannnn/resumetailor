"""Pure, conservative matching for both native and custom choices."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel

from resume_tailor.apply.field_types import ObservedOption


class OptionMatch(BaseModel):
    status: Literal["matched", "no_match", "ambiguous", "unsupported"]
    option_id: str = ""
    method: Literal["exact_label", "exact_value", "alias", ""] = ""


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w+]+", " ", plain).split())


_ALIASES: dict[str, dict[str, set[str]]] = {
    "country": {"united states": {"us", "usa", "united states of america"}},
    "school": {
        "university of california irvine": {"uc irvine", "uci"},
    },
    "degree_level": {
        "bachelors": {"bachelor", "bachelors degree", "bachelor s degree"},
        "bachelor": {"bachelors", "bachelors degree", "bachelor s degree"},
    },
    "race_detail": {"southeast asian": {"south east asian"}},
}


def _skill_norm(value: str) -> str:
    """Like ``normalize`` but keeps ``#`` and ``.`` so C# is not C and .NET is not NET."""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w+#.]+", " ", plain).strip(" .").split())


_PARENTHETICAL = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")


def _skill_forms(text: str) -> set[str]:
    """``Retrieval-Augmented Generation (RAG)`` -> the whole, the name, and the abbreviation."""
    forms = {_skill_norm(text)}
    match = _PARENTHETICAL.match(text.strip())
    if match:
        forms |= {_skill_norm(match.group(1)), _skill_norm(match.group(2))}
    return forms - {""}


def match_skill_option(options: list[str], skill: str) -> str | None:
    """Pick the one skill-search option that names ``skill`` exactly, or None.

    Exact text wins; otherwise a ``Name (ABBR)`` option matches on its name or its
    abbreviation (RAG -> "Retrieval-Augmented Generation (RAG)"), and a skill written
    that way matches either part. Never a partial or substring match; identical labels
    (one skill listed under two categories) count once; any other tie returns None.
    """
    wanted = _skill_norm(skill)
    if not wanted:
        return None
    unique = list(dict.fromkeys(option.strip() for option in options if option.strip()))
    exact = [option for option in unique if _skill_norm(option) == wanted]
    if exact:
        return exact[0] if len(exact) == 1 else None
    forms = _skill_forms(skill)
    related = [option for option in unique if forms & _skill_forms(option)]
    return related[0] if len(related) == 1 else None


def match_option(
    options: list[ObservedOption], target: str, *, key: str = "",
) -> OptionMatch:
    wanted = normalize(target)
    if not wanted:
        return OptionMatch(status="unsupported")
    available = [option for option in options if option.enabled and not option.placeholder]
    for method, field in (("exact_label", "label"), ("exact_value", "value")):
        matches = [option for option in available if normalize(getattr(option, field)) == wanted]
        if len(matches) == 1:
            return OptionMatch(status="matched", option_id=matches[0].option_id, method=method)
        if len(matches) > 1:
            return OptionMatch(status="ambiguous")
    aliases = _ALIASES.get(key, {}).get(wanted, set())
    matches = [
        option for option in available
        if normalize(option.label) in aliases or normalize(option.value) in aliases
    ]
    if len(matches) == 1:
        return OptionMatch(status="matched", option_id=matches[0].option_id, method="alias")
    if not matches and key == "degree_level":
        return _match_degree(available, target)
    if not matches and key == "language_level":
        return _match_level(available, target)
    pattern = eeo_pattern(key, target)
    if not matches and pattern:
        rule = re.compile(pattern)
        matches = [option for option in available if rule.search(normalize(option.label))]
        if len(matches) == 1:
            return OptionMatch(status="matched", option_id=matches[0].option_id, method="alias")
    return OptionMatch(status="ambiguous" if matches else "no_match")


#: Language proficiency wording by rank, most specific first ("limited working" is 2,
#: not the bare "limited" of rank 1).
_LEVEL_RANKS: tuple[tuple[str, int], ...] = (
    (r"\bnative\b|\bbilingual\b|\bmother tongue\b", 5),
    (r"\bfull professional\b|\bfluent\b|\bexpert\b", 4),
    (r"\bprofessional working\b|\badvanced\b|\bproficient\b", 3),
    (r"\blimited working\b|\bintermediate\b|\bconversational\b|\bmoderate\b", 2),
    (r"\belementary\b|\bbeginner\b|\bbasic\b|\bnovice\b|\blimited\b", 1),
)


def level_rank(text: str) -> int | None:
    """1 (beginner) .. 5 (native) for a proficiency answer or option, else None."""
    wanted = normalize(text)
    return next((rank for pattern, rank in _LEVEL_RANKS if re.search(pattern, wanted)), None)


def _match_level(available: list[ObservedOption], target: str) -> OptionMatch:
    """The one option of the same rank; a scale without that rank takes its highest rank
    below it (a "Fluent" applicant is at least "Advanced"), never a higher one."""
    wanted = level_rank(target)
    if wanted is None:
        return OptionMatch(status="no_match")
    ranked = [(option, level_rank(option.label)) for option in available]
    below = sorted({rank for _option, rank in ranked if rank is not None and rank <= wanted}, reverse=True)
    if not below:
        return OptionMatch(status="no_match")
    matches = [option for option, rank in ranked if rank == below[0]]
    if len(matches) == 1:
        return OptionMatch(status="matched", option_id=matches[0].option_id, method="alias")
    return OptionMatch(status="ambiguous")


#: Self-identification keys whose options word the answer at length ("No, I do not have
#: a disability and have not had one in the past" for "No").
EEO_KEYS = frozenset({"gender", "race", "race_detail", "hispanic_latino", "veteran_status", "disability_status"})
#: Declining to self-identify, as forms word it (patterns run on ``normalize``d text).
_DECLINE = (r"\bdecline\b|\b(?:do not|don t) (?:want|wish) to\b|\bprefer not\b|\bchoose not\b"
            r"|\bnot (?:to )?(?:disclose|answer|self identify)\b")
_YES = frozenset({"yes", "y", "true"})
_NO = frozenset({"no", "n", "false"})
_EEO_RULES: dict[str, dict[str, str]] = {
    "disability_status": {
        "yes": r"^yes\b.*\bhave\b.*\bdisabilit",
        "no": r"^no\b.*\b(?:do not|don t) have\b.*\bdisabilit",
    },
    "veteran_status": {
        "yes": r"^(?!.*\bnot\b).*\b(?:identify as|i am a|am a protected)\b.*\bveteran",
        # Not "I identify as a veteran, just not a protected veteran" (CACI, 2026-09):
        # that applicant is a veteran.
        "no": r"^(?!.*\b(?:identify as|i am) a veteran\b).*\b(?:am not|not a)\b(?: protected)? veteran\b",
    },
    "hispanic_latino": {
        "yes": r"^(?!.*\bnot\b)(?:yes\b|hispanic or latino\b)",
        "no": r"^no\b|\bnot hispanic\b",
    },
    "gender": {
        "male": r"^(?:male|man)\b",
        "female": r"^(?:female|woman)\b",
    },
}


def eeo_pattern(key: str, answer: str) -> str | None:
    """Regex (over ``normalize``d option text) for a self-identification answer, or None.

    Deterministic and conservative: "No" picks the one option that says the applicant
    has no disability / is not a protected veteran; "decline" picks the decline option;
    a race or gender answer also matches an option that starts with it ("Asian (United
    States of America)"). A caller treats more than one hit as no answer.
    """
    wanted = normalize(answer)
    if key not in EEO_KEYS or not wanted:
        return None
    if wanted == "decline" or re.search(_DECLINE, wanted):
        return _DECLINE
    rules = _EEO_RULES.get(key, {})
    choice = "yes" if wanted in _YES else "no" if wanted in _NO else wanted
    if choice in rules:
        return rules[choice]
    if key in {"gender", "race", "race_detail"} and choice not in {"yes", "no"}:
        return rf"^{re.escape(wanted)}\b"
    return None


def eeo_patterns(fields: dict[str, str]) -> dict[str, str]:
    """``eeo_pattern`` for every self-identification answer in ``fields`` (filler.js)."""
    patterns = {key: eeo_pattern(key, fields.get(key, "")) for key in EEO_KEYS}
    return {key: pattern for key, pattern in patterns.items() if pattern}


#: Named degrees and the abbreviations forms print for them, normalised ("B.S." -> "b s").
_DEGREES: dict[str, tuple[str, ...]] = {
    "bachelor of science": ("bs", "b s", "bsc", "b sc"),
    "bachelor of arts": ("ba", "b a"),
    "bachelor of science in engineering": ("bse", "b s e"),
    "bachelor of engineering": ("be", "b e", "beng", "b eng"),
    "bachelor of fine arts": ("bfa", "b f a"),
    "bachelor of business administration": ("bba", "b b a"),
    "master of science": ("ms", "m s", "msc", "m sc"),
    "master of arts": ("ma", "m a"),
    "master of engineering": ("meng", "m eng"),
    "master of business administration": ("mba", "m b a"),
    "doctor of philosophy": ("phd", "ph d"),
    "associate of science": ("as", "a s"),
    "associate of arts": ("aa", "a a"),
}
_DEGREE_BY_ABBREVIATION = {abbr: name for name, abbrs in _DEGREES.items() for abbr in abbrs}
#: A level with no field named ("Bachelor's Degree").
_DEGREE_LEVELS = {
    "bachelor": "bachelor", "bachelors": "bachelor", "bachelor s": "bachelor",
    "master": "master", "masters": "master", "master s": "master",
    "associate": "associate", "associates": "associate", "associate s": "associate",
    "doctorate": "doctor", "doctoral": "doctor",
}


def _degree_part(text: str) -> tuple[str, str] | None:
    wanted = re.sub(r"\s+degree$", "", normalize(text))
    if wanted in _DEGREES:
        return wanted.split()[0], wanted
    if wanted in _DEGREE_BY_ABBREVIATION:
        name = _DEGREE_BY_ABBREVIATION[wanted]
        return name.split()[0], name
    # "Bachelor of Science in Computer Science" -> "Bachelor of Science".
    subject = re.match(r"^(\w+ of [\w ]+?) in \w", wanted)
    if subject and subject.group(1) in _DEGREES:
        return subject.group(1).split()[0], subject.group(1)
    # "BS Computer Science" / "B.S. in Computer Science" (longest abbreviation first), but
    # not "BA/BS", which names two degrees.
    for abbr in sorted(_DEGREE_BY_ABBREVIATION, key=len, reverse=True):
        if wanted.startswith(abbr + " "):
            if set(wanted[len(abbr):].split()) & _DEGREE_BY_ABBREVIATION.keys():
                return None
            name = _DEGREE_BY_ABBREVIATION[abbr]
            return name.split()[0], name
    if wanted in _DEGREE_LEVELS:
        return _DEGREE_LEVELS[wanted], ""
    return None


def degree_of(text: str) -> tuple[str, str] | None:
    """(level, named degree or "") for a degree answer or option, else None.

    "BS", "B.S.", "BSc" and "Bachelor of Science (B.S.)" all read as ("bachelor",
    "bachelor of science"); "Bachelor's Degree" reads as ("bachelor", "").
    """
    parts = [text]
    decorated = _PARENTHETICAL.match(text.strip())
    if decorated:
        parts = [decorated.group(1), decorated.group(2)]
    found = [degree for degree in map(_degree_part, parts) if degree]
    # A name beats a bare level: "Bachelor's Degree (B.S.)" is a Bachelor of Science.
    return max(found, key=lambda degree: bool(degree[1]), default=None)


def _match_degree(available: list[ObservedOption], target: str) -> OptionMatch:
    """A named degree picks its own name or abbreviation, else the bare level; a bare
    level never picks a named degree (Bachelors could be the BS or the BA)."""
    wanted = degree_of(target)
    if wanted is None:
        return OptionMatch(status="no_match")
    parsed = [(option, degree_of(option.label) or degree_of(option.value)) for option in available]
    tiers = [[option for option, degree in parsed if degree == wanted]]
    if wanted[1]:
        tiers.append([option for option, degree in parsed if degree == (wanted[0], "")])
    for matches in tiers:
        if len(matches) == 1:
            return OptionMatch(status="matched", option_id=matches[0].option_id, method="alias")
        if matches:
            return OptionMatch(status="ambiguous")
    return OptionMatch(status="no_match")


#: Words that name an institution's kind, not the institution: searching them alone
#: returns hundreds of schools.
_SCHOOL_GENERIC = frozenset({
    "university", "college", "of", "the", "at", "and", "state", "institute", "technology",
    "school", "community", "polytechnic",
})
#: "University of California - Irvine" / "California State University, Long Beach" /
#: "University of Wisconsin at Madison": the campus follows the last separator.
_CAMPUS = re.compile(r"(?:\s[-–—]\s|,\s*|\sat\s)([^,\-–—]+)$", re.I)


def search_terms(key: str, value: str) -> list[str]:
    """Ordered search strings for a searchable prompt, most specific first.

    Workday's school search does not find "University of California - Irvine" typed in
    full, but finds it from the campus ("Irvine"); the typed term only filters the list,
    the committed option is still chosen by ``closest_option``.
    """
    value = value.strip()
    if not value:
        return []
    terms = [value]
    if key == "school":
        campus = _CAMPUS.search(value)
        if campus:
            terms.append(campus.group(1).strip())
        distinctive = [word for word in re.findall(r"[\w']+", value) if word.casefold() not in _SCHOOL_GENERIC]
        if distinctive:
            terms.append(" ".join(distinctive))
        if normalize(value) == "university of california irvine":
            terms.append("UC Irvine")
    elif key == "degree_level":
        if normalize(value).startswith("bachelor"):
            terms.insert(0, "bachelor")
        # A list of abbreviations ("BS", "BA") filters to nothing on "bachelor".
        named = degree_of(value)
        if named and named[1]:
            terms.append(_DEGREES[named[1]][0].upper())
    return list(dict.fromkeys(term for term in terms if term))


#: Keys whose options commonly decorate the answer ("University of California, Irvine
#: (UCI)", "LinkedIn Job Posting"), so one option containing every word may stand for it.
_CONTAINS_KEYS = frozenset({"school", "major", "how_heard", "degree_level", "language"})


def closest_option(options: list[str], value: str, *, key: str = "") -> str | None:
    """Exact/alias match first; then, for ``_CONTAINS_KEYS``, the single option whose
    words include every word of ``value``. A tie is no answer (left for review)."""
    observed = [ObservedOption(option_id=str(index), label=label, value=label) for index, label in enumerate(options)]
    result = match_option(observed, value, key=key)
    if result.status == "matched":
        return options[int(result.option_id)]
    if result.status == "ambiguous" or key not in _CONTAINS_KEYS:
        return None
    wanted = set(normalize(value).split())
    if not wanted:
        return None
    unique = list(dict.fromkeys(option for option in options if option.strip()))
    containing = [option for option in unique if wanted <= set(normalize(option).split())]
    return containing[0] if len(containing) == 1 else None


_MOBILE_DEVICE = frozenset({"mobile", "cell", "cell phone", "mobile phone"})


def fallback_values(key: str, value: str) -> list[str]:
    """Answers to try in order: "How did you hear" falls back to "Other" (the source is
    then typed into the form's "please specify" follow-up as ``how_heard_detail``)."""
    if not value:
        return []
    if key == "how_heard" and normalize(value) != "other":
        return [value, "Other"]
    if key == "phone_device_type" and normalize(value) in _MOBILE_DEVICE:
        # Tenants name the same device "Mobile", "Cell" or "Mobile Phone".
        return list(dict.fromkeys([value, "Mobile", "Cell", "Mobile Phone", "Cell Phone"]))
    return [value]


def choice_values(key: str, fields: dict[str, str]) -> list[str]:
    """Answers to try for a choice control, most specific first: the race detail before
    the race, the named degree ("Bachelor of Science", which also matches "BS" and falls
    back to a bare "Bachelor's" option) before the profile's level ("Bachelors")."""
    value = fields.get(key, "")
    if key == "race":
        candidates = [fields.get("race_detail", ""), value]
    elif key == "degree_level" and value:
        candidates = [fields.get("degree_name", ""), value]
    else:
        candidates = fallback_values(key, value)
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))
