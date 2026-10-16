"""Code-measured quality signals per case. No model calls; everything reuses the
pipeline's own checks so the eval measures what the product enforces."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from resume_tailor import config
from resume_tailor.content import bullet_tags
from resume_tailor.content.data import Bullet, MasterResume
from resume_tailor.pipeline import bullet_checks, fit_selection, selection
from resume_tailor.pipeline import coverage as page_coverage
from resume_tailor.pipeline.expand import Expansion
from resume_tailor.pipeline.jd import JobRequirements, verify_verbatim
from resume_tailor.pipeline.rewrite_prompts import length_band


def _must_haves(requirements: JobRequirements) -> list:
    return [k for k in requirements.keywords
            if k.importance == "must_have" and k.kind != "soft"]


def _shows(text: str, kw) -> bool:
    return bullet_checks.contains_phrase(text, kw.phrase) or bullet_checks.contains_phrase(
        text, kw.canonical.replace("-", " ")
    )


def rewrite_metrics(
    sources: Sequence[Bullet],
    texts: dict[str, str],
    fabrications_rejected: dict[str, list[str]],
    requirements: JobRequirements,
    budget: int,
) -> dict[str, float]:
    """Fallbacks, leftover guard hits, keyword mirroring, length and repetition."""
    by_id = {b.id: b for b in sources}
    n = max(1, len(sources))
    soft_min, hard_max = length_band(budget)
    final = {i: texts.get(i, by_id[i].text) for i in by_id}
    guard = sum(
        len(bullet_checks.guard_offenders([by_id[i]], t))
        for i, t in final.items() if i not in fabrications_rejected
    )
    must = _must_haves(requirements)
    supported = [k for k in must
                 if any(selection._matches(k, set(bullet_tags.match_tags(b))) for b in sources)]
    mirrored = [k for k in supported if any(_shows(t, k) for t in final.values())]
    already = [k for k in supported if any(_shows(b.text, k) for b in sources)]
    phrases = [k.phrase for k in requirements.keywords if k.kind != "soft"]
    collisions = bullet_checks.phrase_collisions(
        final, phrases, by_id, pages=config.DEFAULT_PAGE_TARGET
    )
    return {
        "bullets": len(sources),
        "fallback_rate": len(fabrications_rejected) / n,
        "guard_offenders": guard,
        "must_supported": len(supported),
        "must_mirrored": len(mirrored),
        "must_in_source": len(already),
        "mirror_rate": len(mirrored) / len(supported) if supported else 1.0,
        "over_length": sum(1 for t in final.values() if len(t) > hard_max),
        "under_length": sum(1 for t in final.values() if len(t) < soft_min),
        "verb_collisions": len(bullet_checks.verb_collisions(final)),
        "phrase_collisions": len(collisions),
        "changed_rate": sum(1 for i, t in final.items() if t != by_id[i].text) / n,
        "mean_chars": sum(len(t) for t in final.values()) / n,
        **funnel_metrics(sources, final, requirements),
    }


def funnel_metrics(
    sources: Sequence[Bullet], final: dict[str, str], requirements: JobRequirements
) -> dict[str, float]:
    """`pipeline/coverage.py`'s funnel at bullet level: must-haves the sources state or
    only infer, the ones the final texts name, and skills the rewrites added."""
    must = _must_haves(requirements)
    stated = page_coverage._stated(sources, frozenset())
    inferred = {t for b in sources for t in bullet_tags.match_tags(b)} - stated
    shown = [k for k in must if any(_shows(t, k) for t in final.values())]
    by_id = {b.id: b for b in sources}
    return {
        "must_stated": sum(1 for k in must if k.canonical in stated),
        "must_inferred_only": sum(1 for k in must if k.canonical in inferred),
        "must_expressed": len(shown),
        "must_expressed_unstated": sum(1 for k in shown if k.canonical not in stated),
        "unsupported_additions": len(page_coverage._additions(by_id, final, {}, frozenset())),
    }


def must_sets(
    sources: Sequence[Bullet], final: dict[str, str], requirements: JobRequirements
) -> dict[str, list[str]]:
    """Non-soft must-have phrases the final texts name (`shown`), and the ones the sources
    back by their own text or Extra skills, inferred skills excluded (`backed`). A keyword
    one arm shows and another drops counts as a supported loss only when it is backed."""
    must = _must_haves(requirements)
    tags = set().union(*(bullet_tags.match_tags(b, inferred=False) for b in sources))
    return {
        "shown": sorted(k.phrase for k in must if any(_shows(t, k) for t in final.values())),
        "backed": sorted(k.phrase for k in must if selection._matches(k, tags)),
    }


def expand_metrics(expansion: Expansion) -> dict[str, float]:
    """Entries and bullets produced, bullets the guard dropped, and length."""
    entries = expansion.entries
    bullets = [b for e in entries for b in e.bullets]
    dropped = sum(1 for e in entries for w in e.warnings if "omitted" not in w.lower())
    return {
        "entries": len(entries),
        "empty_entries": sum(1 for e in entries if not e.bullets),
        "bullets": len(bullets),
        "guard_dropped": dropped,
        "chars": sum(e.char_count for e in entries),
        "over_limit": sum(1 for e in entries if expansion.char_limit and
                          e.char_count > expansion.char_limit),
    }


def keyword_set(requirements: JobRequirements, *, must_only: bool = False) -> set[str]:
    return {k.canonical for k in requirements.keywords
            if not must_only or k.importance == "must_have"}


def f1(a: Iterable[str], b: Iterable[str]) -> float:
    """Set agreement between two keyword lists (1.0 when both are empty)."""
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    overlap = len(a & b)
    return 2 * overlap / (len(a) + len(b))


def coverage(resume: MasterResume, requirements: JobRequirements, limit: int = 15) -> dict:
    """Downstream effect of an extraction, with no model call: how many must-haves the
    keyword-only selection of `limit` bullets would show (the `eval_selection` replay)."""
    cap = config.MAX_BULLETS_PER_ENTRY
    entries = fit_selection.choose_entries(
        resume, requirements, semantic=None, max_per_entry=cap,
    )
    pools, weights = fit_selection._section_pools(
        resume, entries, config.EXPERIENCE_BULLET_SHARE,
    )
    chosen = selection.select_within_entries(
        entries, requirements, limit=limit, semantic=None, max_per_entry=cap,
        pools=pools, weights=weights,
    )
    must = {k.canonical for k in _must_haves(requirements)}
    shown = {k.canonical for k in requirements.keywords for b in chosen
             if selection._matches(k, set(bullet_tags.match_tags(b)))}
    return {"must_total": len(must), "must_shown": len(must & shown), "keywords_shown": len(shown)}


def extract_metrics(
    requirements: JobRequirements, jd_text: str, resume: MasterResume
) -> dict[str, float]:
    """Verbatim violations, sizes, and the downstream coverage replay."""
    return {
        "keywords": len(requirements.keywords),
        "must_haves": len(_must_haves(requirements)),
        "verbatim_violations": len(verify_verbatim(requirements, jd_text)),
        **coverage(resume, requirements),
    }
