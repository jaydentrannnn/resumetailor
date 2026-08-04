"""Vocabulary-library proposals: LLM-drafted tag aliases and verb-family additions.

A fifth-ish LLM stage, though it does not add a new *purpose* — it reuses `"extract"`
(config.PURPOSES), the same low-effort, free-under-`hybrid` stage that already reads JD
text, so `MODEL_PROFILES`/`DEFAULT_EFFORT`/`credential_gaps` need no changes for it.

Two independent halves, both in one call: which unmatched JD spellings are genuine
synonyms of a tag the candidate already has (`AliasProposal`), and which resume-opening
verbs the model can place into an *existing* verb family (`VerbProposal`). The model
selects and classifies; every hard constraint — an alias target must already be a known
tag, a verb family must already exist, nothing already effective or already declined is
re-proposed — is enforced afterward in code (`filter_proposals`), the same split
`facets.py` uses for renames.

Never fatal to a caller that cannot afford it: `propose_vocabulary` raises normally
(`LLMError`, `RuntimeError`) like every other LLM stage, and it is the caller's job to
decide whether that should fail loudly (an explicit "Generate suggestions" click) or
degrade silently (the opportunistic post-run hook in `web/jobs.py`).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from . import config, events, libraries, llm, report, rewrite
from .events import ProgressCallback

if TYPE_CHECKING:
    from .data import MasterResume
    from .jd import JobRequirements


class AliasProposal(BaseModel):
    """One drafted tag-alias mapping."""

    alias: str
    #: MUST be one of the `known_tags` supplied in the prompt — enforced again in
    #: `filter_proposals`, since a model is not a validator.
    canonical: str
    rationale: str = ""


class VerbProposal(BaseModel):
    """One drafted verb -> family assignment."""

    verb: str
    #: An existing family id, or the literal string "none".
    family: str
    rationale: str = ""


class VocabularyProposal(BaseModel):
    """Everything the model drafted in one call."""

    tag_aliases: list[AliasProposal] = Field(default_factory=list)
    verb_families: list[VerbProposal] = Field(default_factory=list)


_SYSTEM = """\
You help expand a candidate's resume vocabulary so it matches a wider range of job \
postings and industries.

You are given two independent tasks.

TAG ALIASES
For each entry in <unmatched_spellings>, decide whether it is a synonym of one of the \
candidate's own <known_tags> — the same skill or credential, spelled or phrased \
differently. If it genuinely is, propose it as an alias mapping to that known tag. If it \
is not, or you are unsure, omit it entirely rather than forcing a low-confidence match.
- `canonical` MUST be copied verbatim from <known_tags>. Never invent a target that is \
not already in that list, and never propose a mapping where the alias is itself already \
a known tag — that describes two different things, not a spelling variant of one.
- `alias` is the unmatched spelling itself, unchanged.
- `rationale` is at most one short sentence.

VERB FAMILIES
Resume bullets open with a verb, and grouping near-synonymous openers (e.g. \
"administered", "managed", "oversaw") into a family is what lets repeated use across many \
bullets be caught. You are given the existing families and their members in \
<verb_families>, and <unclassified_verbs> — opening verbs actually used in this resume \
that belong to none of them.
For each unclassified verb, assign it to the ONE existing family whose members make the \
same claim, or return `family: "none"` if it does not resemble any of them. NEVER invent \
a new family name — only the family ids already listed in <verb_families> are valid.
- `rationale` is at most one short sentence.

