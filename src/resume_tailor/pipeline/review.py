"""Opt-in hiring-manager review of a tailored resume.

Synthesises a reviewer from the JD (career-ops Tier C — no web search) and asks for
keep/cut/rewrite verdicts per bullet. Suggested rewrites run through
``rewrite.check_fabrication`` before display; nothing is ever auto-applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..content.data import Bullet, MasterResume
from ..infra import llm
from . import events
from .fabrication import check_fabrication
from .jd import JobRequirements
from .rewrite_prompts import _format_keywords

Verdict = Literal["keep", "cut", "rewrite"]


class BulletVerdict(BaseModel):
    """One bullet's review outcome from the model."""

    id: str
    verdict: Verdict
    reason: str = ""
    #: Optional replacement text when verdict is ``rewrite``. Guarded before display.
    replacement: str = ""


class ReviewLLM(BaseModel):
    """Schema-validated model output for one review pass."""

    scope_read: str = ""
    bullets: list[BulletVerdict] = Field(default_factory=list)


@dataclass
class ReviewedBullet:
    """A single bullet verdict after fabrication filtering."""

    id: str
    verdict: Verdict
    reason: str
    replacement: str = ""
    #: Set when a rewrite suggestion was dropped for fabricating.
    dropped_note: str = ""


@dataclass
class ReviewResult:
    """Full advisory review for one tailored resume."""

    scope_read: str = ""
    bullets: list[ReviewedBullet] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: str = ""


_SYSTEM = """\
You are a hiring manager synthesised from the job posting below. Review the candidate's \
tailored resume bullets for THIS role only.

For each bullet, choose exactly one verdict:
- keep — this bullet should stay on the resume as written
- cut — this bullet does not help for this role; remove it
- rewrite — the claim is useful but the wording should change; supply a replacement

Rules:
- Judge fit for the posting, not general resume quality.
- Never invent a skill, tool, metric, employer, or claim absent from the bullet you are \
reviewing. A rewrite may only rephrase what that bullet already says.
- Give a one-line reason for every verdict.
- Prefer cut over rewrite when the bullet is off-topic; prefer keep when it already \
mirrors the posting honestly.
"""


def _format_bullets(bullets: dict[str, str]) -> str:
    """Format tailored bullets for the review user message."""
    lines = []
    for bid, text in sorted(bullets.items()):
        lines.append(f"<bullet id={bid!r}>\n  {text}\n</bullet>")
    return "\n".join(lines)


def review_bullets(
    resume: MasterResume,
    requirements: JobRequirements,
    bullets: dict[str, str],
    *,
    on_event: events.ProgressCallback | None = None,
) -> ReviewResult:
    """Run one opt-in review pass over the tailored bullets.

    Suggested rewrites that fail ``check_fabrication`` are dropped with a note rather
    than shown. Verdicts are never applied automatically.
    """
    model_label = config.backend_for("review").label()
    if not bullets:
        return ReviewResult(
            warnings=["No tailored bullets to review"],
            model=model_label,
        )

    events.emit(
        on_event,
        "review",
        "Reviewing tailored bullets as a hiring manager",
        cached=False,
        model=config.model_for("review"),
    )

    notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n"
        f"<keywords>\n{_format_keywords(requirements)}\n</keywords>\n\n"
        f"<tailored_bullets>\n{_format_bullets(bullets)}\n</tailored_bullets>"
    )

    client = llm.client_for("review")
    response = client.messages.parse(
        model=config.model_for("review"),
        max_tokens=config.max_tokens_for("review"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=ReviewLLM,
        output_config={"effort": config.effort_for("review")},
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(
            f"Model did not return a parseable review (stop_reason={response.stop_reason!r})."
        )

    by_id = {b.id: b for b in resume.all_bullets()}
    reviewed: list[ReviewedBullet] = []
    warnings: list[str] = []

    for item in parsed.bullets:
        if item.id not in bullets:
            continue
        replacement = item.replacement.strip()
        dropped_note = ""
        if item.verdict == "rewrite" and replacement:
            source = by_id.get(item.id) or Bullet(
                id=item.id, text=bullets[item.id], tags=[]
            )
            offenders = check_fabrication(source, replacement)
            if offenders:
                dropped_note = (
                    f"rewrite dropped (fabricated: {', '.join(offenders)})"
                )
                warnings.append(f"{item.id}: {dropped_note}")
                replacement = ""
        reviewed.append(
            ReviewedBullet(
                id=item.id,
                verdict=item.verdict,
                reason=item.reason.strip(),
                replacement=replacement,
                dropped_note=dropped_note,
            )
        )

    events.emit(
        on_event,
        "review",
        f"Reviewed {len(reviewed)} bullet(s)",
        bullets=len(reviewed),
    )
    return ReviewResult(
        scope_read=parsed.scope_read.strip(),
        bullets=reviewed,
        warnings=warnings,
        model=model_label,
    )
