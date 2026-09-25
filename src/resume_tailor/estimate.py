"""Pre-run estimate of model calls, tokens and cost for one tailoring run (PF4).

Shown next to "Tailor resume" for paid backends, so a student with an API key knows
what a run costs before starting it. Purely arithmetic: no model call, no network.

The figures are for a first run on a posting. A repeat hits the extraction, scoring and
facet caches and costs less. Tokens are estimated as characters / 4 plus each stage's
fixed prompt overhead, measured from the shipped prompts and rounded up. Rewriting is
counted as `_REWRITE_ROUNDS` passes, because the fit loop usually shortens once. Prices
are list prices per million tokens for the model families below. An unknown model gets
token counts and no dollar figure, never a guess. Local backends (Ollama, LM Studio)
cost nothing.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from resume_tailor import config
from resume_tailor.data import MasterResume

#: USD per million (input, output) tokens, matched by model-name prefix (longest wins).
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4": (1.0, 5.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-0": (15.0, 75.0),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
}
_LOCAL_ORIGINS = frozenset({"ollama", "lmstudio"})
_REWRITE_ROUNDS = 2


@dataclass
class StageEstimate:
    stage: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    usd: float | None


def _tokens(chars: int) -> int:
    return math.ceil(chars / 4)


def price_for(origin: str, model: str) -> tuple[float, float] | None:
    """(input, output) USD per million tokens, (0, 0) for local, None when unknown."""
    if origin in _LOCAL_ORIGINS:
        return (0.0, 0.0)
    matches = [prefix for prefix in PRICES_PER_MTOK if model.startswith(prefix)]
    return PRICES_PER_MTOK[max(matches, key=len)] if matches else None


def estimate_run(
    jd_text: str,
    resume: MasterResume,
    *,
    extract_runs: int,
    facets: bool = True,
    expand: bool = True,
    skills: bool = True,
    cover_letter: bool = False,
    vocabulary: bool = False,
) -> dict:
    """Per-stage and total estimate under the current routing (`config.resolve`/`pinned`)."""
    jd_tok = _tokens(len(jd_text))
    bullets = resume.all_bullets()
    bullet_tok = sum(_tokens(len(b.text)) + 8 for b in bullets)
    entry_count = config.MAX_EXPERIENCE_ENTRIES + config.MAX_PROJECT_ENTRIES
    selected = min(len(bullets), entry_count * 4)
    selected_tok = math.ceil(bullet_tok * selected / max(len(bullets), 1))
    skills_tok = _tokens(sum(len(" ".join(g.items)) for g in resume.skills))

    plan: list[tuple[str, str, int, int, int]] = [
        ("extract", "extract", extract_runs, 1500 + jd_tok, 700),
        ("score", "score", 1, 900 + jd_tok + bullet_tok, 10 * len(bullets) + 50),
    ]
    if facets:
        plan.append(("facets", "facets", 1, 900 + jd_tok, 300))
    plan.append(("rewrite", "rewrite", _REWRITE_ROUNDS, 1800 + jd_tok + selected_tok,
                 selected_tok + 20 * selected))
    if expand:
        plan.append(("expand", "expand", 1, 1500 + jd_tok + selected_tok, 800))
    if skills:
        plan.append(("skills", "skills", 1, 1000 + jd_tok + skills_tok, 300))
    if cover_letter:
        plan.append(("cover", "cover", 1, 2500 + jd_tok + selected_tok, 700))
    if vocabulary:
        plan.append(("vocabulary", "extract", 1, 1200, 400))

    stages: list[StageEstimate] = []
    for stage, purpose, calls, tin, tout in plan:
        backend = config.backend_for(purpose)
        origin = backend.origin or backend.provider
        price = price_for(origin, backend.model)
        usd = None
        if price is not None:
            usd = calls * (tin * price[0] + tout * price[1]) / 1_000_000
        stages.append(
            StageEstimate(stage, f"{origin}:{backend.model}", calls, calls * tin, calls * tout, usd)
        )
    known = [s.usd for s in stages]
    return {
        "calls": sum(s.calls for s in stages),
        "input_tokens": sum(s.input_tokens for s in stages),
        "output_tokens": sum(s.output_tokens for s in stages),
        "usd": round(sum(known), 4) if all(u is not None for u in known) else None,
        "local": all(s.model.split(":", 1)[0] in _LOCAL_ORIGINS for s in stages),
        "stages": [asdict(s) for s in stages],
    }
