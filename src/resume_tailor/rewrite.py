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

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field

from . import config, events, llm
from .data import Bullet, Experience, MasterResume, Project
from .jd import JobRequirements
from .merge import MergeGroup


class RewrittenBullet(BaseModel):
    """One rewritten line, keyed back to its source."""

    #: Must match the source bullet's id so the result can be mapped back unambiguously.
    id: str
    text: str


class RewriteResult(BaseModel):
    bullets: list[RewrittenBullet] = Field(default_factory=list)


class FabricationError(RuntimeError):
    """Raised when a rewrite introduces a term absent from the source material.

    This is a hard failure by design: "no fabricated experience" is a correctness
    property of the tool, not a preference.
    """


# --------------------------------------------------------------------------------------
# Stage 1 — selection (deterministic, no LLM)
# --------------------------------------------------------------------------------------


def _keyword_weight(kw) -> float:
    """Weight for one matched keyword.

    Soft-skill must-haves are discounted to `config.SOFT_SKILL_WEIGHT`. Soft tags
    ("communication", "teamwork") are broad and sit on nearly every entry including the
    volunteer and support roles, so at full must-have weight a posting naming three of them
    as required can float a non-technical entry over a relevant job.
    """
    if kw.importance != "must_have":
        return config.NICE_TO_HAVE_WEIGHT
    return config.SOFT_SKILL_WEIGHT if kw.kind == "soft" else config.MUST_HAVE_WEIGHT


def _keyword_score(bullet: Bullet, requirements: JobRequirements) -> float:
    """Tag-overlap score: exact set membership against the bullet's canonical tags."""
    tags = set(bullet.tags)
    return sum(_keyword_weight(kw) for kw in requirements.keywords if kw.canonical in tags)


def score(
    bullet: Bullet,
    requirements: JobRequirements,
    *,
    semantic: dict[str, float] | None = None,
) -> float:
    """Score a bullet's relevance to a posting.

    Two independent signals, added rather than blended away:

    - **Tag overlap** — exact, auditable, and free. Must-have matches dominate
      nice-to-have ones, with soft-skill must-haves discounted (see `_keyword_weight`).
    - **Semantic relevance** — an optional 0-10 score per bullet from `score_table`,
      scaled by `config.SEMANTIC_WEIGHT`. This is the only signal that can see resonance no
      tag encodes: an academic-advising project against a posting about academic-content
      partnerships shares no tag with it and scores zero on overlap alone.

    A bullet carrying a concrete number gets a small nudge on top, but only when it is
    relevant by one of the two signals first — otherwise every quantified bullet floats to
    the top of every posting.

    Passing `semantic=None` (or leaving `SEMANTIC_WEIGHT` at 0.0) reproduces keyword-only
    scoring exactly, which is what makes the semantic layer A/B-testable.
    """
    total = _keyword_score(bullet, requirements)
    if semantic:
        total += config.SEMANTIC_WEIGHT * semantic.get(bullet.id, 0.0)
    if total and bullet.metric:
        total += config.METRIC_BONUS
    return total


def select(
    bullets: list[Bullet],
    requirements: JobRequirements,
    *,
    limit: int,
    semantic: dict[str, float] | None = None,
) -> list[Bullet]:
    """Pick the `limit` most relevant bullets, preserving their original order.

    Ordering is restored after ranking because a resume entry reads as a narrative;
    reordering by score alone produces a jumbled section even when every line is
    individually relevant.

    Zero-scoring bullets are kept as filler only when nothing better is available — an
    entry with no matching bullets should still not render empty.
    """
    if limit <= 0:
        return []

    ranked = sorted(
        bullets, key=lambda b: score(b, requirements, semantic=semantic), reverse=True
    )
    chosen = set(id(b) for b in ranked[:limit])
    return [b for b in bullets if id(b) in chosen]


def score_entry(
    entry: Experience | Project,
    requirements: JobRequirements,
    *,
    semantic: dict[str, float] | None = None,
) -> float:
    """Score a whole job or project by how much relevant material it offers.

    The sum, not the max or the mean: an entry earns its slot on a resume by having
    several usable lines, and a section capped at three entries should prefer the one that
    can fill those lines over one carrying a single strong bullet.
    """
    return sum(score(b, requirements, semantic=semantic) for b in entry.bullets)


