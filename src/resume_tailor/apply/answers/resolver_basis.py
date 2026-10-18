"""The support the resolver's model cites for an answer, checked in code (no LLM).

Every model action names its basis: a profile or packet field (``basis_key``), a resume
skill, or "no_effect" for a how-did-you-hear question. An action is applied only when that
basis has a value, the question is about that field, and the option chosen says what
the field says; anything else is left for the applicant (2026-10-17).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from resume_tailor.apply.answers import answer_memory, form_facts, questions, resolver_types
from resume_tailor.apply.forms import field_matcher

#: What a question about each field mentions. A field with no pattern here is accepted
#: only when the decision layer itself keys the question to it (`questions.classify`).
_LABELS = {
    "country": r"\b(?:country|nation)",
    "state": r"\b(?:state|province|region)\b",
    "city": r"\b(?:city|town|municipality)\b",
    "location": r"\b(?:location|located|city|where)\b",
    "school": r"\b(?:school|university|college|institution)\b",
    "degree_level": r"\b(?:degree|qualification|education level)\b",
    "major": r"\b(?:major|discipline|field of study)\b",
    "phone_device_type": r"\b(?:phone type|device type|mobile or landline)\b",
    "how_heard": r"how did you (?:hear|find|learn)|\bsource\b",
    "authorized_to_work": r"authori[sz]|eligib|legally|permit|right to work",
    "work_authorization": r"authori[sz]|eligib|legally|permit|right to work|visa|status",
    "requires_sponsorship": r"sponsor",
    "requires_sponsorship_future": r"sponsor",
    "requires_sponsorship_any": r"sponsor",
    "us_citizen": r"citizen",
    "us_person_status": r"citizen|permanent resident|green card|u\.?s\.? person|asylee|refugee",
    "citizenship": r"citizen|nationalit",
    "over_18": r"\b18\b|\bage\b",
    "willing_to_relocate": r"relocat",
    "drivers_license": r"driv",
    "security_clearance": r"clearance",
    "noncompete": r"non[- ]?compet|non[- ]?solicit|restrictive|agreement",
    "relatives_at_company": r"relative|family|related",
    "government_employee": r"government|public sector|federal|official|military",
    "veteran_status": r"veteran|military|armed forces|protected",
    "disability_status": r"disab",
    "gender": r"gender|\bsex\b|identify as",
    "race": r"\brace\b|ethn",
    "hispanic_latino": r"hispanic|latin",
    "languages": r"language|speak|fluen",
    "gpa": r"\bgpa\b|grade point",
    "graduation_month": r"graduat|complet|degree",
    "earliest_start": r"\bstart|availab",
    "notice_period": r"notice",
    "class_year": r"\byear\b|standing|grade level|class",
    "visa_status": r"visa|status|authori[sz]",
    "f1_opt_eligible": r"\bopt\b|f-?1",
    "previous_worker": r"previous|former|worked|employed",
    "experience_years": r"years|experience",
    "location_preference": r"location|prefer|office|\bsite\b|\bcity\b",
    "highest_education_obtained": r"degree|diploma|\bged\b|education",
}
#: Fields the decision layer may key a question to where the model cites the other: the
#: chosen option must still say what the cited field says (`_says`).
_RELATED = ({"authorized_to_work", "work_authorization"},)
#: Profile keys whose form-ready answer (`packet_fields`) has another name; the packet
#: value is read for them, so both sources say the same thing in the same words.
_PACKET_FIELD = {
    "requires_sponsorship_now": "requires_sponsorship",
    "subject_to_noncompete": "noncompete",
    "hours_per_week_available": "hours_per_week",
    "graduation_date": "graduation_month",
    "education_start_date": "education_start_month",
    "eeo.gender": "gender",
    "eeo.race": "race",
    "eeo.hispanic_latino": "hispanic_latino",
    "eeo.veteran": "veteran_status",
    "eeo.disability": "disability_status",
}
_HOW_HEARD = re.compile(_LABELS["how_heard"], re.I)
#: A skill question the resume's skill list cannot settle: how much, how long, how well.
_DEGREE_OF_SKILL = re.compile(
    r"\d|\byears?\b|proficien|expert|advanced|fluen|certif|licen|degree", re.I,
)
#: The one question a listed skill answers: a plain ask about that skill alone ("Do you
#: have experience with {skill}?"), never with another skill, a setting or a negation.
_SKILL_ASK = re.compile(
    r"^(?:do\s+you\s+have\s+(?:any\s+)?(?:hands[- ]on\s+)?(?:experience|familiarity|knowledge"
    r"|exposure)(?:\s+(?:working|programming|coding|developing))?\s+(?:with|in|using|of)"
    r"|have\s+you\s+(?:ever\s+)?(?:used|worked\s+(?:with|in)|programmed\s+in|coded\s+in)"
    r"|are\s+you\s+familiar\s+with|do\s+you\s+(?:know|use)"
    r"|(?:any\s+)?(?:experience|familiarity)\s+(?:with|in|using))\s+\{skill\}$"
)
#: A question one fact cannot answer as worded: negated ("Are you not authorized...?",
#: "Have you never...?"), or with a second question or requirement joined on ("... and
#: will you...?", "a driver's license and a car?").
_NEGATED = re.compile(r"\b(?:not|never|neither|nor|no\s+longer|lack\w*|without)\b|n't\b", re.I)
_NOT_NEGATION = re.compile(
    r"\bwith\s+or\s+without\b|\bif\s+(?:not|no)\b|\b(?:whether\s+)?or\s+not\b"
    r"|\bnot\s+(?:sure|only|required|mandatory|applicable)\b", re.I,
)
_SECOND_ASK = re.compile(
    r"\band\s+(?:(?:are|do|does|will|would|have|has|can|could|did|is|were)\s+you"
    r"|an?|own|reliable|access\s+to)\b", re.I,
)


def _as_worded(question: questions.Question) -> bool:
    """Whether a fact's answer can stand for ``question`` as worded (see `_NEGATED`)."""
    text = _NOT_NEGATION.sub(" ", question.text)
    return not _NEGATED.search(text) and not _SECOND_ASK.search(text)