Return one entry per input item you have an opinion on. Omitting an item is always \
better than a forced, low-confidence guess.
"""

#: Bumped whenever `_SYSTEM` or the user-message shape changes, folded into the cache
#: key — the `jd._PROMPT_VERSION` precedent.
_PROMPT_VERSION = 1

#: Hard cap on accepted proposals from one call, so a verbose model draft cannot flood
#: the approval queue.
_MAX_PROPOSALS = 20

#: `report.diagnose_gaps` encodes the matched tag in this exact evidence string for a
#: "near_miss" gap (`report.py`) — extracted rather than re-derived so the two functions
#: cannot silently disagree about what counts as a near miss.
_NEAR_MISS_TAG_RE = re.compile(r'bullet tag: "(.+)"')


def near_miss_alias_candidates(
    requirements: "JobRequirements", master: "MasterResume"
) -> list[tuple[str, str]]:
    """(JD phrase, existing bullet tag) pairs — the exact spelling mismatches a tag
    alias exists to fix, drawn from `report.diagnose_gaps`'s "near_miss" gaps."""
    pairs: list[tuple[str, str]] = []
    for gap in report.diagnose_gaps(requirements, master):
        if gap.reason != "near_miss" or not gap.evidence:
            continue
        match = _NEAR_MISS_TAG_RE.search(gap.evidence[0])
        if match:
            pairs.append((gap.phrase, match.group(1)))
    return pairs


def unclassified_opening_verbs(master: "MasterResume") -> list[str]:
    """Opening verbs this resume's bullets actually use that no verb family claims.

    `config.VERB_FAMILIES`'s own docstring names an unlisted opener a silently missed
    collision catch — this is exactly that gap, fed to the model instead of staying
    invisible.
    """
    verbs: set[str] = set()
    for bullet in master.all_bullets():
        verb = rewrite.opening_verb(bullet.text)
        if verb and config.verb_family(verb) is None:
            verbs.add(verb)
    return sorted(verbs)


