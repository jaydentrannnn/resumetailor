"""Merging redundant bullets within an entry after a measured overflow."""

from __future__ import annotations

from .. import config
from ..content.data import Bullet
from ..infra import llm
from . import bullet_checks, fabrication, followups, rewrite_prompts
from .jd import JobRequirements
from .merge import MergeGroup

_MERGE_INSTRUCTION = """\
Merge the bullets below into ONE bullet.

Absolute rules:
- Do not imply that one bullet caused the other (avoid "thereby", "resulting in",
  "which led to" unless the relationship is already explicit in the provided bullets).
- Preserve every number exactly as written in ANY member bullet.
- Say each thing once. Name a shared tool, system, or metric a single time, and let one \
opening verb govern the whole bullet — "Designed X and engineered Y" is two bullets \
wearing one bullet's clothes. No "and also", no restating a skill already named earlier \
in the same bullet.
- The result must read as one coherent claim, not a list of two. If the members cannot be \
stated as one claim without repeating yourself, return the stronger member alone.
"""

def _format_merge_groups(
    groups: list[MergeGroup],
    texts: dict[str, str],
    sources: dict[str, Bullet],
    budget: int,
) -> str:
    """Format merge groups as XML-like text for the merge LLM call."""
    soft_min, hard_max = rewrite_prompts._length_band(budget)
    parts: list[str] = []
    for group in groups:
        tags = sorted({t for mid in group.member_ids for t in sources[mid].tags})
        currents = "\n".join(f"  - {texts[mid]}" for mid in group.member_ids)
        parts.append(
            f"<merge id={group.survivor_id!r} target={f'{soft_min}-{hard_max}'!r} max={hard_max}>\n"
            f"  <currents>\n{currents}\n  </currents>\n"
            f"  <permitted_skills>{', '.join(tags)}</permitted_skills>\n"
            f"</merge>"
        )
    return "\n".join(parts)

def _merge_bullets(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    groups: list[MergeGroup],
    requirements: JobRequirements,
    *,
    budget: int,
) -> tuple[dict[str, str], list[MergeGroup]]:
    """Rewrite and optionally apply merged bullet text for proposed groups.

    The merge is a non-regressive optional restructure:
    - the merged output must free at least one line vs the sum of source members
    - the merged text must pass multi-source fabrication guard
    - no number-bearing tokens from any member may be dropped
    - the merged text must not restate anything (`redundancy_offenders`)
    - the merged bullet must not be widowed (widow repair happens later if enabled)

    If the LLM fails to return parseable output, this pass is skipped.
    """
    if not groups:
        return texts, []

    budget = max(40, budget)
    _, hard_max = rewrite_prompts._length_band(budget)

    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<keywords_to_mirror>\n{rewrite_prompts._format_keywords(requirements)}\n</keywords_to_mirror>\n\n"
        "<context>\n"
        + "\n".join(f"  - {n}" for n in requirements.domain_notes)
        + "\n</context>\n\n"
        f"<merges_to_combine>\n{_format_merge_groups(groups, texts, sources, budget)}\n"
        f"</merges_to_combine>\n\n{_MERGE_INSTRUCTION}"
    )

    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=rewrite_prompts._system(),
        messages=[{"role": "user", "content": user}],
        output_format=rewrite_prompts.RewriteResult,
        output_config={"effort": config.effort_for("rewrite")},
    )

    result = response.parsed_output
    if result is None:
        return texts, []

    by_id: dict[str, str] = {b.id: b.text for b in result.bullets}
    merged = dict(texts)
    accepted: list[MergeGroup] = []

    for group in groups:
        candidate = by_id.get(group.survivor_id)
        if not candidate:
            continue
        candidate = candidate.strip()

        if len(candidate) > hard_max:
            continue

        before_lines = sum(config.line_span(texts[mid]) for mid in group.member_ids)
        after_lines = config.line_span(candidate)
        if not (after_lines < before_lines):
            continue

        member_sources = [sources[mid] for mid in group.member_ids if mid in sources]
        if not member_sources:
            continue

        offenders = bullet_checks.guard_offenders(member_sources, candidate)
        if offenders:
            continue

        dropped = fabrication.numbers_dropped(member_sources, candidate)
        if dropped:
            continue

        # The failure mode this whole gate exists for: a candidate that is short enough,
        # invents nothing, and drops no number can still simply say both members out loud.
        if bullet_checks.redundancy_offenders(candidate):
            continue

        if bullet_checks.widowed({group.survivor_id: candidate}).get(group.survivor_id) is not None:
            continue

        # Apply only after all checks pass.
        merged[group.survivor_id] = candidate
        for absorbed_id in group.member_ids[1:]:
            merged.pop(absorbed_id, None)
        accepted.append(group)

    return merged, accepted

def merge_into(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    groups: list[MergeGroup],
    requirements: JobRequirements,
    *,
    char_budget: int,
) -> tuple[dict[str, str], list[MergeGroup]]:
    """Apply `groups` to already-rewritten `texts`, leaving every other bullet untouched.

    The fit loop's combine step: one call carrying only the proposed groups, through the
    same acceptance gates as a merge inside `rewrite_bullets`. Public so `fit.py` need
    not reach for a private name.
    """
    return _merge_bullets(texts, sources, groups, requirements, budget=char_budget)

def pull_back(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
    ceilings: dict[str, int],
) -> tuple[dict[str, str], int, dict[str, list[str]]]:
    """Ask for `ceilings` (`{bullet id: max characters}`) on just those bullets.

    The fit loop's targeted shorten: a bullet is replaced only when the reply is shorter,
    spans fewer lines, and passes the fabrication guard. Returns `(texts, bullets pulled
    back, rejected)` where `rejected` maps id to the terms the guard refused.
    """
    if not ceilings:
        return texts, 0, {}
    out, pulled, _, rejected = followups._polish(
        texts, sources, requirements, repair_widows=False, repair_verbs=False, ceilings=ceilings
    )
    return out, pulled, rejected
