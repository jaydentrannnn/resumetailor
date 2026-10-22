"""Must-have coverage from the master resume down to the page — pure, no model, no document.

The run report's long-standing figure ("In your resume") counts posting must-haves any
master bullet matches. This module follows each one onto the page the renderer accepted
(`render.visible_text`) and records where it stopped:

- **expressed**: the page text names it (dictionary detection, the posting's phrase, or
  the canonical itself).
- **demonstrated**: a soft must-have an on-page item backs (its own tag or a
  `config.SOFT_SKILL_RELATED_TAGS` one). The rewrite shows soft skills by the work and
  never names them, so this counts toward the page figure.
- **tag_only**: a technical must-have an on-page item backs by Extra skills or by its
  source wording, but the page text never names it.
- **inferred_only**: only skills a model read into an on-page bullet back it. Matching
  only (`bullet_tags`), never counted as substantiated.
- **not_selected**: the master resume has it; nothing on the page backs it.

The resume side says how the master resume backs each one: **stated** (its text names
it), **tagged** (only an Extra skill does), **inferred** (only model-read skills). Every
figure counts distinct canonicals (`JobRequirements.must_have_canonicals`); a canonical
the posting names twice keeps its best-covered phrase.

Separately, **potentially unsupported additions** lists dictionary skills a final bullet
names that its source bullet neither states nor tags — worth a look, not proof of
invention (a safe synonym the guard accepted lands here too). Known misses: a word form
or synonym the dictionary does not list is not detected as expressed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .. import config
from ..content import bullet_tags
from ..content.data import Bullet, MasterResume
from ..document import render
from ..infra import atomic
from . import bullet_checks
from .fit_types import FitResult
from .jd import JobRequirements, Keyword

PageStatus = Literal["expressed", "demonstrated", "tag_only", "inferred_only", "not_selected"]
#: Statuses the page figure counts.
ON_PAGE: frozenset[str] = frozenset({"expressed", "demonstrated"})
_PAGE_RANK = ("expressed", "demonstrated", "tag_only", "inferred_only", "not_selected", None)


@dataclass
class KeywordCoverage:
    canonical: str
    phrase: str
    #: How the master resume supports it; see the module docstring. A funnel saved
    #: before "tagged" existed calls Extra-skills-only support "stated".
    resume: Literal["stated", "tagged", "inferred"] | None
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
    #: Must-haves the master resume's own text names (`resume == "stated"`), the fair
    #: baseline for `on_page`. None on a funnel saved before it was measured.
    in_resume_text: int | None = None


def _detected(texts: Iterable[str], extra: frozenset[str]) -> set[str]:
    return {canonical for text in texts for canonical, _ in bullet_tags.detect(text, extra)}


def _stated(bullets: Iterable[Bullet], extra: frozenset[str]) -> set[str]:
    """Extra skills and skills the text names: what a bullet substantiates."""
    bullets = list(bullets)
    return {t for b in bullets for t in bullet_tags.user_tags(b)} | _detected(
        (b.text for b in bullets), extra
    )


ResumeStatus = Literal["stated", "tagged", "inferred"] | None
#: The run folder file a bullet edit writes, read back over the run report's funnel.
COVERAGE_FILE = "coverage.json"


def _names(text: str, detected: set[str], kw: Keyword) -> bool:
    """Whether `text` names `kw`: a detected skill, its canonical, or the posting's phrase."""
    return (kw.canonical in detected or bullet_checks.contains_phrase(text, kw.canonical)
            or bullet_checks.contains_phrase(text, kw.phrase))


def _resume_status(requirements: JobRequirements, master: MasterResume) -> dict[str, ResumeStatus]:
    # `known_terms` is the existing figure's evidence: membership decides None, so
    # `in_resume` stays equal to `rewrite.keyword_coverage`.
    extra = bullet_tags.resume_terms(master)
    master_all = set(bullet_tags.known_terms(master))
    tagged = {t for b in master.all_bullets() for t in bullet_tags.user_tags(b)}
    text = "\n".join(render.visible_text(master, {b.id: b.text for b in master.all_bullets()}))
    detected = _detected([text], extra)
    status: dict[str, ResumeStatus] = {}
    for kw in requirements.by_importance("must_have"):
        c = kw.canonical
        if c not in master_all:
            status.setdefault(c, None)
        elif _names(text, detected, kw) or status.get(c) == "stated":
            status[c] = "stated"
        else:
            status[c] = "tagged" if c in tagged else "inferred"
    return status


def funnel(
    requirements: JobRequirements,
    master: MasterResume,
    page_resume: MasterResume,
    bullets: dict[str, str],
    visible: list[str],
    *,
    merges: Iterable[tuple[str, tuple[str, ...]]] = (),
    page_ids: set[str] | None = None,
) -> CoverageFunnel:
    """Coverage of every posting must-have, master resume to page.

    `master` is the resume the existing figure measures (post-include, pre-facets);
    `page_resume` the one rendered (post-facets) with final `bullets` and its `visible`
    text. `merges` maps a merged bullet's survivor id to all its member ids. `page_ids`
    are the bullets that render (`render.page_bullet_ids`); default every one.
    """
    return _page_funnel(requirements, page_resume, bullets, visible, dict(merges),
                        page_ids, _resume_status(requirements, master))


