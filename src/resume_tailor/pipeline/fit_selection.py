"""Choosing what goes on the page: entry ranking, initial sizing, pools, pull-backs and drops."""

from __future__ import annotations

from .. import config
from ..content.data import Bullet, Experience, MasterResume, Project
from ..document import render
from ..document.template_profile import active_layout
from . import fit_lines, fit_types
from .bullet_checks import widowed
from .jd import JobRequirements
from .selection import (
    entry_recency,
    select_entries,
    select_within_entries,
    selectable_total,
)
from .selection import score as score_bullet


# --------------------------------------------------------------------------------------
# Selection sizing
# --------------------------------------------------------------------------------------
def choose_entries(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    max_experience: int | None = None,
    max_projects: int | None = None,
    semantic: dict[str, float] | None = None,
    layout: dict | None = None,
    section_limits: dict[str, int] | None = None,
) -> list:
    """Pick which entries appear, ranking every entry section independently.

    Done once per run, before any rewriting: which entries appear is a decision about the
    resume's shape, and the fit loop is only allowed to trim bullets inside them. Each
    section is ranked against only its own entries — a leadership-section entry never
    competes with a job for a slot, the same guarantee the original two-section split
    gave experience vs. projects, generalised to any number of sections.

    `max_experience`/`max_projects` are the pre-`sections` overrides: they apply as the
    default limit to every experience-kind / project-kind section respectively (today's
    one-of-each behaviour is the special case where that is one section apiece).
    `section_limits`, keyed by section id, overrides a specific section's limit and wins
    over both.

    When the active template has no Projects-kind prototype, every project-kind section
    is forced to a limit of 0. When it has no Experience section (a first-year student's
    Education/Projects/Activities resume), experience-kind sections are always 0, even
    over `section_limits`.
    """
    layout = layout if layout is not None else active_layout()
    enabled = layout.get("enabled") or {}
    section_limits = section_limits or {}
    chosen: list = []
    for section in resume.entry_sections:
        if section.kind == "project":
            default_limit = config.MAX_PROJECT_ENTRIES if max_projects is None else max_projects
            if not enabled.get("projects", True):
                default_limit = 0
        else:
            default_limit = (
                config.MAX_EXPERIENCE_ENTRIES if max_experience is None else max_experience
            )
        limit = section_limits.get(section.id, default_limit)
        if section.kind == "experience" and not enabled.get("experience", True):
            limit = 0  # no Experience layout in the template: nothing could render them
        chosen.extend(
            select_entries(section.entries, requirements, limit=limit, semantic=semantic)
        )
    return chosen

def _select_at_rewrite_budget(
    entries: list,
    requirements: JobRequirements,
    limit: int,
    semantic: dict[str, float] | None = None,
    *,
    experience_share: float | None = None,
    max_per_entry: int | None = None,
    pools: list[list] | None = None,
    weights: list[float | None] | None = None,
) -> dict[str, str]:
    """Map a selection to rewrite-budget placeholders for cheap line estimates.

    Initial sizing assumes each bullet lands near `_TARGET_LINES_PER_BULLET` after the
    first rewrite, not at the (usually longer) master wording — estimating on originals
    under-selected and left the page sparse until grow rounds caught up.
    """
    selected = select_within_entries(
        entries, requirements, limit=limit, semantic=semantic,
        experience_share=experience_share, max_per_entry=max_per_entry,
        pools=pools, weights=weights,
    )
    # Match the hard max the rewrite prompt advertises (budget minus widow safety), not
    # the full line cliff — that is what the model is told to land under.
    stub_len = max(
        40, fit_types._TARGET_LINES_PER_BULLET * config.CHARS_PER_LINE - config.WIDOW_SAFETY
    )
    stub = "x" * stub_len
    return {b.id: stub for b in selected}

def _initial_selection_size(
    resume: MasterResume,
    entries: list,
    requirements: JobRequirements,
    target_pages: int,
    semantic: dict[str, float] | None = None,
    *,
    share: float = 1.0,
    experience_share: float | None = None,
    max_per_entry: int | None = None,
    pools: list[list] | None = None,
    weights: list[float | None] | None = None,
) -> int:
    """Binary search the largest bullet count whose *post-rewrite* size should fit.

    Only used to size the first selection cheaply. Each candidate is estimated at the
    rewrite line budget, not master length; the real render/measure still confirms fit.
    `config.INITIAL_SELECTION_OVERSHOOT` lets the search claim a few lines past capacity
    so the first call packs denser (overflow/shorten still corrects if needed).

    The search floor is one bullet per chosen entry, never zero: dropping below that would
    delete an entry the ranking already decided to keep.

    `share` caps the search's upper bound at `round(total * share)` — a ceiling on the
    first draft, never a floor, and never allowed below one bullet per entry. It does not
    change what the loop grows back to afterward; see `config.INITIAL_BULLET_SHARE`.

    `experience_share`/`max_per_entry`/`pools`/`weights` are forwarded to
    `_select_at_rewrite_budget` so the estimate is computed against the same distribution
    the loop will actually select — `total` (the search's raw ceiling) is
    `selectable_total(entries, max_per_entry=...)` rather than the raw bullet count, since
    a per-entry cap can make part of the pool unreachable regardless of `share`.
    """
    floor = len(entries)
    total = selectable_total(entries, max_per_entry=max_per_entry)
    capacity = target_pages * config.LINES_PER_PAGE + config.INITIAL_SELECTION_OVERSHOOT

    # Ceiling only: `share` may lower the search's upper bound, never raise it past what
    # the estimate says fits. Clamped up to `floor` so a small share can never delete an
    # entry `choose_entries` already decided to keep.
    low, high = floor, max(floor, min(total, round(total * share)))
    while low < high:
        mid = (low + high + 1) // 2
        bullets = _select_at_rewrite_budget(
            entries, requirements, mid, semantic,
            experience_share=experience_share, max_per_entry=max_per_entry,
            pools=pools, weights=weights,
        )
        if fit_lines.estimate_lines(resume, bullets) <= capacity:
            low = mid
        else:
            high = mid - 1
    return low

