"""The bounded follow-up calls after a rewrite: the one-shot fabrication retry and the
widow/verb polish pass."""

from __future__ import annotations

from .. import config
from ..content import industries
from ..content.data import Bullet
from ..infra import llm, telemetry
from . import bullet_checks, fabrication, rewrite_prompts
from .jd import JobRequirements

_REPAIR_INSTRUCTION = """\
Each bullet below runs past its `max` characters — it either wrapped onto a final line \
holding almost nothing or runs longer than a resume bullet should, wasting page space. \
The wording is already right — the only problem is length. Bring each one to at most its \
`max` characters by cutting hedges, redundant context, and secondary detail. Keep every \
number, every required technical keyword, and the opening verb exactly as written.
"""

_REPAIR_PROMPT_VERSION = 6

_TARGET_INSTRUCTION = """\
Each bullet has a character window. For SHORTEN, cut secondary detail while preserving
every number and factual claim. For EXTEND, restore useful detail only from that bullet's
own source. Preserve all numbers. Keep the opening verb of `current`, even where the
source opens differently. Return THREE versions of each bullet, each as its own
entry under the same id: one near min, one in the middle, one near max. Exact counts are
not required — the versions just need to differ in length. Return plain text strings.
"""

#: Most versions of one fit bullet considered from a reply (`_TARGET_INSTRUCTION` asks for
#: three); extra entries under the same id are ignored.
_TARGET_VARIANTS = 3

def _format_targets(targets: dict[str, tuple[int, int]], texts: dict[str, str],
                    sources: dict[str, Bullet]) -> str:
    return "\n".join(
        f"<bullet id={bid!r} direction={'EXTEND' if low > len(texts[bid]) else 'SHORTEN'} "
        f"min={low} max={high}>\n  <current>{texts[bid]}</current>\n"
        f"  <source>{sources[bid].text}</source>\n"
        f"  <permitted_skills>{', '.join(sources[bid].tags)}</permitted_skills>\n</bullet>"
        for bid, (low, high) in targets.items()
    )

_VERB_INSTRUCTION = """\
Each bullet below opens with a verb another bullet already used, or with a near-synonym of \
one. Replace ONLY the opening verb with one that is not in its `avoid` list and does not \
mean the same thing as those. Keep the rest of the bullet word for word, including every \
number, unless the new verb makes the grammar wrong — then change as little as possible. \
Do not lengthen the bullet. Do not restate the claim in different words: this is a \
one-word substitution, not a rewrite.
"""

_RETRY_INSTRUCTION = """\
Each bullet below was rejected: it contains a term, figure, number-noun claim, or \
authorship escalation that does not match the source material. Listed `rejected_terms` \
are invented words or figures — rewrite without them, using only what its `source` and \
`permitted_skills` already state. Listed `rebound_claims` are numbers attached to the \
wrong noun (e.g. "40 hours" when the source said "40 engineers") — restore each number's \
original subject from the source; never drop a source number to evade the check. \
Listed `missing_numbers` are source figures the draft omitted — restore each figure \
and its original subject, using the source's number and lower-bound form. \
Listed `authorship_claims` escalate delegated work into personal authorship — restore the \
external party and the delegation verb from the source; do not claim you built what a \
vendor or agency built. Do not substitute a synonym or a variant for a rejected figure — \
write only a number and lower-bound form supported by the source. Do not borrow a metric \
from any other bullet. \
Keep the rest of the bullet's meaning.
"""

_RETRY_PROMPT_VERSION = 3

def _format_widows(
    ceilings: dict[str, int], texts: dict[str, str], sources: dict[str, Bullet]
) -> str:
    lines = []
    for bullet_id, ceiling in ceilings.items():
        text = texts[bullet_id]
        tags = ", ".join(sources[bullet_id].tags)
        lines.append(
            f"<bullet id={bullet_id!r} current_length={len(text)} max={ceiling}>\n"
            f"  <current>{text}</current>\n"
            f"  <permitted_skills>{tags}</permitted_skills>\n"
            f"</bullet>"
        )
    return "\n".join(lines)