def select_entries(
    entries: list[Experience] | list[Project],
    requirements: JobRequirements,
    *,
    limit: int,
    semantic: dict[str, float] | None = None,
) -> list:
    """Pick the `limit` most relevant entries, preserving their original order.

    Experience and projects are ranked **separately** — a job competes only with other
    jobs. Ranking them in one pool let a stack of relevant side projects push out the
    candidate's current employer, which no reader expects to see missing.

    The sort is stable over document order, which is reverse-chronological, so equally
    scoring entries break ties toward the more recent one.
    """
    if limit <= 0:
        return []

    ranked = sorted(
        entries, key=lambda e: score_entry(e, requirements, semantic=semantic), reverse=True
    )
    chosen = {id(e) for e in ranked[:limit]}
    return [e for e in entries if id(e) in chosen]


def select_within_entries(
    entries: list,
    requirements: JobRequirements,
    *,
    limit: int,
    semantic: dict[str, float] | None = None,
) -> list[Bullet]:
    """Choose up to `limit` bullets from already-selected entries.

    Every entry keeps at least its single best bullet: an entry that survived
    `select_entries` has earned a place in the document, and `render.build_context` omits
    any entry whose bullets were all dropped. Without that floor the fit loop could silently
    delete a job it had just decided to keep. `limit` is therefore raised to the entry count
    when it is smaller.

    Remaining budget goes to the highest-scoring bullets across all the entries pooled
    together, so a rich entry can take more lines than a thin one.
    """
    floors: list[Bullet] = []
    for entry in entries:
        if entry.bullets:
            floors.append(
                max(entry.bullets, key=lambda b: score(b, requirements, semantic=semantic))
            )

    kept = {id(b) for b in floors}
    pool = [b for e in entries for b in e.bullets if id(b) not in kept]
    kept |= {
        id(b)
        for b in select(pool, requirements, limit=limit - len(floors), semantic=semantic)
    }

    return [b for e in entries for b in e.bullets if id(b) in kept]


# --------------------------------------------------------------------------------------
# Stage 1b — semantic relevance table (one batched LLM call, cached, OUTSIDE the fit loop)
# --------------------------------------------------------------------------------------


class BulletScore(BaseModel):
    """One bullet's relevance to the posting, keyed back to its source."""

    id: str
    #: 0-10. Clamped on the way in — a rogue value would otherwise swamp every keyword
    #: signal at once, and this is the only unbounded number in the scoring path.
    relevance: float
    #: One line, for the report and for debugging a surprising ranking. Never rendered.
    reason: str = ""


class ScoreTable(BaseModel):
    scores: list[BulletScore] = Field(default_factory=list)


#: Bumped when `_SCORE_SYSTEM` or the score-table request shape changes, so stored tables
#: invalidate on their own rather than relying on `--no-cache`.
_SCORE_PROMPT_VERSION = 1

_SCORE_SYSTEM = """\
You rate how relevant each of a candidate's resume bullets is to one specific job posting.

Return a relevance score from 0 to 10 for EVERY bullet you are given:
- 9-10: directly demonstrates a core responsibility or required skill of this role.
- 6-8: clearly relevant — adjacent technology, transferable method, or the same domain.
- 3-5: weakly relevant; a hiring manager would not object to it but it does not sell.
- 0-2: unrelated to this posting.

Judge relevance to THIS role, not general impressiveness. A technically harder project that \
has nothing to do with the posting scores lower than a simpler one that matches its daily \
work. Weigh the role context as heavily as the named skills: a project in the same domain \
as the team's subject matter is relevant even when it shares no tooling with the posting.

Do not reward or penalise wording quality, seniority, or recency — those are handled \
elsewhere. Score the substance only.

`reason` is at most one short sentence saying what drove the score.
Return one entry per input bullet, keyed by the exact id you were given.
"""


