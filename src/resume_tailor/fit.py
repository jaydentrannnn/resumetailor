"""The fit loop: select, rewrite, render, and measure until a resume fits its page target.

Page fitting is budget-first (see CLAUDE.md): a cheap character/line estimate sizes the
initial selection, while a real Word render is what decides both overflow and underflow
and produces the file the user actually gets. `estimate_lines` is also the fallback used
when Word/COM is unavailable, so a run can still finish (with a warning) without ever
generating XML or layout logic outside `render.py`.

Never silently truncates: an overflowing draft climbs a fixed ladder (combine, pull back
near-widowed bullets, drop the weakest bullets), and if that cannot fit the page `fit()`
raises `FitError` naming which sections are still over budget. Every merge, pull-back and
drop is reported, never silent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from . import config, events, facets, render
from .data import Bullet, Experience, MasterResume, Project
from .jd import JobRequirements
from .merge import MergeGroup
from .merge import propose as propose_merges
from .rewrite import (
    RewriteOutcome,
    _polish,
    entry_recency,
    merge_into,
    pull_back,
    rewrite_bullets,
    score_entry,
    select_entries,
    select_within_entries,
    selectable_total,
    widowed,
)
from .rewrite import score as score_bullet
from .template_profile import ContactField, active_layout

#: How many physical lines a bullet's rewritten text is targeted at, on average. Passed
#: to `rewrite_bullets` as its starting character budget before any shortening.
_TARGET_LINES_PER_BULLET = 2


def default_bullet_char_budget() -> int:
    """Character budget the first rewrite pass targets for each bullet.

    Exposed so the web config endpoint can tell the editor the same soft/hard length
    band the rewrite prompt advertises, without duplicating `_TARGET_LINES_PER_BULLET`
    or `CHARS_PER_LINE` on the SPA side.
    """
    return _TARGET_LINES_PER_BULLET * config.CHARS_PER_LINE


class FitError(RuntimeError):
    """Raised when the fit loop exhausts its retries without reaching the page target."""


@dataclass
class FitResult:
    out_path: Path
    pages: int
    pages_are_estimated: bool
    iterations: int
    bullets_selected: int
    bullets_total: int

    #: The final {bullet_id: rewritten text} that was rendered. Carried so `report.py` can
    #: attribute rewrites back to their sections without re-running selection.
    bullets: dict[str, str] = field(default_factory=dict)

    #: Whether a semantic relevance table informed selection. Reported, because it changes
    #: how a surprising ranking should be read: with it off, ranking is pure tag overlap.
    semantic_used: bool = False

    #: Bullets the widow pass successfully repaired, and bullets still ending on a
    #: near-empty line. Reported because a wasted line is invisible in a page count — a
    #: resume can fit its target and still be throwing away half an entry's worth of space.
    widows_repaired: int = 0
    widows_remaining: int = 0

    #: Bullets whose opening verb the polish pass replaced, and bullets still opening with
    #: a verb another bullet already used. Costs no page space — reported because a resume
    #: that opens three bullets "Designed... Engineered... Architected..." reads as one
    #: sentence, and nothing else in the output would say so.
    verbs_diversified: int = 0
    verb_collisions_remaining: int = 0

    #: Merge groups successfully accepted and applied during rewriting.
    merges: list[MergeGroup] = field(default_factory=list)

    #: Bullets the overflow ladder pulled back by a line, and bullet ids it dropped whole.
    #: Reported because both change the resume's content, not just its length.
    pulled_back: int = 0
    dropped: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)

    #: Bullet ids the top-up stage added after the loop settled underfull (re-added
    #: bullets, a 4th bullet, or a new entry's bullets). Reported because they change
    #: the resume's shape, not just its length.
    topped_up: list[str] = field(default_factory=list)

    #: One record per render: ``{step, bullets, lines, pages, fill, ...}``. Persisted in
    #: the run report so a surprising final fill can be explained after the fact — the
    #: progress events that say the same thing are not saved.
    trace: list[dict] = field(default_factory=list)


@dataclass
class _Draft:
    """A bullet set that fit its page target, kept so a later, fuller set that cannot be
    trimmed to fit can fall back to it instead of failing the run."""

    texts: dict[str, str]
    selected: list[Bullet]
    outcome: RewriteOutcome
    pulled: int
    dropped: list[str]
    members: dict[str, tuple[str, ...]]
    coursework: list[list[str]] = field(default_factory=list)


def _widow_fits(
    path: Path, texts: dict[str, str], *, estimated: bool
) -> tuple[dict[str, render.LineFit], set[str]]:
    measured: dict[str, render.LineFit] = {}
    pdf = path.with_suffix(".pdf")
    if not estimated and pdf.exists():
        measured = render.line_layout(pdf, texts)
    measured_ids = set(measured)
    for bid, text in texts.items():
        if bid not in measured:
            measured[bid] = render.LineFit(
                config.line_span(text),
                config.last_line_fill(text) / config.CHARS_PER_LINE,
                float(config.CHARS_PER_LINE),
            )
    return measured, measured_ids


def _widow_targets(
    texts: dict[str, str], sources: dict[str, Bullet],
    layout: dict[str, render.LineFit], *, measured_lines: int, capacity: int,
    members: dict[str, tuple[str, ...]], estimated: bool,
    measured_ids: set[str] | None = None,
) -> dict[str, tuple[int, int]]:
    targets: dict[str, tuple[int, int]] = {}
    measured_ids = measured_ids if measured_ids is not None else set(layout)
    for bid, text in texts.items():
        fit = layout[bid]
        floor = (config.WIDOW_MIN_FILL if not estimated and bid in measured_ids
                 else config.WIDOW_EST_FILL)
        if fit.lines <= 1 or fit.last_fill >= floor or bid not in sources:
            continue
        span = fit.chars_per_line
        if fit.last_fill <= config.WIDOW_SHORTEN_MAX or measured_lines >= capacity or bid in members:
            high = int((fit.lines - 1) * span - config.WIDOW_SAFETY)
            if high >= 1:
                targets[bid] = (0, high)
        elif len(sources[bid].text) > len(text):
            low = math.ceil(
                len(text) + (config.WIDOW_EXTEND_FILL - fit.last_fill) * span - 1e-9
            )
            high = int(fit.lines * span - config.WIDOW_SAFETY)
            if low <= high:
                targets[bid] = (low, high)
    return targets


def _line_saving_ceilings(
    targets: dict[str, tuple[int, int]], layout: dict[str, render.LineFit]
) -> dict[str, int]:
    """For EXTEND targets, the length at which a draft instead saves the whole last line.

    A draft that misses the extend window by coming back a full line shorter also cures
    the widow, so `_polish` accepts either rather than asking the model to hit one narrow
    window exactly."""
    ceilings: dict[str, int] = {}
    for bid, (low, _high) in targets.items():
        if low <= 0:
            continue
        fit = layout[bid]
        ceiling = int((fit.lines - 1) * fit.chars_per_line - config.WIDOW_SAFETY)
        if ceiling >= 1:
            ceilings[bid] = ceiling
    return ceilings


# --------------------------------------------------------------------------------------
# Budget estimation — cheap, no LLM, no render. Mirrors build_context's own filtering
# rules so the estimate and the real render always agree on which entries survive.
# --------------------------------------------------------------------------------------


def _bullet_lines(text: str) -> int:
    """Delegated so the budget estimator and the widow detector cannot disagree.

    Both answer "how many lines is this text?" — if they ever computed it differently, the
    loop would be sizing pages against one definition while `rewrite.widowed` trimmed
    against another.
    """
    return config.line_span(text)


def _fixed_overhead_lines(resume: MasterResume, *, layout: dict | None = None) -> int:
    """Lines that render regardless of selection: header, contact, education, skills.

    Education and skills never vary by posting, but their line *count* still depends on
    the master resume's own content (coursework wrap, GPA suffix, skill group length),
    so it is measured from `resume` rather than hard-coded. Sections disabled in the
    active template profile contribute zero.
    """
    layout = layout if layout is not None else active_layout()
    enabled = layout.get("enabled") or {}

    lines = 2  # name line + contact line
    if enabled.get("education", True):
        lines += 1  # section header
        for edu in resume.education:
            lines += 1  # school | location ... dates
            lines += _bullet_lines(render._degree_line(edu))
            for detail in render._education_details(edu):
                lines += _bullet_lines(detail)

    if enabled.get("skills", True) and resume.skills:
        lines += 1  # section header
        for group in resume.skills:
            lines += _bullet_lines(config.skill_group_line(group.label, group.items))
    return lines


def _entry_lines(entry: Experience | Project, bullets: dict[str, str]) -> int:
    kept = [bullets[b.id] for b in entry.bullets if b.id in bullets]
    if not kept:
        return 0
    # An experience entry has its own header line plus a separate title line
    # (`render.build_context`'s `job` dict); a project's header line already carries
    # name/tech/date with no second line.
    header_lines = 2 if isinstance(entry, Experience) else 1
    return header_lines + sum(_bullet_lines(text) for text in kept)


def _section_lines(entries: list[Experience] | list[Project], bullets: dict[str, str]) -> int:
    """Lines for one entry section, honoring the bullets filter.

    An entry whose bullets were all dropped contributes nothing at all — not even its
    header — mirroring `render.build_context`'s own filtering.
    """
    per_entry = [_entry_lines(entry, bullets) for entry in entries]
    total = sum(per_entry)
    return total + (1 if total else 0)  # section header, once, if anything survived


def _spacer_lines(resume: MasterResume, bullets: dict[str, str], *, layout: dict) -> int:
    """Blank-separator lines a generic-mode template's spacing donors add on top of
    content lines — see `template_profile.SpacingProfile` and `template_build.
    build_generic`. Zero whenever the active profile has no spacer donors set, so this
    term is a pure addition for a template that actually reproduces blank lines; every
    existing profile (which has none) sizes exactly as before.

    A separate term rather than folded into `_fixed_overhead_lines`/`_section_lines`:
    those two are shared with fixed mode, where no per-section heading spacer exists to
    count, and mixing "which section is first overall" bookkeeping into them is exactly
    where this would get wrong. This only sizes selection; the real render still
    measures, so an error here costs a retry round, not a wrong final page.
    """
    spacing = layout.get("spacing") or {}
    # Each value is a run of chrome paragraph ids (see `template_profile.SpacingProfile`),
    # so its length is how many physical lines that slot costs each time it fires.
    before_n = len(spacing.get("before_heading") or [])
    after_n = len(spacing.get("after_heading") or [])
    between_n = len(spacing.get("between_entries") or [])
    if not (before_n or after_n or between_n):
        return 0

    enabled = layout.get("enabled") or {}
    kind_enabled = {
        "experience": enabled.get("experience", True),
        "project": enabled.get("projects", True),
        "list": enabled.get("list_section", True),
        "education": enabled.get("education", True),
        "skills": enabled.get("skills", True),
    }

    rendered = 0
    between_total = 0
    for section in resume.sections:
        if not kind_enabled.get(section.kind, True):
            continue
        if section.kind in ("experience", "project"):
            surviving = sum(
                1 for e in section.entries if any(b.id in bullets for b in e.bullets)
            )
            if surviving == 0:
                continue
            rendered += 1
            between_total += max(0, surviving - 1)
        elif section.kind == "education":
            if not section.entries:
                continue
            rendered += 1
            between_total += max(0, len(section.entries) - 1)
        else:  # skills / list — never trimmed by selection, render whenever non-empty
            if not section.entries:
                continue
            rendered += 1

    return (
        before_n * max(0, rendered - 1) + after_n * rendered + between_n * between_total
    )


def estimate_lines(
    resume: MasterResume,
    bullets: dict[str, str],
    *,
    layout: dict | None = None,
) -> int:
    """Cheap character-budget estimate of total rendered lines for this bullet set.

    `layout["section_mode"]` changes how many section-header lines same-kind sections
    cost: under `"fixed"` (the default — see `template_profile.TemplateProfile.
    section_mode`), every experience-kind section flattens under the one physical
    "EXPERIENCE" heading the template was built with, and likewise for projects — so two
    experience-kind resume sections cost one header line, not two. Under `"generic"`,
    each resume section gets its own tagged heading, so each contributes its own header
    line. Getting this wrong biases the estimate in the direction that costs an extra
    grow-or-shorten round, not a wrong final page — the real render still measures.
    """
    layout = layout if layout is not None else active_layout()
    enabled = layout.get("enabled") or {}
    section_mode = layout.get("section_mode", "fixed")
    total = _fixed_overhead_lines(resume, layout=layout)

    if section_mode == "generic":
        for section in resume.entry_sections:
            if section.kind == "project" and not enabled.get("projects", True):
                continue
            if section.kind == "experience" and not enabled.get("experience", True):
                continue
            total += _section_lines(section.entries, bullets)
        total += _spacer_lines(resume, bullets, layout=layout)
    else:
        if enabled.get("experience", True):
            experience_entries = [
                e for s in resume.entry_sections if s.kind == "experience" for e in s.entries
            ]
            total += _section_lines(experience_entries, bullets)
        if enabled.get("projects", True):
            project_entries = [
                e for s in resume.entry_sections if s.kind == "project" for e in s.entries
            ]
            total += _section_lines(project_entries, bullets)
    return total


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
    stub_len = max(40, _TARGET_LINES_PER_BULLET * config.CHARS_PER_LINE - config.WIDOW_SAFETY)
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
        if estimate_lines(resume, bullets) <= capacity:
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
            lines = _entry_lines(entry, bullets)
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

    `recency` maps bullet id to its entry's `rewrite.entry_recency` multiplier, so drops,
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
    for bid, text in texts.items():
        if bid in measured_ids:
            line_fit = layout[bid]
            if line_fit.lines > 1 and line_fit.last_fill <= config.PULLBACK_MAX_FILL:
                ceiling = int((line_fit.lines - 1) * line_fit.chars_per_line - config.WIDOW_SAFETY)
                if ceiling >= 1:
                    eligible[bid] = ceiling
                    fill[bid] = line_fit.last_fill
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
    return {bid: eligible[bid] for bid in ranked[: max(0, count)]}


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
    """
    owner = {b.id: e for e in entries for b in e.bullets}
    recency = {b.id: entry_recency(e) for e in entries for b in e.bullets}
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
        covering = [bid for bid in candidates if _bullet_lines(texts[bid]) >= remaining]
        pick = min(
            covering or candidates,
            key=lambda bid: (
                _bullet_score(bid, sources, requirements, semantic, members, recency),
                -remaining_in_entry[id(owner[bid])],
            ),
        )
        chosen.append(pick)
        remaining_in_entry[id(owner[pick])] -= 1
        remaining -= _bullet_lines(texts[pick])
    return chosen


