"""The fabrication guard: a rewrite may only use terms its source bullet or the JD supports."""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..content.data import Bullet


class FabricationError(RuntimeError):
    """Raised when a rewrite introduces a term absent from the source material.

    This is a hard failure by design: "no fabricated experience" is a correctness
    property of the tool, not a preference.
    """

# --------------------------------------------------------------------------------------
# Stage 3 — fabrication guard (pure, testable, non-negotiable)
# --------------------------------------------------------------------------------------

#: Tokens that look like proper nouns but carry no factual claim, so they never need to
#: be traceable to source material.
_BENIGN = {
    "a", "an", "and", "the", "for", "with", "to", "of", "in", "on", "by", "at", "from",
    "across", "via", "using", "into", "over", "under", "per", "as", "that", "which",
    "i", "we", "my", "our",
}

#: Verbs that attribute execution to someone else. Whole-bullet match — see
#: `delegated_authorship`.
_DELEGATION_VERBS = frozenset(
    {
        "coordinated",
        "managed",
        "oversaw",
        "supervised",
        "commissioned",
        "directed",
        "engaged",
        "partnered",
    }
)

#: External parties whose presence marks a delegated source. Multi-word phrases are
#: matched as contiguous lowercased tokens ("external team", "implementation partner").
_EXTERNAL_PARTY_PHRASES: tuple[tuple[str, ...], ...] = (
    ("vendor",),
    ("agency",),
    ("contractor",),
    ("consultant",),
    ("external", "team"),
    ("outsourced",),
    ("implementation", "partner"),
)

#: Verbs that claim the candidate personally built the work.
_DIRECT_AUTHORSHIP_VERBS = frozenset(
    {
        "built",
        "developed",
        "engineered",
        "implemented",
        "wrote",
        "authored",
        "coded",
        "programmed",
    }
)

#: Prefix marking an authorship escalation inside `guard_offenders`' flat list.
_AUTHORSHIP_PREFIX = "authorship:"

