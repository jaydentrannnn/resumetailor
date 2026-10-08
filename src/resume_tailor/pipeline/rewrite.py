"""Bullet selection and rewriting — the content half of the pipeline.

Three deliberately separate stages:

1. `score` / `select` — pure, deterministic tag matching. No LLM. Cheap and predictable,
   which is what lets the fit loop retry without cost blowing up.
2. `rewrite_bullets` — a batched API call that rewords the surviving bullets to mirror the
   posting's phrasing, plus at most one fabrication-retry call for offending ids, plus at
   most one polish follow-up carrying only widows and/or verb collisions. Each follow-up
   fires only when needed.
3. `check_fabrication` — a post-hoc check *in code*. The prompt asks the model not to
   invent skills; this function is what actually guarantees it. Never relax it to make a
   run pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from ..content.data import Bullet, MasterResume
from ..infra import llm, telemetry
from . import bullet_checks, bullet_merge, events, followups, rewrite_prompts
from .jd import JobRequirements
from .merge import MergeGroup

# --------------------------------------------------------------------------------------
# Stage 2 — rewrite
# --------------------------------------------------------------------------------------


@dataclass
class RewriteOutcome:
    """Final bullet text plus what the polish pass had to do to get there."""

    texts: dict[str, str]
    widows_repaired: int = 0
    verbs_diversified: int = 0
    merges: list[MergeGroup] = field(default_factory=list)
    #: Bullets whose widow-repair candidate was discarded for fabricating, id -> offending
    #: terms. Reported rather than raised: the original text is kept, so the document is
    #: correct — but a run that silently declined to fix a widow should say why.
    widow_repairs_rejected: dict[str, list[str]] = field(default_factory=dict)
    #: Bullets whose *main* rewrite still fabricated after the one targeted retry, id ->
    #: offending terms. The bullet's original, guard-clean master-resume text is kept in
    #: `texts` instead — reported rather than raised, same rationale as
    #: `widow_repairs_rejected`: the document is never wrong, so a hard failure would only
    #: block the whole run over one bullet that's better left untailored.
    fabrications_rejected: dict[str, list[str]] = field(default_factory=dict)
    measured_widows_remaining: int | None = None
    #: Bullets still rendering past `_TARGET_LINES_PER_BULLET` lines after the fit loop's
    #: one capped shortening attempt (measured by the widow pass).
    overlong_remaining: list[str] = field(default_factory=list)

    @property
    def widows_remaining(self) -> int:
        if self.measured_widows_remaining is not None:
            return self.measured_widows_remaining
        return len(bullet_checks.widowed(self.texts))

    @property
    def verb_collisions_remaining(self) -> int:
        """Bullets still opening with a verb another bullet already used."""
        return len(bullet_checks.verb_collisions(self.texts))


@telemetry.stage("rewrite", "initial")
def rewrite_bullets(
    bullets: list[Bullet],
    requirements: JobRequirements,
    *,
    char_budget: int,
    repair_widows: bool = True,
    repair_verbs: bool = True,
    merge_groups: list[MergeGroup] | None = None,
    on_event: events.ProgressCallback | None = None,
    verb_context: dict[str, str] | None = None,
) -> RewriteOutcome:
    """Rewrite `bullets` to surface the posting's keywords.

    `verb_context` is the text of bullets already on the page (`{id: text}`), used only
    to detect repeated opening verbs: the fit loop's top-up rewrites just the bullets it
    adds, and those must not open with a verb the page already uses. Context bullets are
    never re-requested or returned.

    Verb repair can add one follow-up call here. Widow repair waits until fit has a PDF;
    character estimates at this stage have too many false positives to trim safely.

    A first draft that fabricates earns one targeted retry of only the offending ids
    (`_retry_fabrications`). A second fabrication — or an id the model drops on retry —
    keeps that bullet's original, guard-clean master-resume text instead and is reported
    in `RewriteOutcome.fabrications_rejected` as a warning, never raised: the document is
    never wrong (the fallback text is verbatim source), so failing the whole run over one
    stubborn bullet costs more than it protects.
    """
    if not bullets:
        return RewriteOutcome(texts={})

    budget = max(40, char_budget)

    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<keywords_to_mirror>\n{rewrite_prompts._format_keywords(requirements)}\n</keywords_to_mirror>\n\n"
        "<context>\n"
        + "\n".join(f"  - {n}" for n in requirements.domain_notes)
        + "\n</context>\n\n"
        "<bullets_to_rewrite>\n"
        f"{rewrite_prompts._format_bullets(bullets, budget)}\n</bullets_to_rewrite>"
    )

    events.emit(
        on_event,
        "rewrite",
        f"Rewriting {len(bullets)} bullet(s)",
        bullets=len(bullets),
        model=config.model_for("rewrite"),
    )
    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=rewrite_prompts._system(),
        messages=[{"role": "user", "content": user}],
        output_format=rewrite_prompts.RewriteResult,
        # Raise this stage's effort if rewrites come back bland. The SDK merges `format`
        # into `output_config`, so passing both is safe.
        output_config={"effort": config.effort_for("rewrite")},
    )

    result = response.parsed_output
    if result is None:
        raise RuntimeError(
            f"Model did not return parseable rewrites (stop_reason={response.stop_reason!r})."
        )

    by_id = {b.id: b for b in bullets}
    out: dict[str, str] = {}
    rejected: dict[str, tuple[str, list[str]]] = {}

    for item in result.bullets:
        source = by_id.get(item.id)
        if source is None:
            # An unknown id means the mapping is unreliable; skip rather than guess.
            continue
        text = item.text.strip()
        offenders = bullet_checks.guard_offenders([source], text, preserve_numbers=True)
        if offenders:
            rejected[item.id] = (text, offenders)
        else:
            out[item.id] = text

    fabrications_rejected: dict[str, list[str]] = {}
    missing_ids = {bid for bid, (_text, problems) in rejected.items()
                   if any(p.startswith(bullet_checks._DROPPED_NUMBER_PREFIX) for p in problems)}
    telemetry.event("rewrite", number_omissions=len(missing_ids))
    if rejected:
        events.emit(
            on_event,
            "rewrite",
            f"Retrying {len(rejected)} bullet(s) with factual problems",
            fabricated=len(rejected),
        )
        try:
            accepted, survivors = followups._retry_fabrications(
                rejected, by_id, requirements, preserve_numbers=True,
            )
        except llm.LLMError:
            # A failed factual repair keeps verified source text, just like a
            # repair that returns no usable bullet. Never spend another retry.
            accepted = {}
            survivors = {bid: offenders for bid, (_text, offenders) in rejected.items()}
        telemetry.event("rewrite", number_repairs=len(missing_ids & accepted.keys()),
                        number_fallbacks=len(missing_ids & survivors.keys()))
        out.update(accepted)
        if survivors:
            fabrications_rejected = survivors
            for bullet_id in survivors:
                # Fall back to the original, guard-clean master-resume text — never emit
                # the fabrication, but never fail the whole run over one bullet either.
                out[bullet_id] = by_id[bullet_id].text

    # Any bullet the model dropped keeps its original text — better an untailored true
    # line than a missing one.
    for b in bullets:
        out.setdefault(b.id, b.text)

    accepted_merges: list[MergeGroup] = []
    if merge_groups:
        out, accepted_merges = bullet_merge._merge_bullets(
            out, by_id, merge_groups, requirements, budget=budget
        )

    if not repair_widows and not repair_verbs:
        return RewriteOutcome(
            texts=out,
            merges=accepted_merges,
            fabrications_rejected=fabrications_rejected,
        )

    # Both counts are measured before the call so the progress line says what the follow-up
    # is for; the pass itself re-derives them, since merging may have changed either.
    # PDF layout is unavailable until fit has rendered this draft. Do not cut here
    # based on the character estimate; it often flags full physical lines.
    stranded = 0
    context = {bid: text for bid, text in (verb_context or {}).items() if bid not in out}
    revoice_only = set(out) if context else None
    combined = {**context, **out}
    colliding = (
        sum(
            1
            for bid in bullet_checks.verb_collisions(combined)
            if revoice_only is None or bid in revoice_only
        )
        if repair_verbs
        else 0
    )
    if stranded or colliding:
        wanted = []
        if stranded:
            wanted.append(f"{stranded} bullet(s) that spilled onto a near-empty line")
        if colliding:
            wanted.append(f"{colliding} repeated or vague opening verb(s)")
        events.emit(
            on_event,
            "rewrite",
            f"Polishing {' and '.join(wanted)}",
            widowed=stranded,
            verb_collisions=colliding,
        )
    polished, improved, revoiced, rejected_repairs = followups._polish(
        combined,
        by_id,
        requirements,
        repair_widows=False,
        repair_verbs=repair_verbs,
        revoice_only=revoice_only,
    )
    out = {bid: polished[bid] for bid in out}
    return RewriteOutcome(
        texts=out,
        widows_repaired=improved,
        verbs_diversified=revoiced,
        merges=accepted_merges,
        widow_repairs_rejected=rejected_repairs,
        fabrications_rejected=fabrications_rejected,
    )


def keyword_coverage(
    requirements: JobRequirements, resume: MasterResume
) -> tuple[int, int]:
    """Return (matched, total) must-have keywords present anywhere in the master resume.

    Reported by the CLI so an obviously poor-fit posting is visible before applying.
    """
    must = requirements.by_importance("must_have")
    available = {t for b in resume.all_bullets() for t in b.tags}
    matched = sum(1 for kw in must if kw.canonical in available)
    return matched, len(must)
