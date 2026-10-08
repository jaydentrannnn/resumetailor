"""Custom answers that restate a built-in profile field, and folding them into it.

A custom answer is canned text for a question the profile has no field for. One whose
question the classifier already maps to a profile field ("Are you at least 18 years of
age?" -> ``over_18``) is a second copy of the same fact; the Profile page flags it and
offers to merge it. Pure, no LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from resume_tailor.apply.answers import answer_memory, questions
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.content import dates

Kind = Literal["text", "bool", "day", "month"]


@dataclass(frozen=True)
class Target:
    """The built-in field a custom answer restates."""

    key: str
    attr: str
    kind: Kind


#: Canonical field key -> (profile attribute, value kind).
_TARGETS: dict[str, tuple[str, Kind]] = {
    "over_18": ("over_18", "bool"),
    "authorized_to_work": ("authorized_to_work", "bool"),
    "requires_sponsorship": ("requires_sponsorship_now", "bool"),
    "requires_sponsorship_future": ("requires_sponsorship_future", "bool"),
    "willing_to_relocate": ("willing_to_relocate", "bool"),
    "relatives_at_company": ("relatives_at_company", "bool"),
    "noncompete": ("subject_to_noncompete", "bool"),
    "drivers_license": ("drivers_license", "bool"),
    "earliest_start": ("earliest_start", "day"),
    "graduation_month": ("graduation_date", "month"),
    "notice_period": ("notice_period", "text"),
    "how_heard": ("how_heard", "text"),
    "referred_by": ("referred_by", "text"),
    "location_preference": ("location_preference", "text"),
    "highest_education_obtained": ("highest_education_obtained", "text"),
}
#: Wording the classifier has no rule for, but that names one of the fields above.
_EXTRA = (
    (re.compile(r"relatives?|family members?|related to", re.I), "relatives_at_company"),
    (re.compile(r"\breferred\b|\breferral\b", re.I), "referred_by"),
)
#: `ApplicantProfile` defaults that are placeholders, not something the applicant wrote.
_DEFAULT_TEXT = {"how_heard": ApplicantProfile.model_fields["how_heard"].default}


def target(question: str) -> Target | None:
    """The built-in field ``question`` restates, or None when it is a genuinely custom one."""
    text = question.strip()
    if not text or answer_memory.is_sensitive(text):
        return None
    match = questions.classify(questions.Question(text))
    key = match.key if match else None
    if key not in _TARGETS:
        key = next((name for rule, name in _EXTRA if rule.search(text)), None)
    if key not in _TARGETS:
        return None
    attr, kind = _TARGETS[key]
    return Target(key=key, attr=attr, kind=kind)


def duplicates(profile: ApplicantProfile) -> dict[str, str]:
    """``{custom question: profile attribute}`` for each custom answer that restates a field."""
    found: dict[str, str] = {}
    for question in profile.custom_answers:
        hit = target(question)
        if hit is not None:
            found[question] = hit.attr
    return found


def _value(kind: Kind, answer: str) -> object | None:
    text = answer.strip()
    if not text:
        return None
    if kind == "bool":
        head = text.casefold()
        return True if head.startswith(("yes", "true")) else False if head.startswith(("no", "false")) else None
    if kind in {"day", "month"}:
        normalized = dates.normalize(text, kind)  # type: ignore[arg-type]
        return normalized if dates.parse(normalized) is not None else None
    return text


def merge(profile: ApplicantProfile, question: str) -> ApplicantProfile:
    """Fold one custom answer into the field it restates, then drop the custom entry.

    The field is only written while it is unset (blank, or still the shipped default):
    a value the applicant already chose wins, and the redundant custom entry goes either
    way. An answer that cannot be read as the field's value ("Maybe" for a Yes/No)
    raises ``ValueError`` and nothing changes.
    """
    hit = target(question)
    if hit is None or question not in profile.custom_answers:
        raise KeyError(question)
    value = _value(hit.kind, profile.custom_answers[question])
    if value is None:
        raise ValueError(f"'{profile.custom_answers[question]}' cannot be used as {hit.attr.replace('_', ' ')}")
    current = getattr(profile, hit.attr)
    unset = current is None or (isinstance(current, str) and current.strip() in {"", _DEFAULT_TEXT.get(hit.key, "")})
    data = profile.model_dump()
    data["custom_answers"] = {k: v for k, v in profile.custom_answers.items() if k != question}
    if unset:
        data[hit.attr] = value
    return ApplicantProfile.model_validate(data)
