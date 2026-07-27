"""Bullet selection and rewriting — the content half of the pipeline.

Three deliberately separate stages:

1. `score` / `select` — pure, deterministic tag matching. No LLM. Cheap and predictable,
   which is what lets the fit loop retry without cost blowing up.
2. `rewrite_bullets` — a batched API call that rewords the surviving bullets to mirror the
   posting's phrasing, plus at most one follow-up call carrying only the bullets that
   wrapped onto a near-empty final line. The follow-up fires only when one exists.
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


# --------------------------------------------------------------------------------------
# Stage 2 — rewrite (one batched LLM call)
# --------------------------------------------------------------------------------------

_SYSTEM = """\
You rewrite resume bullet points so they mirror the language of a specific job posting.

Absolute rules:
- NEVER introduce a skill, tool, technology, metric, employer, or claim that is not \
already present in the bullet(s) you are given. You are rewording, not embellishing. A \
rewrite that adds a technology the candidate never used is a serious error.
- When combining multiple bullets into one, do not create new causal relationships \
between them. Avoid "thereby", "resulting in", and similar phrasing unless the \
relationship is already explicit in the provided bullets.
- Preserve every number exactly as written. Do not round, restate, or infer new figures.
- Use the job posting's own phrasing wherever it names something the bullet already \
describes. If the bullet says "fuzzy matching" and the posting says "approximate string \
matching", prefer the posting's wording — but only when they genuinely mean the same \
thing.
- Length is a cliff, not a limit. Each bullet gives a `target` range and a hard `max`. \
Text runs to a fixed line width, so a bullet that ends even two characters past `max` \
wraps onto an extra line holding a single word, wasting a whole line of the page. Landing \
25 characters short of `target` wastes nothing. Err short, never long.
- Keep the strong-verb-first resume register. No first person, no full stops mid-bullet \
where a semicolon reads better, no filler.

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
    lines = []
    for kw in requirements.keywords:
        marker = "REQUIRED" if kw.importance == "must_have" else "preferred"
        lines.append(f"  [{marker}] {kw.phrase}")
    return "\n".join(lines) or "  (none extracted)"


# --------------------------------------------------------------------------------------
# Stage 2b — widow repair (at most one extra call, only when one is needed)
# --------------------------------------------------------------------------------------


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