# --------------------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------------------


def fit(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    target_pages: int | None = None,
    template: Path | None = None,
    out: Path | None = None,
    max_experience: int | None = None,
    max_projects: int | None = None,
    semantic: dict[str, float] | None = None,
    repair_widows: bool = True,
    repair_verbs: bool = True,
    merge_bullets: bool = True,
    include_project_links: bool = True,
    contact_fields: list[ContactField] | None = None,
    fill_target: float | None = None,
    initial_bullet_share: float | None = None,
    experience_bullet_share: float | None = None,
    max_bullets_per_entry: int | None = None,
    coursework_pool: list[str] | None = None,
    on_event: events.ProgressCallback | None = None,
) -> FitResult:
    """Select, rewrite, render, and measure until the resume fits `target_pages`.

    Which entries appear is decided once up front by `choose_entries` (experience and
    projects ranked separately, capped by `config.MAX_EXPERIENCE_ENTRIES` /
    `MAX_PROJECT_ENTRIES`). The loop then varies how many *bullets* those entries get —
    overall via `limit`, and now optionally by section (`experience_bullet_share`) and
    per-entry (`max_bullets_per_entry`) — but never drops an entry entirely.

    `semantic` is an optional {bullet_id: 0-10} relevance table from `rewrite.score_table`,
    computed once by the caller and held fixed for the whole run. It must not be recomputed
    per iteration: a table that shifted between grow steps could swap bullets rather than
    add them, which is the one thing the estimate/measure relationship depends on.

    Overflow (measured page count above target) climbs a ladder on the *same* draft, one
    rung at a time, stopping as soon as it fits: combine redundant bullets
    (`merge_bullets`), pull back bullets whose last line is nearly empty by one line
    (`config.PULLBACK_MAX_FILL`), then drop the weakest bullets whole (at most
    `config.MAX_DROP_ROUNDS` rounds, never an entry's last bullet). Only the first rung
    and the pull-back call the model, each once; drops cost a render. A ladder that still
    cannot fit raises `FitError` — unless an earlier, smaller draft already fit, in which
    case that draft is returned with a warning instead of being thrown away.

    `repair_widows` enables one post-render pass using PDF line boxes. It matters to the
    loop because a short final line wastes space and can push a fitting resume onto two
    pages. Without PDF measurement, the pass uses the conservative character estimate.
    `coursework_pool` (the education pool `facets` chose from) lets that pass top up or
    trim the coursework line; without it, coursework is left as `facets` selected it.

    `repair_verbs` is passed through the same way and shares that call. It does not affect
    fitting at all — a repeated opening verb costs no space — so it is purely a readability
    pass the loop carries rather than owns.

    `merge_bullets` enables the combine rung, which fires only after a measured overflow:
    merging is a space lever, and one applied to a page that already fit combined bullets
    for no reason.

    `include_project_links` is passed straight to `render.render`. It is not a fit lever:
    the link sits inline in a project's header line, so hiding it frees no lines.

    `contact_fields` is also passed straight to `render.render` and is not a fit lever
    either: the contact line is one centered line regardless of how many fields it
    carries, so `_fixed_overhead_lines`' flat `lines = 2` stays correct either way.

    `fill_target` overrides `config.UNDERFLOW_THRESHOLD` for this run (fraction of page
    capacity). Lower means the loop accepts a sparser page; higher packs tighter at the
    cost of extra grow/rewrite rounds.

    `initial_bullet_share` overrides `config.INITIAL_BULLET_SHARE`: a ceiling on the
    fraction of available bullets `_initial_selection_size` may claim for the first draft,
    never below one bullet per chosen entry. It bounds only the first draft, not the grow
    loop below — at the default `fill_target`, a low share is often grown back and mostly
    trades extra rewrite rounds for the same final page. Pair it with a lower `fill_target`
    to actually end on a sparser page.

    `experience_bullet_share` overrides `config.EXPERIENCE_BULLET_SHARE`: the fraction of
    the *overall* selected bullets that go to experience, budgeted separately from
    projects (see `rewrite._section_budgets`). `None` is one flat pool ranked purely by
    `score`, which is how a keyword-dense project can otherwise out-rank every job for the
    shared discretionary budget.

    `max_bullets_per_entry` overrides `config.MAX_BULLETS_PER_ENTRY`: a ceiling on how many
    bullets any single job or project may take. Because this can make the achievable total
    lower than the raw bullet pool, the loop's grow ceiling is
    `rewrite.selectable_total(entries, max_per_entry=...)`, not the raw count — comparing
    against the raw count here would keep raising `limit` while the selection stays
    unchanged, burning grow attempts for nothing.

    `on_event` observes progress. A run costs several minutes of model calls and renders,
    so a UI driving this needs to report which iteration it is on; the callback cannot
    influence the loop and is optional everywhere.

    Underflow (measured fill below `fill_target`) restores bullets and starts a fresh
    rewrite — a half-empty page is a failure mode, not an acceptable result, per
    CLAUDE.md. Unlike overflow it is not fatal: after `config.MAX_GROW_ATTEMPTS` the loop
    returns the fullest version it reached and says so in `FitResult.warnings`.
    """
    target_pages = target_pages or config.DEFAULT_PAGE_TARGET
    # Local so a per-run override does not mutate the process-wide constant.
    underflow = fill_target if fill_target is not None else config.UNDERFLOW_THRESHOLD
    initial_share = (
        initial_bullet_share if initial_bullet_share is not None else config.INITIAL_BULLET_SHARE
    )
    section_share = (
        experience_bullet_share
        if experience_bullet_share is not None
        else config.EXPERIENCE_BULLET_SHARE
    )
    entry_cap = (
        max_bullets_per_entry if max_bullets_per_entry is not None else config.MAX_BULLETS_PER_ENTRY
    )
    warnings: list[str] = []
    iterations = 0
    grow_attempts = 0
    # Set the first time a bullet set overflows; growing back to (or past) it would only
    # re-add what the ladder just removed and overflow again.
    grow_cap: int | None = None
    best: _Draft | None = None

    # A resume section whose kind the active template has no prototype for is skipped by
    # `render.build_context` silently (it has no result channel of its own to carry a
    # warning) — this is where that becomes visible, per the "skip it and warn loudly"
    # policy for a declared-but-unbuildable section kind.
    layout_check = active_layout()
    enabled_check = layout_check.get("enabled") or {}
    for section in resume.sections:
        if not section.entries:
            continue
        key = config.SECTION_KIND_ENABLED_KEY[section.kind]
        if not enabled_check.get(key, config.SECTION_KIND_ENABLED_DEFAULT[section.kind]):
            warnings.append(
                f"Section {section.title!r} has no matching layout in the active "
                f"template and will not appear in the rendered resume."
            )

    entries = choose_entries(
        resume,
        requirements,
        max_experience=max_experience,
        max_projects=max_projects,
        semantic=semantic,
    )
    if not entries:
        raise FitError("No experience or project entries were selected; nothing to render.")

    # The pool the loop draws from is the chosen entries' bullets, not the whole master
    # resume — a bullet in a dropped entry can never come back. `total_bullets` is the raw
    # pool size (reported in `FitResult.bullets_total`); `growth_ceiling` is what the caps
    # actually let the loop reach, which is what the grow condition must compare against.
    total_bullets = sum(len(e.bullets) for e in entries)
    growth_ceiling = selectable_total(entries, max_per_entry=entry_cap)
    section_pools, section_weights = _section_pools(resume, entries, section_share)
    limit = _initial_selection_size(
        resume, entries, requirements, target_pages, semantic, share=initial_share,
        max_per_entry=entry_cap, pools=section_pools, weights=section_weights,
    )
    share_note = (
        f" (capped at {initial_share:.0%} of {total_bullets})" if initial_share < 1.0 else ""
    )
    events.emit(
        on_event,
        "fit",
        f"Selected {len(entries)} entries; starting at {limit} of {total_bullets} "
        f"bullets{share_note}",
        entries=len(entries),
        limit=limit,
        total_bullets=total_bullets,
        initial_bullet_share=initial_share,
        experience_bullet_share=section_share,
        max_bullets_per_entry=entry_cap,
    )

    by_id: dict[str, Bullet] = {b.id: b for e in entries for b in e.bullets}
    capacity = target_pages * config.LINES_PER_PAGE
    trace: list[dict] = []
    topped_up: list[str] = []

    # Every entry the template can render, for the top-up's new-entry step (the same
    # section gating `choose_entries` applies), with each bullet's recency multiplier.
    enabled_kinds = active_layout().get("enabled") or {}
    section_of: dict[int, str] = {}
    candidate_entries: list = []
    for section in resume.entry_sections:
        key = "projects" if section.kind == "project" else "experience"
        if not enabled_kinds.get(key, True):
            continue
        for entry in section.entries:
            section_of[id(entry)] = section.id
            candidate_entries.append(entry)
    recency_of: dict[str, float] = {
        b.id: entry_recency(e) for e in candidate_entries for b in e.bullets
    }
    all_sources: dict[str, Bullet] = {b.id: b for e in candidate_entries for b in e.bullets}
    all_sources.update(by_id)

    def draw(texts: dict[str, str], step: str = "draft", **note) -> tuple[Path, int, int, bool]:
        """Render `texts`, then measure: `(doc path, pages, lines, measurement estimated)`.

        `step` and `note` label the draw in `trace` (`FitResult.trace`)."""
        nonlocal iterations
        iterations += 1
        events.emit(on_event, "render", f"Rendering draft {iterations}", iteration=iterations)
        path = render.render(
            resume,
            bullets=texts,
            template=template,
            out=out,
            include_project_links=include_project_links,
            contact_fields=contact_fields,
        )
        try:
            # Keep Word alive across retries within this run; the caller gets the
            # final measurement (and Word is released) once the loop concludes.
            pages_, lines_ = render.measure_detail(path, keep_active=True)
            estimated = False
        except RuntimeError as exc:
            warnings.append(f"PDF measurement unavailable, using budget estimate: {exc}")
            lines_ = estimate_lines(resume, texts)
            pages_ = math.ceil(lines_ / config.LINES_PER_PAGE)
            estimated = True
        events.emit(
            on_event,
            "measure",
            f"Draft {iterations}: {pages_} page(s), {lines_} line(s)",
            iteration=iterations,
            pages=pages_,
            lines=lines_,
            estimated=estimated,
        )
        trace.append({
            "step": step,
            "bullets": len(texts),
            "lines": lines_,
            "pages": pages_,
            "fill": round(lines_ / capacity, 3),
            "estimated": estimated,
            **note,
        })
        return path, pages_, lines_, estimated

    def widow_pass(only: set[str] | None = None) -> None:
        """One bounded measured layout pass on a draft that already fits.

        Shortens or extends bullets whose measured last line is under
        `config.WIDOW_MIN_FILL` (`_widow_targets`), and tops up or trims the coursework
        line. Keeps the pre-pass document so any unexpected page growth is reverted
        exactly. `only` restricts the pass to those bullet ids and skips coursework — the
        top-up uses it to repair just the bullets it added.
        """
        nonlocal rewritten, doc_path, pages, measured_lines, pages_are_estimated
        course_edu = (
            next((edu for edu in resume.education if edu.coursework), None)
            if only is None else None
        )
        course_text = (
            "Relevant Coursework: " + ", ".join(course_edu.coursework)
            if course_edu else None
        )
        requested = dict(rewritten)
        if course_text:
            requested["__coursework__"] = course_text
        layout, measured_ids = _widow_fits(
            doc_path, requested, estimated=pages_are_estimated
        )

        def is_widow(fits: dict[str, render.LineFit], measured: set[str], bid: str) -> bool:
            return fits[bid].lines > 1 and fits[bid].last_fill < (
                config.WIDOW_MIN_FILL if bid in measured else config.WIDOW_EST_FILL
            )

        scope = set(rewritten) if only is None else set(rewritten) & only
        before_widows = {bid for bid in scope if is_widow(layout, measured_ids, bid)}
        targets = _widow_targets(
            rewritten, by_id, layout, measured_lines=measured_lines,
            capacity=capacity, members=members, estimated=pages_are_estimated,
            measured_ids=measured_ids,
        ) if repair_widows else {}
        if only is not None:
            targets = {bid: window for bid, window in targets.items() if bid in only}
        old_texts = dict(rewritten)
        old_courses = list(course_edu.coursework) if course_edu else []
        if targets:
            repair_sources = dict(by_id)
            for survivor, member_ids in members.items():
                if survivor in targets:
                    originals = [by_id[mid] for mid in member_ids]
                    repair_sources[survivor] = Bullet(
                        id=survivor,
                        text=" ".join(item.text for item in originals),
                        tags=list({tag for item in originals for tag in item.tags}),
                    )
            repaired, _, _, rejected = _polish(
                rewritten, repair_sources, requirements, repair_widows=False,
                repair_verbs=False, targets=targets,
                line_ceilings=_line_saving_ceilings(targets, layout),
            )
            rewritten = outcome.texts = repaired
            outcome.widow_repairs_rejected.update(rejected)
        if repair_widows and course_edu and coursework_pool:
            course_edu.coursework = facets.fit_coursework_to_budget(
                old_courses, pool=coursework_pool,
                jd_keywords=[k.phrase for k in requirements.keywords],
                chars_per_line=layout["__coursework__"].chars_per_line,
                last_fill=(layout["__coursework__"].last_fill
                           if "__coursework__" in measured_ids else None),
                rendered_lines=(layout["__coursework__"].lines
                                if "__coursework__" in measured_ids else None),
            )
        changed = rewritten != old_texts or (
            course_edu is not None and course_edu.coursework != old_courses
        )
        if changed:
            doc_path, pages, measured_lines, pages_are_estimated = draw(rewritten, "widow")
            if pages > target_pages:
                rewritten = outcome.texts = old_texts
                if course_edu:
                    course_edu.coursework = old_courses
                doc_path, pages, measured_lines, pages_are_estimated = draw(rewritten, "revert")
                warnings.append("Widow repair overflowed the page; kept the fitting draft.")
                changed = False
        if changed:
            final_layout, final_measured_ids = _widow_fits(
                doc_path, rewritten, estimated=pages_are_estimated
            )
        else:
            final_layout, final_measured_ids = layout, measured_ids
        remaining = {
            bid for bid in rewritten if is_widow(final_layout, final_measured_ids, bid)
        }
        if only is None:
            outcome.widows_repaired = len(before_widows - remaining)
        else:
            outcome.widows_repaired += len(before_widows - remaining)
        outcome.measured_widows_remaining = len(remaining)

    def entry_label(entry) -> str:
        return getattr(entry, "company", "") or getattr(entry, "name", "") or "an entry"

    def rewrite_new(new: list[Bullet]) -> dict[str, str]:
        """Rewrite only `new`, then re-voice any of them whose opening verb the page
        already uses. Existing bullets are never re-requested: their text and wrap are
        already measured."""
        fresh = rewrite_bullets(
            new, requirements, char_budget=char_budget,
            repair_widows=False, repair_verbs=repair_verbs, on_event=on_event,
            verb_context=dict(rewritten),
        )
        outcome.fabrications_rejected.update(fresh.fabrications_rejected)
        outcome.verbs_diversified += fresh.verbs_diversified
        return {b.id: fresh.texts.get(b.id, b.text) for b in new}

    def add(new: list[Bullet], step: str, *, shrink: int) -> list[str]:
        """Add `new` to the page: one rewrite, then render. On overflow, retry up to
        `shrink` times without the last (lowest-ranked) bullet — render only, no new
        call. Returns the ids kept, or [] after re-rendering the pre-step draft."""
        nonlocal rewritten, doc_path, pages, measured_lines, pages_are_estimated
        base = dict(rewritten)
        fresh = rewrite_new(new)
        ids = [b.id for b in new]
        while ids:
            candidate = {**base, **{bid: fresh[bid] for bid in ids}}
            drawn = draw(candidate, step, added=list(ids))
            if drawn[1] <= target_pages:
                rewritten = outcome.texts = candidate
                doc_path, pages, measured_lines, pages_are_estimated = drawn
                return ids
            if shrink <= 0 or len(ids) == 1:
                break
            shrink -= 1
            ids = ids[:-1]
        doc_path, pages, measured_lines, pages_are_estimated = draw(base, "revert")
        rewritten = outcome.texts = base
        return []

    def bullet_cost(bullet: Bullet) -> int:
        # The rewrite is asked for `_TARGET_LINES_PER_BULLET` lines; a shorter source
        # stays shorter.
        return min(_bullet_lines(bullet.text), _TARGET_LINES_PER_BULLET)

    def bullet_rank(bullet: Bullet) -> float:
        return score_bullet(bullet, requirements, semantic=semantic) * recency_of.get(
            bullet.id, 1.0
        )

    def top_up_ladder() -> tuple[list[str], str | None]:
        """One A/B/C pass. Returns (ids added, why it stopped short or None)."""
        nonlocal total_bullets
        added: list[str] = []
        target_lines = math.ceil(underflow * capacity)

        def shortfall() -> tuple[int, int]:
            return target_lines - measured_lines, capacity - measured_lines

        def rendered_ids() -> set[str]:
            ids = set(rewritten)
            for member_ids in members.values():
                ids.update(member_ids)
            return ids

        def counts() -> dict[int, int]:
            live = rendered_ids()
            return {id(e): sum(1 for b in e.bullets if b.id in live) for e in entries}

        def stop_text() -> str:
            return (
                f"no more bullets or entries fit in the remaining "
                f"{max(0, capacity - measured_lines)} line(s)"
            )

        def take(ids: list[str]) -> None:
            added.extend(ids)
            topped_up.extend(ids)
            already = {b.id for b in selected}
            for bid in ids:
                if bid in dropped:
                    dropped.remove(bid)
                if bid not in already:
                    selected.append(all_sources[bid])

        goal, room = shortfall()
        if goal <= 0:
            return added, None

        # A — bullets of the chosen entries the caps still allow, including any the
        # drop rung cut: they were relevant enough to pick once.
        live, per_entry = rendered_ids(), counts()
        owner = {b.id: e for e in entries for b in e.bullets}
        pool = sorted(
            (b for e in entries for b in e.bullets
             if b.id not in live and (entry_cap is None or per_entry[id(e)] < entry_cap)),
            key=bullet_rank, reverse=True,
        )
        picked: list[Bullet] = []
        estimate = 0
        for bullet in pool:
            entry = owner[bullet.id]
            if entry_cap is not None and per_entry[id(entry)] >= entry_cap:
                continue
            cost = bullet_cost(bullet)
            if estimate + cost > room:
                continue
            picked.append(bullet)
            per_entry[id(entry)] += 1
            estimate += cost
            if estimate >= goal:
                break
        if picked:
            events.emit(
                on_event, "fit",
                f"Page {measured_lines / capacity:.0%} full; adding back "
                f"{len(picked)} bullet(s)",
                rung="topup-A", bullets=len(picked),
            )
            ids = add(picked, "topup-A", shrink=1)
            if ids:
                take(ids)
            goal, room = shortfall()
            if goal <= 0:
                return added, None
        last_failure: str | None = None

        # B — one bullet past the per-entry cap, from an entry already at it.
        b_draft: tuple[dict[str, str], list[str]] | None = None
        if entry_cap is not None:
            live, per_entry = rendered_ids(), counts()
            extra = sorted(
                (b for e in entries if per_entry[id(e)] >= entry_cap
                 for b in e.bullets if b.id not in live and bullet_cost(b) <= room),
                key=bullet_rank, reverse=True,
            )
            if extra:
                bullet = extra[0]
                events.emit(
                    on_event, "fit",
                    f"Page {measured_lines / capacity:.0%} full; trying bullet "
                    f"{entry_cap + 1} in {entry_label(owner[bullet.id])}",
                    rung="topup-B", bullet=bullet.id,
                )
                before = dict(rewritten)
                ids = add([bullet], "topup-B", shrink=0)
                if ids:
                    goal, room = shortfall()
                    if goal <= 0:
                        take(ids)
                        return added, None
                    # Still short: take the extra bullet back out and try a new entry
                    # instead; keep this draft in case no entry fits.
                    b_draft = (dict(rewritten), ids)
                    doc_path_b = draw(before, "revert")
                    _set_state(before, doc_path_b)
                    goal, room = shortfall()
                else:
                    last_failure = (
                        f"adding a bullet to {entry_label(owner[bullet.id])} "
                        f"overflowed the page"
                    )

        # C — the best entry not on the page yet, with as many of its top bullets
        # (up to the cap) as reach the target.
        chosen = {id(e) for e in entries}
        live = rendered_ids()
        live_sections = {
            section_of.get(id(e)) for e in candidate_entries
            if any(b.id in live for b in e.bullets)
        }
        ranked_entries = sorted(
            (e for e in candidate_entries if id(e) not in chosen and e.bullets),
            key=lambda e: score_entry(e, requirements, semantic=semantic),
            reverse=True,
        )
        for entry in ranked_entries:
            header = (2 if isinstance(entry, Experience) else 1) + (
                0 if section_of.get(id(entry)) in live_sections else 1
            )
            top = sorted(entry.bullets, key=bullet_rank, reverse=True)
            if entry_cap is not None:
                top = top[:entry_cap]
            k = 0
            estimate = header
            for bullet in top:
                if estimate + bullet_cost(bullet) > room:
                    break
                estimate += bullet_cost(bullet)
                k += 1
                if estimate >= goal:
                    break
            if k == 0:
                continue
            events.emit(
                on_event, "fit",
                f"Page {measured_lines / capacity:.0%} full; adding "
                f"{entry_label(entry)} with {k} bullet(s)",
                rung="topup-C", entry=entry_label(entry), bullets=k,
            )
            ids = add(top[:k], "topup-C", shrink=k - 1)
            if ids:
                entries.append(entry)
                by_id.update({b.id: b for b in entry.bullets})
                total_bullets += len(entry.bullets)
                take(ids)
                goal, _ = shortfall()
                if goal <= 0:
                    return added, None
                return added, f"top-up limit reached after adding {entry_label(entry)}"
            last_failure = f"adding {entry_label(entry)} overflowed the page"
            break

        if b_draft is not None:
            # No entry fit, but the extra bullet did: a fuller page beats a sparser one.
            texts_b, ids_b = b_draft
            _set_state(texts_b, draw(texts_b, "restore", added=list(ids_b)))
            take(ids_b)
        return added, last_failure or stop_text()

    def _set_state(texts: dict[str, str], drawn: tuple[Path, int, int, bool]) -> None:
        nonlocal rewritten, doc_path, pages, measured_lines, pages_are_estimated
        rewritten = outcome.texts = texts
        doc_path, pages, measured_lines, pages_are_estimated = drawn

    def top_up() -> str | None:
        """Fill the space trimming and widow repair freed, once the loop has settled on an
        underfull page it cannot grow (see `top_up_ladder`). Every round's added bullets
        get their own measured widow pass — they arrive after the main widow pass, so
        nothing else would catch one ending on a near-empty line. If that pass frees
        lines on a still-short page, one more round runs (`config.MAX_TOPUP_ROUNDS`).

        Returns why the page is still short, or None once it reaches the fill target."""
        reason: str | None = None
        for round_index in range(config.MAX_TOPUP_ROUNDS):
            if measured_lines >= math.ceil(underflow * capacity):
                return None
            added, reason = top_up_ladder()
            if not added or not repair_widows:
                break
            lines_before = measured_lines
            widow_pass(only=set(added))
            if round_index == config.MAX_TOPUP_ROUNDS - 1 or measured_lines >= lines_before:
                break
        if measured_lines >= math.ceil(underflow * capacity):
            return None
        return reason or "widow repair of the added bullets freed lines after the last round"

    while True:
        selected = select_within_entries(
            entries, requirements, limit=limit, semantic=semantic,
            max_per_entry=entry_cap, pools=section_pools, weights=section_weights,
        )
        char_budget = _TARGET_LINES_PER_BULLET * config.CHARS_PER_LINE

        # One rewrite per bullet set. Overflow is relieved on this draft by the ladder
        # below — never by re-rewriting every bullet, which only freed a line when a
        # bullet happened to cross a wrap boundary.
        outcome = rewrite_bullets(
            selected,
            requirements,
            char_budget=char_budget,
            repair_widows=repair_widows,
            repair_verbs=repair_verbs,
            on_event=on_event,
        )
        rewritten = outcome.texts
        doc_path, pages, measured_lines, pages_are_estimated = draw(
            rewritten, "draft" if grow_attempts == 0 else "grow"
        )

        members: dict[str, tuple[str, ...]] = {}
        pulled = 0
        dropped: list[str] = []
        restored = False

        if pages > target_pages:
            grow_cap = limit if grow_cap is None else min(grow_cap, limit)

            def over_by() -> int:
                return max(1, measured_lines - capacity)

            # Rung 1 — combine. One call over the current texts only, so every other
            # bullet keeps its exact wording and each merge is attributable to this
            # measured overflow.
            if merge_bullets:
                live = [b for b in selected if b.id in rewritten]
                groups = propose_merges(
                    entries, live, requirements,
                    semantic=semantic, char_budget=char_budget, attempt=1,
                )
                if groups:
                    events.emit(
                        on_event, "fit",
                        f"Over by ~{over_by()} line(s); combining bullets",
                        rung="combine", groups=len(groups),
                    )
                    merged, accepted = merge_into(
                        rewritten, by_id, groups, requirements, char_budget=char_budget
                    )
                    if accepted:
                        rewritten = outcome.texts = merged
                        outcome.merges.extend(accepted)
                        for group in accepted:
                            members[group.survivor_id] = group.member_ids
                        doc_path, pages, measured_lines, pages_are_estimated = draw(
                            rewritten, "combine"
                        )

            # Rung 2 — pull back the bullets a few words from saving a whole line: one
            # call, only as many as the overflow needs plus one spare for wrap error.
            if pages > target_pages:
                # Judge near-widows on the overflowing PDF itself (every page of it), not
                # the character estimate; unmeasured bullets fall back to the estimate.
                over_layout, over_measured = _widow_fits(
                    doc_path, rewritten, estimated=pages_are_estimated
                )
                targets = _choose_pullbacks(
                    rewritten, by_id, requirements, semantic, members, count=over_by() + 1,
                    layout=over_layout, measured_ids=over_measured, recency=recency_of,
                )
                if targets:
                    events.emit(
                        on_event, "fit",
                        f"Over by ~{over_by()} line(s); pulling back {len(targets)} bullet(s)",
                        rung="pullback", bullets=len(targets),
                    )
                    pulled_texts, n_pulled, rejected = pull_back(
                        rewritten, by_id, requirements, targets
                    )
                    outcome.widow_repairs_rejected.update(rejected)
                    if n_pulled:
                        rewritten = outcome.texts = pulled_texts
                        pulled += n_pulled
                        doc_path, pages, measured_lines, pages_are_estimated = draw(
                            rewritten, "pullback", pulled=n_pulled
                        )

            # Rung 3 — drop the weakest bullets whole. Deterministic, no model call.
            drop_rounds = 0
            while pages > target_pages and drop_rounds < config.MAX_DROP_ROUNDS:
                doomed = _choose_drops(
                    entries, rewritten, by_id, requirements, semantic, members,
                    overflow=over_by(),
                )
                if not doomed:
                    break
                drop_rounds += 1
                events.emit(
                    on_event, "fit",
                    f"Over by ~{over_by()} line(s); dropping {len(doomed)} bullet(s)",
                    rung="drop", bullets=len(doomed), dropped=list(doomed),
                )
                dropped.extend(doomed)
                rewritten = outcome.texts = {
                    bid: text for bid, text in rewritten.items() if bid not in doomed
                }
                doc_path, pages, measured_lines, pages_are_estimated = draw(
                    rewritten, "drop", dropped=list(doomed)
                )

            if pages > target_pages:
                if best is None:
                    if not pages_are_estimated:
                        render.to_pdf(doc_path, keep_active=False)  # release Word before failing
                    raise FitError(
                        f"Could not fit the resume to {target_pages} page(s) after combining, "
                        f"pulling back and dropping bullets (last measured at {pages} "
                        f"page(s)). "
                        f"{_overflow_report(resume, rewritten, target_pages, measured_lines)}"
                    )
                # A smaller draft already fit. Bring it back rather than fail: re-render
                # it (the render overwrites the same output file) and say so.
                outcome, selected = best.outcome, best.selected
                rewritten, pulled = best.texts, best.pulled
                dropped, members = best.dropped, best.members
                for edu, courses in zip(resume.education, best.coursework, strict=False):
                    edu.coursework = list(courses)
                doc_path, pages, measured_lines, pages_are_estimated = draw(rewritten, "restore")
                if pages > target_pages:
                    if not pages_are_estimated:
                        render.to_pdf(doc_path, keep_active=False)
                    raise FitError(
                        f"Could not fit the resume to {target_pages} page(s): a larger draft "
                        f"overflowed and the earlier draft that fit re-measured at {pages} "
                        f"page(s). "
                        f"{_overflow_report(resume, rewritten, target_pages, measured_lines)}"
                    )
                restored = True
                warnings.append(
                    f"A fuller draft overflowed {target_pages} page(s) and could not be "
                    f"trimmed to fit; kept the earlier {len(rewritten)}-bullet draft that fit."
                )
            else:
                events.emit(
                    on_event, "fit",
                    f"Fit after trimming: {len(outcome.merges)} merged, {pulled} pulled "
                    f"back, {len(dropped)} dropped",
                    merges=len(outcome.merges), pulled_back=pulled, dropped=len(dropped),
                )

        # One bounded layout pass on a draft that already fits.
        if pages <= target_pages:
            widow_pass()
        else:
            outcome.measured_widows_remaining = 0

        if not restored:
            best = _Draft(
                texts=rewritten, selected=selected, outcome=outcome,
                pulled=pulled, dropped=dropped, members=members,
                coursework=[list(edu.coursework) for edu in resume.education],
            )

        # Underflow is judged on the same measurement overflow is, not on the estimate:
        # the budget model over-predicted a real run into skipping a page that was only
        # 82% full. `measured_lines` is the estimate only when Word was unavailable.
        fill_ratio = measured_lines / capacity

        underfull = fill_ratio < underflow
        # `grow_cap` is the first limit that overflowed: growing back to it would only
        # re-add what the ladder just removed.
        grow_limit = growth_ceiling if grow_cap is None else min(growth_ceiling, grow_cap)
        can_grow = limit < grow_limit and grow_attempts < config.MAX_GROW_ATTEMPTS

        if not underfull or not can_grow:
            topup_reason: str | None = None
            if underfull:
                topup_reason = top_up()
                fill_ratio = measured_lines / capacity
                underfull = fill_ratio < underflow
            if underfull:
                if topup_reason:
                    reason = topup_reason
                elif limit >= growth_ceiling:
                    reason = "reached the selectable bullet cap"
                elif limit >= grow_limit:
                    reason = "a fuller draft overflowed, so the page was kept as trimmed"
                else:
                    reason = f"stopped growing after {grow_attempts} attempt(s)"
                warnings.append(
                    f"Page is only {fill_ratio:.0%} full (target {underflow:.0%}); "
                    f"{reason}."
                )
            if outcome.widow_repairs_rejected:
                detail = "; ".join(
                    f"{bid}: {', '.join(terms)}"
                    for bid, terms in outcome.widow_repairs_rejected.items()
                )
                warnings.append(
                    f"Widow repair was discarded for {len(outcome.widow_repairs_rejected)} "
                    f"bullet(s) whose repair text introduced content absent from the "
                    f"master resume ({detail}); the original wording was kept."
                )
            if outcome.widows_remaining:
                warnings.append(
                    f"{outcome.widows_remaining} bullet(s) still end on a near-empty line, "
                    f"wasting that much of the page."
                )
            if outcome.verb_collisions_remaining:
                warnings.append(
                    f"{outcome.verb_collisions_remaining} bullet(s) still open with a verb "
                    f"another bullet already used, or a near-synonym of one."
                )
            kept = len(selected) - len(dropped)
            if not pages_are_estimated:
                render.to_pdf(doc_path, keep_active=False)  # release Word on the way out
            events.emit(
                on_event,
                "fit",
                f"Done: {pages} page(s), {fill_ratio:.0%} full, {kept} bullet(s)",
                pages=pages,
                fill_ratio=round(fill_ratio, 3),
                bullets=kept,
                iterations=iterations,
            )
            return FitResult(
                out_path=doc_path,
                pages=pages,
                pages_are_estimated=pages_are_estimated,
                iterations=iterations,
                bullets_selected=kept,
                bullets_total=total_bullets,
                bullets=rewritten,
                semantic_used=bool(semantic),
                widows_repaired=outcome.widows_repaired,
                widows_remaining=outcome.widows_remaining,
                verbs_diversified=outcome.verbs_diversified,
                verb_collisions_remaining=outcome.verb_collisions_remaining,
                merges=outcome.merges,
                pulled_back=pulled,
                dropped=dropped,
                warnings=warnings,
                topped_up=topped_up,
                trace=trace,
            )

        # Convert the measured shortfall into bullets rather than adding one per round
        # trip. The divisor deliberately exceeds `_TARGET_LINES_PER_BULLET`: a restored
        # bullet may drag a whole entry's header lines back with it, so erring low costs
        # an extra cheap iteration, while erring high costs an overflow re-rewrite.
        deficit = underflow * capacity - measured_lines
        limit = min(growth_ceiling, limit + max(1, int(deficit // (_TARGET_LINES_PER_BULLET + 1))))
        grow_attempts += 1
        events.emit(
            on_event,
            "fit",
            f"Page only {fill_ratio:.0%} full; growing to {limit} bullet(s)",
            fill_ratio=round(fill_ratio, 3),
            limit=limit,
            grow_attempt=grow_attempts,
        )
