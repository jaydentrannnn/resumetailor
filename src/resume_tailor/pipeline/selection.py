"""Deterministic bullet ranking and selection: keyword weights, recency, per-entry budgets."""

from __future__ import annotations

import re

from .. import config
from ..content.data import Bullet, Experience, Project
from .jd import JobRequirements


# --------------------------------------------------------------------------------------
# Stage 1 — selection (deterministic, no LLM)
# --------------------------------------------------------------------------------------
def _keyword_weight(kw) -> float:
    """Weight for one matched keyword.

    Soft-skill must-haves are discounted to `config.SOFT_SKILL_WEIGHT`. Soft tags
    ("communication", "teamwork") are broad and sit on nearly every entry including the
    volunteer and support roles, so at full must-have weight a posting naming three of them
    as required can float a non-technical entry over a relevant job.
    """
    if kw.importance != "must_have":
        return config.NICE_TO_HAVE_WEIGHT
    return config.SOFT_SKILL_WEIGHT if kw.kind == "soft" else config.MUST_HAVE_WEIGHT

def _keyword_score(bullet: Bullet, requirements: JobRequirements) -> float:
    """Tag-overlap score: exact set membership against the bullet's canonical tags.

    A soft keyword also matches the related tags in `config.SOFT_SKILL_RELATED_TAGS`.
    """
    tags = set(bullet.tags)
    return sum(_keyword_weight(kw) for kw in requirements.keywords if _matches(kw, tags))

def _matches(kw, tags: set[str]) -> bool:
    if kw.canonical in tags:
        return True
    return kw.kind == "soft" and not tags.isdisjoint(
        config.SOFT_SKILL_RELATED_TAGS.get(kw.canonical, ())
    )

def score(
    bullet: Bullet,
    requirements: JobRequirements,
    *,
    semantic: dict[str, float] | None = None,
) -> float:
    """Score a bullet's relevance to a posting.

    Two independent signals, added rather than blended away:

    - **Tag overlap** — exact, auditable, and free. Must-have matches dominate
      nice-to-have ones, with soft-skill must-haves discounted (see `_keyword_weight`).
    - **Semantic relevance** — an optional 0-10 score per bullet from `score_table`,
      scaled by `config.SEMANTIC_WEIGHT`. This is the only signal that can see resonance no
      tag encodes: an academic-advising project against a posting about academic-content
      partnerships shares no tag with it and scores zero on overlap alone.

    A bullet carrying a concrete number gets a small nudge on top, but only when it is
    relevant by one of the two signals first — otherwise every quantified bullet floats to
    the top of every posting.

    Passing `semantic=None` (or leaving `SEMANTIC_WEIGHT` at 0.0) reproduces keyword-only
    scoring exactly, which is what makes the semantic layer A/B-testable.
    """
    total = _keyword_score(bullet, requirements)
    if semantic:
        total += config.SEMANTIC_WEIGHT * semantic.get(bullet.id, 0.0)
    if total and bullet.metric:
        total += config.METRIC_BONUS
    return total

def select(
    bullets: list[Bullet],
    requirements: JobRequirements,
    *,
    limit: int,
    semantic: dict[str, float] | None = None,
) -> list[Bullet]:
    """Pick the `limit` most relevant bullets, preserving their original order.

    Ordering is restored after ranking because a resume entry reads as a narrative;
    reordering by score alone produces a jumbled section even when every line is
    individually relevant.

    Zero-scoring bullets are kept as filler only when nothing better is available — an
    entry with no matching bullets should still not render empty.
    """
    if limit <= 0:
        return []

    ranked = sorted(
        bullets, key=lambda b: score(b, requirements, semantic=semantic), reverse=True
    )
    chosen = set(id(b) for b in ranked[:limit])
    return [b for b in bullets if id(b) in chosen]

