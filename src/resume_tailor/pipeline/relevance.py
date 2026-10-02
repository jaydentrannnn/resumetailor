"""The semantic relevance table: every bullet scored 0-10 against the JD once, cached."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field

from .. import config
from ..content import industries
from ..content.data import Bullet
from ..infra import llm
from . import events, rewrite_prompts
from .jd import JobRequirements


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
_SCORE_PROMPT_VERSION = 2

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
        f"<skills_the_posting_asks_for>\n{rewrite_prompts._format_keywords(requirements)}\n"
        f"</skills_the_posting_asks_for>\n\n"
        f"<bullets_to_score>\n{_format_scoring_bullets(bullets)}\n</bullets_to_score>"
    )

    client = llm.client_for("score")
    response = client.messages.parse(
        model=config.model_for("score"),
        max_tokens=config.max_tokens_for("score"),
        system=industries.system("score", _SCORE_SYSTEM),
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
