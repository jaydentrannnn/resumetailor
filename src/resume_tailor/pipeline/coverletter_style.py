"""Deterministic cover-letter style checks: AI tells, dashes, first person, numbers (no LLM)."""

from __future__ import annotations

import re

from ..content.data import Bullet
from .fabrication import _HAS_DIGIT, _TOKEN

#: Long dashes the model must never emit. Mechanical replacement is safe when one slips
#: through after a retry.
_LONG_DASHES = ("\u2012", "\u2013", "\u2014", "\u2015")

#: Phrase blocklist for AI-tell detection. Curated against ``style.DEFAULT_REWRITE_STYLE``
#: so it never blocks a verb the rewrite style recommends (e.g. "spearheaded").
_AI_PHRASES = (
    "delve",
    "tapestry",
    "testament to",
    "i am writing to apply",
    "in today's fast-paced",
    "moreover",
    "furthermore",
    "in conclusion",
    "it is worth noting",
    "seamless",
    "cutting-edge",
    "synergy",
    "passionate about",
    "excited about the opportunity",
    "resonates with",
    "wealth of experience",
    "proven track record",
    "hit the ground running",
    "deep dive",
    "unlock",
    "harness",
    "pivotal",
)

#: Structural patterns that read as template prose rather than a human voice.
_AI_STRUCTURAL = (
    re.compile(r"\bnot just\b.+\bbut\b", re.IGNORECASE),
    re.compile(r"\bit is not about\b.+\bit is about\b", re.IGNORECASE),
)

#: First-person verbs that mark a sentence as a resume claim worth checking.
_FIRST_PERSON_VERB = re.compile(
    r"\b(?:I|i)'?(?:ve|m|d)?\s+"
    r"(?:built|designed|developed|engineered|led|managed|created|implemented|"
    r"improved|increased|reduced|achieved|delivered|shipped|trained|mentored|"
    r"optimized|optimised|launched|deployed|wrote|coded|programmed|researched|"
    r"analyzed|analysed|worked|contributed|helped|used|applied)\b"
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

def ai_tells(text: str) -> list[str]:
    """Return AI-tell offenders found in ``text`` (long dashes, phrases, structures)."""
    offenders: list[str] = []
    lowered = text.lower()
    for dash in _LONG_DASHES:
        if dash in text:
            offenders.append(f"long dash {dash!r}")
    for phrase in _AI_PHRASES:
        if phrase in lowered:
            offenders.append(f"phrase {phrase!r}")
    for pattern in _AI_STRUCTURAL:
        if pattern.search(text):
            offenders.append(f"structure {pattern.pattern!r}")
    return list(dict.fromkeys(offenders))

def consecutive_first_person(paragraphs: list[str]) -> list[str]:
    """Return descriptions of consecutive sentences that both open with "I"."""
    offenders: list[str] = []
    for para in paragraphs:
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(para.strip()) if s.strip()]
        for prev, curr in zip(sentences, sentences[1:]):
            if prev.startswith("I ") and curr.startswith("I "):
                offenders.append(f'consecutive "I" after "{prev[:40]}..."')
    return offenders

def _replace_long_dashes(text: str) -> str:
    """Replace any surviving long dash with a comma and a space."""
    for dash in _LONG_DASHES:
        text = text.replace(dash, ", ")
    return re.sub(r",\s+,", ", ", text)

def _word_count(paragraphs: list[str]) -> int:
    """Count words across all body paragraphs."""
    return sum(len(p.split()) for p in paragraphs)

def _verbatim_in_jd(value: str, jd_text: str) -> bool:
    """Return True when ``value`` appears verbatim in the posting (case-insensitive)."""
    stripped = value.strip()
    if not stripped:
        return True
    return stripped.lower() in jd_text.lower()

def _numbers_not_in_source(
    text: str,
    source_bullets: list[Bullet],
    jd_text: str,
) -> list[str]:
    """Return number-bearing tokens in ``text`` absent from bullets or the posting."""
    allowed: set[str] = set()
    for match in _TOKEN.finditer(jd_text):
        term = match.group(0)
        if _HAS_DIGIT.search(term):
            allowed.add(term.lower())
    for bullet in source_bullets:
        for src in (bullet.text, " ".join(bullet.tags)):
            for match in _TOKEN.finditer(src):
                term = match.group(0)
                if _HAS_DIGIT.search(term):
                    allowed.add(term.lower())

    offenders: list[str] = []
    for match in _TOKEN.finditer(text):
        term = match.group(0)
        if _HAS_DIGIT.search(term) and term.lower() not in allowed:
            offenders.append(term)
    return list(dict.fromkeys(offenders))