_REPAIR_INSTRUCTION = """\
Each bullet below wrapped onto a final line holding almost nothing, wasting a whole line \
of the page. The wording is already right — the only problem is length. Bring each one to \
at most its `max` characters by cutting hedges, redundant context, and secondary detail. \
Keep every number and REQUIRED keyword exactly as written.
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


def _tighten_widows(
    texts: dict[str, str],
    sources: dict[str, Bullet],
    requirements: JobRequirements,
) -> tuple[dict[str, str], int]:
    """Re-request the widowed bullets only. Returns (texts, number actually improved).

    One round trip, never more: the same reasoning as `llm._repair`, that a model which
    cannot hit an explicit ceiling once will not hit it on the third try. Anything still
    widowed afterwards is reported, not retried.

    The pass is non-regressive by construction. A returned bullet replaces the original
    only if it is both shorter *and* no longer widowed; a reply that is longer, still
    widowed, unrecognised, or missing leaves the original text exactly as it was. It can
    improve a run or do nothing, but it cannot make one worse.

    Fabrication is still a hard failure here. Shortening under pressure is precisely when a
    model is tempted to compress a claim into something the source never said, so the guard
    runs on repaired text on the same terms as on the first draft.
    """
    ceilings = widowed(texts)
    if not ceilings:
        return texts, 0

    user = (
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
        f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n</keywords_to_mirror>\n\n"
        f"<bullets_to_shorten>\n{_format_widows(ceilings, texts, sources)}\n"
        f"</bullets_to_shorten>\n\n{_REPAIR_INSTRUCTION}"
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
        # Not fatal: the first draft is still valid output, just wasteful. Report it as a
        # surviving widow rather than failing a run over a cosmetic pass.
        return texts, 0

    repaired = dict(texts)
    violations: list[str] = []
    improved = 0

    for item in result.bullets:
        source = sources.get(item.id)
        if source is None or item.id not in ceilings:
            continue
        candidate = item.text.strip()
        offenders = check_fabrication(source, candidate)
        if offenders:
            violations.append(
                f"  {item.id}: introduced {', '.join(offenders)}\n    -> {candidate}"
            )
            continue
        if len(candidate) < len(texts[item.id]) and not widowed({item.id: candidate}):
            repaired[item.id] = candidate
            improved += 1

    if violations:
        raise FabricationError(
            "Shortening a widowed bullet introduced content absent from the master "
            "resume:\n" + "\n".join(violations)
            + "\n\nThis is a hard failure. Re-run with --no-widow-repair to skip this pass, "
            "or shorten the source bullet in master_resume.json so the rewrite has room."
        )

    return repaired, improved


# --------------------------------------------------------------------------------------
# Stage 2 — rewrite
# --------------------------------------------------------------------------------------


@dataclass
class RewriteOutcome:
    """Final bullet text plus what the widow pass had to do to get there."""

    texts: dict[str, str]
    widows_repaired: int = 0
    merges: list[MergeGroup] = field(default_factory=list)

    @property
    def widows_remaining(self) -> int:
        return len(widowed(self.texts))


def rewrite_bullets(
    bullets: list[Bullet],
    requirements: JobRequirements,
    *,
    char_budget: int,
    shorten_pct: int = 0,
    repair_widows: bool = True,
    merge_groups: list[MergeGroup] | None = None,
    on_event: events.ProgressCallback | None = None,
) -> RewriteOutcome:
    """Rewrite `bullets` to surface the posting's keywords.

    `shorten_pct` is the fit loop's lever: it tightens the character budget and tells the
    model explicitly to cut, so successive overflow attempts get progressively terser
    output rather than the same length again.

    `repair_widows` allows one follow-up call carrying only the bullets that ended on a
    near-empty line. It fires only when such a bullet exists, so a clean draft costs exactly
    one call as it always did. Setting it False is the control half of an A/B — it isolates
    what the prompt's target band achieves on its own.

    Raises `FabricationError` if any rewrite introduces untraceable content.
    """
    if not bullets:
        return RewriteOutcome(texts={})

    budget = max(40, int(char_budget * (1 - shorten_pct / 100)))

    instruction = ""
    if shorten_pct:
        instruction = (
            f"\n\nThe previous draft overflowed the page. Shorten every bullet by roughly "
            f"{shorten_pct}% relative to its current text. Cut hedges, redundant context, "
            f"and secondary detail first; keep the numbers and the REQUIRED keywords."
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
    violations: list[str] = []

    for item in result.bullets:
        source = by_id.get(item.id)
        if source is None:
            # An unknown id means the mapping is unreliable; skip rather than guess.
            continue
        offenders = check_fabrication(source, item.text)
        if offenders:
            violations.append(f"  {item.id}: introduced {', '.join(offenders)}\n    -> {item.text}")
        out[item.id] = item.text.strip()

    if violations:
        raise FabricationError(
            "Rewrite introduced content absent from the master resume:\n"
            + "\n".join(violations)
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

    if not repair_widows:
        return RewriteOutcome(texts=out, merges=accepted_merges)

    stranded = len(widowed(out))
    if stranded:
        events.emit(
            on_event,
            "rewrite",
            f"Tightening {stranded} bullet(s) that spilled onto a near-empty line",
            widowed=stranded,
        )
    out, improved = _tighten_widows(out, by_id, requirements)
    return RewriteOutcome(texts=out, widows_repaired=improved, merges=accepted_merges)


_MERGE_INSTRUCTION = """\
Merge the bullets below into ONE bullet.

Absolute rules:
- Do not imply that one bullet caused the other (avoid "thereby", "resulting in",
  "which led to" unless the relationship is already explicit in the provided bullets).
- Preserve every number exactly as written in ANY member bullet.
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