def score_entry(
    entry: Experience | Project,
    requirements: JobRequirements,
    *,
    semantic: dict[str, float] | None = None,
    max_per_entry: int | None = None,
) -> float:
    """Score a whole job or project by how much relevant material it offers.

    Sum the best three usable bullets, respecting any tighter configured bullet cap.
    Additional weak stored content cannot boost an entry that will not render it.
    """
    cap = config.MAX_BULLETS_PER_ENTRY if max_per_entry is None else max_per_entry
    count = 3 if cap is None else min(3, max(0, cap))
    scores = sorted((score(b, requirements, semantic=semantic) for b in entry.bullets),
                    reverse=True)
    total = sum(scores[:count])
    return total * entry_recency(entry)

_MONTHS = {
    m: i for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        1,
    )
}

_ISO_MONTH = re.compile(r"\b(\d{4})-(0[1-9]|1[0-2])\b")

_NAMED_MONTH = re.compile(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{4})\b")

_BARE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")

_ONGOING = re.compile(r"\b(?:present|current|now|ongoing)\b", re.IGNORECASE)

def _end_month(text: str) -> tuple[int, int] | None:
    """The last (year, month) a free-text date range names, or None.

    Accepts ``2025-06``, ``Jun 2025`` / ``June 2025`` and a bare ``2025`` (read as
    December, the most recent month it can mean). The last match wins, since a range's
    end is written after its start.
    """
    found: list[tuple[int, int, int]] = []  # (position, year, month)
    for match in _ISO_MONTH.finditer(text):
        found.append((match.start(), int(match.group(1)), int(match.group(2))))
    for match in _NAMED_MONTH.finditer(text):
        month = _MONTHS.get(match.group(1).lower())
        if month:
            found.append((match.start(), int(match.group(2)), month))
    if not found:
        for match in _BARE_YEAR.finditer(text):
            found.append((match.start(), int(match.group(1)), 12))
    if not found:
        return None
    _, year, month = max(found)
    return year, month

def _today_month() -> tuple[int, int]:
    if config.RECENCY_TODAY:
        year, month = config.RECENCY_TODAY.split("-")[:2]
        return int(year), int(month)
    from datetime import date

    today = date.today()
    return today.year, today.month

def entry_recency(entry: object, *, today: tuple[int, int] | None = None) -> float:
    """Recency multiplier for an entry's relevance score (`config.RECENCY_WEIGHT`).

    Age is measured from the entry's end: ``Experience.end`` or ``Project.date`` (any
    entry kind exposing one of those). An ongoing entry gets the full boost; an entry with
    no parseable date is neutral (1.0) rather than penalised, so a missing date never
    costs an entry its slot.
    """
    if config.RECENCY_WEIGHT <= 0:
        return 1.0
    text = str(getattr(entry, "end", "") or getattr(entry, "date", "") or "")
    if not text.strip():
        return 1.0
    if _ONGOING.search(text):
        age = 0.0
    else:
        end = _end_month(text)
        if end is None:
            return 1.0
        now = today or _today_month()
        age = max(0.0, float((now[0] - end[0]) * 12 + (now[1] - end[1])))
    return 1.0 + config.RECENCY_WEIGHT * 0.5 ** (age / config.RECENCY_HALF_LIFE_MONTHS)

def select_entries(
    entries: list[Experience] | list[Project],
    requirements: JobRequirements,
    *,
    limit: int,
    semantic: dict[str, float] | None = None,
    max_per_entry: int | None = None,
) -> list:
    """Pick the `limit` most relevant entries, preserving their original order.

    Experience and projects are ranked **separately** — a job competes only with other
    jobs. Ranking them in one pool let a stack of relevant side projects push out the
    candidate's current employer, which no reader expects to see missing.

    The sort is stable over document order, which is reverse-chronological, so equally
    scoring entries break ties toward the more recent one.
    """
    if limit <= 0:
        return []

    ranked = sorted(
        entries, key=lambda e: score_entry(
            e, requirements, semantic=semantic, max_per_entry=max_per_entry,
        ), reverse=True,
    )
    chosen = {id(e) for e in ranked[:limit]}
    return [e for e in entries if id(e) in chosen]