def _page_funnel(
    requirements: JobRequirements,
    page_resume: MasterResume,
    bullets: dict[str, str],
    visible: list[str],
    members: dict[str, tuple[str, ...]],
    page_ids: set[str] | None,
    resume_status: dict[str, ResumeStatus],
) -> CoverageFunnel:
    extra = bullet_tags.resume_terms(page_resume)
    by_id = {b.id: b for b in page_resume.all_bullets()}
    shown = [bid for bid in bullets if page_ids is None or bid in page_ids]
    on_page = [by_id[bid] for bid in shown if bid in by_id]
    on_page += [by_id[m] for bid in shown for m in members.get(bid, ())[1:] if m in by_id]
    backed = _stated(on_page, extra)
    # Rendered pools (skills items, project tech, coursework, headers) back what they name.
    pools = [text for text in visible if text not in bullets.values()]
    backed |= _detected(pools, extra)
    inferred = {t for b in on_page for t in bullet_tags.match_tags(b)} - backed
    page_text = "\n".join(visible)
    expressed = _detected(visible, extra)

    best: dict[str, KeywordCoverage] = {}
    for kw in requirements.by_importance("must_have"):
        c = kw.canonical
        resume = resume_status.get(c)
        if _names(page_text, expressed, kw):
            page: PageStatus | None = "expressed"
        elif kw.kind == "soft" and (
            c in backed or not backed.isdisjoint(config.SOFT_SKILL_RELATED_TAGS.get(c, ()))
        ):
            page = "demonstrated"
        elif c in backed:
            page = "tag_only"
        elif c in inferred:
            page = "inferred_only"
        elif resume is not None:
            page = "not_selected"
        else:
            page = None
        row = KeywordCoverage(c, kw.phrase, resume, page)
        if c not in best or _PAGE_RANK.index(page) < _PAGE_RANK.index(best[c].page):
            best[c] = row
    keywords = list(best.values())

    return CoverageFunnel(
        total=len(keywords),
        in_resume=sum(1 for k in keywords if k.resume is not None),
        on_page=sum(1 for k in keywords if k.page in ON_PAGE),
        keywords=keywords,
        unsupported_additions=_additions(
            by_id, {bid: bullets[bid] for bid in shown}, members, extra),
        in_resume_text=sum(1 for k in keywords if k.resume == "stated"),
    )


def refresh(
    saved: CoverageFunnel,
    requirements: JobRequirements,
    page_resume: MasterResume,
    bullets: dict[str, str],
    *,
    layout: dict,
    merges: Iterable[tuple[str, tuple[str, ...]]] = (),
) -> CoverageFunnel:
    """The page side again after a bullet edit; the resume side is the run's own (the
    master resume is not part of a run folder, and an edit never changes it)."""
    status = {k.canonical: k.resume for k in saved.keywords}
    out = _page_funnel(
        requirements.as_claimed(), page_resume, bullets,
        render.visible_text(page_resume, bullets, layout=layout), dict(merges),
        render.page_bullet_ids(page_resume, bullets, layout=layout), status,
    )
    if saved.in_resume_text is None:
        out.in_resume_text = None  # its "stated" still includes Extra-skills-only support
    return out


def to_dict(f: CoverageFunnel) -> dict:
    return {
        "total": f.total, "in_resume": f.in_resume, "on_page": f.on_page,
        "in_resume_text": f.in_resume_text,
        "keywords": [{"canonical": k.canonical, "phrase": k.phrase, "resume": k.resume,
                      "page": k.page} for k in f.keywords],
        "unsupported_additions": [[bid, skill] for bid, skill in f.unsupported_additions],
    }


def save(out_dir: Path, f: CoverageFunnel) -> None:
    atomic.write_text(out_dir / COVERAGE_FILE, json.dumps(to_dict(f), indent=2))


def read(out_dir: Path) -> CoverageFunnel | None:
    """The run's latest funnel: `coverage.json` after an edit, else the run report's."""
    for path, pick in ((out_dir / COVERAGE_FILE, lambda d: d),
                       (out_dir / "run.json", lambda d: (d.get("report") or {}).get(
                           "coverage_funnel"))):
        try:
            raw = pick(json.loads(path.read_text("utf-8")))
            if raw:
                return from_dict(raw)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def from_dict(d: dict) -> CoverageFunnel:
    return CoverageFunnel(
        total=d["total"], in_resume=d["in_resume"], on_page=d["on_page"],
        keywords=[KeywordCoverage(k["canonical"], k["phrase"], k["resume"], k["page"])
                  for k in d.get("keywords", [])],
        unsupported_additions=[(bid, skill) for bid, skill in d.get("unsupported_additions", [])],
        in_resume_text=d.get("in_resume_text"),
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
        page_ids=render.page_bullet_ids(page_resume, result.bullets),
    )
