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

from pathlib import Path

from .. import config
from ..content.data import MasterResume
from ..document import render
from ..document.template_profile import ContactField
from . import events, fit_topup, fit_types
from .jd import JobRequirements

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
) -> fit_types.FitResult:
    """Select, rewrite, render, and measure until the resume fits `target_pages`.

    Which entries appear is decided once up front by `choose_entries` (experience and
    projects ranked separately, capped by `config.MAX_EXPERIENCE_ENTRIES` /
    `MAX_PROJECT_ENTRIES`). The loop then varies how many *bullets* those entries get —
    overall via `limit`, and now optionally by section (`experience_bullet_share`) and
    per-entry (`max_bullets_per_entry`) — but never drops an entry entirely.

    `semantic` is an optional {bullet_id: 0-10} relevance table from `relevance.score_table`,
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
    `selection.selectable_total(entries, max_per_entry=...)`, not the raw count — comparing
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
    return _FitRun(
        resume,
        requirements,
        target_pages=target_pages,
        template=template,
        out=out,
        max_experience=max_experience,
        max_projects=max_projects,
        semantic=semantic,
        repair_widows=repair_widows,
        repair_verbs=repair_verbs,
        merge_bullets=merge_bullets,
        include_project_links=include_project_links,
        contact_fields=contact_fields,
        fill_target=fill_target,
        initial_bullet_share=initial_bullet_share,
        experience_bullet_share=experience_bullet_share,
        max_bullets_per_entry=max_bullets_per_entry,
        coursework_pool=coursework_pool,
        on_event=on_event,
    ).run()


class _FitRun(fit_topup._FitTopUp):
    """The state and steps of one `fit` call (see its docstring for the policy).

    The working draft is `rewritten` (the texts on the page, always the same object as
    `outcome.texts`) plus its last measurement: `doc_path`, `pages`, `measured_lines`,
    `pages_are_estimated`. Every render replaces the measurement via `_set_draft`.
    """

    # -- the loop ----------------------------------------------------------------------

    def run(self) -> fit_types.FitResult:
        while True:
            self._draft_round()
            if self.pages > self.target_pages:
                self._relieve_overflow()

            # One bounded layout pass on a draft that already fits.
            if self.pages <= self.target_pages:
                self.widow_pass()
            else:
                self.outcome.measured_widows_remaining = 0

            if not self.restored:
                self.best = fit_types._Draft(
                    texts=self.rewritten, selected=self.selected, outcome=self.outcome,
                    pulled=self.pulled, dropped=self.dropped, members=self.members,
                    coursework=[list(edu.coursework) for edu in self.resume.education],
                )

            # Underflow is judged on the same measurement overflow is, not on the estimate:
            # the budget model over-predicted a real run into skipping a page that was only
            # 82% full. `measured_lines` is the estimate only when Word was unavailable.
            fill_ratio = self.measured_lines / self.capacity

            underfull = fill_ratio < self.underflow
            # `grow_cap` is the first limit that overflowed: growing back to it would only
            # re-add what the ladder just removed.
            grow_limit = (
                self.growth_ceiling if self.grow_cap is None
                else min(self.growth_ceiling, self.grow_cap)
            )
            can_grow = self.limit < grow_limit and self.grow_attempts < config.MAX_GROW_ATTEMPTS

            if not underfull or not can_grow:
                return self._finish(fill_ratio, underfull, grow_limit)
            self._grow(fill_ratio)

    def _grow(self, fill_ratio: float) -> None:
        # Convert the measured shortfall into bullets rather than adding one per round
        # trip. The divisor deliberately exceeds `_TARGET_LINES_PER_BULLET`: a restored
        # bullet may drag a whole entry's header lines back with it, so erring low costs
        # an extra cheap iteration, while erring high costs an overflow re-rewrite.
        deficit = self.underflow * self.capacity - self.measured_lines
        self.limit = min(
            self.growth_ceiling,
            self.limit + max(1, int(deficit // (fit_types._TARGET_LINES_PER_BULLET + 1))),
        )
        self.grow_attempts += 1
        events.emit(
            self.on_event,
            "fit",
            f"Page only {fill_ratio:.0%} full; growing to {self.limit} bullet(s)",
            fill_ratio=round(fill_ratio, 3),
            limit=self.limit,
            grow_attempt=self.grow_attempts,
        )

    def _finish(self, fill_ratio: float, underfull: bool, grow_limit: int) -> fit_types.FitResult:
        from resume_tailor.document.template_profile import active_layout
        from resume_tailor.pipeline import resume_quality
        topup_reason: str | None = None
        if underfull:
            topup_reason = self.top_up()
            fill_ratio = self.measured_lines / self.capacity
            underfull = fill_ratio < self.underflow
        if underfull:
            self.warnings.append(
                f"Page is only {fill_ratio:.0%} full (target {self.underflow:.0%}); "
                f"{self._underfull_reason(topup_reason, grow_limit)}."
            )
        self._quality_warnings()
        kept = len(self.selected) - len(self.dropped)
        if not self.pages_are_estimated:
            render.to_pdf(self.doc_path, keep_active=False)  # release Word on the way out
        events.emit(
            self.on_event,
            "fit",
            f"Done: {self.pages} page(s), {fill_ratio:.0%} full, {kept} bullet(s)",
            pages=self.pages,
            fill_ratio=round(fill_ratio, 3),
            bullets=kept,
            iterations=self.iterations,
        )
        outcome = self.outcome
        return fit_types.FitResult(
            out_path=self.doc_path,
            pages=self.pages,
            pages_are_estimated=self.pages_are_estimated,
            iterations=self.iterations,
            bullets_selected=kept,
            bullets_total=self.total_bullets,
            bullets=self.rewritten,
            semantic_used=bool(self.semantic),
            widows_repaired=outcome.widows_repaired,
            widows_remaining=outcome.widows_remaining,
            verbs_diversified=outcome.verbs_diversified,
            verb_collisions_remaining=outcome.verb_collisions_remaining,
            merges=outcome.merges,
            pulled_back=self.pulled,
            dropped=self.dropped,
            warnings=self.warnings,
            topped_up=self.topped_up,
            trace=self.trace,
            fill_ratio=fill_ratio,
            fill_target=self.underflow,
            quality=resume_quality.assess(
                self.resume, self.rewritten, active_layout(), fill_ratio=fill_ratio,
                fill_target=self.underflow, estimated=self.pages_are_estimated,
            ).model_dump(),
        )

    def _underfull_reason(self, topup_reason: str | None, grow_limit: int) -> str:
        if topup_reason:
            return topup_reason
        if self.limit >= self.growth_ceiling:
            return "reached the selectable bullet cap"
        if self.limit >= grow_limit:
            return "a fuller draft overflowed, so the page was kept as trimmed"
        return f"stopped growing after {self.grow_attempts} attempt(s)"

    def _quality_warnings(self) -> None:
        outcome = self.outcome
        if outcome.widow_repairs_rejected:
            detail = "; ".join(
                f"{bid}: {', '.join(terms)}"
                for bid, terms in outcome.widow_repairs_rejected.items()
            )
            self.warnings.append(
                f"Widow repair was discarded for {len(outcome.widow_repairs_rejected)} "
                f"bullet(s) whose repair text introduced content absent from the "
                f"master resume ({detail}); the original wording was kept."
            )
        if outcome.widows_remaining:
            self.warnings.append(
                f"{outcome.widows_remaining} bullet(s) still end on a near-empty line, "
                f"wasting that much of the page."
            )
        if outcome.verb_collisions_remaining:
            self.warnings.append(
                f"{outcome.verb_collisions_remaining} bullet(s) still open with a verb "
                f"another bullet already used, or a near-synonym of one."
            )