def _cache_path(
    known_tags: list[str],
    unmatched: list[tuple[str, str]],
    unknown_verbs: list[str],
    families: dict[str, tuple[str, ...]],
    jd_text: str,
) -> Path:
    """Cache key covering every input the draft depends on.

    `libraries.effective_fingerprint()` is part of the key because a proposal drafted
    against one workspace's effective table can be wrong for another's — a family named
    in `families` here might not even exist once the table changes.
    """
    payload = "\n".join(
        [
            str(_PROMPT_VERSION),
            config.fingerprint("extract"),
            libraries.effective_fingerprint(),
            *sorted(t.strip().lower() for t in known_tags),
            *sorted(f"{phrase}|{tag}" for phrase, tag in unmatched),
            *sorted(v.strip().lower() for v in unknown_verbs),
            *sorted(f"{family}={','.join(sorted(verbs))}" for family, verbs in families.items()),
            jd_text.strip(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.vocab.json"


def propose_vocabulary(
    *,
    known_tags: list[str],
    unmatched: list[tuple[str, str]],
    unknown_verbs: list[str],
    families: dict[str, tuple[str, ...]],
    jd_text: str = "",
    use_cache: bool = True,
    on_event: ProgressCallback | None = None,
) -> VocabularyProposal:
    """Ask the model to draft tag-alias and verb-family additions.

    Raises normally (`LLMError`, `RuntimeError`) — a caller that must not fail on this
    wraps it itself; see `web/app.py`'s `generate_library_proposals` route and
    `web/jobs.py`'s post-run hook.
    """
    if not unmatched and not unknown_verbs:
        return VocabularyProposal()

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(known_tags, unmatched, unknown_verbs, families, jd_text)

    if use_cache and cache_path.exists():
        events.emit(on_event, "propose", "Reusing cached vocabulary proposal", cached=True)
        return VocabularyProposal.model_validate_json(cache_path.read_text(encoding="utf-8"))

    events.emit(
        on_event,
        "propose",
        "Drafting vocabulary suggestions",
        cached=False,
        unmatched=len(unmatched),
        unknown_verbs=len(unknown_verbs),
        model=config.model_for("extract"),
    )

    unmatched_block = "\n".join(f'  - "{phrase}"' for phrase, _tag in unmatched) or "  (none)"
    verbs_block = "\n".join(f"  - {v}" for v in unknown_verbs) or "  (none)"
    families_block = (
        "\n".join(
            f"  - {family}: {', '.join(sorted(verbs))}"
            for family, verbs in sorted(families.items())
        )
        or "  (none)"
    )
    known_tags_block = "\n".join(f"  - {t}" for t in sorted(known_tags)) or "  (none)"

    user = (
        f"<known_tags>\n{known_tags_block}\n</known_tags>\n\n"
        f"<unmatched_spellings>\n{unmatched_block}\n</unmatched_spellings>\n\n"
        f"<verb_families>\n{families_block}\n</verb_families>\n\n"
        f"<unclassified_verbs>\n{verbs_block}\n</unclassified_verbs>"
    )
    if jd_text.strip():
        user += f"\n\n<job_description>\n{jd_text.strip()}\n</job_description>"

    client = llm.client_for("extract")
    response = client.messages.parse(
        model=config.model_for("extract"),
        max_tokens=config.max_tokens_for("extract"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=VocabularyProposal,
        output_config={"effort": config.effort_for("extract")},
    )
    raw = response.parsed_output
    if raw is None:
        raise RuntimeError(
            f"Model did not return a parseable vocabulary proposal "
            f"(stop_reason={response.stop_reason!r})."
        )
    cache_path.write_text(raw.model_dump_json(indent=2), encoding="utf-8")
    return raw


def _proposal_id(kind: str, key: str, value: str) -> str:
    """Stable id from (kind, key, value), so the same proposal from two separate runs
    dedupes into one queue entry instead of stacking."""
    digest = hashlib.sha256(f"{kind}|{key}|{value}".encode("utf-8")).hexdigest()[:6]
    return f"p-{digest}"


def filter_proposals(
    raw: VocabularyProposal,
    *,
    known_tags: list[str],
    effective: libraries.EffectiveLibrary,
    rejected: list[libraries.RejectedEntry],
    source: str = "manual",
) -> list[libraries.LibraryProposal]:
    """Deterministic acceptance rules a drafted item must clear before it becomes a
    pending proposal. Drops: a target not in `known_tags`; an alias that is itself
    already a known tag or is already effective; anything previously rejected; a verb
    family of "none" or one not in `effective.verb_families`; a verb already classified;
    a non-alphabetic verb. Caps at `_MAX_PROPOSALS`.
    """
    known_set = {t.strip().lower() for t in known_tags}
    rejected_aliases = {(r.alias or "").strip().lower() for r in rejected if r.kind == "tag_alias"}
    rejected_verbs = {(r.verb or "").strip().lower() for r in rejected if r.kind == "verb_family"}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out: list[libraries.LibraryProposal] = []

    for item in raw.tag_aliases:
        if len(out) >= _MAX_PROPOSALS:
            return out
        alias = item.alias.strip().lower()
        canonical = item.canonical.strip().lower()
        if not alias or not canonical or alias == canonical:
            continue
        if canonical not in known_set:
            continue
        if alias in known_set:
            continue
        if alias in effective.tag_aliases:
            continue
        if alias in rejected_aliases:
            continue
        out.append(
            libraries.LibraryProposal(
                id=_proposal_id("tag_alias", alias, canonical),
                kind="tag_alias",
                alias=alias,
                canonical=canonical,
                rationale=item.rationale[:200],
                source=source,
                created_at=now,
            )
        )

    for item in raw.verb_families:
        if len(out) >= _MAX_PROPOSALS:
            return out
        verb = item.verb.strip().lower()
        family = item.family.strip().lower()
        if not verb or not verb.isalpha():
            continue
        if family == "none" or family not in effective.verb_families:
            continue
        if verb in effective.verb_index:
            continue
        if verb in rejected_verbs:
            continue
        out.append(
            libraries.LibraryProposal(
                id=_proposal_id("verb_family", verb, family),
                kind="verb_family",
                verb=verb,
                family=family,
                rationale=item.rationale[:200],
                source=source,
                created_at=now,
            )
        )

    return out
