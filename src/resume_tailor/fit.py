"""The fit loop: select, rewrite, render, and measure until a resume fits its page target.

Page fitting is budget-first (see CLAUDE.md): a cheap character/line estimate sizes the
initial selection, while a real Word render is what decides both overflow and underflow
and produces the file the user actually gets. `estimate_lines` is also the fallback used
when Word/COM is unavailable, so a run can still finish (with a warning) without ever
generating XML or layout logic outside `render.py`.

Never silently truncates: after `config.MAX_FIT_ATTEMPTS` overflowing rewrites, `fit()`
raises `FitError` naming which sections are still over budget instead of cutting content
on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from . import config, events, render
from .data import Experience, MasterResume, Project
from .jd import JobRequirements
from .merge import MergeGroup, propose as propose_merges
from .rewrite import rewrite_bullets, select_entries, select_within_entries

#: How many physical lines a bullet's rewritten text is targeted at, on average. Passed
#: to `rewrite_bullets` as its starting character budget before any shortening.
_TARGET_LINES_PER_BULLET = 2


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

    #: Bullets the widow pass successfully tightened, and bullets still ending on a
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

    warnings: list[str] = field(default_factory=list)


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


def _fixed_overhead_lines(resume: MasterResume) -> int:
    """Lines that render regardless of selection: header, contact, education, skills.

    Education and skills never vary by posting, but their line *count* still depends on
    the master resume's own content (coursework wrap, GPA suffix, skill group length),
    so it is measured from `resume` rather than hard-coded.
    """
    lines = 2  # name line + contact line
    lines += 1  # "EDUCATION" header
    for edu in resume.education:
        lines += 1  # school | location ... dates
        lines += _bullet_lines(render._degree_line(edu))
        for detail in render._education_details(edu):
            lines += _bullet_lines(detail)

    if resume.skills:
        lines += 1  # "SKILLS" header
        for group in resume.skills:
            lines += _bullet_lines(f"{group.label}: {', '.join(group.items)}")
    return lines


def _entry_lines(entry: Experience | Project, bullets: dict[str, str]) -> int:
    kept = [bullets[b.id] for b in entry.bullets if b.id in bullets]
    if not kept:
        return 0
    return 2 + sum(_bullet_lines(text) for text in kept)  # header/title line + tab line


def _section_lines(entries: list[Experience] | list[Project], bullets: dict[str, str]) -> int:
    """Lines for one experience/project section, honoring the bullets filter.

    An entry whose bullets were all dropped contributes nothing at all — not even its
    header — mirroring `render.build_context`'s own filtering.
    """
    per_entry = [_entry_lines(entry, bullets) for entry in entries]
    total = sum(per_entry)
    return total + (1 if total else 0)  # section header, once, if anything survived


def estimate_lines(resume: MasterResume, bullets: dict[str, str]) -> int:
    """Cheap character-budget estimate of total rendered lines for this bullet set."""
    return (
        _fixed_overhead_lines(resume)
        + _section_lines(resume.experience, bullets)
        + _section_lines(resume.projects, bullets)
    )


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
) -> list:
    """Pick which jobs and projects appear, ranking the two sections independently.

    Done once per run, before any rewriting: which entries appear is a decision about the
    resume's shape, and the fit loop is only allowed to trim bullets inside them.
    """
    experience = select_entries(
        resume.experience,
        requirements,
        limit=config.MAX_EXPERIENCE_ENTRIES if max_experience is None else max_experience,
        semantic=semantic,
    )
    projects = select_entries(
        resume.projects,
        requirements,
        limit=config.MAX_PROJECT_ENTRIES if max_projects is None else max_projects,
        semantic=semantic,
    )
    return [*experience, *projects]


def _select_at_rewrite_budget(
    entries: list,
    requirements: JobRequirements,
    limit: int,
    semantic: dict[str, float] | None = None,
) -> dict[str, str]:
    """Map a selection to rewrite-budget placeholders for cheap line estimates.

    Initial sizing assumes each bullet lands near `_TARGET_LINES_PER_BULLET` after the
    first rewrite, not at the (usually longer) master wording — estimating on originals
    under-selected and left the page sparse until grow rounds caught up.
    """
    selected = select_within_entries(entries, requirements, limit=limit, semantic=semantic)
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
) -> int:
    """Binary search the largest bullet count whose *post-rewrite* size should fit.

    Only used to size the first selection cheaply. Each candidate is estimated at the
    rewrite line budget, not master length; the real render/measure still confirms fit.
    `config.INITIAL_SELECTION_OVERSHOOT` lets the search claim a few lines past capacity
    so the first call packs denser (overflow/shorten still corrects if needed).

    The search floor is one bullet per chosen entry, never zero: dropping below that would
    delete an entry the ranking already decided to keep.
    """
    floor = len(entries)
    total = sum(len(e.bullets) for e in entries)
    capacity = target_pages * config.LINES_PER_PAGE + config.INITIAL_SELECTION_OVERSHOOT

    low, high = floor, total
    while low < high:
        mid = (low + high + 1) // 2
        bullets = _select_at_rewrite_budget(entries, requirements, mid, semantic)
        if estimate_lines(resume, bullets) <= capacity:
            low = mid
        else:
            high = mid - 1
    return low


def _overflow_report(resume: MasterResume, bullets: dict[str, str], target_pages: int) -> str:
    capacity = target_pages * config.LINES_PER_PAGE
    total = estimate_lines(resume, bullets)

    contributions: list[tuple[int, str]] = []
    for label, entries in (("experience", resume.experience), ("projects", resume.projects)):
        for entry in entries:
            lines = _entry_lines(entry, bullets)
            if lines:
                name = entry.company if isinstance(entry, Experience) else entry.name
                contributions.append((lines, f"{label}: {name} (~{lines} lines)"))
    contributions.sort(reverse=True)
    top = "\n".join(f"  - {desc}" for _, desc in contributions[:5]) or "  (none)"

    return (
        f"~{total} estimated lines vs a {capacity}-line budget for {target_pages} page(s), "
        f"over by ~{total - capacity}. Largest contributors:\n{top}"
    )


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
    merge_bullets: bool = False,
    include_project_links: bool = True,
    fill_target: float | None = None,
    on_event: events.ProgressCallback | None = None,
) -> FitResult:
    """Select, rewrite, render, and measure until the resume fits `target_pages`.

    Which entries appear is decided once up front by `choose_entries` (experience and
    projects ranked separately, capped by `config.MAX_EXPERIENCE_ENTRIES` /
    `MAX_PROJECT_ENTRIES`). The loop then only varies how many *bullets* those entries get,
    and never drops one entirely.

    `semantic` is an optional {bullet_id: 0-10} relevance table from `rewrite.score_table`,
    computed once by the caller and held fixed for the whole run. It must not be recomputed
    per iteration: a table that shifted between grow steps could swap bullets rather than
    add them, which is the one thing the estimate/measure relationship depends on.

    Overflow (measured page count above target) escalates through
    `config.SHORTEN_SCHEDULE`, re-rewriting the same bullet set at most
    `config.MAX_FIT_ATTEMPTS` times before raising `FitError`.

    `repair_widows` is passed through to `rewrite_bullets`; see there. It matters to the
    loop because a widowed bullet inflates the measured line count with space that holds
    one word, which both hides real capacity and can push a fitting resume onto two pages.

    `repair_verbs` is passed through the same way and shares that call. It does not affect
    fitting at all — a repeated opening verb costs no space — so it is purely a readability
    pass the loop carries rather than owns.

    `merge_bullets` enables the merge proposal step, which fires only after a measured
    overflow: merging is a space lever, and one applied to a page that already fit combined
    bullets for no reason.

    `include_project_links` is passed straight to `render.render`. It is not a fit lever:
    the link sits inline in a project's header line, so hiding it frees no lines.

    `fill_target` overrides `config.UNDERFLOW_THRESHOLD` for this run (fraction of page
    capacity). Lower means the loop accepts a sparser page; higher packs tighter at the
    cost of extra grow/rewrite rounds.

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
    warnings: list[str] = []
    iterations = 0
    grow_attempts = 0

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
    # resume — a bullet in a dropped entry can never come back.
    total_bullets = sum(len(e.bullets) for e in entries)
    limit = _initial_selection_size(resume, entries, requirements, target_pages, semantic)
    events.emit(
        on_event,
        "fit",
        f"Selected {len(entries)} entries; starting at {limit} of {total_bullets} bullets",
        entries=len(entries),
        limit=limit,
        total_bullets=total_bullets,
    )

    while True:
        selected = select_within_entries(entries, requirements, limit=limit, semantic=semantic)
        char_budget = _TARGET_LINES_PER_BULLET * config.CHARS_PER_LINE

        shorten_pct = 0
        attempt = 0
        while True:
            iterations += 1
            # Merging is a space lever, so it fires only once the page has actually
            # measured over — never on the first draft. Proposing at `attempt == 0` merged
            # bullets the page had room for, and because affinity ranks the *most similar*
            # adjacent pair first, those gratuitous merges were exactly the ones that read
            # repetitively. Waiting for overflow makes every merge attributable to a
            # measured shortfall.
            merge_groups = (
                propose_merges(
                    entries,
                    selected,
                    requirements,
                    semantic=semantic,
                    char_budget=char_budget,
                    shorten_pct=shorten_pct,
                    attempt=attempt,
                )
                if merge_bullets and attempt >= 1
                else []
            )
            outcome = rewrite_bullets(
                selected,
                requirements,
                char_budget=char_budget,
                shorten_pct=shorten_pct,
                repair_widows=repair_widows,
                repair_verbs=repair_verbs,
                merge_groups=merge_groups,
                on_event=on_event,
            )
            rewritten = outcome.texts
            events.emit(
                on_event, "render", f"Rendering draft {iterations}", iteration=iterations
            )
            doc_path = render.render(
                resume,
                bullets=rewritten,
                template=template,
                out=out,
                include_project_links=include_project_links,
            )

            try:
                # Keep Word alive across retries within this run; the caller gets the
                # final measurement (and Word is released) once the loop concludes.
                pages, measured_lines = render.measure_detail(doc_path, keep_active=True)
                pages_are_estimated = False
            except RuntimeError as exc:
                warnings.append(f"PDF measurement unavailable, using budget estimate: {exc}")
                measured_lines = estimate_lines(resume, rewritten)
                pages = math.ceil(measured_lines / config.LINES_PER_PAGE)
                pages_are_estimated = True

            events.emit(
                on_event,
                "measure",
                f"Draft {iterations}: {pages} page(s), {measured_lines} line(s)",
                iteration=iterations,
                pages=pages,
                lines=measured_lines,
                estimated=pages_are_estimated,
            )

            if pages <= target_pages:
                break

            attempt += 1
            if attempt >= config.MAX_FIT_ATTEMPTS:
                if not pages_are_estimated:
                    render.to_pdf(doc_path, keep_active=False)  # release Word before failing
                raise FitError(
                    f"Could not fit the resume to {target_pages} page(s) after {attempt} "
                    f"rewrite attempt(s) (last measured at {pages} page(s)). "
                    f"{_overflow_report(resume, rewritten, target_pages)}"
                )
            shorten_pct = config.SHORTEN_SCHEDULE[min(attempt - 1, len(config.SHORTEN_SCHEDULE) - 1)]
            events.emit(
                on_event,
                "fit",
                f"Over by {pages - target_pages} page(s); retrying {shorten_pct}% shorter",
                attempt=attempt,
                shorten_pct=shorten_pct,
            )

        # Underflow is judged on the same measurement overflow is, not on the estimate:
        # the budget model over-predicted a real run into skipping a page that was only
        # 82% full. `measured_lines` is the estimate only when Word was unavailable.
        capacity = target_pages * config.LINES_PER_PAGE
        fill_ratio = measured_lines / capacity

        underfull = fill_ratio < underflow
        can_grow = limit < total_bullets and grow_attempts < config.MAX_GROW_ATTEMPTS

        if not underfull or not can_grow:
            if underfull:
                warnings.append(
                    f"Page is only {fill_ratio:.0%} full (target {underflow:.0%}); "
                    f"{'ran out of bullets' if limit >= total_bullets else 'stopped growing after '
                       f'{grow_attempts} attempt(s)'}."
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
            if not pages_are_estimated:
                render.to_pdf(doc_path, keep_active=False)  # release Word on the way out
            events.emit(
                on_event,
                "fit",
                f"Done: {pages} page(s), {fill_ratio:.0%} full, {len(selected)} bullet(s)",
                pages=pages,
                fill_ratio=round(fill_ratio, 3),
                bullets=len(selected),
                iterations=iterations,
            )
            return FitResult(
                out_path=doc_path,
                pages=pages,
                pages_are_estimated=pages_are_estimated,
                iterations=iterations,
                bullets_selected=len(selected),
                bullets_total=total_bullets,
                bullets=rewritten,
                semantic_used=bool(semantic),
                widows_repaired=outcome.widows_repaired,
                widows_remaining=outcome.widows_remaining,
                verbs_diversified=outcome.verbs_diversified,
                verb_collisions_remaining=outcome.verb_collisions_remaining,
                merges=outcome.merges,
                warnings=warnings,
            )

        # Convert the measured shortfall into bullets rather than adding one per round
        # trip. The divisor deliberately exceeds `_TARGET_LINES_PER_BULLET`: a restored
        # bullet may drag a whole entry's header lines back with it, so erring low costs
        # an extra cheap iteration, while erring high costs an overflow re-rewrite.
        deficit = underflow * capacity - measured_lines
        limit = min(total_bullets, limit + max(1, int(deficit // (_TARGET_LINES_PER_BULLET + 1))))
        grow_attempts += 1
        events.emit(
            on_event,
            "fit",
            f"Page only {fill_ratio:.0%} full; growing to {limit} bullet(s)",
            fill_ratio=round(fill_ratio, 3),
            limit=limit,
            grow_attempt=grow_attempts,
        )