def _score_cache_path(bullets: list[Bullet], requirements: JobRequirements) -> Path:
    """Cache key covering everything the table depends on.

    The bullets' text is part of the key, not just their ids: editing a bullet in the master
    resume changes what is being scored, and silently reusing the old number would misrank
    it with no visible symptom.

    So is the backend. Relevance scores are a model's judgement, not a fact about the
    bullet — replaying Claude's table under Ollama's name would misattribute a ranking and
    make the two impossible to compare.
    """
    payload = "\n".join(
        [
            str(_SCORE_PROMPT_VERSION),
            config.fingerprint("score"),
            requirements.model_dump_json(),
            *(f"{b.id}\t{b.text}" for b in bullets),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.scores.json"


def _format_scoring_bullets(bullets: list[Bullet]) -> str:
    return "\n".join(
        f"<bullet id={b.id!r}>{b.text}</bullet>" for b in bullets
    )


def score_table(
    bullets: list[Bullet],
    requirements: JobRequirements,
    *,
    use_cache: bool = True,
    on_event: events.ProgressCallback | None = None,
) -> dict[str, float]:
    """Rate every bullet's relevance to the posting. Returns {bullet_id: 0-10}.

    Called **once per run, before the fit loop** — deliberately not inside it.
    `fit._initial_selection_size` binary-searches over the bullet count, calling selection on
    every iteration, and the loop calls it again on every grow attempt; an API call in that
    path would cost a dozen round trips per run. Worse, a table that changed between
    iterations would break the loop's monotonicity assumption, letting a grow step *swap*
    bullets instead of adding them and decoupling the estimate from the render.

    This is the only place `requirements.domain_notes` reaches selection. Tag overlap cannot
    encode "this project is in the same domain as this team", which is exactly the judgement
    a reader makes first.

    Bullets the model omits are simply absent from the result, and `score` treats a missing
    id as 0.0 — an unscored bullet falls back to its keyword score rather than failing the
    run.
    """
    if not bullets:
        return {}

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _score_cache_path(bullets, requirements)
    if use_cache and cache_path.exists():
        events.emit(on_event, "score", "Reusing cached relevance scores", cached=True)
        cached = ScoreTable.model_validate_json(cache_path.read_text(encoding="utf-8"))
        return {s.id: s.relevance for s in cached.scores}

    events.emit(
        on_event,
        "score",
        f"Scoring {len(bullets)} bullet(s) for relevance",
        cached=False,
        bullets=len(bullets),
        model=config.model_for("score"),
    )
    notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n"
        f"<skills_the_posting_asks_for>\n{_format_keywords(requirements)}\n"
        f"</skills_the_posting_asks_for>\n\n"
        f"<bullets_to_score>\n{_format_scoring_bullets(bullets)}\n</bullets_to_score>"
    )

    client = llm.client_for("score")
    response = client.messages.parse(
        model=config.model_for("score"),
        max_tokens=config.max_tokens_for("score"),
        system=_SCORE_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=ScoreTable,
        output_config={"effort": config.effort_for("score")},
    )

    result = response.parsed_output
    if result is None:
        raise RuntimeError(
            f"Model did not return parseable relevance scores "
            f"(stop_reason={response.stop_reason!r})."
        )

    known = {b.id for b in bullets}
    # An unknown id means the mapping is unreliable; drop it rather than guess, mirroring
    # `rewrite_bullets`. Clamping is not defensive theatre — this number is multiplied by
    # SEMANTIC_WEIGHT and added straight into the ranking.
    kept = [
        BulletScore(id=s.id, relevance=min(10.0, max(0.0, s.relevance)), reason=s.reason)
        for s in result.scores
        if s.id in known
    ]

    cache_path.write_text(
        ScoreTable(scores=kept).model_dump_json(indent=2), encoding="utf-8"
    )
    return {s.id: s.relevance for s in kept}


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

    dropped: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for text in (source.text, " ".join(source.tags)):
            for match in _TOKEN.finditer(text):
                term = match.group(0)
                if not _HAS_DIGIT.search(term):
                    continue
                lowered = term.lower()
                if lowered in haystack_numbers or lowered in seen:
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

    for match in _TOKEN.finditer(text):
        term = match.group(0)
        family = config.verb_family(term)
        if first:
            opening_family = family
            first = False
        elif family is not None and family == opening_family:
            offenders.append(term)

        key = _significant(term)
        if key is None:
            continue
        if key in seen:
            offenders.append(term)
        seen.add(key)

    return list(dict.fromkeys(offenders))


# --------------------------------------------------------------------------------------
# Stage 2 — rewrite (one batched LLM call)
# --------------------------------------------------------------------------------------

_SYSTEM = """\
You rewrite resume bullet points so they mirror the language of a specific job posting.

Absolute rules:
- NEVER introduce a skill, tool, technology, metric, employer, or claim that is not \
already present in the bullet(s) you are given. You are rewording, not embellishing. A \
rewrite that adds a technology the candidate never used is a serious error.
- Never move a number or metric from one bullet id to another. Each figure belongs only \
to the bullet that already contains it — a sibling's 0.88 or p95 must not appear under a \
different id, even when both bullets describe evaluation work.
- When combining multiple bullets into one, do not create new causal relationships \
between them. Avoid "thereby", "resulting in", and similar phrasing unless the \
relationship is already explicit in the provided bullets.
- Preserve every number exactly as written. Do not round, restate, or infer new figures.
- Mirror the posting's wording only where it names something the bullet already does, and \
only when the two genuinely mean the same thing: if the bullet says "fuzzy matching" and \
the posting says "approximate string matching", prefer the posting's. Never bend a bullet \
toward a keyword to work it in. A keyword the resume cannot honestly claim is meant to go \
unused; a forced one reads as padding and costs a line.
- Soft skills are shown by the work, never named. Do not open a bullet by asserting \
communication, collaboration, problem-solving, organisation, attention to detail, or \
teamwork. "Applied problem-solving skills to a 45% accuracy bottleneck" and "Utilized \
verbal communication skills to facilitate three weekly labs" both waste their strongest \
words on a claim the rest of the sentence already proves — write "Diagnosed a 45% accuracy \
bottleneck" and "Facilitated three weekly labs" instead.
- Write like a person. The bullet should read as a plain description of what was done, \
not as a checklist of the posting's vocabulary stitched into a sentence.
- Length is a cliff, not a limit. Each bullet gives a `target` range and a hard `max`. \
Text runs to a fixed line width, so a bullet that ends even two characters past `max` \
wraps onto an extra line holding a single word, wasting a whole line of the page. Landing \
25 characters short of `target` wastes nothing. Err short, never long.
- Keep the strong-verb-first resume register. No first person, no full stops mid-bullet \
where a semicolon reads better, no filler.
- Vary the opening verb. You are given every bullet at once, so treat them as one \
document: no two may open with the same verb, and no more than two may open with \
near-synonyms — "designed", "engineered", "architected" and "built" are one verb wearing \
four hats. Reach for the verb that names what the work actually was.
- Say each thing once across the whole set. Two bullets making the same claim in different \
words waste a line and read as padding; distinguish them by what each one actually did.

Return one entry per input item, keyed by the exact id you were given.
"""

#: How far below `max` the advertised target range opens. Wide enough that hitting it
#: leaves real headroom, narrow enough that the model does not aim at a half-empty line —
#: it spans the 180-199 window both widow-free runs already occupied.
_TARGET_BAND = 25


def _length_band(budget: int) -> tuple[int, int]:
    """The (soft minimum, hard maximum) character range advertised for `budget`.

    `max` sits `WIDOW_SAFETY` characters below the budget rather than on it, because the
    measured failure was a 2-to-5 character overshoot: a ceiling placed exactly on the line
    boundary is simply crossed again.
    """
    hard_max = max(40, budget - config.WIDOW_SAFETY)
    return max(20, hard_max - _TARGET_BAND), hard_max


def _format_bullets(bullets: list[Bullet], budget: int) -> str:
    soft_min, hard_max = _length_band(budget)
    lines = []
    for b in bullets:
        lines.append(
            f"<bullet id={b.id!r} target={f'{soft_min}-{hard_max}'!r} max={hard_max}>\n"
            f"  <current>{b.text}</current>\n"
            f"  <permitted_skills>{', '.join(b.tags)}</permitted_skills>\n"
            f"</bullet>"
        )
    return "\n".join(lines)


def _format_keywords(requirements: JobRequirements) -> str:
    """Render the posting's keywords one per line for the rewrite prompt.

    Soft skills are labelled rather than marked REQUIRED. Marked as required they came back
    asserted verbatim ("Utilized verbal communication skills to..."), because the model was
    correctly told to mirror required phrasing; they stay visible as a signal of what the
    posting cares about without licensing the phrase itself.
    """
    lines = []
    for kw in requirements.keywords:
        if kw.kind == "soft":
            marker = "soft — demonstrate, never name"
        else:
            marker = "REQUIRED" if kw.importance == "must_have" else "preferred"
        lines.append(f"  [{marker}] {kw.phrase}")
    return "\n".join(lines) or "  (none extracted)"


# --------------------------------------------------------------------------------------
# Stage 2b — polish (at most one extra call, only when one is needed)
# --------------------------------------------------------------------------------------
#
# Two cosmetic defects are detected here in code, for free, and repaired in a single
# shared follow-up call: bullets that wrapped onto a near-empty line, and bullets whose
# opening verb repeats another's. They ride together because the call is the expensive
# part — separating them would double the cost of a run that has one of each.


def widowed(texts: dict[str, str]) -> dict[str, int]:
    """`{bullet id: hard character ceiling}` for every bullet ending on a near-empty line.

    The ceiling is one full line below where the text currently ends, less
    `config.WIDOW_SAFETY` — so a 204-character bullet spanning three lines is asked for 197,
    an exact "cut seven characters" rather than a vague "shorten by 15%".

    Single-line bullets are never widows: there is no earlier line for them to fall back
    onto, and a short one-line bullet is simply a short bullet.
    """
    floor = config.WIDOW_MIN_FILL * config.CHARS_PER_LINE
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


def verb_collisions(texts: dict[str, str]) -> dict[str, list[str]]:
    """`{bullet id: verbs to avoid}` for every bullet whose opener repeats another's.

    Two rules, both deterministic and both free:
      - **exact duplicate**: a second bullet opening with the same word as an earlier one.
        Applies to any alphabetic opener, so an unlisted verb is still caught.
      - **family over-concentration**: more than `config.MAX_SAME_FAMILY_OPENERS` bullets
        opening with near-synonyms ("Designed... Engineered... Architected..."), which
        reads as one note held too long even though no word repeats. Only verbs in
        `config.VERB_FAMILIES` participate, so an opener the table has never seen can
        never be flagged wrongly.

    The *first* bullet to claim a word or family keeps it; later ones are the offenders,
    so the returned ids are the minimum set that has to change. Iteration follows the
    dict's insertion order, which is selection order, making the choice reproducible.

    The value is the list of verbs that bullet must not come back with: every opener
    currently in use, plus the whole family when the family is what overflowed.
    """
    openers = {bid: opening_verb(text) for bid, text in texts.items()}

    used_words: set[str] = set()
    family_counts: dict[str, int] = {}
    offenders: dict[str, set[str]] = {}

    for bullet_id, word in openers.items():
        if word is None:
            continue
        family = config.verb_family(word)

        if word in used_words:
            offenders[bullet_id] = set()
        elif family is not None and family_counts.get(family, 0) >= config.MAX_SAME_FAMILY_OPENERS:
            offenders[bullet_id] = set(config.family_verbs(family))
        else:
            # Only a bullet that keeps its opener holds a claim on it; an offender is
            # about to change, so counting it would forbid a family it will vacate.
            used_words.add(word)
            if family is not None:
                family_counts[family] = family_counts.get(family, 0) + 1

    in_use = {w for w in openers.values() if w is not None}
    return {bid: sorted(forbidden | in_use) for bid, forbidden in offenders.items()}


_REPAIR_INSTRUCTION = """\
Each bullet below wrapped onto a final line holding almost nothing, wasting a whole line \
of the page. The wording is already right — the only problem is length. Bring each one to \
at most its `max` characters by cutting hedges, redundant context, and secondary detail. \
Keep every number and every required technical keyword exactly as written.
"""

_VERB_INSTRUCTION = """\
Each bullet below opens with a verb another bullet already used, or with a near-synonym of \
one. Replace ONLY the opening verb with one that is not in its `avoid` list and does not \
mean the same thing as those. Keep the rest of the bullet word for word, including every \
number, unless the new verb makes the grammar wrong — then change as little as possible. \
Do not lengthen the bullet. Do not restate the claim in different words: this is a \
one-word substitution, not a rewrite.
"""

_RETRY_INSTRUCTION = """\
Each bullet below was rejected: it contains a term or figure that does not appear in the \
source material. The listed `rejected_terms` are the problem. Rewrite each bullet without \
them, using only what its `source` and `permitted_skills` already state. Do not substitute \
a synonym or a variant for a rejected figure — write a number exactly as the source writes \
it (if the source says "over 130", do not write "130+"), or leave it out entirely. Do not \
borrow a metric from any other bullet. Keep the rest of the bullet's meaning.
"""


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


def _format_fabrications(
    rejected: dict[str, tuple[str, list[str]]], sources: dict[str, Bullet]
) -> str:
    """Format rejected bullets, each carrying the terms that failed the guard.

    The master text ships alongside the rejected draft because the model's mistake is
    usually a *variant* of something the source does say ("130+" for "over 130"), and it
    cannot correct that without seeing how the source words it.
    """
    lines = []
    for bullet_id, (text, offenders) in rejected.items():
        tags = ", ".join(sources[bullet_id].tags)
        lines.append(
            f"<bullet id={bullet_id!r} rejected_terms={', '.join(offenders)!r}>\n"
            f"  <rejected>{text}</rejected>\n"
            f"  <source>{sources[bullet_id].text}</source>\n"
            f"  <permitted_skills>{tags}</permitted_skills>\n"
            f"</bullet>"
        )
    return "\n".join(lines)


def _retry_fabrications(
    rejected: dict[str, tuple[str, list[str]]],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
) -> tuple[dict[str, str], list[str]]:
    """Re-request only the fabricating bullets. Returns (accepted, surviving violations).

    One round trip, never more — same bound as `_polish`. Each returned bullet replaces
    its draft only if it passes the guard; length is left to the widow pass and the fit
    loop. An id the model omits, or a candidate that fabricates again, stays in the
    violation list so the caller can raise.
    """
    if not rejected:
        return {}, []

    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n</keywords_to_mirror>\n\n"
        f"<bullets_to_retry>\n{_format_fabrications(rejected, sources)}\n"
        f"</bullets_to_retry>\n\n{_RETRY_INSTRUCTION}"
    )

    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=RewriteResult,
        output_config={"effort": config.effort_for("rewrite")},
    )

    result = response.parsed_output
    if result is None:
        # Unparseable reply leaves every id unresolved — report all rather than pass.
        return {}, [
            f"  {bid}: introduced {', '.join(offenders)}\n    -> {text}"
            for bid, (text, offenders) in rejected.items()
        ]

    by_reply = {item.id: item.text.strip() for item in result.bullets}
    accepted: dict[str, str] = {}
    survivors: list[str] = []

    for bullet_id, (draft, _offenders) in rejected.items():
        candidate = by_reply.get(bullet_id)
        if candidate is None:
            survivors.append(
                f"  {bullet_id}: introduced {', '.join(_offenders)}\n    -> {draft}"
            )
            continue
        source = sources[bullet_id]
        still = check_fabrication(source, candidate)
        if still:
            survivors.append(
                f"  {bullet_id}: introduced {', '.join(still)}\n    -> {candidate}"
            )
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
    new_verb = opening_verb(candidate)
    if new_verb is None or new_verb == opening_verb(original) or new_verb in avoid:
        return False
    if config.line_span(candidate) > config.line_span(original):
        return False
    if widowed({"_": candidate}):
        return False
    return not check_fabrication(source, candidate)