def _format_verb_items(
    collisions: dict[str, list[str]], texts: dict[str, str], sources: dict[str, Bullet]
) -> str:
    """Format verb-colliding bullets, each carrying the openers it must not reuse."""
    lines = []
    for bullet_id, avoid in collisions.items():
        text = texts[bullet_id]
        tags = ", ".join(sources[bullet_id].tags)
        lines.append(
            f"<bullet id={bullet_id!r} max={len(text)} avoid={', '.join(avoid)!r}>\n"
            f"  <current>{text}</current>\n"
            f"  <permitted_skills>{tags}</permitted_skills>\n"
            f"</bullet>"
        )
    return "\n".join(lines)

def _split_offenders(offenders: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Separate terms, rebound claims, authorship claims, and missing source figures."""
    terms: list[str] = []
    rebounds: list[str] = []
    authorship: list[str] = []
    missing: list[str] = []
    for o in offenders:
        if o.startswith(bullet_checks._DROPPED_NUMBER_PREFIX):
            missing.append(o[len(bullet_checks._DROPPED_NUMBER_PREFIX):])
        elif o.startswith(bullet_checks._REBOUND_PREFIX):
            rebounds.append(o[len(bullet_checks._REBOUND_PREFIX) :])
        elif o.startswith(fabrication._AUTHORSHIP_PREFIX):
            authorship.append(o[len(fabrication._AUTHORSHIP_PREFIX) :])
        else:
            terms.append(o)
    return terms, rebounds, authorship, missing

def _format_offender_summary(offenders: list[str]) -> str:
    """Human-readable summary of mixed fabrication / rebound / authorship offenders."""
    terms, rebounds, authorship, missing = _split_offenders(offenders)
    parts: list[str] = []
    if terms:
        parts.append(", ".join(terms))
    if rebounds:
        parts.append("rebound " + ", ".join(rebounds))
    if authorship:
        parts.append("authorship " + ", ".join(authorship))
    if missing:
        parts.append("missing source numbers " + ", ".join(missing))
    return "; ".join(parts) if parts else "(unknown)"

def _format_fabrications(
    rejected: dict[str, tuple[str, list[str]]], sources: dict[str, Bullet]
) -> str:
    """Format rejected bullets, each carrying the terms that failed the guard.

    The master text ships alongside the rejected draft because the model's mistake is
    usually a *variant* of something the source does say ("130+" for "over 130"), and it
    cannot correct that without seeing how the source words it. Rebound and authorship
    claims get their own attributes so the model is told what to restore, not delete.
    """
    lines = []
    for bullet_id, (text, offenders) in rejected.items():
        tags = ", ".join(sources[bullet_id].tags)
        terms, rebounds, authorship, missing = _split_offenders(offenders)
        attrs = [f"id={bullet_id!r}"]
        if terms:
            attrs.append(f"rejected_terms={', '.join(terms)!r}")
        if rebounds:
            attrs.append(f"rebound_claims={', '.join(rebounds)!r}")
        if authorship:
            attrs.append(f"authorship_claims={', '.join(authorship)!r}")
        if missing:
            attrs.append(f"missing_numbers={', '.join(missing)!r}")
        lines.append(
            f"<bullet {' '.join(attrs)}>\n"
            f"  <rejected>{text}</rejected>\n"
            f"  <source>{sources[bullet_id].text}</source>\n"
            f"  <permitted_skills>{tags}</permitted_skills>\n"
            f"</bullet>"
        )
    return "\n".join(lines)

@telemetry.stage("rewrite", "factual_retry")
def _retry_fabrications(
    rejected: dict[str, tuple[str, list[str]]],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
    *,
    targets: dict[str, tuple[int, int]] | None = None,
    preserve_numbers: bool = False,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Re-request only the fabricating bullets. Returns (accepted, surviving offenders).

    One round trip, never more — same bound as `_polish`. Each returned bullet replaces
    its draft only if it passes the guard; length is left to the widow pass and the fit
    loop. An id the model omits, or a candidate that fabricates again, is reported (id ->
    offending terms) so the caller can fall back to that bullet's original, guard-clean
    text rather than emit the fabrication.
    """
    if not rejected:
        return {}, {}

    user = (
        f"<retry_prompt_version>{_RETRY_PROMPT_VERSION}</retry_prompt_version>\n"
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<keywords_to_mirror>\n{rewrite_prompts._format_keywords(requirements)}\n</keywords_to_mirror>\n\n"
        f"<bullets_to_retry>\n{_format_fabrications(rejected, sources)}\n"
        f"</bullets_to_retry>\n\n{_RETRY_INSTRUCTION}"
    )
    if targets:
        user += "\n\nRequired character windows:\n" + "\n".join(
            f"{bid}: min={low}, max={high}; preserve all source numbers."
            for bid, (low, high) in targets.items() if bid in rejected
        )

    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=rewrite_prompts._system(),
        messages=[{"role": "user", "content": user}],
        output_format=rewrite_prompts.RewriteResult,
        output_config={"effort": config.effort_for("rewrite")},
    )

    result = response.parsed_output
    if result is None:
        # Unparseable reply leaves every id unresolved — report all rather than pass.
        return {}, {bid: offenders for bid, (_text, offenders) in rejected.items()}

    by_reply = {item.id: item.text.strip() for item in result.bullets}
    accepted: dict[str, str] = {}
    survivors: dict[str, list[str]] = {}

    for bullet_id, (_draft, _offenders) in rejected.items():
        candidate = by_reply.get(bullet_id)
        if candidate is None:
            survivors[bullet_id] = _offenders
            continue
        source = sources[bullet_id]
        still = bullet_checks.guard_offenders(
            [source], candidate, preserve_numbers=preserve_numbers,
        )
        if still:
            survivors[bullet_id] = still
            continue
        accepted[bullet_id] = candidate

    return accepted, survivors