#: Matches a word, allowing internal dots/pluses/hyphens/commas ("node.js", "C++", "GPT-4",
#: "55k+", "1,000") but never a trailing one, so sentence punctuation stays out of the token.
#:
#: The comma is load-bearing for numbers, not cosmetic. Without it "1,000" tokenises as "1"
#: + "000", which put both fragments into the vocabulary as whole tokens and let a rewrite
#: assert either one freely — a hole in the "numbers are checked whole" invariant, and the
#: reason a faithful rewrite of "over 1,000" was once rejected over a phantom "000+".
#: A comma only joins when digits/letters sit on *both* sides, so ordinary "errors, and"
#: punctuation is untouched.
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[+#./_,-]+[A-Za-z0-9]+)*[+#]*")

#: Separators `_TOKEN` allows *inside* a token. A compound joined by these asserts the
#: union of its parts' claims and nothing more. Tried in this order, coarsest first: "/"
#: joins independent names ("Next.js/React"), so splitting there before the finer
#: separators lets each side still match a vocabulary entry that is itself a compound.
#:
#: Splitting on "," cannot launder a fabricated figure: `_vocabulary` contributes only
#: letter-bearing parts, so "1,000" in the source never puts "1" or "000" in scope, and an
#: invented "2,500" finds neither half traceable.
_SPLIT_PATTERNS = (re.compile(r"/+"), re.compile(r"[+#./_,-]+"))

#: A capitalised word directly after one of these is starting a sentence.
_SENTENCE_END = frozenset(".!?;:")

_ACRONYM = re.compile(r"^[A-Z]{2,}$")

_INTERNAL_CAPS = re.compile(r"^.*[a-z].*[A-Z].*$")

_HAS_DIGIT = re.compile(r"\d")

_HAS_LETTER = re.compile(r"[A-Za-z]")

_CAPITALISED = re.compile(r"^[A-Z]")

_NUMBER_PLUS = re.compile(r"\d[\d,]*(?:\.\d+)?\+")

_LOWER_BOUND = re.compile(
    r"\b(?:over|more than|at least)\s+(\d[\d,]*(?:\.\d+)?)\b"
    r"|\b(\d[\d,]*(?:\.\d+)?)\s+(?:or more)\b"
    r"|\b(\d[\d,]*(?:\.\d+)?)\+"
)

def _lower_bounds(text: str) -> set[str]:
    return {next(group for group in match.groups() if group is not None)
            for match in _LOWER_BOUND.finditer(text)}

def _vocabulary(bullet: Bullet) -> set[str]:
    """Every word the rewriter is permitted to draw on for this bullet.

    Source compounds contribute their parts as well as the whole, because the guard is
    willing to decompose a compound in the rewrite and the two sides must speak the same
    vocabulary: "Recall@k/MRR" in the source has to license a bare "MRR". (`_TOKEN` does
    not treat "@" as internal, so that source text arrives as "Recall" + "k/MRR" — which
    is exactly why the whole-token form alone was not enough.)

    Only parts containing a letter are added. Splitting "96.3" into "96" and "3" would
    invent numeric vocabulary the source never asserted, and a fabricated metric is
    precisely what this guard exists to catch.
    """
    words: set[str] = set()
    for source in (bullet.text, " ".join(bullet.tags)):
        for match in _TOKEN.finditer(source):
            token = match.group(0).lower()
            words.add(token)
            for pattern in _SPLIT_PATTERNS:
                words.update(p for p in pattern.split(token) if p and _HAS_LETTER.search(p))
    # A plus suffix asserts a lower bound. License it only when the source itself
    # states that bound, never merely because it contains the same number.
    words.update(f"{number}+" for number in _lower_bounds(bullet.text))
    return words

#: An all-caps run this long is worth testing as an initialism ("CS", "GRPO"). Bounded so
#: the generated set stays small and a long fabricated acronym is never waved through.
_INITIALISM_LENGTHS = (2, 3, 4, 5)

_WORDS_ONLY = re.compile(r"[A-Za-z]+")

def _initialisms(bullet: Bullet) -> set[str]:
    """Acronyms formable from consecutive words in the source material.

    Resumes abbreviate constantly, and the master data stores the expanded form: a bullet
    tagged "computer science fundamentals" legitimately supports "CS". Restricted to runs
    of *consecutive* words so the acronym reflects a phrase the source actually contains.

    The tradeoff is accepted deliberately: an invented acronym could coincidentally match
    some run of source words, costing one missed catch. Rejecting every abbreviation
    instead blocks faithful rewrites outright, which is the worse failure — and an invented
    *tool name* is nearly always spelled out rather than acronymised.
    """
    out: set[str] = set()
    for source in (bullet.text, *bullet.tags):
        words = _WORDS_ONLY.findall(source)
        for n in _INITIALISM_LENGTHS:
            for i in range(len(words) - n + 1):
                out.add("".join(w[0] for w in words[i : i + n]).lower())
    return out

def _is_sentence_initial(text: str, start: int) -> bool:
    """Whether the token at `start` opens a sentence (or the whole string)."""
    for ch in reversed(text[:start]):
        if ch.isspace():
            continue
        return ch in _SENTENCE_END
    return True

def _is_factual_claim(term: str, sentence_initial: bool) -> bool:
    """Whether a token could name a technology or assert a quantity.

    Four signals: an acronym (GRPO), internal capitals (RapidFuzz, PyTorch), any digit
    (99%, GPT-4), or a capitalised word that is *not* opening a sentence (Kubernetes).

    The sentence-initial exemption is what lets ordinary rewording through — a bullet
    rewritten from "Developed..." to "Built..." must not be treated as fabrication. The
    tradeoff is that a fabricated lowercase-or-sentence-initial common word slips past;
    that is accepted, because the risk this guard exists to stop is an invented *tool or
    number*, and those are always caught by one of the four signals.
    """
    if _HAS_DIGIT.search(term) or _ACRONYM.match(term) or _INTERNAL_CAPS.match(term):
        return True
    return bool(_CAPITALISED.match(term)) and not sentence_initial

def _is_permitted(
    term: str, allowed: set[str], *, sentence_initial: bool, initialisms: set[str] = frozenset()
) -> bool:
    """Whether `term` is traceable to the source material.

    A trailing "s" is matched in either direction ("GPUs" against a `gpu` tag, and the
    reverse), because pluralising a permitted term asserts nothing the singular did not.
    Only the +s form is handled: the terms this guard protects are tools and acronyms,
    which pluralise that way ("LLMs", "SDKs"), and a broader stemmer would start conflating
    genuinely different words.

    A compound ("Python/FastAPI", "LLM-powered", "Next.js/React") is permitted when every
    part is permitted on its own, because it claims exactly what its parts claim. Splitting
    is tried coarsest-separator-first and each part is re-checked whole, so a part that is
    itself a vocabulary compound ("Next.js") matches before being broken up further.

    This cannot launder a fabricated metric or version number past the guard: "99%" and the
    "16" in "Next.js 16" are single tokens with no separator to split on, so they are still
    checked whole. Nor does it excuse a version bump — a source naming "GPT-4.1" tokenises
    it whole, leaving "GPT" untraceable on its own, so "GPT-5" still fails.

    Parts are re-checked with `sentence_initial=False`, the stricter reading: a capitalised
    part must be in the vocabulary rather than excused as opening a sentence.
    """
    lowered = term.lower()
    if lowered in allowed or lowered in _BENIGN:
        return True
    if lowered.endswith("s") and lowered[:-1] in allowed:
        return True
    if f"{lowered}s" in allowed:
        return True
    if _ACRONYM.match(term) and lowered in initialisms:
        return True
    if not _is_factual_claim(term, sentence_initial):
        return True
    for pattern in _SPLIT_PATTERNS:
        parts = [p for p in pattern.split(term) if p]
        if len(parts) > 1 and all(
            _is_permitted(p, allowed, sentence_initial=False, initialisms=initialisms)
            for p in parts
        ):
            return True
    return False

def _check_fabrication(sources: Sequence[Bullet], rewritten: str) -> list[str]:
    """Return terms in `rewritten` not traceable to any `sources`.

    Matching is case-insensitive against each bullet's own text plus its tags, so
    legitimate rephrasing passes while a genuinely new technology name or metric does not.
    """
    allowed: set[str] = set()
    initialisms: set[str] = set()
    for source in sources:
        allowed.update(_vocabulary(source))
        initialisms.update(_initialisms(source))

    # A source's N+ also licenses the equivalent prose "over N" / "more than N".
    source_pluses = {m.group(0)[:-1] for source in sources
                     for m in _TOKEN.finditer(source.text)
                     if _NUMBER_PLUS.fullmatch(m.group(0))}
    for number in source_pluses:
        if number in _lower_bounds(rewritten):
            allowed.add(number)

    offenders: list[str] = []
    for match in _TOKEN.finditer(rewritten):
        term = match.group(0)
        if not _is_permitted(
            term,
            allowed,
            sentence_initial=_is_sentence_initial(rewritten, match.start()),
            initialisms=initialisms,
        ):
            offenders.append(term)

    source_bounds = set().union(*(_lower_bounds(source.text) for source in sources))
    for number in _lower_bounds(rewritten) - source_bounds:
        offenders.append(number + "+" if number + "+" in rewritten else number)

    # Preserve first-seen order without duplicates, for a readable error message.
    return list(dict.fromkeys(offenders))

def numbers_dropped(sources: Sequence[Bullet], merged: str) -> list[str]:
    """Return number-bearing tokens present in `sources` but absent from `merged`.

    This is a code-side answer to a weakness of token-only fabrication checks: a model can
    omit an existing metric without inventing anything new, and the guard would still pass.
    """
    haystack_numbers: set[str] = set()
    for match in _TOKEN.finditer(merged):
        term = match.group(0)
        if _HAS_DIGIT.search(term):
            haystack_numbers.add(term.lower())
            if _NUMBER_PLUS.fullmatch(term):
                haystack_numbers.add(term[:-1].lower())
    haystack_numbers.update(_lower_bounds(merged))

    dropped: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for text in (source.text, " ".join(source.tags)):
            for match in _TOKEN.finditer(text):
                term = match.group(0)
                if not _HAS_DIGIT.search(term):
                    continue
                lowered = term.lower()
                if lowered in haystack_numbers or (_NUMBER_PLUS.fullmatch(lowered) and lowered[:-1] in haystack_numbers) or lowered in seen:
                    continue
                seen.add(lowered)
                dropped.append(term)
    return dropped

def check_fabrication(source: Bullet, rewritten: str) -> list[str]:
    """Return terms in `rewritten` that are not traceable to `source`.

    This is a wrapper around `_check_fabrication` so existing callers keep the same
    single-source signature.
    """
    return _check_fabrication([source], rewritten)

#: Shortest word that repeating actually reads as repetition. Below this the word is
#: almost always structural ("and", "of", "team") rather than a claim being restated.
_SIGNIFICANT_LENGTH = 4

def _significant(term: str) -> str | None:
    """`term` reduced to its comparison key, or None if repeating it means nothing.

    Lowercased and de-pluralised so "pipeline" and "pipelines" count as the same word —
    a merged bullet naming the same thing twice in two grammatical numbers is exactly as
    repetitive as naming it twice identically.
    """
    lowered = term.lower()
    if lowered in _BENIGN or len(lowered) < _SIGNIFICANT_LENGTH:
        return None
    if not _HAS_LETTER.search(lowered):
        return None
    return lowered[:-1] if lowered.endswith("s") and len(lowered) > _SIGNIFICANT_LENGTH else lowered