def _polish(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
    *,
    repair_widows: bool = True,
    repair_verbs: bool = True,
) -> tuple[dict[str, str], int, int]:
    """Re-request only the defective bullets. Returns (texts, widows fixed, verbs changed).

    One round trip, never more, and shared between both defects: the same reasoning as
    `llm._repair`, that a model which cannot hit an explicit ceiling once will not hit it
    on the third try. Anything still defective afterwards is reported, not retried.

    A bullet that is both widowed and verb-colliding is sent as a widow only. Two entries
    under one id would make the reply ambiguous, and a wasted line costs real page space
    while a repeated verb only reads badly — so length wins and the collision is reported.

    The pass is non-regressive by construction. Each returned bullet replaces its original
    only if it strictly improves that bullet's own defect without introducing another; a
    reply that is longer, still defective, unrecognised, or missing leaves the original
    text exactly as it was. It can improve a run or do nothing, but it cannot make one
    worse.

    Fabrication remains a hard failure for widow repair — shortening under pressure is
    precisely when a model compresses a claim into something the source never said — and a
    discard for verb swaps, per `_accept_verb_swap`.
    """
    ceilings = widowed(texts) if repair_widows else {}
    collisions = (
        {bid: avoid for bid, avoid in verb_collisions(texts).items() if bid not in ceilings}
        if repair_verbs
        else {}
    )
    if not ceilings and not collisions:
        return texts, 0, 0

    sections = [
        f"<role>{requirements.title} ({requirements.seniority})</role>",
        f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n</keywords_to_mirror>",
    ]
    if ceilings:
        sections.append(
            f"<bullets_to_shorten>\n{_format_widows(ceilings, texts, sources)}\n"
            f"</bullets_to_shorten>\n\n{_REPAIR_INSTRUCTION}"
        )
    if collisions:
        sections.append(
            f"<bullets_to_revoice>\n{_format_verb_items(collisions, texts, sources)}\n"
            f"</bullets_to_revoice>\n\n{_VERB_INSTRUCTION}"
        )
    user = "\n\n".join(sections)

    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=RewriteResult,
        output_config={"effort": config.effort_for("rewrite")},
    )

    result = response.parsed_output
    if result is None:
        # Not fatal: the first draft is still valid output, just wasteful. Report it as a
        # surviving widow rather than failing a run over a cosmetic pass.
        return texts, 0, 0

    repaired = dict(texts)
    violations: list[str] = []
    tightened = 0
    revoiced = 0
    # An accepted swap claims its new opener, so two colliding bullets cannot both be
    # handed the same replacement verb.
    claimed: set[str] = set()

    for item in result.bullets:
        source = sources.get(item.id)
        if source is None:
            continue
        candidate = item.text.strip()

        if item.id in ceilings:
            offenders = check_fabrication(source, candidate)
            if offenders:
                violations.append(
                    f"  {item.id}: introduced {', '.join(offenders)}\n    -> {candidate}"
                )
                continue
            if len(candidate) < len(texts[item.id]) and not widowed({item.id: candidate}):
                repaired[item.id] = candidate
                tightened += 1
        elif item.id in collisions:
            avoid = set(collisions[item.id]) | claimed
            if _accept_verb_swap(texts[item.id], candidate, source, avoid):
                repaired[item.id] = candidate
                revoiced += 1
                verb = opening_verb(candidate)
                if verb is not None:
                    claimed.add(verb)

    if violations:
        raise FabricationError(
            "Shortening a widowed bullet introduced content absent from the master "
            "resume:\n" + "\n".join(violations)
            + "\n\nThis is a hard failure. Re-run with --no-widow-repair to skip this pass, "
            "or shorten the source bullet in master_resume.json so the rewrite has room."
        )

    return repaired, tightened, revoiced


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

    @property
    def widows_remaining(self) -> int:
        return len(widowed(self.texts))

    @property
    def verb_collisions_remaining(self) -> int:
        """Bullets still opening with a verb another bullet already used."""
        return len(verb_collisions(self.texts))


