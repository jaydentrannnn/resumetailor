"""JD screening rules for the daily apply funnel — pure, no LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from resume_tailor.data import MasterResume
from resume_tailor.jd import JobRequirements
from resume_tailor.report import diagnose_gaps

#: Phrases that flag a posting for human review without hard-rejecting it.
_ENROLLMENT_FLAG_PATTERNS = [
    r"\bmust be (currently )?enrolled\b",
    r"\breturning to school\b",
    r"\bcontinue enrollment\b",
]


class ScreenSettings(BaseModel):
    """Hard-reject thresholds for ``screen()``. Coverage is informational only — see
    `screen()`'s own comment on why must-have overlap never rejects a posting."""

    allowed_seniority: list[str] = Field(default_factory=lambda: ["intern", "entry"])
    block_patterns: list[str] = Field(
        default_factory=lambda: [
            r"\bU\.?S\.? citizen",
            r"security clearance",
        ]
    )


class ScreenResult(BaseModel):
    """Outcome of screening one posting against the master resume."""

    passed: bool
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    coverage: float = 0.0
    coverage_matched: int = 0
    coverage_total: int = 0
    seniority: str = ""


@dataclass
class _Coverage:
    """Internal coverage counts before packing into ``ScreenResult``."""

    matched: int = 0
    total: int = 0
    no_evidence: int = 0
    ratio: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _coverage(
    requirements: JobRequirements,
    resume: MasterResume,
) -> _Coverage:
    """Compute must-have coverage and count ``no_evidence`` gaps."""
    must = [k for k in requirements.keywords if k.importance == "must_have"]
    if not must:
        return _Coverage(matched=0, total=0, ratio=1.0)
    gaps = diagnose_gaps(requirements, resume)
    by_canonical = {g.canonical: g for g in gaps}
    no_evidence = 0
    matched = 0
    for kw in must:
        gap = by_canonical.get(kw.canonical)
        if gap is None:
            matched += 1
        elif gap.reason == "no_evidence":
            no_evidence += 1
    total = len(must)
    ratio = matched / total if total else 1.0
    reasons: list[str] = []
    return _Coverage(
        matched=matched,
        total=total,
        no_evidence=no_evidence,
        ratio=ratio,
        reasons=reasons,
    )


def screen(
    jd_text: str,
    requirements: JobRequirements,
    resume: MasterResume,
    settings: ScreenSettings | None = None,
) -> ScreenResult:
    """Return whether a posting should be tailored, with reasons and soft flags."""
    settings = settings or ScreenSettings()
    reasons: list[str] = []
    flags: list[str] = []
    seniority = requirements.seniority or ""
    if seniority and seniority not in settings.allowed_seniority:
        reasons.append(f"seniority {seniority!r} not in {settings.allowed_seniority}")

    for pattern in settings.block_patterns:
        if re.search(pattern, jd_text, re.IGNORECASE):
            reasons.append(f"blocked by pattern {pattern!r}")

    for pattern in _ENROLLMENT_FLAG_PATTERNS:
        if re.search(pattern, jd_text, re.IGNORECASE):
            flags.append(f"enrollment wording matched {pattern!r}")

    # Must-have coverage is informational only (see `ScreenResult.coverage`/
    # `coverage_matched`/`coverage_total`) — it never rejects a posting. Low overlap
    # between a JD's must-haves and the resume's own tags is exactly what the tailoring
    # stage (facets/rewrite) exists to bridge, not a reason to skip trying.
    cov = _coverage(requirements, resume)

    return ScreenResult(
        passed=not reasons,
        reasons=reasons,
        flags=flags,
        coverage=cov.ratio,
        coverage_matched=cov.matched,
        coverage_total=cov.total,
        seniority=seniority,
    )
