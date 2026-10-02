"""When a facet rename is anchored in the JD and keeps the original claim (pure)."""

from __future__ import annotations

import re

from .. import config
from .jd import JobRequirements

#: Word tokens for acronym / containment checks (letters and digits only).
_WORDS_ONLY = re.compile(r"[A-Za-z0-9]+")

#: Acronym lengths considered when expanding consecutive source words.
_INITIALISM_LENGTHS = (2, 3, 4, 5)

def _norm_ws(text: str) -> str:
    """Lowercase and collapse whitespace for JD anchoring comparisons."""
    return " ".join(text.lower().split())

def _alnum_compact(text: str) -> str:
    """Lowercase alphanumeric-only form for prefix / containment checks."""
    return "".join(_WORDS_ONLY.findall(text.lower()))

def _token_set(text: str) -> set[str]:
    """Lowercase word tokens from `text`."""
    return {w.lower() for w in _WORDS_ONLY.findall(text)}

def _initialisms_from(text: str) -> set[str]:
    """Acronyms formable from consecutive words in `text` (lowercase)."""
    out: set[str] = set()
    words = _WORDS_ONLY.findall(text)
    for n in _INITIALISM_LENGTHS:
        for i in range(len(words) - n + 1):
            out.add("".join(w[0] for w in words[i : i + n]).lower())
    return out

def _jd_anchors(requirements: JobRequirements) -> set[str]:
    """Normalised JD phrases and canonicals a rename may target."""
    anchors: set[str] = set()
    for kw in requirements.keywords:
        if kw.phrase.strip():
            anchors.add(_norm_ws(kw.phrase))
        if kw.canonical.strip():
            anchors.add(_norm_ws(kw.canonical))
    return anchors

def rename_is_jd_anchored(new_label: str, requirements: JobRequirements) -> bool:
    """True when `new_label` matches a JD keyword phrase or canonical."""
    target = _norm_ws(new_label)
    if not target:
        return False
    return target in _jd_anchors(requirements)

def _aligns(a: str, b: str) -> bool:
    """True when every word of `a` maps in order onto `b`, expanding acronyms.

    Greedy left-to-right: a word matches a `b` word by prefix either way (with a 2-char
    floor on both sides — see below), or a run of 2-5 `b` words whose initials spell it
    ("RAG" -> "retrieval augmented generation"). Requires BOTH sides fully consumed, so
    alignment can never drop a claim — that is why `rename_preserves_claim` can
    short-circuit on it.

    The 2-char floor on the prefix branch closes the same hole `labels_are_equivalent`'s
    alphanumeric-prefix branch had: every word "starts with" any single-letter word, so
    without it `_aligns("curiosity", "C++")` and `_aligns("R", "React")` both spuriously
    return `True` — reproduced live via `report.diagnose_gaps` misreporting a posting's
    "Curiosity" requirement as evidenced by this resume's "C++" skill. An exact match
    (line below) is exempt from the floor: two single-letter words that are actually
    equal is a real identity, not a hole.
    """
    a_words = [w.lower() for w in _WORDS_ONLY.findall(a)]
    b_words = [w.lower() for w in _WORDS_ONLY.findall(b)]
    i = j = 0
    while i < len(a_words) and j < len(b_words):
        word = a_words[i]
        b_word = b_words[j]
        if b_word == word or (
            min(len(word), len(b_word)) >= 2
            and (b_word.startswith(word) or word.startswith(b_word))
        ):
            i += 1
            j += 1
            continue
        matched = False
        for n in _INITIALISM_LENGTHS:
            if j + n > len(b_words):
                continue
            if "".join(w[0] for w in b_words[j : j + n]) == word:
                i += 1
                j += n
                matched = True
                break
        if not matched:
            return False
    return i == len(a_words) and j == len(b_words)

def labels_are_equivalent(old: str, new: str) -> bool:
    """True when `new` names the same technology as `old` under the rename rules.

    Accepts: identical after ``canonical_tag``, acronym expansion either way, alphanumeric
    *prefix* containment either way, full token-set containment either way, or a full
    word-by-word alignment that expands an acronym embedded in a longer phrase (``RAG
    pipelines`` <-> ``retrieval-augmented generation pipelines``).
    Rejects substring-only matches (so ``SQL`` does not license ``MySQL``).
    """
    if not old.strip() or not new.strip():
        return False
    if config.canonical_tag(old) == config.canonical_tag(new):
        return True

    old_n, new_n = _norm_ws(old), _norm_ws(new)
    if old_n == new_n:
        return True

    # Acronym: GRPO <-> Group Relative Policy Optimization (either direction).
    old_acro = _alnum_compact(old)
    new_acro = _alnum_compact(new)
    if len(old_acro) >= 2 and old_acro in _initialisms_from(new):
        return True
    if len(new_acro) >= 2 and new_acro in _initialisms_from(old):
        return True

    # Prefix containment on alphanumerics (postgres / postgresql), not bare substring.
    # A floor of 2 chars on *both* sides matters: `_alnum_compact("C++")` is `"c"` (the
    # `+`s are stripped by `_WORDS_ONLY`), so without the floor `"cloudcomputing"` and
    # `"react"` both spuriously "start with" a single letter and `labels_are_equivalent`
    # would license "C++" -> "cloud computing" or "R" -> "React". 2 is the minimal floor
    # that still keeps legitimate short renames like Go/Golang and CI/CI-CD.
    if (
        old_acro
        and new_acro
        and min(len(old_acro), len(new_acro)) >= 2
        and (old_acro.startswith(new_acro) or new_acro.startswith(old_acro))
    ):
        return True

    old_tokens, new_tokens = _token_set(old), _token_set(new)
    if old_tokens and new_tokens and (old_tokens <= new_tokens or new_tokens <= old_tokens):
        return True

    # Whole-phrase alignment: an acronym embedded alongside other words, not just the
    # entire label (LLM fine-tuning <-> large language model fine-tuning).
    return bool(_aligns(old, new) or _aligns(new, old))

#: Characters that join *distinct* claims inside one label. "." "-" "+" "#" are internal
#: to a single name (Next.js, scikit-learn, C++) and are deliberately NOT split on.
_CLAIM_SPLIT = re.compile(r"[\s/&,;]+")

def _claim_parts(text: str) -> list[str]:
    """Split `text` into distinct claims for `rename_preserves_claim`."""
    return [p for p in _CLAIM_SPLIT.split(text) if p]

def rename_preserves_claim(old: str, new: str) -> bool:
    """True when `new` does not drop anything `old` claims (the "not less" guard).

    `labels_are_equivalent` alone accepts token-set containment, alphanumeric prefix
    containment, and sub-phrase acronyms — all safe for single-word project tags but
    unsafe for skill *phrases*, where each lets a rename narrow to part of what the item
    claims (``"hybrid retrieval & reranking" -> "retrieval"``,
    ``"Scikit-learn/XGBoost" -> "scikit-learn"``, ``"hybrid retrieval & reranking" ->
    "HR"``). This is deliberately a separate predicate rather than a flag on
    `labels_are_equivalent`, since narrowing arrives via three different branches there
    and a single flag cannot close all three without also touching project-tag behaviour.
    """
    if _aligns(old, new) or _aligns(new, old):
        return True  # full word-by-word coverage either way: nothing dropped
    if len(_claim_parts(old)) <= 1:
        return True  # a single claim cannot lose a claim by being respelled
    new_tokens = _token_set(new)
    return all(
        any(t == word or t.startswith(word) for t in new_tokens)
        for word in _token_set(old)
    )