def rewrite_bullets(
    bullets: list[Bullet],
    requirements: JobRequirements,
    *,
    char_budget: int,
    shorten_pct: int = 0,
    repair_widows: bool = True,
    repair_verbs: bool = True,
    merge_groups: list[MergeGroup] | None = None,
    on_event: events.ProgressCallback | None = None,
) -> RewriteOutcome:
    """Rewrite `bullets` to surface the posting's keywords.

    `shorten_pct` is the fit loop's lever: it tightens the character budget and tells the
    model explicitly to cut, so successive overflow attempts get progressively terser
    output rather than the same length again.

    `repair_widows` and `repair_verbs` each allow one *shared* follow-up call carrying only
    the defective bullets — those that ended on a near-empty line, and those whose opening
    verb repeats another's. The call fires only when such a bullet exists, so a clean draft
    costs exactly one call as it always did, and a draft with one of each still costs two
    rather than three. Setting either False is the control half of an A/B: `repair_widows`
    isolates what the prompt's target band achieves alone, `repair_verbs` what its
    verb-variety rule does.

    A first draft that fabricates earns one targeted retry of only the offending ids
    (`_retry_fabrications`). A second fabrication — or an id the model drops on retry —
    still raises `FabricationError`.
    """
    if not bullets:
        return RewriteOutcome(texts={})

    budget = max(40, int(char_budget * (1 - shorten_pct / 100)))

    instruction = ""
    if shorten_pct:
        instruction = (
            f"\n\nThe previous draft overflowed the page. Shorten every bullet by roughly "
            f"{shorten_pct}% relative to its current text. Cut hedges, redundant context, "
            f"and secondary detail first; keep every number and the required "
            f"technical keywords."
        )

    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n</keywords_to_mirror>\n\n"
        f"<context>\n" + "\n".join(f"  - {n}" for n in requirements.domain_notes) + "\n</context>\n\n"
        f"<bullets_to_rewrite>\n{_format_bullets(bullets, budget)}\n</bullets_to_rewrite>"
        f"{instruction}"
    )

    events.emit(
        on_event,
        "rewrite",
        (
            f"Rewriting {len(bullets)} bullet(s)"
            + (f", {shorten_pct}% shorter" if shorten_pct else "")
        ),
        bullets=len(bullets),
        shorten_pct=shorten_pct,
        model=config.model_for("rewrite"),
    )
    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=RewriteResult,
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
        offenders = check_fabrication(source, text)
        if offenders:
            rejected[item.id] = (text, offenders)
        else:
            out[item.id] = text

    if rejected:
        events.emit(
            on_event,
            "rewrite",
            f"Retrying {len(rejected)} fabricated bullet(s)",
            fabricated=len(rejected),
        )
        accepted, survivors = _retry_fabrications(rejected, by_id, requirements)
        out.update(accepted)
        if survivors:
            raise FabricationError(
                "Rewrite introduced content absent from the master resume:\n"
                + "\n".join(survivors)
                + "\n\nThis is a hard failure. Either the model embellished, or the source "
                "bullet's `tags` are missing a technology it legitimately mentions."
            )

    # Any bullet the model dropped keeps its original text — better an untailored true
    # line than a missing one.
    for b in bullets:
        out.setdefault(b.id, b.text)

    accepted_merges: list[MergeGroup] = []
    if merge_groups:
        out, accepted_merges = _merge_bullets(out, by_id, merge_groups, requirements, budget=budget)

    if not repair_widows and not repair_verbs:
        return RewriteOutcome(texts=out, merges=accepted_merges)

    # Both counts are measured before the call so the progress line says what the follow-up
    # is for; the pass itself re-derives them, since merging may have changed either.
    stranded = len(widowed(out)) if repair_widows else 0
    colliding = len(verb_collisions(out)) if repair_verbs else 0
    if stranded or colliding:
        wanted = []
        if stranded:
            wanted.append(f"{stranded} bullet(s) that spilled onto a near-empty line")
        if colliding:
            wanted.append(f"{colliding} repeated opening verb(s)")
        events.emit(
            on_event,
            "rewrite",
            f"Polishing {' and '.join(wanted)}",
            widowed=stranded,
            verb_collisions=colliding,
        )
    out, improved, revoiced = _polish(
        out,
        by_id,
        requirements,
        repair_widows=repair_widows,
        repair_verbs=repair_verbs,
    )
    return RewriteOutcome(
        texts=out,
        widows_repaired=improved,
        verbs_diversified=revoiced,
        merges=accepted_merges,
    )