def selectable_total(entries: list, *, max_per_entry: int | None = None) -> int:
    """How many bullets the caps actually allow — what the fit loop can grow to.

    Without a cap this is just the raw pool size. With `max_per_entry` set, the pool
    saturates below that once every entry hits its ceiling, and the fit loop's grow
    condition (`limit < total_bullets`) has to compare against *this*, not the raw count —
    otherwise it keeps raising `limit` while `select_within_entries` returns the same
    selection, burning grow attempts (an LLM call and a render each) for no change.
    """
    if max_per_entry is None:
        return sum(len(e.bullets) for e in entries)
    return sum(min(len(e.bullets), max_per_entry) for e in entries)

def _allocate_budgets(
    pools: list[list],
    *,
    limit: int,
    weights: list[float | None],
    max_per_entry: int | None = None,
) -> list[int]:
    """Split `limit` bullets across `pools` (one list of entries per pool) by `weights`.

    Generalises the old two-section (`experience`, `projects`) split to N pools — needed
    because two experience-*kind* sections are the same Python class, so nothing but
    section identity can tell them apart; `select_within_entries` now groups entries into
    `pools` by section rather than by `isinstance`.

    Each weight is a share of the *total* `limit`, not just the discretionary remainder
    past a pool's floor — that is the more intuitive read of "70% experience" and matches
    how a user would describe the split they want. A pool whose weight is `None` splits
    whatever share the explicit weights leave unclaimed evenly with every other `None`
    pool; all-`None` is an even split.

    Each pool's floor (one bullet per non-empty entry) is a hard minimum a weight can
    never starve it below. Each pool's cap is `selectable_total`, not the raw bullet
    count — when `max_per_entry` is also set, a pool can be achievably smaller than its
    raw bullet count, and budgeting against the raw count would hand it more than
    `_take_ranked` can actually fill. Any budget a pool cannot use spills to whichever
    other pools still have room, iterated until nothing moves, so a weight never strands
    part of `limit` and stalls the grow loop into thinking it must keep growing.
    """
    n = len(pools)
    floors = [sum(1 for e in pool if e.bullets) for pool in pools]
    caps = [selectable_total(pool, max_per_entry=max_per_entry) for pool in pools]

    explicit = sum(w for w in weights if w is not None)
    unweighted = [i for i, w in enumerate(weights) if w is None]
    remainder_share = max(0.0, 1.0 - explicit) / len(unweighted) if unweighted else 0.0
    resolved = [w if w is not None else remainder_share for w in weights]

    allocations = [
        max(floors[i], min(caps[i], round(limit * resolved[i]))) for i in range(n)
    ]

    # Iterative spill: hand any budget a pool cannot use (its floor already exceeds its
    # share, or it has less capacity than its share implies) to pools that still have
    # room, until the total reaches `limit` or every pool is at its cap. N passes is
    # always enough — each pass either converges or drains at least one pool to its cap.
    for _ in range(max(n, 1)):
        deficit = limit - sum(allocations)
        if deficit <= 0:
            break
        room = [caps[i] - allocations[i] for i in range(n)]
        if sum(room) <= 0:
            break
        for i in range(n):
            if room[i] <= 0 or deficit <= 0:
                continue
            give = min(room[i], deficit)
            allocations[i] += give
            deficit -= give
    return allocations

def _take_ranked(
    entries: list,
    requirements: JobRequirements,
    *,
    limit: int,
    semantic: dict[str, float] | None = None,
    max_per_entry: int | None = None,
) -> set[int]:
    """Return `id()`s of up to `limit` bullets: every entry's floor, then the
    highest-scoring remainder, skipping any entry already at `max_per_entry`.

    A capped entry's forfeited slot is not lost — the walk simply continues to the
    next-best bullet elsewhere, so spillover within the pool falls out for free.
    """
    floors: list[Bullet] = []
    counts: dict[int, int] = {}
    for entry in entries:
        if entry.bullets:
            best = max(entry.bullets, key=lambda b: score(b, requirements, semantic=semantic))
            floors.append(best)
            counts[id(entry)] = 1

    kept = {id(b) for b in floors}
    remaining = limit - len(floors)
    if remaining <= 0:
        return kept

    entry_of = {id(b): id(e) for e in entries for b in e.bullets}
    recency = {id(e): entry_recency(e) for e in entries}
    pool = [b for e in entries for b in e.bullets if id(b) not in kept]
    ranked = sorted(
        pool,
        key=lambda b: score(b, requirements, semantic=semantic) * recency[entry_of[id(b)]],
        reverse=True,
    )

    taken = 0
    for b in ranked:
        if taken >= remaining:
            break
        eid = entry_of[id(b)]
        if max_per_entry is not None and counts.get(eid, 0) >= max_per_entry:
            continue
        kept.add(id(b))
        counts[eid] = counts.get(eid, 0) + 1
        taken += 1

    return kept

