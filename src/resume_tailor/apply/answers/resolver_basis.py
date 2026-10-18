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

from resume_tailor.apply.answers import answer_memory, questions, resolver_types
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
    "gender": r"gender|\bsex\b",
    "race": r"\brace\b|ethnic",
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
}
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
    wanted = questions.profile_field(key)
    if match and match.key != key and questions.profile_field(match.key) != wanted:
        return False
    pattern = _LABELS.get(key) or _LABELS.get(wanted)
    if pattern is None:
        return match is not None
    return bool(re.search(pattern, f"{question.text} {question.help_text}", re.I))


def _says(action: resolver_types.FieldAction, question: questions.Question, key: str,
          value: str) -> bool:
    """Whether the chosen option(s) say what the field's ``value`` says."""
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
    if _DEGREE_OF_SKILL.search(label):
        return False
    if action.action == "check_options":
        picked = [item.strip() for item in action.value.split(" | ")]
        return all(item and field_matcher.same_skill_in(skills, item) for item in picked)
    term = action.basis_key.strip()
    named = bool(term) and re.search(rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])", label, re.I)
    affirmative = field_matcher.affirmative_option(list(question.options))
    return bool(named) and field_matcher.same_skill_in(skills, term) and (
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
    if action.basis_kind in {"profile", "packet"}:
        key, value, custom = _fact(action, question, profile=profile, packet_fields=packet_fields)
        if not value:
            return False
        if custom:
            return _says(action, question, "", value)
        return _about(key, question) and _says(action, question, key, value)
    return False
