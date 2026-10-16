"""Must-have coverage from the master resume down to the page — pure, no model, no document.

The run report's long-standing figure ("In your resume") counts posting must-haves any
master bullet matches. This module follows each one onto the page the renderer accepted
(`render.visible_text`) and records where it stopped:

- **expressed**: the page text names it (dictionary detection, or the posting's phrase).
- **tag_only**: an on-page item backs it by Extra skills or by its source wording, but the
  page text never names it.
- **inferred_only**: only skills a model read into an on-page bullet back it. Matching
  only (`bullet_tags`), never counted as substantiated.
- **not_selected**: the master resume has it; nothing on the page backs it.

Separately, **potentially unsupported additions** lists dictionary skills a final bullet
names that its source bullet neither states nor tags — worth a look, not proof of
invention (a safe synonym the guard accepted lands here too). Known misses: a word form
or synonym the dictionary does not list is not detected as expressed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from ..content import bullet_tags
from ..content.data import Bullet, MasterResume
from ..document import render
from . import bullet_checks
from .fit_types import FitResult
from .jd import JobRequirements

PageStatus = Literal["expressed", "tag_only", "inferred_only", "not_selected"]


@dataclass
class KeywordCoverage:
    canonical: str
    phrase: str
    #: How the master resume supports it: "stated" (Extra skills or bullet text),
    #: "inferred" (model-read skills only), or None (not at all).
    resume: Literal["stated", "inferred"] | None
    #: Where it ends on the page; None when neither the resume nor the page has it.
    page: PageStatus | None


@dataclass
class CoverageFunnel:
    total: int
    in_resume: int
    on_page: int
    keywords: list[KeywordCoverage] = field(default_factory=list)
    #: `(bullet id, canonical skill)` pairs; see the module docstring.
    unsupported_additions: list[tuple[str, str]] = field(default_factory=list)


def _detected(texts: Iterable[str], extra: frozenset[str]) -> set[str]:
    return {canonical for text in texts for canonical, _ in bullet_tags.detect(text, extra)}


def _stated(bullets: Iterable[Bullet], extra: frozenset[str]) -> set[str]:
    """Extra skills and skills the text names: what a bullet substantiates."""
    bullets = list(bullets)
    return {t for b in bullets for t in bullet_tags.user_tags(b)} | _detected(
        (b.text for b in bullets), extra
    )


def funnel(
    requirements: JobRequirements,
    master: MasterResume,
    page_resume: MasterResume,
    bullets: dict[str, str],
    visible: list[str],
    *,
    merges: Iterable[tuple[str, tuple[str, ...]]] = (),
) -> CoverageFunnel:
    """Coverage of every posting must-have, master resume to page.

    `master` is the resume the existing figure measures (post-include, pre-facets);
    `page_resume` the one rendered (post-facets) with final `bullets` and its `visible`
    text. `merges` maps a merged bullet's survivor id to all its member ids.
    """
    extra = bullet_tags.resume_terms(page_resume)
    # `known_terms` is the existing figure's evidence; its non-inferred part is `_stated`.
    master_all = set(bullet_tags.known_terms(master))
    master_stated = _stated(master.all_bullets(), bullet_tags.resume_terms(master))

    by_id = {b.id: b for b in page_resume.all_bullets()}
    members = dict(merges)
    on_page = [by_id[bid] for bid in bullets if bid in by_id]
    on_page += [by_id[m] for bid in bullets for m in members.get(bid, ())[1:] if m in by_id]
    backed = _stated(on_page, extra)
    # Rendered pools (skills items, project tech, coursework) back what they name.
    pools = [text for text in visible if text not in bullets.values()]
    backed |= _detected(pools, extra)
    inferred = {t for b in on_page for t in bullet_tags.match_tags(b)} - backed
    page_text = "\n".join(visible)
    expressed = _detected(visible, extra)

    keywords: list[KeywordCoverage] = []
    for kw in requirements.by_importance("must_have"):
        c = kw.canonical
        resume = None if c not in master_all else "stated" if c in master_stated else "inferred"
        if c in expressed or bullet_checks.contains_phrase(page_text, kw.phrase):
            page: PageStatus | None = "expressed"
        elif c in backed:
            page = "tag_only"
        elif c in inferred:
            page = "inferred_only"
        elif resume is not None:
            page = "not_selected"
        else:
            page = None
        keywords.append(KeywordCoverage(c, kw.phrase, resume, page))

    return CoverageFunnel(
        total=len(keywords),
        in_resume=sum(1 for k in keywords if k.resume is not None),
        on_page=sum(1 for k in keywords if k.page == "expressed"),
        keywords=keywords,
        unsupported_additions=_additions(by_id, bullets, members, extra),
    )


def _additions(
    by_id: dict[str, Bullet],
    bullets: dict[str, str],
    members: dict[str, tuple[str, ...]],
    extra: frozenset[str],
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for bid, text in bullets.items():
        sources = [by_id[m] for m in members.get(bid, (bid,)) if m in by_id]
        if not sources:
            continue
        supported = _detected((s.text for s in sources), extra)
        supported |= {t for s in sources for t in bullet_tags.user_tags(s)}
        out.extend((bid, c) for c in sorted(_detected([text], extra) - supported))
    return out


def for_run(
    requirements: JobRequirements,
    master: MasterResume,
    page_resume: MasterResume,
    result: FitResult,
) -> CoverageFunnel:
    """`funnel` for a finished fit: its final bullets, merges and rendered text."""
    visible = render.visible_text(page_resume, result.bullets)
    return funnel(
        requirements, master, page_resume, result.bullets, visible,
        merges=[(g.survivor_id, tuple(g.member_ids)) for g in result.merges],
    )