_MERGE_INSTRUCTION = """\
Merge the bullets below into ONE bullet.

Absolute rules:
- Do not imply that one bullet caused the other (avoid "thereby", "resulting in",
  "which led to" unless the relationship is already explicit in the provided bullets).
- Preserve every number exactly as written in ANY member bullet.
- Say each thing once. Name a shared tool, system, or metric a single time, and let one \
opening verb govern the whole bullet — "Designed X and engineered Y" is two bullets \
wearing one bullet's clothes. No "and also", no restating a skill already named earlier \
in the same bullet.
- The result must read as one coherent claim, not a list of two. If the members cannot be \
stated as one claim without repeating yourself, return the stronger member alone.
"""


def _format_merge_groups(
    groups: list[MergeGroup],
    texts: dict[str, str],
    sources: dict[str, Bullet],
    budget: int,
) -> str:
    """Format merge groups as XML-like text for the merge LLM call."""
    soft_min, hard_max = _length_band(budget)
    parts: list[str] = []
    for group in groups:
        tags = sorted({t for mid in group.member_ids for t in sources[mid].tags})
        currents = "\n".join(f"  - {texts[mid]}" for mid in group.member_ids)
        parts.append(
            f"<merge id={group.survivor_id!r} target={f'{soft_min}-{hard_max}'!r} max={hard_max}>\n"
            f"  <currents>\n{currents}\n  </currents>\n"
            f"  <permitted_skills>{', '.join(tags)}</permitted_skills>\n"
            f"</merge>"
        )
    return "\n".join(parts)


