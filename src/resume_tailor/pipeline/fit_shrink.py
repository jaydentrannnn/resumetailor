"""Shrinking an over-long draft: combine, pull back near-widows, drop the weakest; widow repair."""

from __future__ import annotations

from .. import config
from ..content.data import Bullet
from ..document import render
from . import events, facets, fit_lines, fit_selection, fit_state, fit_types
from .bullet_merge import merge_into, pull_back
from .followups import _polish
from .merge import propose as propose_merges


class _FitShrink(fit_state._FitState):
    """`_FitRun` steps that relieve an overflow and repair widowed bullets."""

    def _relieve_overflow(self) -> None:
        """Climb the combine → pull back → drop ladder on this draft until it fits, else
        fall back to the last draft that fit (or raise `FitError`)."""
        self.grow_cap = self.limit if self.grow_cap is None else min(self.grow_cap, self.limit)
        if self.merge_bullets:
            self._combine()
        if self.pages > self.target_pages:
            self._pull_back_near_widows()
        self._drop_weakest()

        if self.pages > self.target_pages:
            self._restore_best()
        else:
            events.emit(
                self.on_event, "fit",
                f"Fit after trimming: {len(self.outcome.merges)} merged, {self.pulled} pulled "
                f"back, {len(self.dropped)} dropped",
                merges=len(self.outcome.merges), pulled_back=self.pulled,
                dropped=len(self.dropped),
            )

    def _combine(self) -> None:
        # Rung 1 — combine. One call over the current texts only, so every other bullet
        # keeps its exact wording and each merge is attributable to this measured overflow.
        live = [b for b in self.selected if b.id in self.rewritten]
        groups = propose_merges(
            self.entries, live, self.requirements,
            semantic=self.semantic, char_budget=self.char_budget, attempt=1,
        )
        if not groups:
            return
        events.emit(
            self.on_event, "fit",
            f"Over by ~{self._over_by()} line(s); combining bullets",
            rung="combine", groups=len(groups),
        )
        merged, accepted = merge_into(
            self.rewritten, self.by_id, groups, self.requirements, char_budget=self.char_budget
        )
        if accepted:
            self.rewritten = self.outcome.texts = merged
            self.outcome.merges.extend(accepted)
            for group in accepted:
                self.members[group.survivor_id] = group.member_ids
            self._set_draft(self.draw(self.rewritten, "combine"))

    def _pull_back_near_widows(self) -> None:
        # Rung 2 — pull back the bullets a few words from saving a whole line: one call,
        # only as many as the overflow needs plus one spare for wrap error.
        # Judge near-widows on the overflowing PDF itself (every page of it), not the
        # character estimate; unmeasured bullets fall back to the estimate.
        over_layout, over_measured = fit_lines._widow_fits(
            self.doc_path, self.rewritten, estimated=self.pages_are_estimated
        )
        targets = fit_selection._choose_pullbacks(
            self.rewritten, self.by_id, self.requirements, self.semantic, self.members,
            count=self._over_by() + 1, layout=over_layout, measured_ids=over_measured,
            recency=self.recency_of,
        )
        if not targets:
            return
        events.emit(
            self.on_event, "fit",
            f"Over by ~{self._over_by()} line(s); pulling back {len(targets)} bullet(s)",
            rung="pullback", bullets=len(targets),
        )
        pulled_texts, n_pulled, rejected = pull_back(
            self.rewritten, self.by_id, self.requirements, targets
        )
        self.outcome.widow_repairs_rejected.update(rejected)
        if n_pulled:
            self.rewritten = self.outcome.texts = pulled_texts
            self.pulled += n_pulled
            self._set_draft(self.draw(self.rewritten, "pullback", pulled=n_pulled))

    def _drop_weakest(self) -> None:
        # Rung 3 — drop the weakest bullets whole. Deterministic, no model call.
        drop_rounds = 0
        while self.pages > self.target_pages and drop_rounds < config.MAX_DROP_ROUNDS:
            doomed = fit_selection._choose_drops(
                self.entries, self.rewritten, self.by_id, self.requirements, self.semantic,
                self.members, overflow=self._over_by(),
            )
            if not doomed:
                break
            drop_rounds += 1
            events.emit(
                self.on_event, "fit",
                f"Over by ~{self._over_by()} line(s); dropping {len(doomed)} bullet(s)",
                rung="drop", bullets=len(doomed), dropped=list(doomed),
            )
            self.dropped.extend(doomed)
            self.rewritten = self.outcome.texts = {
                bid: text for bid, text in self.rewritten.items() if bid not in doomed
            }
            self._set_draft(self.draw(self.rewritten, "drop", dropped=list(doomed)))

    def _restore_best(self) -> None:
        target_pages = self.target_pages
        if self.best is None:
            if not self.pages_are_estimated:
                render.to_pdf(self.doc_path, keep_active=False)  # release Word before failing
            raise fit_types.FitError(
                f"Could not fit the resume to {target_pages} page(s) after combining, "
                f"pulling back and dropping bullets (last measured at {self.pages} "
                f"page(s)). "
                f"{self._overflow_report()}"
            )
        # A smaller draft already fit. Bring it back rather than fail: re-render it (the
        # render overwrites the same output file) and say so.
        best = self.best
        self.outcome, self.selected = best.outcome, best.selected
        self.rewritten, self.pulled = best.texts, best.pulled
        self.dropped, self.members = best.dropped, best.members
        for edu, courses in zip(self.resume.education, best.coursework, strict=False):
            edu.coursework = list(courses)
        self._set_draft(self.draw(self.rewritten, "restore"))
        if self.pages > target_pages:
            if not self.pages_are_estimated:
                render.to_pdf(self.doc_path, keep_active=False)
            raise fit_types.FitError(
                f"Could not fit the resume to {target_pages} page(s): a larger draft "
                f"overflowed and the earlier draft that fit re-measured at {self.pages} "
                f"page(s). "
                f"{self._overflow_report()}"
            )
        self.restored = True
        self.warnings.append(
            f"A fuller draft overflowed {target_pages} page(s) and could not be "
            f"trimmed to fit; kept the earlier {len(self.rewritten)}-bullet draft that fit."
        )

    def widow_pass(self, only: set[str] | None = None) -> None:
        """One bounded measured layout pass on a draft that already fits.

        Shortens or extends bullets whose measured last line is under
        `config.WIDOW_MIN_FILL` (`_widow_targets`), and tops up or trims the coursework
        line. Keeps the pre-pass document so any unexpected page growth is reverted
        exactly. `only` restricts the pass to those bullet ids and skips coursework — the
        top-up uses it to repair just the bullets it added.
        """
        course_edu = (
            next((edu for edu in self.resume.education if edu.coursework), None)
            if only is None else None
        )
        course_text = (
            "Relevant Coursework: " + ", ".join(course_edu.coursework)
            if course_edu else None
        )
        requested = dict(self.rewritten)
        if course_text:
            requested["__coursework__"] = course_text
        layout, measured_ids = fit_lines._widow_fits(
            self.doc_path, requested, estimated=self.pages_are_estimated
        )

        scope = set(self.rewritten) if only is None else set(self.rewritten) & only
        before_widows = {bid for bid in scope if fit_lines._is_widow(layout, measured_ids, bid)}
        targets = fit_lines._widow_targets(
            self.rewritten, self.by_id, layout, measured_lines=self.measured_lines,
            capacity=self.capacity, members=self.members, estimated=self.pages_are_estimated,
            measured_ids=measured_ids,
        ) if self.repair_widows else {}
        if only is not None:
            targets = {bid: window for bid, window in targets.items() if bid in only}
        old_texts = dict(self.rewritten)
        old_courses = list(course_edu.coursework) if course_edu else []
        if targets:
            self._repair_widows(targets, layout)
        if self.repair_widows and course_edu and self.coursework_pool:
            self._fit_coursework(course_edu, old_courses, layout, measured_ids)
        changed = self.rewritten != old_texts or (
            course_edu is not None and course_edu.coursework != old_courses
        )
        if changed:
            changed = self._keep_widow_repair(old_texts, course_edu, old_courses)
        if changed:
            final_layout, final_measured_ids = fit_lines._widow_fits(
                self.doc_path, self.rewritten, estimated=self.pages_are_estimated
            )
        else:
            final_layout, final_measured_ids = layout, measured_ids
        remaining = {
            bid
            for bid in self.rewritten
            if fit_lines._is_widow(final_layout, final_measured_ids, bid)
        }
        if only is None:
            self.outcome.widows_repaired = len(before_widows - remaining)
        else:
            self.outcome.widows_repaired += len(before_widows - remaining)
        self.outcome.measured_widows_remaining = len(remaining)

    def _repair_widows(self, targets: dict, layout: dict[str, render.LineFit]) -> None:
        repair_sources = dict(self.by_id)
        for survivor, member_ids in self.members.items():
            if survivor in targets:
                originals = [self.by_id[mid] for mid in member_ids]
                repair_sources[survivor] = Bullet(
                    id=survivor,
                    text=" ".join(item.text for item in originals),
                    tags=list({tag for item in originals for tag in item.tags}),
                )
        repaired, _, _, rejected = _polish(
            self.rewritten, repair_sources, self.requirements, repair_widows=False,
            repair_verbs=False, targets=targets,
            line_ceilings=fit_lines._line_saving_ceilings(targets, layout),
        )
        self.rewritten = self.outcome.texts = repaired
        self.outcome.widow_repairs_rejected.update(rejected)

    def _fit_coursework(
        self, course_edu, old_courses: list[str], layout: dict[str, render.LineFit],
        measured_ids: set[str],
    ) -> None:
        course_fit = layout["__coursework__"]
        measured = "__coursework__" in measured_ids
        course_edu.coursework = facets.fit_coursework_to_budget(
            old_courses, pool=self.coursework_pool,
            jd_keywords=[k.phrase for k in self.requirements.keywords],
            chars_per_line=course_fit.chars_per_line,
            last_fill=course_fit.last_fill if measured else None,
            rendered_lines=course_fit.lines if measured else None,
        )

    def _keep_widow_repair(
        self, old_texts: dict[str, str], course_edu, old_courses: list[str]
    ) -> bool:
        """Render the repaired draft; revert it if it overflowed. True when it was kept."""
        self._set_draft(self.draw(self.rewritten, "widow"))
        if self.pages <= self.target_pages:
            return True
        self.rewritten = self.outcome.texts = old_texts
        if course_edu:
            course_edu.coursework = old_courses
        self._set_draft(self.draw(self.rewritten, "revert"))
        self.warnings.append("Widow repair overflowed the page; kept the fitting draft.")
        return False