def select_within_entries(
    entries: list,
    requirements: JobRequirements,
    *,
    limit: int,
    semantic: dict[str, float] | None = None,
    experience_share: float | None = None,
    max_per_entry: int | None = None,
    pools: list[list] | None = None,
    weights: list[float | None] | None = None,
) -> list[Bullet]:
    """Choose up to `limit` bullets from already-selected entries.

    Every entry keeps at least its single best bullet: an entry that survived
    `select_entries` has earned a place in the document, and `render.build_context` omits
    any entry whose bullets were all dropped. Without that floor the fit loop could silently
    delete a job it had just decided to keep. `limit` is therefore raised to the entry count
    when it is smaller.

    Remaining budget goes to the highest-scoring bullets across all the entries pooled
    together, so a rich entry can take more lines than a thin one.

    `pools`/`weights` overrides this: each pool (one list of entries per resume section)
    is budgeted separately via `_allocate_budgets` and filled independently, so a
    keyword-dense section can no longer out-rank every entry in one flat pool. This is
    what `fit.py` passes once a resume can hold more than one experience-kind section —
    `isinstance` can no longer tell two sections of the same kind apart, so section
    membership has to come from the caller. `weights` defaults to an even split across
    `pools` when omitted.

    `experience_share` is two-pool sugar for the same mechanism, kept for backward
    compatibility and for callers (including tests) that pass a flat, unwrapped list of
    `Experience`/`Project` entries with no section grouping at all: it derives `pools` via
    `isinstance(e, Project)` and `weights=[experience_share, None]`. Ignored when `pools`
    is given explicitly.

    `max_per_entry` caps how many bullets any single entry may take, applied within
    whichever pool (flat, or per-section under `pools`/`experience_share`) is in play.

    All of `experience_share`, `pools`, and `weights` default to `None`, reproducing the
    original flat-pool selection exactly.
    """
    if pools is not None:
        resolved_weights = weights if weights is not None else [None] * len(pools)
        allocations = _allocate_budgets(
            pools, limit=limit, weights=resolved_weights, max_per_entry=max_per_entry
        )
        kept: set[int] = set()
        for pool, pool_limit in zip(pools, allocations, strict=True):
            kept |= _take_ranked(
                pool, requirements, limit=pool_limit, semantic=semantic,
                max_per_entry=max_per_entry,
            )
        return [b for e in entries for b in e.bullets if id(b) in kept]

    if experience_share is None:
        kept = _take_ranked(
            entries, requirements, limit=limit, semantic=semantic, max_per_entry=max_per_entry
        )
        return [b for e in entries for b in e.bullets if id(b) in kept]

    experience = [e for e in entries if not isinstance(e, Project)]
    projects = [e for e in entries if isinstance(e, Project)]
    exp_limit, proj_limit = _allocate_budgets(
        [experience, projects], limit=limit, weights=[experience_share, None],
        max_per_entry=max_per_entry,
    )
    kept = _take_ranked(
        experience, requirements, limit=exp_limit, semantic=semantic, max_per_entry=max_per_entry
    )
    kept |= _take_ranked(
        projects, requirements, limit=proj_limit, semantic=semantic, max_per_entry=max_per_entry
    )
    return [b for e in entries for b in e.bullets if id(b) in kept]