def _section_pools(
    resume: MasterResume, entries: list, experience_share: float | None
) -> tuple[list[list] | None, list[float | None] | None]:
    """Group `entries` (already narrowed to the chosen subset) back into per-section
    pools, with one weight per pool derived from `experience_share`.

    Returns `(None, None)` when `experience_share` is None — the original flat-pool
    default, which `select_within_entries` handles without any pool at all. When set,
    every experience-kind section shares `experience_share` evenly and every
    project-kind section shares the remainder evenly: the natural generalisation of the
    old single-float experience-vs-projects split to any number of sections. Pools are
    built from section identity, not `isinstance` — two experience-kind sections are the
    same Python class, so only the section itself can tell them apart.
    """
    if experience_share is None:
        return None, None
    chosen_ids = {id(e) for e in entries}
    pools = [
        [e for e in section.entries if id(e) in chosen_ids] for section in resume.entry_sections
    ]
    kinds = [section.kind for section in resume.entry_sections]
    present = {i for i, pool in enumerate(pools) if pool}
    n_experience = sum(1 for i in present if kinds[i] == "experience")
    n_project = sum(1 for i in present if kinds[i] == "project")
    remainder = max(0.0, 1.0 - experience_share)

    weights: list[float | None] = []
    for i, kind in enumerate(kinds):
        if i not in present:
            weights.append(None)
        elif kind == "experience":
            weights.append(experience_share / n_experience if n_experience else None)
        else:
            weights.append(remainder / n_project if n_project else None)
    return pools, weights

def _overflow_report(
    resume: MasterResume, bullets: dict[str, str], target_pages: int, measured_lines: int
) -> str:
    """Why the page is over, in *measured* lines.

    The character-budget estimate undercounts real output by several lines on some
    templates, so quoting it produced "over by ~-4" for a page that plainly overflowed.
    The per-entry contributions below are still estimates; they only rank which entries
    are largest.
    """
    capacity = target_pages * config.LINES_PER_PAGE
    over = measured_lines - capacity

    contributions: list[tuple[int, str]] = []
    for section in resume.entry_sections:
        for entry in section.entries:
            lines = fit_lines._entry_lines(entry, bullets)
            if lines:
                name = entry.company if isinstance(entry, Experience) else entry.name
                contributions.append((lines, f"{section.title}: {name} (~{lines} lines)"))
    contributions.sort(reverse=True)
    top = "\n".join(f"  - {desc}" for _, desc in contributions[:5]) or "  (none)"

    if over > 0:
        head = (
            f"Measured {measured_lines} lines vs a {capacity}-line budget for "
            f"{target_pages} page(s), over by {over}."
        )
    else:
        head = (
            f"Measured {measured_lines} lines, within the {capacity}-line budget, but the "
            f"content still spilled onto another page (a page break or keep-together rule "
            f"moved it)."
        )
    return f"{head} Largest contributors:\n{top}"

def _bullet_score(
    bullet_id: str,
    sources: dict[str, Bullet],
    requirements: JobRequirements,
    semantic: dict[str, float] | None,
    members: dict[str, tuple[str, ...]],
    recency: dict[str, float] | None = None,
) -> float:
    """Relevance of a rendered bullet. A merged survivor is as relevant as its best
    member: merging must not make the strongest claim in a group easier to drop.

    `recency` maps bullet id to its entry's `selection.entry_recency` multiplier, so drops,
    pull-back ties and the top-up all prefer recent work the way selection does."""
    ids = members.get(bullet_id, (bullet_id,))
    recency = recency or {}
    return max(
        score_bullet(sources[m], requirements, semantic=semantic) * recency.get(m, 1.0)
        for m in ids if m in sources
    )

