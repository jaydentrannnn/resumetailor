"""Experiment 4e: a broader advisory review, eval-only until it beats the current one.

Besides keep / cut / rewrite, each bullet gets `scope_risk` ("stretch" when its wording
may claim more ownership, scale or impact than its own facts show) with a note, and a
`softer_replacement` that claims less, guarded like the rewrite. Across the page,
`consistency` lists statements that contradict each other, the cover letter included
when the run has one. Plain text in, JSON out, through the `review` purpose; nothing is
applied.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.content.data import Bullet, MasterResume
from resume_tailor.infra import llm
from resume_tailor.pipeline import review
from resume_tailor.pipeline.fabrication import check_fabrication
from resume_tailor.pipeline.jd import JobRequirements
from resume_tailor.pipeline.rewrite_prompts import _format_keywords


class BulletVerdict(BaseModel):
    """One bullet's review outcome from the model."""

    id: str
    verdict: Literal["keep", "cut", "rewrite"]
    reason: str = ""
    replacement: str = ""


class ReviewLLM(BaseModel):
    """Schema-validated model output for one review pass."""

    scope_read: str = ""
    bullets: list[BulletVerdict] = Field(default_factory=list)


class NotedVerdict(BulletVerdict):
    scope_risk: Literal["none", "stretch"] = "none"
    scope_note: str = ""


class ScopedVerdict(NotedVerdict):
    softer_replacement: str = ""


class ScopedReviewLLM(BaseModel):
    scope_read: str = ""
    bullets: list[ScopedVerdict] = Field(default_factory=list)
    consistency: list[str] = Field(default_factory=list)


class NotedReviewLLM(BaseModel):
    scope_read: str = ""
    bullets: list[NotedVerdict] = Field(default_factory=list)


#: Frozen from pipeline/review.py before 8390edb (parent d7435e4). The baseline's
#: prompt and response schema above must not follow changes to the shipped review.
BASE_SYSTEM = """\
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


SYSTEM = BASE_SYSTEM + """
Also, for each bullet:
- scope_risk: "stretch" when the wording may claim more ownership, scale or impact than \
the bullet's own facts show, so an interviewer could catch it; otherwise "none".
- scope_note: one line saying what could be questioned, only when scope_risk is "stretch".
- softer_replacement: only when scope_risk is "stretch", the same bullet reworded to claim \
exactly what it shows. It may only remove or soften words; it never adds anything.

Across all bullets, and the cover letter when one is given:
- consistency: short notes on statements that contradict each other (dates, roles, \
numbers, tools, team sizes). Leave it empty when there are none.
"""

#: Variant B ("note"): the stretch flag and its note only. The rewrite instructions are
#: untouched and no softer text is generated, so nothing new reaches the guard. It passed
#: on 2026-10-23 and shipped. Keep this measured arm fixed alongside the baseline.
NOTE_SYSTEM = BASE_SYSTEM + """
Also, for each bullet:
- scope_risk: "stretch" when the wording may claim more ownership, scale or impact than \
the bullet's own facts show, so an interviewer could catch it; otherwise "none".
- scope_note: one line saying what could be questioned, only when scope_risk is "stretch".
"""


def _guarded(source: Bullet, text: str) -> tuple[str, str]:
    """`(text, note)`: the suggestion, or "" with a note when it fabricates."""
    text = text.strip()
    if not text:
        return "", ""
    offenders = check_fabrication(source, text)
    if offenders:
        return "", f"dropped (fabricated: {', '.join(offenders)})"
    return text, ""


def review_scoped(
    resume: MasterResume,
    requirements: JobRequirements,
    bullets: dict[str, str],
    cover_paragraphs: Sequence[str] = (),
    *,
    variant: Literal["baseline", "scope", "note"] = "scope",
) -> dict[str, Any]:
    """One broader review pass; the record shape `stages.review_record` also produces.
    `variant="baseline"` replays the pre-8390edb review. `variant="note"` asks for
    the stretch flag and note only, over the same user message (no cover letter,
    no consistency, no softer text). Both prompts and schemas are frozen here."""
    baseline = variant == "baseline"
    scope = variant == "scope"
    if baseline and not bullets:
        return {"scope_read": "", "bullets": [], "consistency": []}
    notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
    cover = "\n\n".join(p.strip() for p in cover_paragraphs if p.strip()) if scope else ""
    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n"
        f"<keywords>\n{_format_keywords(requirements)}\n</keywords>\n\n"
        f"<tailored_bullets>\n{review._format_bullets(bullets)}\n</tailored_bullets>"
        + (f"\n\n<cover_letter>\n{cover}\n</cover_letter>" if cover else "")
    )
    response = llm.client_for("review").messages.parse(
        model=config.model_for("review"),
        max_tokens=config.max_tokens_for("review"),
        system={"baseline": BASE_SYSTEM, "note": NOTE_SYSTEM, "scope": SYSTEM}[variant],
        messages=[{"role": "user", "content": user}],
        output_format={"baseline": ReviewLLM, "note": NotedReviewLLM,
                       "scope": ScopedReviewLLM}[variant],
        output_config={"effort": config.effort_for("review")},
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(f"no parseable review (stop_reason={response.stop_reason!r})")
    by_id = {b.id: b for b in resume.all_bullets()}
    rows = []
    for item in parsed.bullets:
        if item.id not in bullets:
            continue
        source = by_id.get(item.id) or Bullet(id=item.id, text=bullets[item.id], tags=[])
        replacement, dropped = (
            _guarded(source, item.replacement) if item.verdict == "rewrite" else ("", ""))
        if baseline and dropped:
            dropped = "rewrite " + dropped
        risk = "none" if baseline else item.scope_risk
        stretch = risk == "stretch"
        offered_softer = item.softer_replacement if scope else ""
        softer, softer_dropped = _guarded(source, offered_softer) if stretch else ("", "")
        rows.append({
            "id": item.id, "verdict": item.verdict, "reason": item.reason.strip(),
            "replacement": replacement, "dropped_note": dropped,
            "offered": bool(item.replacement.strip()) and item.verdict == "rewrite",
            "scope_risk": risk, "scope_note": item.scope_note.strip() if stretch else "",
            "softer": softer, "softer_dropped": softer_dropped,
            "softer_offered": stretch and bool(offered_softer.strip()),
        })
    consistency = [c.strip() for c in parsed.consistency if c.strip()] if scope else []
    return {"scope_read": parsed.scope_read.strip(), "bullets": rows, "consistency": consistency}