def _accept_verb_swap(
    original: str, candidate: str, source: Bullet, avoid: set[str]
) -> bool:
    """Whether a returned verb substitution is safe to apply.

    Non-regressive on every axis the pass could damage: the opener must actually have
    changed, must not be one of the openers already in use, the bullet must not occupy
    more lines than before, and it must not have become a widow. A model that reworded
    instead of substituting is also re-checked against the fabrication guard.

    Unlike widow repair, a guard failure here *discards* the candidate instead of raising.
    Widow repair earns its hard failure by compressing claims under length pressure;
    swapping one verb asks for no compression at all, so the honest response to a bad
    reply is to keep the original wording — failing a whole run over a cosmetic
    substitution would be the worse outcome.
    """
    new_verb = bullet_checks.opening_verb(candidate)
    if new_verb is None or new_verb == bullet_checks.opening_verb(original) or new_verb in avoid:
        return False
    if config.line_span(candidate) > config.line_span(original):
        return False
    if bullet_checks.widowed({"_": candidate}):
        return False
    floor = source.model_copy(update={"text": original, "tags": []})
    return (not fabrication.check_fabrication(source, candidate)
            and not fabrication.numbers_dropped([floor], candidate))

def _keep_opener(texts: dict[str, str], bid: str, candidate: str) -> str | None:
    """`candidate` for `bid` with an opener that repeats no more verbs than `texts[bid]`.

    A length repair is shown the master source, which often opens with the very verb the
    verb pass just replaced ("Built…" for the third time), and nothing else re-checks the
    opener. A candidate that adds a collision gets the current opener back when its own is
    a known resume verb, a one-word swap that keeps the grammar. One that cannot be
    swapped that way ("Using Python, built…") returns None and is discarded.
    """
    if len(bullet_checks.verb_collisions({**texts, bid: candidate})) <= len(
        bullet_checks.verb_collisions(texts)
    ):
        return candidate
    new = bullet_checks.opening_verb(candidate)
    current = texts[bid].split(maxsplit=1)
    _, _, rest = candidate.strip().partition(" ")
    if new is None or config.verb_family(new) is None or not current or not rest:
        return None
    return f"{current[0]} {rest}"

def _verb_instruction() -> str:
    if industries.active() is None:
        return _VERB_INSTRUCTION
    return (
        "Prefer a varied opening verb only when an equally accurate alternative exists. "
        "The avoid list is a preference. Keep the original bullet unchanged when a "
        "substitution would change its meaning, responsibility, or causal claim. "
        "Otherwise change only the opening verb and minimal necessary grammar; "
        "preserve every number and do not lengthen the bullet."
    )