def _choose_pullbacks(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
    semantic: dict[str, float] | None,
    members: dict[str, tuple[str, ...]],
    *,
    count: int,
    layout: dict[str, render.LineFit] | None = None,
    measured_ids: set[str] | None = None,
    recency: dict[str, float] | None = None,
) -> dict[str, int]:
    """`{bullet id: character ceiling}` for the bullets worth a one-line pull-back.

    Eligible: multi-line bullets whose last line is at most `config.PULLBACK_MAX_FILL`
    full — cutting a few words frees a whole line. Emptiest last line first (the smallest
    cut), ties to the lower relevance. Merged survivors are excluded: they were just
    condensed from several sources, and a single-source guard check would misread them.

    `layout`/`measured_ids` come from the overflowing PDF (`_widow_fits`). A measured
    bullet is judged on its real line count and last-line fill, with its ceiling one
    measured line below where it ends; the character estimate both missed real near-widows
    and flagged full lines. Unmeasured bullets fall back to the estimate (`widowed`).
    """
    estimated = widowed(texts, max_fill=config.PULLBACK_MAX_FILL)
    measured_ids = measured_ids if layout is not None and measured_ids is not None else set()
    eligible: dict[str, int] = {}
    fill: dict[str, float] = {}
    # A bullet past the line cap is always eligible, ranked first, ceilinged at the cap:
    # cutting it frees a line or more without dropping content, and the widow pass would
    # cap it anyway once the draft fits.
    cap = fit_types._TARGET_LINES_PER_BULLET
    for bid, text in texts.items():
        if bid in measured_ids:
            line_fit = layout[bid]
            if line_fit.lines > cap:
                eligible[bid] = int(cap * line_fit.chars_per_line - config.WIDOW_SAFETY)
                fill[bid] = -1.0
            elif line_fit.lines > 1 and line_fit.last_fill <= config.PULLBACK_MAX_FILL:
                ceiling = int((line_fit.lines - 1) * line_fit.chars_per_line - config.WIDOW_SAFETY)
                if ceiling >= 1:
                    eligible[bid] = ceiling
                    fill[bid] = line_fit.last_fill
        elif config.line_span(text) > cap:
            eligible[bid] = int(cap * config.CHARS_PER_LINE - config.WIDOW_SAFETY)
            fill[bid] = -1.0
        elif bid in estimated:
            eligible[bid] = estimated[bid]
            fill[bid] = config.last_line_fill(text) / config.CHARS_PER_LINE
    ranked = sorted(
        (bid for bid in eligible if bid not in members),
        key=lambda bid: (
            fill[bid],
            _bullet_score(bid, sources, requirements, semantic, members, recency),
        ),
    )
    overlong = sum(1 for bid in ranked if fill[bid] < 0)
    return {bid: eligible[bid] for bid in ranked[: max(0, count, overlong)]}

def _choose_drops(
    entries: list[Experience | Project],
    texts: dict[str, str],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
    semantic: dict[str, float] | None,
    members: dict[str, tuple[str, ...]],
    *,
    overflow: int,
) -> list[str]:
    """Bullet ids to drop whole, lowest relevance first, until `overflow` lines are freed.

    Pure and deterministic. Never takes an entry's last rendered bullet — the same floor
    `select_within_entries` keeps, because `render.build_context` omits an entry with no
    bullets and the loop must not silently delete a job it decided to keep. Prefers the
    weakest bullet tall enough to cover what remains; when none is, takes the weakest and
    repeats.

    The most recent job's lead bullet (`_lead_bullet`) is taken only when nothing else
    can be: it is the candidate's headline, and a posting-specific relevance score that
    rates it low otherwise strips the newest role down to its supporting lines.
    """
    owner = {b.id: e for e in entries for b in e.bullets}
    recency = {b.id: entry_recency(e) for e in entries for b in e.bullets}
    lead = _lead_bullet(entries, texts)
    remaining_in_entry: dict[int, int] = {}
    for bid in texts:
        entry = owner.get(bid)
        if entry is not None:
            remaining_in_entry[id(entry)] = remaining_in_entry.get(id(entry), 0) + 1

    chosen: list[str] = []
    remaining = overflow
    while remaining > 0:
        candidates = [
            bid
            for bid in texts
            if bid not in chosen
            and bid in owner
            and remaining_in_entry.get(id(owner[bid]), 0) > 1
        ]
        if not candidates:
            break
        candidates = [bid for bid in candidates if bid != lead] or candidates
        covering = [bid for bid in candidates if fit_lines._bullet_lines(texts[bid]) >= remaining]
        pick = min(
            covering or candidates,
            key=lambda bid: (
                _bullet_score(bid, sources, requirements, semantic, members, recency),
                -remaining_in_entry[id(owner[bid])],
            ),
        )
        chosen.append(pick)
        remaining_in_entry[id(owner[pick])] -= 1
        remaining -= fit_lines._bullet_lines(texts[pick])
    return chosen

def _lead_bullet(entries: list[Experience | Project], texts: dict[str, str]) -> str | None:
    """The first on-page bullet, in master order, of the most recent experience entry.

    Most recent by `entry_recency`; ties keep master order, which lists newest first.
    """
    best: tuple[float, str] | None = None
    for entry in entries:
        if not isinstance(entry, Experience):
            continue
        first = next((b.id for b in entry.bullets if b.id in texts), None)
        if first is None:
            continue
        recency = entry_recency(entry)
        if best is None or recency > best[0]:
            best = (recency, first)
    return best[1] if best else None
