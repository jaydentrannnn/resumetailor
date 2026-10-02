"""The state one fit run carries: initial selection, drafting and measuring a draft."""

from __future__ import annotations

import math
from pathlib import Path

from .. import config
from ..content.data import Bullet, MasterResume
from ..document import render
from ..document.template_profile import ContactField, active_layout
from . import events, fit_lines, fit_selection, fit_types
from .jd import JobRequirements
from .rewrite import rewrite_bullets
from .selection import (
    entry_recency,
    select_within_entries,
    selectable_total,
)


class _FitState:
    """What `_FitRun` sets up before its loop, and the draft/measure steps every layer uses."""

    def __init__(
        self,
        resume: MasterResume,
        requirements: JobRequirements,
        *,
        target_pages: int | None,
        template: Path | None,
        out: Path | None,
        max_experience: int | None,
        max_projects: int | None,
        semantic: dict[str, float] | None,
        repair_widows: bool,
        repair_verbs: bool,
        merge_bullets: bool,
        include_project_links: bool,
        contact_fields: list[ContactField] | None,
        fill_target: float | None,
        initial_bullet_share: float | None,
        experience_bullet_share: float | None,
        max_bullets_per_entry: int | None,
        coursework_pool: list[str] | None,
        on_event: events.ProgressCallback | None,
    ) -> None:
        self.resume = resume
        self.requirements = requirements
        self.target_pages = target_pages or config.DEFAULT_PAGE_TARGET
        self.template = template
        self.out = out
        self.semantic = semantic
        self.repair_widows = repair_widows
        self.repair_verbs = repair_verbs
        self.merge_bullets = merge_bullets
        self.include_project_links = include_project_links
        self.contact_fields = contact_fields
        self.coursework_pool = coursework_pool
        self.on_event = on_event
        # Local so a per-run override does not mutate the process-wide constant.
        self.underflow = fill_target if fill_target is not None else config.UNDERFLOW_THRESHOLD
        self.initial_share = (
            initial_bullet_share
            if initial_bullet_share is not None
            else config.INITIAL_BULLET_SHARE
        )
        self.section_share = (
            experience_bullet_share
            if experience_bullet_share is not None
            else config.EXPERIENCE_BULLET_SHARE
        )
        self.entry_cap = (
            max_bullets_per_entry
            if max_bullets_per_entry is not None
            else config.MAX_BULLETS_PER_ENTRY
        )
        self.warnings: list[str] = []
        self.iterations = 0
        self.grow_attempts = 0
        # Set the first time a bullet set overflows; growing back to (or past) it would only
        # re-add what the ladder just removed and overflow again.
        self.grow_cap: int | None = None
        self.best: fit_types._Draft | None = None

        self._warn_unbuildable_sections()
        self.entries = fit_selection.choose_entries(
            resume,
            requirements,
            max_experience=max_experience,
            max_projects=max_projects,
            semantic=semantic,
        )
        if not self.entries:
            raise fit_types.FitError(
                "No experience or project entries were selected; nothing to render."
            )
        self._start_selection()

        self.capacity = self.target_pages * config.LINES_PER_PAGE
        self.trace: list[dict] = []
        self.topped_up: list[str] = []
        self._collect_candidates()

    def _warn_unbuildable_sections(self) -> None:
        # A resume section whose kind the active template has no prototype for is skipped
        # by `render.build_context` silently (it has no result channel of its own to carry
        # a warning) — this is where that becomes visible, per the "skip it and warn
        # loudly" policy for a declared-but-unbuildable section kind.
        enabled_check = active_layout().get("enabled") or {}
        for section in self.resume.sections:
            if not section.entries:
                continue
            key = config.SECTION_KIND_ENABLED_KEY[section.kind]
            if not enabled_check.get(key, config.SECTION_KIND_ENABLED_DEFAULT[section.kind]):
                self.warnings.append(
                    f"Section {section.title!r} has no matching layout in the active "
                    f"template and will not appear in the rendered resume."
                )

    def _start_selection(self) -> None:
        # The pool the loop draws from is the chosen entries' bullets, not the whole master
        # resume — a bullet in a dropped entry can never come back. `total_bullets` is the
        # raw pool size (reported in `FitResult.bullets_total`); `growth_ceiling` is what the
        # caps actually let the loop reach, which is what the grow condition must compare
        # against.
        entries = self.entries
        self.total_bullets = sum(len(e.bullets) for e in entries)
        self.growth_ceiling = selectable_total(entries, max_per_entry=self.entry_cap)
        self.section_pools, self.section_weights = fit_selection._section_pools(
            self.resume, entries, self.section_share
        )
        self.limit = fit_selection._initial_selection_size(
            self.resume, entries, self.requirements, self.target_pages, self.semantic,
            share=self.initial_share, max_per_entry=self.entry_cap,
            pools=self.section_pools, weights=self.section_weights,
        )
        share_note = (
            f" (capped at {self.initial_share:.0%} of {self.total_bullets})"
            if self.initial_share < 1.0 else ""
        )
        events.emit(
            self.on_event,
            "fit",
            f"Selected {len(entries)} entries; starting at {self.limit} of "
            f"{self.total_bullets} bullets{share_note}",
            entries=len(entries),
            limit=self.limit,
            total_bullets=self.total_bullets,
            initial_bullet_share=self.initial_share,
            experience_bullet_share=self.section_share,
            max_bullets_per_entry=self.entry_cap,
        )
        self.by_id: dict[str, Bullet] = {b.id: b for e in entries for b in e.bullets}

    def _collect_candidates(self) -> None:
        # Every entry the template can render, for the top-up's new-entry step (the same
        # section gating `choose_entries` applies), with each bullet's recency multiplier.
        enabled_kinds = active_layout().get("enabled") or {}
        self.section_of: dict[int, str] = {}
        self.candidate_entries: list = []
        for section in self.resume.entry_sections:
            key = "projects" if section.kind == "project" else "experience"
            if not enabled_kinds.get(key, True):
                continue
            for entry in section.entries:
                self.section_of[id(entry)] = section.id
                self.candidate_entries.append(entry)
        self.recency_of: dict[str, float] = {
            b.id: entry_recency(e) for e in self.candidate_entries for b in e.bullets
        }
        self.all_sources: dict[str, Bullet] = {
            b.id: b for e in self.candidate_entries for b in e.bullets
        }
        self.all_sources.update(self.by_id)

    def _draft_round(self) -> None:
        """Select `limit` bullets, rewrite them once, and render the first draft."""
        self.selected = select_within_entries(
            self.entries, self.requirements, limit=self.limit, semantic=self.semantic,
            max_per_entry=self.entry_cap, pools=self.section_pools,
            weights=self.section_weights,
        )
        self.char_budget = fit_types._TARGET_LINES_PER_BULLET * config.CHARS_PER_LINE

        # One rewrite per bullet set. Overflow is relieved on this draft by the ladder
        # below — never by re-rewriting every bullet, which only freed a line when a
        # bullet happened to cross a wrap boundary.
        self.outcome = rewrite_bullets(
            self.selected,
            self.requirements,
            char_budget=self.char_budget,
            repair_widows=self.repair_widows,
            repair_verbs=self.repair_verbs,
            on_event=self.on_event,
        )
        self.rewritten = self.outcome.texts
        self._set_draft(
            self.draw(self.rewritten, "draft" if self.grow_attempts == 0 else "grow")
        )

        self.members: dict[str, tuple[str, ...]] = {}
        self.pulled = 0
        self.dropped: list[str] = []
        self.restored = False

    def draw(
        self, texts: dict[str, str], step: str = "draft", **note
    ) -> tuple[Path, int, int, bool]:
        """Render `texts`, then measure: `(doc path, pages, lines, measurement estimated)`.

        `step` and `note` label the draw in `trace` (`FitResult.trace`)."""
        self.iterations += 1
        iterations = self.iterations
        events.emit(self.on_event, "render", f"Rendering draft {iterations}", iteration=iterations)
        path = render.render(
            self.resume,
            bullets=texts,
            template=self.template,
            out=self.out,
            include_project_links=self.include_project_links,
            contact_fields=self.contact_fields,
        )
        try:
            # Keep Word alive across retries within this run; the caller gets the
            # final measurement (and Word is released) once the loop concludes.
            pages_, lines_ = render.measure_detail(path, keep_active=True)
            estimated = False
        except RuntimeError as exc:
            self.warnings.append(f"PDF measurement unavailable, using budget estimate: {exc}")
            lines_ = fit_lines.estimate_lines(self.resume, texts)
            pages_ = math.ceil(lines_ / config.LINES_PER_PAGE)
            estimated = True
        events.emit(
            self.on_event,
            "measure",
            f"Draft {iterations}: {pages_} page(s), {lines_} line(s)",
            iteration=iterations,
            pages=pages_,
            lines=lines_,
            estimated=estimated,
        )
        self.trace.append({
            "step": step,
            "bullets": len(texts),
            "lines": lines_,
            "pages": pages_,
            "fill": round(lines_ / self.capacity, 3),
            "estimated": estimated,
            **note,
        })
        return path, pages_, lines_, estimated

    def _set_draft(self, drawn: tuple[Path, int, int, bool]) -> None:
        self.doc_path, self.pages, self.measured_lines, self.pages_are_estimated = drawn

    def _set_state(self, texts: dict[str, str], drawn: tuple[Path, int, int, bool]) -> None:
        self.rewritten = self.outcome.texts = texts
        self._set_draft(drawn)

    def _overflow_report(self) -> str:
        return fit_selection._overflow_report(
            self.resume, self.rewritten, self.target_pages, self.measured_lines
        )

    def _over_by(self) -> int:
        return max(1, self.measured_lines - self.capacity)

    def rewrite_new(self, new: list[Bullet]) -> dict[str, str]:
        """Rewrite only `new`, then re-voice any of them whose opening verb the page
        already uses. Existing bullets are never re-requested: their text and wrap are
        already measured."""
        fresh = rewrite_bullets(
            new, self.requirements, char_budget=self.char_budget,
            repair_widows=False, repair_verbs=self.repair_verbs, on_event=self.on_event,
            verb_context=dict(self.rewritten),
        )
        self.outcome.fabrications_rejected.update(fresh.fabrications_rejected)
        self.outcome.verbs_diversified += fresh.verbs_diversified
        return {b.id: fresh.texts.get(b.id, b.text) for b in new}
