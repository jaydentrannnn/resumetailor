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
    return OptionMatch(status="ambiguous" if matches else "no_match")
