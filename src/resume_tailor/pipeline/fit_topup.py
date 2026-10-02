"""Growing an under-full page: the top-up ladder of bullets, extra sections and entries."""

from __future__ import annotations

import math

from .. import config
from ..content.data import Bullet, Experience, Project
from . import events, fit_lines, fit_shrink, fit_types
from .selection import score as score_bullet
from .selection import (
    score_entry,
)


class _FitTopUp(fit_shrink._FitShrink):
    """`_FitRun` steps that add content back when the page has room."""

    def top_up(self) -> str | None:
        """Fill the space trimming and widow repair freed, once the loop has settled on an
        underfull page it cannot grow (see `top_up_ladder`). Every round's added bullets
        get their own measured widow pass — they arrive after the main widow pass, so
        nothing else would catch one ending on a near-empty line. If that pass frees
        lines on a still-short page, one more round runs (`config.MAX_TOPUP_ROUNDS`).

        Returns why the page is still short, or None once it reaches the fill target."""
        reason: str | None = None
        for round_index in range(config.MAX_TOPUP_ROUNDS):
            if self.measured_lines >= math.ceil(self.underflow * self.capacity):
                return None
            added, reason = self.top_up_ladder()
            if not added or not self.repair_widows:
                break
            lines_before = self.measured_lines
            self.widow_pass(only=set(added))
            if (
                round_index == config.MAX_TOPUP_ROUNDS - 1
                or self.measured_lines >= lines_before
            ):
                break
        if self.measured_lines >= math.ceil(self.underflow * self.capacity):
            return None
        return reason or "widow repair of the added bullets freed lines after the last round"

    def top_up_ladder(self) -> tuple[list[str], str | None]:
        """One A/B/C pass. Returns (ids added, why it stopped short or None)."""
        p = fit_types._TopUpPass(*self._shortfall())
        if p.goal <= 0:
            return p.added, None
        if self._top_up_bullets(p):
            return p.added, None
        if self.entry_cap is not None and self._top_up_extra(p, self.entry_cap):
            return p.added, None
        finished, reason = self._top_up_entry(p)
        if finished:
            return p.added, reason
        if p.b_draft is not None:
            # No entry fit, but the extra bullet did: a fuller page beats a sparser one.
            texts_b, ids_b = p.b_draft
            self._set_state(texts_b, self.draw(texts_b, "restore", added=list(ids_b)))
            self._take(p, ids_b)
        return p.added, p.last_failure or self._stop_text()

    def _top_up_bullets(self, p: fit_types._TopUpPass) -> bool:
        """A — bullets of the chosen entries the caps still allow, including any the drop
        rung cut: they were relevant enough to pick once. True once the goal is met."""
        entry_cap = self.entry_cap
        live, per_entry = self._rendered_ids(), self._counts()
        owner = self._owner()
        pool = sorted(
            (b for e in self.entries for b in e.bullets
             if b.id not in live and (entry_cap is None or per_entry[id(e)] < entry_cap)),
            key=self.bullet_rank, reverse=True,
        )
        picked: list[Bullet] = []
        estimate = 0
        for bullet in pool:
            entry = owner[bullet.id]
            if entry_cap is not None and per_entry[id(entry)] >= entry_cap:
                continue
            cost = fit_lines._bullet_cost(bullet)
            if estimate + cost > p.room:
                continue
            picked.append(bullet)
            per_entry[id(entry)] += 1
            estimate += cost
            if estimate >= p.goal:
                break
        if not picked:
            return False
        events.emit(
            self.on_event, "fit",
            f"Page {self.measured_lines / self.capacity:.0%} full; adding back "
            f"{len(picked)} bullet(s)",
            rung="topup-A", bullets=len(picked),
        )
        ids = self.add(picked, "topup-A", shrink=1)
        if ids:
            self._take(p, ids)
        p.goal, p.room = self._shortfall()
        return p.goal <= 0

    def _top_up_extra(self, p: fit_types._TopUpPass, cap: int) -> bool:
        """B — one bullet past the per-entry cap, from an entry already at it. True once
        the goal is met; a draft that fits but is still short is parked in `p.b_draft`."""
        live, per_entry = self._rendered_ids(), self._counts()
        owner = self._owner()
        extra = sorted(
            (b for e in self.entries if per_entry[id(e)] >= cap
             for b in e.bullets if b.id not in live and fit_lines._bullet_cost(b) <= p.room),
            key=self.bullet_rank, reverse=True,
        )
        if not extra:
            return False
        bullet = extra[0]
        events.emit(
            self.on_event, "fit",
            f"Page {self.measured_lines / self.capacity:.0%} full; trying bullet "
            f"{cap + 1} in {fit_types._entry_label(owner[bullet.id])}",
            rung="topup-B", bullet=bullet.id,
        )
        before = dict(self.rewritten)
        ids = self.add([bullet], "topup-B", shrink=0)
        if not ids:
            p.last_failure = (
                f"adding a bullet to {fit_types._entry_label(owner[bullet.id])} overflowed the page"
            )
            return False
        p.goal, p.room = self._shortfall()
        if p.goal <= 0:
            self._take(p, ids)
            return True
        # Still short: take the extra bullet back out and try a new entry instead; keep
        # this draft in case no entry fits.
        p.b_draft = (dict(self.rewritten), ids)
        self._set_state(before, self.draw(before, "revert"))
        p.goal, p.room = self._shortfall()
        return False

    def _top_up_entry(self, p: fit_types._TopUpPass) -> tuple[bool, str | None]:
        """C — the best entry not on the page yet, with as many of its top bullets (up to
        the cap) as reach the target. Returns (finished, why it stopped short or None)."""
        chosen = {id(e) for e in self.entries}
        live = self._rendered_ids()
        live_sections = {
            self.section_of.get(id(e)) for e in self.candidate_entries
            if any(b.id in live for b in e.bullets)
        }
        ranked_entries = sorted(
            (e for e in self.candidate_entries if id(e) not in chosen and e.bullets),
            key=lambda e: score_entry(e, self.requirements, semantic=self.semantic),
            reverse=True,
        )
        for entry in ranked_entries:
            top, k = self._entry_top_bullets(entry, p, live_sections)
            if k == 0:
                continue
            events.emit(
                self.on_event, "fit",
                f"Page {self.measured_lines / self.capacity:.0%} full; adding "
                f"{fit_types._entry_label(entry)} with {k} bullet(s)",
                rung="topup-C", entry=fit_types._entry_label(entry), bullets=k,
            )
            ids = self.add(top[:k], "topup-C", shrink=k - 1)
            if ids:
                self.entries.append(entry)
                self.by_id.update({b.id: b for b in entry.bullets})
                self.total_bullets += len(entry.bullets)
                self._take(p, ids)
                goal, _ = self._shortfall()
                if goal <= 0:
                    return True, None
                return True, f"top-up limit reached after adding {fit_types._entry_label(entry)}"
            p.last_failure = f"adding {fit_types._entry_label(entry)} overflowed the page"
            break
        return False, None

    def _entry_top_bullets(
        self, entry, p: fit_types._TopUpPass, live_sections: set
    ) -> tuple[list[Bullet], int]:
        """`entry`'s top bullets (up to the cap) and how many of them reach the goal
        within the room left, counting the header lines the entry brings with it."""
        header = (2 if isinstance(entry, Experience) else 1) + (
            0 if self.section_of.get(id(entry)) in live_sections else 1
        )
        top = sorted(entry.bullets, key=self.bullet_rank, reverse=True)
        if self.entry_cap is not None:
            top = top[:self.entry_cap]
        k = 0
        estimate = header
        for bullet in top:
            if estimate + fit_lines._bullet_cost(bullet) > p.room:
                break
            estimate += fit_lines._bullet_cost(bullet)
            k += 1
            if estimate >= p.goal:
                break
        return top, k

    def add(self, new: list[Bullet], step: str, *, shrink: int) -> list[str]:
        """Add `new` to the page: one rewrite, then render. On overflow, retry up to
        `shrink` times without the last (lowest-ranked) bullet — render only, no new
        call. Returns the ids kept, or [] after re-rendering the pre-step draft."""
        base = dict(self.rewritten)
        fresh = self.rewrite_new(new)
        ids = [b.id for b in new]
        while ids:
            candidate = {**base, **{bid: fresh[bid] for bid in ids}}
            drawn = self.draw(candidate, step, added=list(ids))
            if drawn[1] <= self.target_pages:
                self.rewritten = self.outcome.texts = candidate
                self._set_draft(drawn)
                return ids
            if shrink <= 0 or len(ids) == 1:
                break
            shrink -= 1
            ids = ids[:-1]
        self._set_draft(self.draw(base, "revert"))
        self.rewritten = self.outcome.texts = base
        return []

    def bullet_rank(self, bullet: Bullet) -> float:
        return score_bullet(bullet, self.requirements, semantic=self.semantic) * (
            self.recency_of.get(bullet.id, 1.0)
        )

    def _take(self, p: fit_types._TopUpPass, ids: list[str]) -> None:
        p.added.extend(ids)
        self.topped_up.extend(ids)
        already = {b.id for b in self.selected}
        for bid in ids:
            if bid in self.dropped:
                self.dropped.remove(bid)
            if bid not in already:
                self.selected.append(self.all_sources[bid])

    def _shortfall(self) -> tuple[int, int]:
        """(lines to the fill target, lines to a full page)."""
        target_lines = math.ceil(self.underflow * self.capacity)
        return target_lines - self.measured_lines, self.capacity - self.measured_lines

    def _rendered_ids(self) -> set[str]:
        ids = set(self.rewritten)
        for member_ids in self.members.values():
            ids.update(member_ids)
        return ids

    def _counts(self) -> dict[int, int]:
        live = self._rendered_ids()
        return {id(e): sum(1 for b in e.bullets if b.id in live) for e in self.entries}

    def _owner(self) -> dict[str, Experience | Project]:
        return {b.id: e for e in self.entries for b in e.bullets}

    def _stop_text(self) -> str:
        return (
            f"no more bullets or entries fit in the remaining "
            f"{max(0, self.capacity - self.measured_lines)} line(s)"
        )
