"""JD-text similarity for advisory reuse of a prior run's tailored bullets.

Pure functions, no I/O. Thresholds match career-ops' jd-similarity bands; seniority
mismatch forces `regenerate` because we already have a validated enum from extraction
and do not need their regex false-friend table.
"""

from __future__ import annotations

import re
from typing import Literal

from .jd import JobRequirements

Recommendation = Literal["reuse", "reuse_with_edits", "regenerate"]

#: Inclusive lower bounds — career-ops' measured cutoffs.
_REUSE_FLOOR = 0.72
_EDITS_FLOOR = 0.45

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens from JD text."""
    return set(_TOKEN.findall(text.lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets; 0.0 when both are empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def recommend_reuse(
    current_jd: str,
    prior_jd: str,
    *,
    current_requirements: JobRequirements | None = None,
    prior_requirements: JobRequirements | None = None,
) -> tuple[Recommendation, float]:
    """Return `(recommendation, jaccard_score)` for reusing a prior run against `current_jd`.

    A seniority mismatch between validated extractions forces `regenerate` regardless of
    lexical overlap — the roles are different even when the postings share vocabulary.
    """
    score = jaccard(tokenize(current_jd), tokenize(prior_jd))
    if (
        current_requirements is not None
        and prior_requirements is not None
        and current_requirements.seniority != prior_requirements.seniority
    ):
        return "regenerate", score
    if score >= _REUSE_FLOOR:
        return "reuse", score
    if score >= _EDITS_FLOOR:
        return "reuse_with_edits", score
    return "regenerate", score
