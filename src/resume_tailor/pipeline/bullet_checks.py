"""Deterministic checks on rewritten bullets: re-bound numbers, delegated authorship,
redundancy, widowed last lines, repeated opening verbs, and over-used posting phrases."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .. import config
from ..content import bullet_tags
from ..content.data import Bullet
from . import fabrication

#: Max intervening tokens between a digit token and the noun it binds to. Three
#: covers "40 remote engineers" / "8 years of experience" without stretching to
#: an unrelated later noun.
_NOUN_BIND_WINDOW = 3

#: Modifiers a rewrite inserts before a counted noun ("18 core topics"). Each still binds,
#: but none uses up a window slot, so the noun after it stays in reach. Closed on purpose:
#: a broader rule would let any adjective push the real subject out of comparison.
_FREE_MODIFIERS = frozenset({
    "core", "key", "fundamental", "major", "distinct", "different", "separate", "unique",
    "total", "additional", "various", "multiple",
})

#: Verbs that only introduce a percentage ("reaching 85%"); skipped directly before it.
#: Closed to the forms seen in rejected drafts, not a suffix rule: "staffing" and
#: "testing" are subjects.
_OUTCOME_VERBS = frozenset({
    "reach", "reaches", "reaching", "reached", "achieve", "achieves", "achieving",
    "achieved", "attain", "attains", "attaining", "attained", "hit", "hits", "hitting",
})

#: Prefix marking a rebound claim inside the flat offender list `guard_offenders`
#: returns. `_format_fabrications` splits on it so the retry prompt can name a
#: rebinding distinctly from a fabricated term.
_REBOUND_PREFIX = "rebound:"
_DROPPED_NUMBER_PREFIX = "missing_number:"

def _noun_key(term: str) -> str | None:
    """`term` reduced to the key two number-noun bindings are compared on.

    `_significant` first (lowercase, de-pluralise), then `config.canonical_tag`, so
    two spellings of the same subject compare equal whenever the active vocabulary
    packs say they are the same thing ("undergraduates" against a source's
    "students", given that alias). Read through `config.` at call time because
    `libraries.apply_to_config()` rebinds `TAG_ALIASES` to a new dict per workspace.

    Returns None for a token repeating which asserts nothing (see `_significant`).
    A short all-caps acronym ("ARR", "UI", "APIs") still binds: `_significant` drops
    it for being short, but in "increasing ARR by 12%" it is the subject the figure
    measures, and without it the figure bound only the verb, so any rephrased verb
    read as a rebinding.
    """
    sig = fabrication._significant(term)
    if sig is None and _ACRONYM.fullmatch(term):
        sig = term.lower().removesuffix("s")
    return None if sig is None else config.canonical_tag(sig)

_ACRONYM = re.compile(r"[A-Z]{2,}s?")
#: A bare version number ("15", "3.11") — the shape `_is_version` checks after a name.
_VERSION = re.compile(r"\d+(?:\.\d+)*")

def _is_version(tokens: list[str], matches: list[re.Match[str]], text: str, i: int) -> bool:
    """Whether `tokens[i]` is a version of the name before it ("Next.js 15", "Python 3.11").

    The name must sit mid-bullet (the first token is the opening verb, so "Led 40
    engineers" is a count), be separated from the number by whitespace only, and carry
    a capital or an internal dot. A version is not a quantity of anything, so binding it
    to the next words flagged "Next.js 15 frontend" as a rebinding of "Next.js 15 UI".
    """
    if i < 2 or not _VERSION.fullmatch(tokens[i]) or text[matches[i].end():].startswith("%"):
        return False
    name = tokens[i - 1]
    if text[matches[i - 1].end():matches[i].start()].strip():
        return False
    return "." in name or any(c.isupper() for c in name)

def _number_noun_bindings(text: str) -> dict[str, set[str]]:
    """Map each digit-bearing token (lowercased) to significant nouns near it.

    Collects every letter-bearing significant token within `_NOUN_BIND_WINDOW`
    following words (stopping at the next number), normalised through `_noun_key`.
    Taking the whole window — not only the nearest token — keeps "40 remote
    engineers" bound to both `remote` and `engineer`, so a faithful restatement
    that inserts an adjective still shares the source noun.

    A slash compound also binds its letter parts: "130 students/week" binds `students`
    and `week` as well as the whole token, so "130 students" restates it rather than
    rebinding the number. Only the source side splits (this function is only called on
    sources): a rewrite's own compound must still match whole, so "130 students/semester"
    against that source is flagged.
    """
    out: dict[str, set[str]] = {}
    for number, pairs in _number_noun_surface(text).items():
        keys = out.setdefault(number, set())
        for surface, key in pairs:
            keys.add(key)
            if "/" in surface:
                for part in surface.split("/"):
                    part_key = _noun_key(part) if fabrication._HAS_LETTER.search(part) else None
                    if part_key is not None:
                        keys.add(part_key)
    return out

def _number_noun_surface(text: str) -> dict[str, list[tuple[str, str]]]:
    """Like `_number_noun_bindings` but keeps (surface, key) pairs in window order.

    Used when reporting a rebound claim so the retry prompt shows the rewrite's own
    wording ("40 hours") rather than the normalised key, and so the nearest bound
    noun — pair index 0 — can be named on its own.
    """
    text = fabrication.split_figure_compounds(text)
    matches = list(fabrication._TOKEN.finditer(text))
    tokens = [m.group(0) for m in matches]
    out: dict[str, list[tuple[str, str]]] = {}
    for i, term in enumerate(tokens):
        if not fabrication._HAS_DIGIT.search(term):
            continue
        # "EC2", "S3", "GPT-4" name a thing that happens to carry a digit; a version
        # after a name ("Next.js 15") counts nothing. The term guard still checks both.
        if not term[0].isdigit() or _is_version(tokens, matches, text, i):
            continue
        key = term.lower()
        if fabrication._NUMBER_PLUS.fullmatch(key):
            key = key[:-1]
        pairs = out.setdefault(key, [])
        forward = range(i + 1, len(tokens))
        if text[matches[i].end():].startswith("%"):
            # A percentage measures the outcome named before it ("increasing ARR by
            # 12%") as often as the thing after it ("12% of tickets"); a rewrite moves
            # it between the two freely, so it binds both ways. The "by" in "time by
            # 50-66%" is skipped so the window reaches the outcome itself, and so is an
            # outcome verb ("reaching 91.3%" -> "achieving 91.3%"), which names no subject.
            start = i - 2 if i > 0 and tokens[i - 1].lower() == "by" else i - 1
            while start >= 0 and tokens[start].lower() in _OUTCOME_VERBS:
                start -= 1
            windows = [range(start, -1, -1), forward]
        else:
            windows = [forward]
        for indices in windows:
            taken = 0
            for j in indices:
                candidate = tokens[j]
                if fabrication._HAS_DIGIT.search(candidate) or taken == _NOUN_BIND_WINDOW:
                    break
                sig = _noun_key(candidate)
                if sig is not None:
                    pairs.append((candidate.lower(), sig))
                if candidate.lower() not in _FREE_MODIFIERS:
                    taken += 1
    return out

def rebound_numbers(sources: Sequence[Bullet], rewritten: str) -> list[str]:
    """Return "<number> <noun>" claims the rewrite makes that no source makes.

    The mirror of `numbers_dropped`: that catches a metric silently dropped, this
    catches one silently re-attached to a different noun. Both are fabrications the
    token-membership guard cannot see, because every token involved is permitted.

    Deliberately conservative: flag only when the rewrite binds `N` to noun `X`, at
    least one source binds the same `N` to some noun, and no source binding of `N`
    uses an equivalent noun (equivalence is `_noun_key`, so a vocabulary-pack alias
    makes two spellings of one subject match). When the source mentions `N` with no
    noun binding at all, do not flag — the guard cannot judge, and a false positive
    here blocks a truthful rewrite, which is the worse failure.

    One offender per rebound number, naming the nearest bound noun. The window holds
    the adjectives around that noun too, and listing them all made a single
    rebinding read as several unrelated fabrications ("130 students", "130
    clarifying", "130 python") in the error and the retry prompt. Nothing about what
    is *rejected* changes — only how it is named.
    """
    source_bindings: dict[str, set[str]] = {}
    for source in sources:
        for text in (source.text, " ".join(source.tags)):
            for number, nouns in _number_noun_bindings(text).items():
                source_bindings.setdefault(number, set()).update(nouns)

    offenders: list[str] = []
    seen: set[str] = set()
    for number, pairs in _number_noun_surface(rewritten).items():
        source_nouns = source_bindings.get(number)
        if source_nouns is None:
            continue
        if not source_nouns:
            continue
        # If any rewrite noun for this number matches a source noun, the number
        # is still attached to a licensed subject — do not flag sibling adjectives.
        if any(sig in source_nouns for _surface, sig in pairs):
            continue
        if not pairs:
            continue
        surface, _sig = pairs[0]
        claim = f"{number} {surface}"
        if claim in seen:
            continue
        seen.add(claim)
        offenders.append(claim)
    return offenders

def _lower_tokens(text: str) -> list[str]:
    """Letter-bearing tokens lowercased, for closed-list authorship matching."""
    return [
        m.group(0).lower()
        for m in fabrication._TOKEN.finditer(text)
        if fabrication._HAS_LETTER.search(m.group(0))
    ]

def _contains_phrase(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    """Whether `phrase` appears as contiguous tokens in `tokens`."""
    n = len(phrase)
    if n == 0 or n > len(tokens):
        return False
    for i in range(len(tokens) - n + 1):
        if tuple(tokens[i : i + n]) == phrase:
            return True
    return False

def _has_external_party(tokens: list[str]) -> bool:
    """Whether any external-party phrase appears in `tokens`."""
    return any(_contains_phrase(tokens, phrase) for phrase in fabrication._EXTERNAL_PARTY_PHRASES)

def _has_any_verb(tokens: list[str], verbs: frozenset[str]) -> bool:
    """Whether any token is in `verbs` (already lowercased)."""
    return any(t in verbs for t in tokens)

def delegated_authorship(sources: Sequence[Bullet], rewritten: str) -> list[str]:
    """Return direct-authorship claims whose source attributed execution elsewhere.

    Whole-bullet evaluation (no sentence splitter): a source that both delegates and
    asserts direct authorship ("Managed a vendor and wrote the ingestion layer")
    contains a direct-authorship verb, so it is not a delegated source and never
    fires. "Led a team that built X" never fires either — an internal team is not
    on the external-party list.

    Fires only when all of: the source carries a delegation verb *and* an
    external-party noun *and* no direct-authorship verb of its own; the rewrite
    asserts direct authorship; the rewrite has dropped every external-party noun;
    and the two share at least two significant tokens.
    """
    rewrite_tokens = _lower_tokens(rewritten)
    if not _has_any_verb(rewrite_tokens, fabrication._DIRECT_AUTHORSHIP_VERBS):
        return []
    if _has_external_party(rewrite_tokens):
        # Still attributes the work externally — not an escalation.
        return []

    rewrite_sig = {s for t in rewrite_tokens if (s := fabrication._significant(t)) is not None}
    offenders: list[str] = []
    seen: set[str] = set()

    for source in sources:
        source_tokens = _lower_tokens(source.text)
        if not _has_any_verb(source_tokens, fabrication._DELEGATION_VERBS):
            continue
        if not _has_external_party(source_tokens):
            continue
        if _has_any_verb(source_tokens, fabrication._DIRECT_AUTHORSHIP_VERBS):
            # Source already claims direct authorship alongside delegation.
            continue
        source_sig = {s for t in source_tokens if (s := fabrication._significant(t)) is not None}
        shared = rewrite_sig & source_sig
        if len(shared) < 2:
            continue
        # Name the escalation by the rewrite's direct-authorship verb that fired.
        verb = next(t for t in rewrite_tokens if t in fabrication._DIRECT_AUTHORSHIP_VERBS)
        claim = f"{verb} (delegated in source)"
        if claim in seen:
            continue
        seen.add(claim)
        offenders.append(claim)
    return offenders

def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def licensed_synonyms(sources: Sequence[Bullet], rewritten: str) -> set[str]:
    """Squashed spellings (whole and per word) of skills in `rewritten` that the sources
    state under another name, in the safe direction only.

    The rewrite may use a skill's canonical (general) name or the source's own spelling
    — "Postgres" -> "PostgreSQL", "VLOOKUP" -> "Excel" — or spell out a source acronym
    ("RAG" -> "retrieval-augmented generation"); never a narrower alias ("Excel" ->
    "VLOOKUP"), since dictionary aliases are built for matching, not as true synonyms.
    """
    backed = [hit for b in sources for hit in bullet_tags.detect(b.text)]
    backed += [(config.canonical_tag(t), t) for b in sources for t in b.tags if t.strip()]
    licensed: set[str] = set()
    for canonical, surface in bullet_tags.detect(rewritten):
        words = re.findall(r"[A-Za-z0-9]+", surface)
        spelled = "".join(w[0] for w in words).lower()
        for source_canonical, source_surface in backed:
            if source_canonical != canonical:
                continue
            if (_squash(surface) in (_squash(canonical), _squash(source_surface))
                    or (len(words) > 1 and spelled == _squash(source_surface))):
                # The guard names a multi-word skill one word at a time.
                licensed.update(_squash(part) for part in (surface, *surface.split()))
                break
    return licensed


def guard_offenders(
    sources: Sequence[Bullet], rewritten: str, *, preserve_numbers: bool = False,
) -> list[str]:
    """Every rewrite-path guard violation in one call.

    Fabricated terms, rebound numbers, and escalated authorship. One function so
    the four rewrite call sites cannot drift apart on which checks they run.

    Rebound and authorship claims are prefixed so the retry formatter can name
    them distinctly. Cover-letter and expand callers keep using
    `check_fabrication` / `_check_fabrication` unchanged.

    A term the guard rejects only because the source spells the same skill differently
    ("PostgreSQL" for "Postgres") is excused when the dictionary maps it in the safe
    direction (`licensed_synonyms`); a narrower alias still fails.
    """
    offenders = list(fabrication._check_fabrication(sources, rewritten))
    if offenders:
        synonyms = licensed_synonyms(sources, rewritten)
        offenders = [o for o in offenders if _squash(o) not in synonyms]
    for claim in rebound_numbers(sources, rewritten):
        offenders.append(f"{_REBOUND_PREFIX}{claim}")
    for claim in delegated_authorship(sources, rewritten):
        offenders.append(f"{fabrication._AUTHORSHIP_PREFIX}{claim}")
    if preserve_numbers:
        # Numeric tags license wording, but are not figures the source actually stated.
        text_sources = [b.model_copy(update={"tags": []}) for b in sources]
        offenders.extend(_DROPPED_NUMBER_PREFIX + n
                         for n in fabrication.numbers_dropped(text_sources, rewritten))
    return offenders

def redundancy_offenders(text: str) -> list[str]:
    """Terms `text` states more than once, in first-seen order.

    Merging is the one stage that can produce this: `merge.propose` ranks candidates by
    affinity, so the pair it offers first is the *most similar* one in the entry, and the
    laziest way to combine two similar bullets is to concatenate them — restating the
    shared tool, the shared metric, or the action verb on both sides of an "and".

    Two signals, both computed on the merged text alone (no source needed):
      - any significant word appearing twice
      - a later verb from the *same family* as the opener, which is how "Designed X and
        engineered Y" reads as two bullets wearing one bullet's clothes

    Only the same family counts. A second verb from a different family is how a good
    bullet states an outcome ("Built a service that reduced latency"), and rejecting that
    would reject nearly every legitimate merge.

    An empty result means the text says each thing once. Callers treat a non-empty result
    as grounds to reject a merge candidate, never to fail a run.
    """
    seen: set[str] = set()
    offenders: list[str] = []
    opening_family: str | None = None
    first = True

    for match in fabrication._TOKEN.finditer(text):
        term = match.group(0)
        family = config.verb_family(term)
        if first:
            opening_family = family
            first = False
        elif family is not None and family == opening_family:
            offenders.append(term)

        key = fabrication._significant(term)
        if key is None:
            continue
        if key in seen:
            offenders.append(term)
        seen.add(key)

    return list(dict.fromkeys(offenders))

# --------------------------------------------------------------------------------------
# Stage 2b — polish (at most one extra call, only when one is needed)
# --------------------------------------------------------------------------------------
#
# Two cosmetic defects are detected here in code, for free, and repaired in a single
# shared follow-up call: bullets that wrapped onto a near-empty line, and bullets whose
# opening verb repeats another's. They ride together because the call is the expensive
# part — separating them would double the cost of a run that has one of each.
def widowed(
    texts: dict[str, str], *, max_fill: float | None = None
) -> dict[str, int]:
    """`{bullet id: hard character ceiling}` for every bullet ending on a near-empty line.

    The ceiling is one full line below where the text currently ends, less
    `config.WIDOW_SAFETY` — so a 204-character bullet spanning three lines is asked for 197,
    an exact "cut seven characters" rather than a vague "shorten by 15%".

    Single-line bullets are never widows: there is no earlier line for them to fall back
    onto, and a short one-line bullet is simply a short bullet.

    `max_fill` widens the net (default `config.WIDOW_MIN_FILL`): the fit loop's pull-back
    asks for every bullet whose last line is at most that fraction full.
    """
    if max_fill is None:
        max_fill = config.WIDOW_EST_FILL
    floor = max_fill * config.CHARS_PER_LINE
    ceilings: dict[str, int] = {}
    for bullet_id, text in texts.items():
        span = config.line_span(text)
        if span > 1 and config.last_line_fill(text) < floor:
            ceilings[bullet_id] = (span - 1) * config.CHARS_PER_LINE - config.WIDOW_SAFETY
    return ceilings

def opening_verb(text: str) -> str | None:
    """`text`'s first word lowercased, or None if it is not a plain word.

    Only a purely alphabetic first token counts. A hyphenated or numeric opener
    ("Full-stack", "3-tier") is not a verb, and admitting it would let two bullets that
    merely begin with the same adjective be flagged as a verb collision.
    """
    stripped = text.strip()
    if not stripped:
        return None
    word = stripped.split(maxsplit=1)[0].strip(".,;:")
    return word.lower() if word.isalpha() else None

def verb_collisions(
    texts: dict[str, str], *, families: bool = True
) -> dict[str, list[str]]:
    """`{bullet id: verbs to avoid}` for every bullet whose opener repeats another's.

    Two rules, both deterministic and both free:
      - **exact duplicate**: a second bullet opening with the same word as an earlier one.
        Applies to any alphabetic opener, so an unlisted verb is still caught.
      - **family over-concentration**: more than `config.family_opener_cap(len(texts))`
        bullets (two, plus one per five bullets past ten) opening with near-synonyms
        ("Designed... Engineered... Architected..."), which
        reads as one note held too long even though no word repeats. Only verbs in
        `config.VERB_FAMILIES` participate, so an opener the table has never seen can
        never be flagged wrongly.

    The *first* bullet to claim a word or family keeps it; later ones are the offenders,
    so the returned ids are the minimum set that has to change. Iteration follows the
    dict's insertion order, which is selection order, making the choice reproducible.

    A third rule needs no neighbour: **weak opener**. A bullet opening with one of
    `config.WEAK_OPENERS` ("Assisted…", "Helped…") always changes, and never claims its
    opener, so the repair also has to leave the weak set.

    The value is the list of verbs that bullet must not come back with: every opener
    currently in use, plus the whole family (or the weak set) when that is what flagged it.

    `families=False` drops the family rule (exact repeats and weak openers only): what is
    still worth reporting when no repair ran (`rewrite.cosmetic_polish_enabled`).
    """
    openers = {bid: opening_verb(text) for bid, text in texts.items()}
    family_cap = config.family_opener_cap(len(texts))

    used_words: set[str] = set()
    family_counts: dict[str, int] = {}
    offenders: dict[str, set[str]] = {}

    for bullet_id, word in openers.items():
        if word is None:
            continue
        family = config.verb_family(word)

        if word in config.WEAK_OPENERS:
            offenders[bullet_id] = set(config.WEAK_OPENERS)
        elif word in used_words:
            offenders[bullet_id] = set()
        elif families and family is not None and family_counts.get(family, 0) >= family_cap:
            offenders[bullet_id] = set(config.family_verbs(family))
        else:
            # Only a bullet that keeps its opener holds a claim on it; an offender is
            # about to change, so counting it would forbid a family it will vacate.
            used_words.add(word)
            if family is not None:
                family_counts[family] = family_counts.get(family, 0) + 1

    in_use = {w for w in openers.values() if w is not None}
    return {bid: sorted(forbidden | in_use) for bid, forbidden in offenders.items()}

def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in phrase.lower().split()]
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(words) + r"(?![a-z0-9])")

def phrase_collisions(
    texts: dict[str, str],
    phrases: Sequence[str],
    sources: dict[str, Bullet],
    *,
    pages: int,
    repairable: set[str] | None = None,
) -> dict[str, list[str]]:
    """`{bullet id: posting phrases to remove}` for bullets past the phrase-repeat cap.

    Only multi-word phrases count: a single tool name ("Python") recurring across
    bullets is the candidate's real stack, while a repeated multi-word posting phrase
    reads as keyword stuffing. At most `config.phrase_repeat_cap(pages)` bullets keep a
    phrase. Bullets that cannot change keep it first (`repairable` excludes them —
    context bullets already on the page), then bullets whose master source already says
    it, then selection order. An offender is only ever a bullet that *added* the phrase:
    removing words the source itself states would cut the candidate's own claim.
    """
    cap = config.phrase_repeat_cap(pages)
    offenders: dict[str, list[str]] = {}
    seen: set[str] = set()
    for phrase in phrases:
        key = " ".join(phrase.lower().split())
        if len(key.split()) < 2 or key in seen:
            continue
        seen.add(key)
        pattern = _phrase_pattern(key)
        hits = [bid for bid, text in texts.items() if pattern.search(text.lower())]
        if len(hits) <= cap:
            continue

        changeable = {
            bid: (repairable is None or bid in repairable) and bid in sources for bid in hits
        }
        injected = {
            bid: bid not in sources or not pattern.search(sources[bid].text.lower())
            for bid in hits
        }
        order = sorted(
            range(len(hits)), key=lambda i: (changeable[hits[i]], injected[hits[i]], i)
        )
        for i in order[cap:]:
            bid = hits[i]
            if changeable[bid] and injected[bid]:
                offenders.setdefault(bid, []).append(phrase)
    return offenders

def contains_phrase(text: str, phrase: str) -> bool:
    """Whether `text` contains `phrase`, case- and whitespace-insensitively, as whole words."""
    return bool(_phrase_pattern(phrase).search(text.lower()))
