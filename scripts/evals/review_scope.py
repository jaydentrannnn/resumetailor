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


class ScopedVerdict(review.BulletVerdict):
    scope_risk: Literal["none", "stretch"] = "none"
    scope_note: str = ""
    softer_replacement: str = ""


class ScopedReviewLLM(BaseModel):
    scope_read: str = ""
    bullets: list[ScopedVerdict] = Field(default_factory=list)
    consistency: list[str] = Field(default_factory=list)


SYSTEM = review._SYSTEM + """
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
) -> dict[str, Any]:
    """One broader review pass; the record shape `stages.review_record` also produces."""
    notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
    cover = "\n\n".join(p.strip() for p in cover_paragraphs if p.strip())
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
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=ScopedReviewLLM,
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
        stretch = item.scope_risk == "stretch"
        softer, softer_dropped = _guarded(source, item.softer_replacement) if stretch else ("", "")
        rows.append({
            "id": item.id, "verdict": item.verdict, "reason": item.reason.strip(),
            "replacement": replacement, "dropped_note": dropped,
            "offered": bool(item.replacement.strip()) and item.verdict == "rewrite",
            "scope_risk": item.scope_risk, "scope_note": item.scope_note.strip() if stretch else "",
            "softer": softer, "softer_dropped": softer_dropped,
            "softer_offered": stretch and bool(item.softer_replacement.strip()),
        })
    return {"scope_read": parsed.scope_read.strip(), "bullets": rows,
            "consistency": [c.strip() for c in parsed.consistency if c.strip()]}
