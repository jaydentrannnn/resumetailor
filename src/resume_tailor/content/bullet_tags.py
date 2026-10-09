"""Which skills a bullet shows — computed, never maintained by hand.

A bullet's *match tags* drive JD matching (selection, coverage, the gap report, JD
canonicalisation). They are the union of three layers:

- **Extra skills** — `Bullet.tags`, whatever the user typed. The only layer that also
  extends the fabrication guard's whitelist and `<permitted_skills>`; those call sites
  read `bullet.tags` directly and must keep doing so.
- **Detected** — dictionary terms/spellings and the resume's own Skills items, project
  tech and coursework found in the bullet's text. Pure string matching, recomputed per run.
- **Inferred** — skills a model read into the text (`pipeline/tag_infer.py`), handed in
  through `annotate`. Matching only: never the whitelist, never the Skills pool.

Everything is canonicalised at read time through `config.canonical_tag`, so a vocabulary
edit changes what matches without ever rewriting resume data.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .. import config
from . import libraries

if TYPE_CHECKING:
    from .data import Bullet, MasterResume

#: Dictionary words that are also ordinary English ("the rest of the team", "a lean
#: budget"). Detected only when the text capitalises them ("REST", "Lean"); otherwise
#: they are left to the user's Extra skills or the model's inference.
AMBIGUOUS = frozenset({"rest", "lean", "node", "performance", "evaluation", "comps", "precedents"})

#: Longest resume-own phrase (Skills item, tech, course) treated as a detectable term.
_MAX_TERM_WORDS = 4


@dataclass
class _Annotation:
    """Per-run context set by `annotate`: the resume's own terms and inferred skills."""

    extra: frozenset[str] = frozenset()
    inferred: dict[str, tuple[str, ...]] = field(default_factory=dict)


_ANNOTATION = _Annotation()


@dataclass
class _Table:
    """One compiled phrase table; rebuilt when the vocabulary or resume terms change."""

    aliases: object
    terms: frozenset[str]
    extra: frozenset[str]
    canonical: dict[str, str]
    pattern: re.Pattern[str] | None
    hits: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)


_TABLE: _Table | None = None


def _norm(value: str) -> str:
    return " ".join(value.split()).lower()


def resume_terms(resume: MasterResume) -> frozenset[str]:
    """The resume's own short skill phrases: Skills items, project tech, coursework."""
    labels: list[str] = [item for group in resume.skills for item in group.items]
    labels += [tech for proj in resume.projects for tech in proj.tech]
    labels += [course for edu in resume.education for course in edu.coursework]
    return frozenset(
        n for n in (_norm(label) for label in labels) if n and len(n.split()) <= _MAX_TERM_WORDS
    )


def _table(extra: frozenset[str]) -> _Table:
    global _TABLE
    aliases = config.TAG_ALIASES
    terms = libraries.resolve_effective().terms
    cached = _TABLE
    if cached and cached.aliases is aliases and cached.terms is terms and cached.extra == extra:
        return cached
    canonical: dict[str, str] = {}
    for alias, target in aliases.items():
        canonical.setdefault(_norm(alias), config.canonical_tag(target))
        canonical.setdefault(_norm(target), config.canonical_tag(target))
    for term in (*terms, *extra):
        key = _norm(term)
        if key:
            canonical.setdefault(key, config.canonical_tag(key))
    # Longest first, so "machine learning" wins over "learning" at the same position.
    phrases = sorted(canonical, key=len, reverse=True)
    pattern = (
        re.compile(
            r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, phrases)) + r")(?![a-z0-9])",
            re.IGNORECASE,
        )
        if phrases
        else None
    )
    _TABLE = _Table(aliases, terms, extra, canonical, pattern)
    return _TABLE


def _accept(phrase: str, surface: str) -> bool:
    """One- and two-letter names ("r", "go") need capitals; so do `AMBIGUOUS` words."""
    if len(phrase) <= 2:
        return surface == surface.upper()
    if phrase in AMBIGUOUS:
        return surface != surface.lower()
    return True


def detect(text: str, extra: Iterable[str] = ()) -> list[tuple[str, str]]:
    """`(canonical, surface)` for every known skill `text` names, in text order, deduped.

    Candidates are the effective dictionary (terms and spellings) plus `extra` — normally
    `resume_terms(resume)`, so a skill outside the dictionary still counts once the user
    lists it in their Skills section.
    """
    table = _table(frozenset(_norm(e) for e in extra))
    if table.pattern is None:
        return []
    if text not in table.hits:
        found: dict[str, str] = {}
        for match in table.pattern.finditer(text):
            surface = match.group(0)
            phrase = _norm(surface)
            if phrase in table.canonical and _accept(phrase, surface):
                found.setdefault(table.canonical[phrase], surface)
        table.hits[text] = tuple(found.items())
    return list(table.hits[text])


def annotate(resume: MasterResume, inferred: Mapping[str, Iterable[str]] | None = None) -> None:
    """Install this run's context: `resume`'s own terms and inferred skills by bullet text.

    Process-wide like `config._ACTIVE` (runs are one at a time). Inferred skills are keyed
    by text, so a bullet rebuilt mid-run (`fit_shrink`, `bullet_merge`) with the same text
    still finds them, and one with new text simply falls back to detection.
    """
    global _ANNOTATION
    _ANNOTATION = _Annotation(
        extra=resume_terms(resume),
        inferred={
            text: tuple(sorted({config.canonical_tag(s) for s in skills if s.strip()}))
            for text, skills in (inferred or {}).items()
        },
    )


def clear() -> None:
    """Drop the run context (test seam; `annotate` replaces it wholesale anyway)."""
    global _ANNOTATION
    _ANNOTATION = _Annotation()


def user_tags(bullet: Bullet) -> set[str]:
    """The bullet's Extra skills, canonicalised."""
    return {config.canonical_tag(t) for t in bullet.tags if t.strip()}


def match_tags(bullet: Bullet, *, inferred: bool = True) -> frozenset[str]:
    """Extra skills ∪ detected ∪ inferred, canonical — the JD matching key.

    `inferred=False` keeps only what the user wrote (merge affinity wants that).
    """
    tags = user_tags(bullet)
    tags |= {canonical for canonical, _ in detect(bullet.text, _ANNOTATION.extra)}
    if inferred:
        tags |= set(_ANNOTATION.inferred.get(bullet.text, ()))
    return frozenset(tags)


def skill_evidence(bullet: Bullet) -> list[str]:
    """Labels this bullet evidences for the Skills section: Extra skills as typed, then
    detected skills by their surface text ("DCF", never the expansion). No inferred."""
    labels = [t for t in bullet.tags if t.strip()]
    have = user_tags(bullet)
    for canonical, surface in detect(bullet.text, _ANNOTATION.extra):
        if canonical not in have:
            have.add(canonical)
            labels.append(surface)
    return labels


def known_terms(resume: MasterResume) -> list[str]:
    """Every canonical skill any bullet of `resume` matches — JD canonicalisation's
    vocabulary (`known_tags`) and the gap report's "available" set."""
    extra = resume_terms(resume)
    found: set[str] = set()
    for bullet in resume.all_bullets():
        found |= user_tags(bullet)
        found |= {canonical for canonical, _ in detect(bullet.text, extra)}
        found |= set(_ANNOTATION.inferred.get(bullet.text, ()))
    return sorted(found)
