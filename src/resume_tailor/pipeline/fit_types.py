"""The fit loop's result and error types, its draft and top-up records."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..content.data import Bullet
from .merge import MergeGroup
from .rewrite import RewriteOutcome

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

def _entry_label(entry) -> str:
    return getattr(entry, "company", "") or getattr(entry, "name", "") or "an entry"

@dataclass
class _TopUpPass:
    """One `_FitRun.top_up_ladder` pass: the shortfall it is closing and what it did."""

    goal: int
    room: int
    added: list[str] = field(default_factory=list)
    last_failure: str | None = None
    # The rung-B draft (texts, ids added), kept in case no new entry fits.
    b_draft: tuple[dict[str, str], list[str]] | None = None