@telemetry.stage("rewrite", "polish")
def _polish(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
    *,
    repair_widows: bool = True,
    repair_verbs: bool = True,
    ceilings: dict[str, int] | None = None,
    targets: dict[str, tuple[int, int]] | None = None,
    line_ceilings: dict[str, int] | None = None,
    revoice_only: set[str] | None = None,
    number_floor: dict[str, str] | None = None,
) -> tuple[dict[str, str], int, int, dict[str, list[str]]]:
    """Re-request only the defective bullets.

    `ceilings` replaces the widow detection with a caller-chosen `{id: character ceiling}`
    (the fit loop's targeted pull-back of bullets that are not quite widows). Each such
    bullet is accepted only if it is shorter *and* spans fewer lines — a cut that stays on
    the same line count frees nothing, which is the whole point of the call.

    `targets` gives measured widow repairs a minimum and maximum character window. The
    model returns several versions of each (`_TARGET_INSTRUCTION`) and code keeps the
    longest clean one inside the window — the model only has to vary length, not count
    characters. `line_ceilings` optionally gives a target a second acceptable outcome: a
    version at or under that length saves the bullet's whole last line, which cures the
    widow just as well as filling it.

    `revoice_only` limits verb repair to those ids while `texts` still carries every
    rendered bullet, so the fit loop's top-up can re-voice only the bullets it just added
    against openers the page already uses, without touching (and re-wrapping) the rest.
    The guard and numeric-preservation check apply to both shortening and extension.
    `number_floor` (`{id: text}`) checks a target's numbers against that text instead of
    its master source — for capping an over-long rewrite, which may already have dropped
    a minor figure the master states; the guard itself still runs against the source.

    Returns ``(texts, widows fixed, verbs changed, widow repairs rejected)`` where the
    last mapping is bullet id to offending terms for shorten candidates discarded by the
    fabrication guard.

    One polish round trip is shared between the requested defects. Guard-rejected
    length candidates get one targeted fabrication retry; anything still defective
    afterwards keeps the original text and is reported.

    A bullet that is both widowed and verb-colliding is sent as a widow only. Two entries
    under one id would make the reply ambiguous, and a wasted line costs real page space
    while a repeated verb only reads badly — so length wins and the collision is reported.

    The pass is non-regressive by construction. Each returned bullet replaces its original
    only if it strictly improves that bullet's own defect without introducing another; a
    reply that is longer, still defective, unrecognised, or missing leaves the original
    text exactly as it was. It can improve a run or do nothing, but it cannot make one
    worse.

    A fabricating widow-repair candidate is discarded like a bad verb swap: the pre-polish
    text is already guard-clean, so the document stays correct and the surviving widow is
    reported upstream rather than aborting the run. Shortening under pressure is precisely
    when a model compresses a claim into something the source never said — the guard still
    binds — but a cosmetic pass must not kill an otherwise-good run.
    """
    pullback = ceilings is not None
    targeted = targets is not None
    targets = targets or {}
    if ceilings is None:
        ceilings = bullet_checks.widowed(texts) if repair_widows and not targeted else {}
    collisions = (
        {
            bid: avoid for bid, avoid in bullet_checks.verb_collisions(texts).items()
            if bid not in ceilings and bid not in targets
            and (revoice_only is None or bid in revoice_only)
        }
        if repair_verbs
        else {}
    )
    if not ceilings and not collisions and not targets:
        return texts, 0, 0, {}

    sections = [
        f"<repair_prompt_version>{_REPAIR_PROMPT_VERSION}</repair_prompt_version>",
        f"<role>{requirements.title} ({requirements.seniority})</role>",
        f"<keywords_to_mirror>\n{rewrite_prompts._format_keywords(requirements)}\n</keywords_to_mirror>",
    ]
    if ceilings:
        sections.append(
            f"<bullets_to_shorten>\n{_format_widows(ceilings, texts, sources)}\n"
            f"</bullets_to_shorten>\n\n{_REPAIR_INSTRUCTION}"
        )
    if targets:
        sections.append(
            f"<bullets_to_fit>\n{_format_targets(targets, texts, sources)}\n"
            f"</bullets_to_fit>\n\n{_TARGET_INSTRUCTION}"
        )
    if collisions:
        sections.append(
            f"<bullets_to_revoice>\n{_format_verb_items(collisions, texts, sources)}\n"
            f"</bullets_to_revoice>\n\n{_verb_instruction()}"
        )
    user = "\n\n".join(sections)

    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=rewrite_prompts._system(),
        messages=[{"role": "user", "content": user}],
        output_format=rewrite_prompts.RewriteResult,
        output_config={"effort": config.effort_for("rewrite")},
    )

    result = response.parsed_output
    if result is None:
        # Not fatal: the first draft is still valid output, just wasteful. Report it as a
        # surviving widow rather than failing a run over a cosmetic pass.
        return texts, 0, 0, {}

    repaired = dict(texts)
    rejected: dict[str, list[str]] = {}
    retry_candidates: dict[str, tuple[str, list[str]]] = {}
    tightened = 0
    revoiced = 0
    # An accepted swap claims its new opener, so two colliding bullets cannot both be
    # handed the same replacement verb.
    claimed: set[str] = set()
    line_ceilings = line_ceilings or {}
    number_floor = number_floor or {}

    def keeps_numbers(bid: str, candidate: str) -> bool:
        floor = number_floor.get(bid)
        base = (
            sources[bid] if floor is None
            else sources[bid].model_copy(update={"text": floor, "tags": []})
        )
        return not fabrication.numbers_dropped([base], candidate)

    def fits_target(bid: str, candidate: str) -> bool:
        low, high = targets[bid]
        return bool(candidate) and (
            low <= len(candidate) <= high or len(candidate) <= line_ceilings.get(bid, 0)
        )

    # Fit targets come back as several versions per id; judge them together.
    variants: dict[str, list[str]] = {}
    for item in result.bullets:
        if item.id in targets and item.id in sources:
            bucket = variants.setdefault(item.id, [])
            if len(bucket) < _TARGET_VARIANTS:
                bucket.append(item.text.strip())
    for bid, candidates in variants.items():
        source = sources[bid]
        clean: list[str] = []
        fabricated: tuple[str, list[str]] | None = None
        for raw in candidates:
            candidate = _keep_opener(repaired, bid, raw)
            if candidate is None:
                continue
            offenders = bullet_checks.guard_offenders([source], candidate)
            if offenders:
                fabricated = fabricated or (candidate, offenders)
                continue
            if fits_target(bid, candidate) and keeps_numbers(bid, candidate):
                clean.append(candidate)
        if clean:
            # Prefer the window over the line-saving fallback, then the longest version:
            # it keeps the most detail and fills the last line furthest.
            low, high = targets[bid]
            repaired[bid] = max(clean, key=lambda c: (low <= len(c) <= high, len(c)))
            tightened += 1
        elif fabricated is not None:
            rejected[bid] = fabricated[1]
            retry_candidates[bid] = fabricated

    for item in result.bullets:
        source = sources.get(item.id)
        if source is None or item.id in targets:
            continue
        candidate = item.text.strip()

        if item.id in ceilings:
            candidate = _keep_opener(repaired, item.id, candidate)
            if candidate is None:
                continue
            offenders = bullet_checks.guard_offenders([source], candidate)
            if offenders:
                rejected[item.id] = offenders
                retry_candidates[item.id] = (candidate, offenders)
                continue
            original = texts[item.id]
            if pullback:
                # The ceiling is one line below where the text ends — measured from the
                # PDF when the fit loop had one — so landing under it frees that line.
                improved = len(candidate) < len(original) and len(candidate) <= ceilings[item.id]
            else:
                improved = len(candidate) < len(original) and not bullet_checks.widowed(
                    {item.id: candidate}
                )
            if improved:
                repaired[item.id] = candidate
                tightened += 1
        elif item.id in collisions:
            avoid = set(collisions[item.id]) | claimed
            if _accept_verb_swap(texts[item.id], candidate, source, avoid):
                repaired[item.id] = candidate
                revoiced += 1
                verb = bullet_checks.opening_verb(candidate)
                if verb is not None:
                    claimed.add(verb)

    if retry_candidates:
        windows = {bid: (0, high) for bid, high in ceilings.items()}
        windows.update(targets)
        accepted, survivors = _retry_fabrications(
            retry_candidates, sources, requirements, targets=windows
        )
        rejected = survivors
        for bid, raw in accepted.items():
            candidate = _keep_opener(repaired, bid, raw)
            if candidate is None or (
                candidate != raw and bullet_checks.guard_offenders([sources[bid]], candidate)
            ):
                continue
            if bid in number_floor:
                if not keeps_numbers(bid, candidate):
                    continue
            elif fabrication.numbers_dropped([sources[bid]], candidate):
                continue
            if bid in targets:
                valid = fits_target(bid, candidate)
            else:
                valid = len(candidate) < len(texts[bid]) and (
                    len(candidate) <= ceilings[bid]
                    if pullback else not bullet_checks.widowed({bid: candidate})
                )
            if valid:
                repaired[bid] = candidate
                tightened += 1
    return repaired, tightened, revoiced, rejected