def _value(value: Any) -> str:
    """``value`` as text, "" when absent or not a single value."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    return value.strip() if isinstance(value, str) else ""


def _lookup(facts: Mapping[str, Any], key: str) -> Any:
    """``facts[key]``, following a dotted path into a nested section ("eeo.gender")."""
    value: Any = facts
    for part in key.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _fact(
    action: resolver_types.FieldAction, question: questions.Question, *,
    profile: Mapping[str, Any], packet_fields: Mapping[str, Any],
) -> tuple[str, str, bool]:
    """(field, value, custom) the action's basis names; custom when it is one of the
    applicant's own saved answers, which decides only its very question."""
    key = action.basis_key.strip()
    if action.basis_kind == "packet":
        return key, _value(packet_fields.get(key)), False
    if key == "custom_answers" or key.startswith("custom_answers."):
        asked = answer_memory.normalize_label(question.text)
        saved = profile.get("custom_answers")
        for text, answer in (saved.items() if isinstance(saved, Mapping) else []):
            if asked and answer_memory.normalize_label(str(text)) == asked:
                return "", _value(answer), True
        return "", "", True
    field = _PACKET_FIELD.get(key, key)
    if field != key or field in packet_fields:
        return field, _value(packet_fields.get(field)), False
    return field, _value(_lookup(profile, key)), False


def _question(field: dict[str, Any]) -> questions.Question:
    kind = {"combobox": "typeahead", "radiogroup": "choice", "checkboxgroup": "multi"}.get(
        str(field.get("type") or ""), "text",
    )
    return questions.Question(
        str(field.get("label") or ""), kind=kind,
        options=tuple(str(option) for option in field.get("options") or []),
        help_text=str(field.get("help") or field.get("help_text") or ""),
    )


def _about(key: str, question: questions.Question) -> bool:
    """Whether ``question`` asks about field ``key``: its wording names the field, and the
    decision layer does not key it to a different one."""
    match = questions.classify(question)
    wanted = {key, questions.profile_field(key)}
    wanted |= {field for group in _RELATED if wanted & group for field in group}
    if match and not {match.key, questions.profile_field(match.key)} & wanted:
        return False
    pattern = _LABELS.get(key) or _LABELS.get(questions.profile_field(key))
    if pattern is None:
        return match is not None
    return bool(re.search(pattern, f"{question.text} {question.help_text}", re.I))


_NUMBER = r"(\d+(?:\.\d+)?)"
#: A numeric option's range: "3.5 - 3.74", "3.5 to 4.0", "3.5+", "3.5 or above", "Below 3.0".
_RANGES = (
    (re.compile(rf"^{_NUMBER}\s*(?:-|–|to)\s*{_NUMBER}$"), lambda low, high, x: low <= x <= high),
    (re.compile(rf"^{_NUMBER}\s*(?:\+|or\s+(?:above|higher|more|greater))$"),
     lambda low, x: x >= low),
    (re.compile(rf"^(?:above|over|greater\s+than|more\s+than)\s+{_NUMBER}$"),
     lambda low, x: x > low),
    (re.compile(rf"^(?:below|under|less\s+than)\s+{_NUMBER}$"), lambda high, x: x < high),
)


def _in_range(option: str, value: str) -> bool:
    """Whether numeric option ``option`` holds the number ``value`` ("3.8" in "3.75 - 4.0")."""
    try:
        number = float(re.sub(r"\s*/\s*4(?:\.0+)?$", "", value.strip()))
    except ValueError:
        return False
    text = " ".join(option.casefold().replace("gpa", "").split())
    for pattern, holds in _RANGES:
        found = pattern.match(text)
        if found:
            return bool(holds(*map(float, found.groups()), number))
    return False


