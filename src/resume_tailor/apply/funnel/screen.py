"""JD screening rules for the daily apply funnel — pure, no LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from resume_tailor.content.data import MasterResume
from resume_tailor.pipeline.jd import JobRequirements
from resume_tailor.pipeline.report import diagnose_gaps

#: Phrases that flag a posting for human review without hard-rejecting it.
_ENROLLMENT_FLAG_PATTERNS = [
    r"\bmust be (currently )?enrolled\b",
    r"\breturning to school\b",
    r"\bcontinue enrollment\b",
]


#: Readable names for the default ``block_patterns``: a match records this name as the
#: reason instead of the regex source. A user-added pattern has no name and keeps the
#: legacy ``blocked by pattern '<regex>'`` wording.
_NAMED_BLOCKS = {
    r"\bU\.?S\.? citizen": "citizenship_required",
    r"security clearance": "clearance_required",
}

_EVIDENCE_CHARS = 160
#: A sentence end: a line break, or ./?/! before whitespace unless it closes a
#: single-letter abbreviation ("U.S. citizen", "8 U.S.C. 1324b").
_SENTENCE_END = re.compile(r"\n|(?<!\b[A-Za-z])[.?!](?=\s)")


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
    #: The JD sentence behind each work-restriction reason, trimmed for display.
    evidence: list[str] = Field(default_factory=list)


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


def _sentence_around(text: str, start: int, end: int) -> str:
    """The sentence containing ``text[start:end]``, whitespace-collapsed and trimmed."""
    left = max((m.end() for m in _SENTENCE_END.finditer(text, 0, start)), default=0)
    after = _SENTENCE_END.search(text, end)
    right = after.end() if after else len(text)
    head = " ".join(text[left:start].split())
    sentence = " ".join(text[left:right].split())
    if len(sentence) > _EVIDENCE_CHARS:
        offset = max(0, len(head) - _EVIDENCE_CHARS // 3)
        clipped = sentence[offset : offset + _EVIDENCE_CHARS].strip()
        sentence = ("…" if offset else "") + clipped + "…"
    return sentence


def check_blocks(
    jd_text: str, settings: ScreenSettings | None = None
) -> tuple[list[str], list[str]]:
    """Work-restriction block patterns (citizenship, clearance, user extras) — pure text.

    Returns ``(reasons, evidence)``: one reason per matching pattern, and the JD sentence
    that matched it. Runs before JD extraction, so a restricted posting costs no LLM call.
    """
    settings = settings or ScreenSettings()
    reasons: list[str] = []
    evidence: list[str] = []
    for pattern in settings.block_patterns:
        match = re.search(pattern, jd_text, re.IGNORECASE)
        if match is None:
            continue
        reasons.append(_NAMED_BLOCKS.get(pattern) or f"blocked by pattern {pattern!r}")
        evidence.append(_sentence_around(jd_text, match.start(), match.end()))
    return reasons, evidence


def seniority_reasons(
    seniority: str, role: str, settings: ScreenSettings | None = None
) -> tuple[list[str], list[str]]:
    """``(reasons, flags)`` for the extracted seniority.

    An intern / new-grad / entry title outranks the model's label: the disagreement is
    flagged (``seniority_mismatch``), never a rejection.
    """
    from resume_tailor.apply.funnel.eligibility import is_early_career_title

    settings = settings or ScreenSettings()
    if not seniority or seniority in settings.allowed_seniority:
        return [], []
    if is_early_career_title(role):
        return [], ["seniority_mismatch"]
    return [f"seniority {seniority!r} not in {settings.allowed_seniority}"], []


def screen(
    jd_text: str,
    requirements: JobRequirements,
    resume: MasterResume,
    settings: ScreenSettings | None = None,
    *,
    role: str = "",
) -> ScreenResult:
    """Return whether a posting should be tailored, with reasons and soft flags.

    The block patterns normally already ran in the prefilter stage (`check_blocks`);
    they are re-applied here so a direct caller still gets the full screen.
    """
    settings = settings or ScreenSettings()
    seniority = requirements.seniority or ""
    reasons, flags = seniority_reasons(seniority, role, settings)
    block_reasons, evidence = check_blocks(jd_text, settings)
    reasons += block_reasons

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
        evidence=evidence,
    )


#: Short labels for the Status column, in priority order (first match wins).
_LABELS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"citizenship_required|citizen", re.I), "Citizenship required"),
    (re.compile(r"clearance", re.I), "Clearance required"),
    (re.compile(r"advanced_degree"), "Grad degree only"),
    (re.compile(r"^title_senior$"), "Senior title"),
    (re.compile(r"^seniority "), "Too senior"),
    (re.compile(r"^requires_(\d+)_years$"), "{0}+ yrs experience"),
    (re.compile(r"coverage|no_evidence"), "Low skill match"),
    (re.compile(r"^(title_block|text_block):|^blocked by pattern "), "Blocked term"),
]


def _label_for(reason: str) -> tuple[int, str]:
    for rank, (pattern, label) in enumerate(_LABELS):
        match = pattern.search(reason)
        if match:
            return rank, label.format(*match.groups())
    return len(_LABELS), "Other"


def screen_label(reasons: list[str]) -> str | None:
    """2–3 word summary of why a posting was screened out, or None with no reasons.

    Accepts every reason form ever stored on a row, including legacy regex-source
    strings (``blocked by pattern '…citizen'``) and prefilter codes.
    """
    labels = sorted({_label_for(reason) for reason in reasons})
    if not labels:
        return None
    first = labels[0][1]
    return first if len(labels) == 1 else f"{first} +{len(labels) - 1}"