def _merge_bullets(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    groups: list[MergeGroup],
    requirements: JobRequirements,
    *,
    budget: int,
) -> tuple[dict[str, str], list[MergeGroup]]:
    """Rewrite and optionally apply merged bullet text for proposed groups.

    The merge is a non-regressive optional restructure:
    - the merged output must free at least one line vs the sum of source members
    - the merged text must pass multi-source fabrication guard
    - no number-bearing tokens from any member may be dropped
    - the merged text must not restate anything (`redundancy_offenders`)
    - the merged bullet must not be widowed (widow repair happens later if enabled)

    If the LLM fails to return parseable output, this pass is skipped.
    """
    if not groups:
        return texts, []

    budget = max(40, budget)
    _, hard_max = _length_band(budget)

    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n</keywords_to_mirror>\n\n"
        f"<context>\n" + "\n".join(f"  - {n}" for n in requirements.domain_notes) + "\n</context>\n\n"
        f"<merges_to_combine>\n{_format_merge_groups(groups, texts, sources, budget)}\n"
        f"</merges_to_combine>\n\n{_MERGE_INSTRUCTION}"
    )

    client = llm.client_for("rewrite")
    response = client.messages.parse(
        model=config.model_for("rewrite"),
        max_tokens=config.max_tokens_for("rewrite"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=RewriteResult,
        output_config={"effort": config.effort_for("rewrite")},
    )

    result = response.parsed_output
    if result is None:
        return texts, []

    by_id: dict[str, str] = {b.id: b.text for b in result.bullets}
    merged = dict(texts)
    accepted: list[MergeGroup] = []

    for group in groups:
        candidate = by_id.get(group.survivor_id)
        if not candidate:
            continue
        candidate = candidate.strip()

        if len(candidate) > hard_max:
            continue

        before_lines = sum(config.line_span(texts[mid]) for mid in group.member_ids)
        after_lines = config.line_span(candidate)
        if not (after_lines < before_lines):
            continue

        member_sources = [sources[mid] for mid in group.member_ids if mid in sources]
        if not member_sources:
            continue

        offenders = _check_fabrication(member_sources, candidate)
        if offenders:
            continue

        dropped = numbers_dropped(member_sources, candidate)
        if dropped:
            continue

        # The failure mode this whole gate exists for: a candidate that is short enough,
        # invents nothing, and drops no number can still simply say both members out loud.
        if redundancy_offenders(candidate):
            continue

        if widowed({group.survivor_id: candidate}).get(group.survivor_id) is not None:
            continue

        # Apply only after all checks pass.
        merged[group.survivor_id] = candidate
        for absorbed_id in group.member_ids[1:]:
            merged.pop(absorbed_id, None)
        accepted.append(group)

    return merged, accepted


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