def _languages(profile: Mapping[str, Any], question: questions.Question) -> set[str]:
    """The languages the profile lists, only the fluent (or native) ones for a question
    about fluency."""
    fluent = bool(re.search(r"fluen", f"{question.text} {question.help_text}", re.I))
    entries = profile.get("languages")

    def counts(entry: Mapping[str, Any]) -> bool:
        levels = " ".join(str(level) for level in (entry.get("levels") or {}).values())
        return not fluent or bool(entry.get("fluent")) or bool(
            re.search(r"fluen|native|bilingual", levels, re.I)
        )

    return {
        field_matcher.normalize(str(entry.get("language") or ""))
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, Mapping) and counts(entry)
    } - {""}


def _says(action: resolver_types.FieldAction, question: questions.Question, key: str,
          value: str) -> bool:
    """Whether the chosen option(s) say what the field's ``value`` says."""
    if key == "gpa" and action.action != "check_options" and _in_range(action.value, value):
        return True
    if action.action == "check_options":
        wanted = field_matcher.normalize(value)
        picked = [field_matcher.normalize(item) for item in action.value.split(" | ")]
        return bool(wanted) and all(item and (item in wanted or wanted in item) for item in picked)
    options = list(question.options)
    chosen = (questions.choose(question, questions.profile_field(key), [value]) if key else None
              ) or field_matcher.closest_option(options, value, key=key)
    return chosen is not None and field_matcher.normalize(chosen) == field_matcher.normalize(
        action.value
    )


def _from_resume(
    action: resolver_types.FieldAction, question: questions.Question, skills: list[str],
) -> bool:
    """A skill the resume lists, asked about by name: "Yes" to "experience with X?", or
    only listed skills ticked in a list of skills. Never how much or how long."""
    label = f"{question.text} {question.help_text}"
    if _DEGREE_OF_SKILL.search(label) or not _as_worded(question):
        return False
    if action.action == "check_options":
        picked = [item.strip() for item in action.value.split(" | ")]
        return all(item and field_matcher.same_skill_in(skills, item) for item in picked)
    term = action.basis_key.strip()
    asked = re.sub(rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])", "{skill}",
                   " ".join(question.text.casefold().split()), count=1, flags=re.I) if term else ""
    asked = re.sub(r"\s*(?:\(required\)|[?*:.\s])*$", "", asked)
    affirmative = field_matcher.affirmative_option(list(question.options))
    return bool(_SKILL_ASK.match(asked)) and field_matcher.same_skill_in(skills, term) and (
        affirmative is not None
        and field_matcher.normalize(affirmative) == field_matcher.normalize(action.value)
    )


def supported(
    action: resolver_types.FieldAction, field: dict[str, Any], *,
    profile: Mapping[str, Any], packet_fields: Mapping[str, Any], skills: Iterable[str],
) -> bool:
    """Whether the basis ``action`` cites supports the value it picks for ``field``."""
    question = _question(field)
    if action.basis_kind == "no_effect":
        # Only where any listed source is as true as another: never a yes/no question
        # ("were you referred?"), "consider me for other positions" or anything else.
        match = questions.classify(question)
        return (
            bool(_HOW_HEARD.search(f"{question.text} {question.help_text}"))
            and (match is None or match.key == "how_heard")
            and not questions.yes_no_options(question.options)
        )
    if action.basis_kind == "resume":
        return _from_resume(action, question, list(skills))
    if action.basis_kind in {"profile", "packet"} and action.basis_key.strip() == "languages":
        names = _languages(profile, question)
        picked = action.value.split(" | ") if action.action == "check_options" else [action.value]
        return bool(names) and _about("languages", question) and all(
            field_matcher.normalize(item) in names for item in picked
        )
    if (action.basis_kind in {"profile", "packet"}
            and action.basis_key.strip() == "auto_accept_routine_acknowledgements"):
        # The applicant's standing agreement to routine notices, for one the detector
        # itself reads as routine.
        agreed = _value(_lookup(profile, "auto_accept_routine_acknowledgements")) == "Yes"
        affirmative = field_matcher.affirmative_option(list(question.options))
        return agreed and form_facts.acknowledgement(question.text, question.help_text) == (
            "routine"
        ) and affirmative is not None and field_matcher.normalize(affirmative) == (
            field_matcher.normalize(action.value)
        )
    if action.basis_kind in {"profile", "packet"}:
        key, value, custom = _fact(action, question, profile=profile, packet_fields=packet_fields)
        if not value:
            return False
        if custom:  # the applicant's own answer to this very question
            return _says(action, question, "", value)
        if questions.yes_no_options(question.options) and not _as_worded(question):
            return False
        if key == "race" and re.search(r"hispanic|latin[oax]", action.value, re.I):
            # "Asian (Not Hispanic or Latino)" says two things; both must hold.
            said = "No" if re.search(r"\bnot\b|\bnon\b", action.value, re.I) else "Yes"
            if _value(packet_fields.get("hispanic_latino")) != said:
                return False
        return _about(key, question) and _says(action, question, key, value)
    return False
