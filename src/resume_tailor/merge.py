"""Merge-pass proposal logic for combining redundant bullets.

This module is the deterministic, no-LLM half of the merge feature. It proposes
candidate merge groups inside a single entry; the actual merging (LLM rewrite + guard)
is implemented in `rewrite.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .data import Bullet, Experience, Project
from .jd import JobRequirements


#: Tokens that look like proper nouns but carry no factual claim, so they never need to
#: be traceable to source material.
_BENIGN = {
    "a",
    "an",
    "and",
    "the",
    "for",
    "with",
    "to",
    "of",
    "in",
    "on",
    "by",
    "at",
    "from",
    "across",
    "via",
    "using",
    "into",
    "over",
    "under",
    "per",
    "as",
    "that",
    "which",
    "i",
    "we",
    "my",
    "our",
}

#: Matches a word, allowing internal dots/pluses/hyphens/commas ("node.js", "C++", "GPT-4",
#: "55k+", "1,000") but never a trailing one.
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[+#./_,-]+[A-Za-z0-9]+)*[+#]*")

_HAS_LETTER = re.compile(r"[A-Za-z]")


def _jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _keyword_score(bullet: Bullet, requirements: JobRequirements) -> float:
    """Compute the same keyword-overlap signal as `rewrite.score` (minus semantic)."""
    tags = set(bullet.tags)
    total = 0.0
    for kw in requirements.keywords:
        if kw.canonical not in tags:
            continue
        if kw.importance != "must_have":
            total += config.NICE_TO_HAVE_WEIGHT
        else:
            total += config.SOFT_SKILL_WEIGHT if kw.kind == "soft" else config.MUST_HAVE_WEIGHT
    if total and bullet.metric:
        total += config.METRIC_BONUS
    return min(10.0, max(0.0, total))


def _content_tokens(bullet: Bullet) -> set[str]:
    """Tokenise bullet text/tags for overlap checks (letters-only, excludes `_BENIGN`)."""
    tokens: set[str] = set()
    for source in (bullet.text, " ".join(bullet.tags)):
        for match in _TOKEN.finditer(source):
            token = match.group(0).lower()
            if token in _BENIGN:
                continue
            if not _HAS_LETTER.search(token):
                # Numbers can be factual/guarded later; affinity shouldn't hinge on them.
                continue
            tokens.add(token)
    return tokens


def _affinity(members: list[Bullet]) -> tuple[float, float, float]:
    """Compute (affinity, tag_jaccard, content_overlap) for a candidate member list.

    For >2 members we use pairwise averages so the score is stable as group size grows.
    """
    if len(members) < 2:
        return 0.0, 0.0, 0.0

    tag_jaccards: list[float] = []
    content_overlaps: list[float] = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            tag_jaccards.append(_jaccard(set(members[i].tags), set(members[j].tags)))
            content_overlaps.append(
                _jaccard(_content_tokens(members[i]), _content_tokens(members[j]))
            )

    tag_mean = sum(tag_jaccards) / len(tag_jaccards)
    content_mean = sum(content_overlaps) / len(content_overlaps)
    affinity = 0.6 * tag_mean + 0.4 * content_mean
    return affinity, tag_mean, content_mean


@dataclass(frozen=True)
class MergeGroup:
    """A proposed merge group.

    The merge is "N bullets -> 1 bullet" inside one entry. The survivor is the earliest
    member in master order; absorbed members must be removed from the rewritten bullets
    dict so `render.build_context` will no longer render them.
    """

    survivor_id: str
    member_ids: tuple[str, ...]
    affinity: float
    reason: str


def propose(
    entries: list[Experience | Project],
    selected: list[Bullet],
    requirements: JobRequirements,
    *,
    semantic: dict[str, float] | None,
    char_budget: int,
    shorten_pct: int,
    attempt: int,
) -> list[MergeGroup]:
    """Propose redundant bullet groups for merging (pure, deterministic).

    The output is a list of `MergeGroup`s. They are accepted or rejected later by
    the actual merge stage in `rewrite.py` after the model rewrites the combined bullet
    and the guard checks multi-source factuality and number preservation.
    """
    if not selected:
        return []

    selected_ids = {b.id for b in selected}
    order_map = {b.id: i for i, b in enumerate(selected)}

    budget = max(40, int(char_budget * (1 - shorten_pct / 100)))
    hard_max = max(40, budget - config.WIDOW_SAFETY)

    affinity_threshold = config.MERGE_AFFINITY_SCHEDULE[
        min(attempt, len(config.MERGE_AFFINITY_SCHEDULE) - 1)
    ]

    max_group_size = min(config.MAX_MERGE_GROUP_SIZE + (1 if attempt >= 1 else 0), 3)
    if max_group_size < 2:
        return []

    # Each tuple: (affinity, survivor_order, members, tag_jaccard, content_overlap).
    candidates: list[tuple[float, int, list[Bullet], float, float]] = []
    for entry in entries:
        entry_selected = [b for b in entry.bullets if b.id in selected_ids]
        if len(entry_selected) < 2:
            continue

        for i in range(len(entry_selected) - 1):
            group2 = entry_selected[i : i + 2]
            affinity, tag_j, content_j = _affinity(group2)
            candidates.append((affinity, order_map[group2[0].id], group2, tag_j, content_j))

            if max_group_size >= 3 and i + 2 < len(entry_selected):
                group3 = entry_selected[i : i + 3]
                affinity, tag_j, content_j = _affinity(group3)
                candidates.append(
                    (affinity, order_map[group3[0].id], group3, tag_j, content_j)
                )

    # Greedy non-overlap selection, sorted so "best" wins deterministically.
    candidates.sort(key=lambda c: (-c[0], c[1], -len(c[2])))
    chosen: list[MergeGroup] = []
    used_member_ids: set[str] = set()
    for affinity, survivor_order, group, tag_j, content_j in candidates:
        if len(chosen) >= config.MAX_MERGES_PER_RUN:
            break
        member_ids = tuple(b.id for b in group)
        if any(mid in used_member_ids for mid in member_ids):
            continue

        weakest = _weakest_score(group, requirements, semantic)
        redundant = affinity >= affinity_threshold + 0.15
        weak = weakest <= config.MERGE_WEAK_SCORE
        if not (affinity >= affinity_threshold and (weak or redundant)):
            continue

        if sum(len(b.text) for b in group) > config.MERGE_SOURCE_RATIO * hard_max:
            continue

        survivor_id = group[0].id
        reason = (
            f"affinity={affinity:.2f} (tags={tag_j:.2f}, content={content_j:.2f}), "
            f"weakest_member={weakest:.1f}"
        )
        chosen.append(
            MergeGroup(
                survivor_id=survivor_id,
                member_ids=member_ids,
                affinity=affinity,
                reason=reason,
            )
        )
        used_member_ids.update(member_ids)

    chosen.sort(key=lambda g: order_map.get(g.survivor_id, 10**9))
    return chosen


def _weakest_score(
    group: list[Bullet],
    requirements: JobRequirements,
    semantic: dict[str, float] | None,
) -> float:
    """Compute the weakest member score used by the merge proposal weakness gate."""
    if semantic:
        return min(semantic.get(b.id, 0.0) for b in group)
    return min(_keyword_score(b, requirements) for b in group)



