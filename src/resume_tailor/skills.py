"""Tailored skills list for application-form "Skills" fields.

A sixth LLM stage, separate from the page-fitted resume rewrite and from `expand.py`'s
application-form descriptions. Many application forms ask for a flat list of skills —
free-text or a picker — and nothing else in the pipeline answers that question: the
skills-section wording is fixed by `facets.py` (rewording only, never resized), and no
other stage ranks the resume's evidence against a specific posting.

The pool of candidate skills is a closed set drawn from the resume's own evidence —
skills-group items, every bullet tag, project tech labels, and coursework titles — built
deterministically in code (`build_pool`). The model only *selects and ranks* from that
pool; it may propose a JD-anchored respelling of a chosen label, but code validates every
choice against the pool and rejects (never invents) anything outside it. Same "model
selects, code enforces" split `facets.py` uses for project tech and coursework.

Tier (required/preferred/additional) and JD evidence are computed in code, not asked of
the model: `jd.Keyword.importance` is already a *voted* field (see `jd.extract_consensus`),
and asking a second call to re-derive it would reintroduce exactly the instability that
voting exists to remove — and could let this tile disagree with `ReportCard`'s coverage
summary about the very same posting.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import config, events, llm
from .data import MasterResume
from .facets import (
    _norm_ws,
    labels_are_equivalent,
    rename_is_jd_anchored,
    rename_preserves_claim,
)
from .jd import JobRequirements, Keyword

#: Bumped when `_SYSTEM` or the request/response shape changes, so cached selections
#: invalidate on their own rather than relying on `--no-cache`.
_SKILLS_PROMPT_VERSION = 1

#: Display precedence when the same normalised skill appears under multiple sources —
#: lower rank wins. Skills-section items are the only source the user hand-wrote *as a
#: skills list*, so they win over a project tech proper noun, which in turn reads better
#: than a coursework title, which in turn reads better than a bullet tag (a lowercase
#: matching key that happens to be legible, a label of last resort).
_SOURCE_RANK: dict[str, int] = {"skills": 0, "project": 1, "coursework": 2, "tag": 3}


_SYSTEM = """\
You select and rank skills to enter into an application form's "Skills" field (free-text \
or a picker) for one specific job posting.

You are GIVEN a closed pool of the candidate's own skills, grouped by where each comes \
from. You may ONLY choose from this pool — never invent a skill, tool, or technology that \
is not listed. Do not combine, split, or generalise a pool item into something else.

For each skill you choose:
- Set `skill` to the pool label EXACTLY as given (copy it verbatim).
- Optionally set `display` to a respelling of that same skill in the posting's own \
wording, ONLY when the posting names it differently but means the same thing (e.g. pool \
"Postgres" + posting says "PostgreSQL" -> display "PostgreSQL"). Leave `display` empty \
otherwise. Never use `display` to shorten, generalise, or narrow the skill (never \
"hybrid retrieval & reranking" -> "retrieval").
- Optionally set `reason` to one short clause naming what in the posting it supports.

Order your selections best-first — the skills most worth leading with for this posting. \
Do not group or label them yourself; that is handled separately. Prefer breadth across \
the pool's different sources over repeating near-duplicates. Skip pool items that are \
irrelevant to this posting rather than padding the list.
"""


class SelectedSkillLLM(BaseModel):
    """One chosen skill as returned by the model."""

    skill: str
    #: Optional JD-anchored respelling of `skill`; guarded in code before use.
    display: str = ""
    reason: str = ""


class SkillsSelectionLLM(BaseModel):
    """Batched model output: every skill chosen for this posting, best-first."""

    selected: list[SelectedSkillLLM] = Field(default_factory=list)


@dataclass(frozen=True)
class SkillCandidate:
    """One pool item: a skill the resume can honestly claim, with its display spelling."""

    key: str
    label: str
    sources: tuple[str, ...] = ()
    bullet_count: int = 0


@dataclass
class SkillSuggestion:
    """One skill to enter, ready for the tile."""

    skill: str
    pool_label: str
    tier: Literal["required", "preferred", "additional"]
    jd_phrase: str = ""
    sources: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class SkillsPlan:
    """Full skills-selection artifact for one tailoring run."""

    skills: list[SkillSuggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    pool_size: int = 0


def pool_key(label: str) -> str:
    """Membership key for pool merging and validation.

    Reuses `config.canonical_tag` — the project's global spelling-collapser, already
    applied to every `Bullet.tag` at load time — rather than `facets.labels_are_equivalent`,
    which is deliberately NOT used for pool merging: its token-set/prefix-containment
    branches would collapse "retrieval" into "hybrid retrieval & reranking" and destroy a
    distinct pasteable claim, exactly what `rename_preserves_claim` exists to prevent
    elsewhere. Fuzzy relation belongs in JD *matching* (`_match_keyword`), never in set
    construction: membership needs a decidable answer for "the model cannot invent a
    skill" to be checkable at all.
    """
    return config.canonical_tag(_norm_ws(label))


def build_pool(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    limit: int | None = None,
) -> list[SkillCandidate]:
    """Build the closed set of skills the model may choose from.

    Merges four evidence sources on `pool_key` exact equality: skills-group items,
    `Project.tech`, `Education.coursework`, and every bullet tag. Compounds
    ("Python/FastAPI") are never split — that would mint a label the user never wrote.

    `ListItem.tags` (certifications/awards sections) are deliberately excluded, matching
    `report.diagnose_gaps`'s own evidence universe — the two are kept in lockstep so a
    skill this pool offers and a gap `diagnose_gaps` reports never talk about different
    evidence.

    JD-matched candidates sort first, so a `limit` truncation can only ever drop
    unmatched evidence, never something the posting actually asked for.
    """
    limit = limit if limit is not None else config.SKILLS_POOL_LIMIT
    observations: dict[str, list[tuple[int, str, str]]] = {}
    order: dict[str, int] = {}
    bullet_counts: dict[str, int] = {}

    def observe(raw_label: str, rank: int, source: str) -> None:
        key = pool_key(raw_label)
        if not key:
            return
        if key not in order:
            order[key] = len(order)
        observations.setdefault(key, []).append((rank, raw_label, source))

    for group in resume.skills:
        for item in group.items:
            observe(item, _SOURCE_RANK["skills"], f"skills:{group.label}")
    for proj in resume.projects:
        for tech in proj.tech:
            observe(tech, _SOURCE_RANK["project"], f"project:{proj.id}")
    for edu in resume.education:
        for course in edu.coursework:
            observe(course, _SOURCE_RANK["coursework"], "coursework")
    for bullet in resume.all_bullets():
        for tag in bullet.tags:
            key = pool_key(tag)
            if key:
                bullet_counts[key] = bullet_counts.get(key, 0) + 1
            observe(tag, _SOURCE_RANK["tag"], "tag")

    jd_keys = {kw.canonical for kw in requirements.keywords}

    candidates: list[SkillCandidate] = []
    for key, obs in observations.items():
        best_rank, label, _ = min(obs, key=lambda o: o[0])
        sources = tuple(dict.fromkeys(s for _, _, s in obs))
        candidates.append(
            SkillCandidate(
                key=key,
                label=label,
                sources=sources,
                bullet_count=bullet_counts.get(key, 0),
            )
        )

    candidates.sort(
        key=lambda c: (
            0 if c.key in jd_keys else 1,
            _SOURCE_RANK.get(c.sources[0].split(":", 1)[0], 9) if c.sources else 9,
            -c.bullet_count,
            order[c.key],
        )
    )
    return candidates[:limit]


def _format_pool(pool: list[SkillCandidate]) -> str:
    """Group the pool by source for the prompt, so a truncation-order bias never shows."""
    from_skills = [c for c in pool if any(s.startswith("skills:") for s in c.sources)]
    from_projects = [c for c in pool if any(s.startswith("project:") for s in c.sources)]
    from_coursework = [c for c in pool if "coursework" in c.sources]
    from_tags = [c for c in pool if "tag" in c.sources]

    def block(title: str, items: list[SkillCandidate], *, show_count: bool = False) -> str:
        if not items:
            return f"<{title}>\n  (none)\n</{title}>"
        lines = []
        for c in items:
            suffix = f" ({c.bullet_count} bullets)" if show_count and c.bullet_count else ""
            lines.append(f"  - {c.label}{suffix}")
        return f"<{title}>\n" + "\n".join(lines) + f"\n</{title}>"

    return "\n\n".join(
        [
            block("from_skills_section", from_skills),
            block("from_project_tech", from_projects),
            block("from_coursework", from_coursework),
            block("from_bullet_tags", from_tags, show_count=True),
        ]
    )


def _cache_path(
    pool: list[SkillCandidate],
    requirements: JobRequirements,
    *,
    limit: int,
) -> Path:
    """Cache key covering prompt version, backend, JD, and the pool itself.

    `TAG_ALIASES` needs no separate fingerprint entry: it determines every `c.key`, and
    the keys are already in the payload, so an alias-table edit self-invalidates.
    """
    payload = "\n".join(
        [
            str(_SKILLS_PROMPT_VERSION),
            config.fingerprint("skills"),
            str(limit),
            requirements.model_dump_json(),
            *(f"{c.key}\t{c.label}\t{','.join(c.sources)}" for c in pool),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.skills.json"


def _prefer_must_have(keywords: list[Keyword]) -> Keyword:
    """Among several matching keywords, prefer the must-have (and the first one)."""
    must_haves = [k for k in keywords if k.importance == "must_have"]
    return must_haves[0] if must_haves else keywords[0]


def _match_keyword(candidate: SkillCandidate, requirements: JobRequirements) -> Keyword | None:
    """Find the JD keyword `candidate` supports, exact match preferred over fuzzy.

    Two passes so an exact canonical hit always wins over a fuzzy one regardless of
    keyword order — `labels_are_equivalent` is the same spelling-variance matcher
    `report.diagnose_gaps` uses for its near-miss/untagged-evidence checks, reused here
    rather than forked.
    """
    exact = [kw for kw in requirements.keywords if kw.canonical == candidate.key]
    if exact:
        return _prefer_must_have(exact)
    fuzzy = [
        kw
        for kw in requirements.keywords
        if labels_are_equivalent(kw.canonical, candidate.label)
        or labels_are_equivalent(kw.phrase, candidate.label)
    ]
    return _prefer_must_have(fuzzy) if fuzzy else None


def _tier_for(match: Keyword | None) -> Literal["required", "preferred", "additional"]:
    if match is None:
        return "additional"
    return "required" if match.importance == "must_have" else "preferred"


def _accept(
    raw: list[SelectedSkillLLM],
    pool: list[SkillCandidate],
    requirements: JobRequirements,
) -> tuple[list[SkillSuggestion], list[str]]:
    """Validate model output against the pool, apply the display-rename guard, tier it.

    Returns `(suggestions, warnings)`. A skill outside the pool is dropped, never fatal.
    Force-includes any pool candidate whose key exactly equals a must-have keyword's
    canonical and that the model omitted — mirroring `expand.choose_entries`'s `forced`
    set: the tile's worst failure is silently omitting a skill the resume unambiguously
    and exactly claims, and code can catch that for free.
    """
    warnings: list[str] = []
    by_key = {c.key: c for c in pool}
    suggestions: list[SkillSuggestion] = []
    seen: set[str] = set()

    for item in raw:
        key = pool_key(item.skill)
        candidate = by_key.get(key)
        if candidate is None:
            warnings.append(f"skills: dropped unknown skill {item.skill!r}")
            continue
        if key in seen:
            continue
        seen.add(key)

        display = candidate.label
        # Compare against the *label*, not `pool_key`: two spellings that share a pool key
        # (e.g. "Postgres" / "PostgreSQL", both alias to "postgresql") are exactly the case
        # `display` exists to let the model pick between — comparing keys here would treat
        # that as a no-op and silently drop the JD's preferred spelling.
        if item.display.strip() and _norm_ws(item.display) != _norm_ws(candidate.label):
            if (
                rename_is_jd_anchored(item.display, requirements)
                and labels_are_equivalent(candidate.label, item.display)
                and rename_preserves_claim(candidate.label, item.display)
            ):
                display = item.display.strip()
            else:
                warnings.append(
                    f"skills: rejected display {item.display!r} for {candidate.label!r}; "
                    "keeping pool spelling"
                )

        match = _match_keyword(candidate, requirements)
        suggestions.append(
            SkillSuggestion(
                skill=display,
                pool_label=candidate.label,
                tier=_tier_for(match),
                jd_phrase=match.phrase if match else "",
                sources=list(candidate.sources),
                reason=item.reason.strip(),
            )
        )

    for kw in requirements.by_importance("must_have"):
        candidate = by_key.get(kw.canonical)
        if candidate is None or candidate.key in seen:
            continue
        seen.add(candidate.key)
        suggestions.append(
            SkillSuggestion(
                skill=candidate.label,
                pool_label=candidate.label,
                tier="required",
                jd_phrase=kw.phrase,
                sources=list(candidate.sources),
                reason="required by the posting",
            )
        )
        warnings.append(
            f"skills: added {candidate.label!r} — an exact required match the model omitted"
        )

    tier_rank = {"required": 0, "preferred": 1, "additional": 2}
    suggestions.sort(key=lambda s: tier_rank[s.tier])

    if len(suggestions) > config.MAX_SKILLS_SUGGESTED:
        suggestions = suggestions[: config.MAX_SKILLS_SUGGESTED]

    return suggestions, warnings


def paste_line(plan: SkillsPlan) -> str:
    """One comma-separated line, the single highest-value affordance for a Skills field."""
    return ", ".join(s.skill for s in plan.skills)


def format_markdown(plan: SkillsPlan) -> str:
    """Render the plan as plain text for a single copy-all action."""
    if not plan.skills:
        return ""
    lines = [paste_line(plan), ""]
    for tier in ("required", "preferred", "additional"):
        tier_items = [s for s in plan.skills if s.tier == tier]
        if not tier_items:
            continue
        lines.append(f"{tier.capitalize()}:")
        for s in tier_items:
            suffix = f" — {s.jd_phrase}" if s.jd_phrase else ""
            lines.append(f"  - {s.skill}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip()


def select_skills(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    limit: int | None = None,
    use_cache: bool = True,
    on_event: events.ProgressCallback | None = None,
) -> SkillsPlan:
    """Select and rank skills to enter for this posting from the resume's own evidence.

    Selection pool and tiering are deterministic. The LLM call is one batched request.
    Fabrication is structurally impossible rather than guarded after the fact: the model
    can only return pool labels, and anything else is dropped in `_accept`.
    """
    model_label = config.backend_for("skills").label()
    pool = build_pool(resume, requirements, limit=limit)

    if not pool:
        events.emit(on_event, "skills", "No skill evidence to select from")
        return SkillsPlan(skills=[], warnings=[], model=model_label, pool_size=0)

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(pool, requirements, limit=limit or config.SKILLS_POOL_LIMIT)
    llm_result: SkillsSelectionLLM | None = None

    if use_cache and cache_path.exists():
        events.emit(on_event, "skills", "Reusing cached skills selection", cached=True)
        llm_result = SkillsSelectionLLM.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )
    else:
        events.emit(
            on_event,
            "skills",
            f"Selecting skills to enter from {len(pool)} candidates",
            cached=False,
            pool=len(pool),
            model=config.model_for("skills"),
        )
        notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
        keyword_lines = "\n".join(
            f"  [{'REQUIRED' if kw.importance == 'must_have' else 'preferred'}] "
            f"{kw.phrase} (canonical: {kw.canonical})"
            for kw in requirements.keywords
        ) or "  (none extracted)"
        user = (
            f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
            f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n"
            f"<skills_the_posting_asks_for>\n{keyword_lines}\n"
            f"</skills_the_posting_asks_for>\n\n"
            f"<skill_pool>\n{_format_pool(pool)}\n</skill_pool>"
        )
        client = llm.client_for("skills")
        response = client.messages.parse(
            model=config.model_for("skills"),
            max_tokens=config.max_tokens_for("skills"),
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=SkillsSelectionLLM,
            output_config={"effort": config.effort_for("skills")},
        )
        llm_result = response.parsed_output
        if llm_result is None:
            raise RuntimeError(
                f"Model did not return a parseable skills selection "
                f"(stop_reason={response.stop_reason!r})."
            )
        # Cache only pool-resident keys, so a hallucinated skill cannot poison a later
        # reuse (the same discipline `expand._cache_path` uses) — but keep the model's
        # full, unpruned output for `_accept` below, so the fresh call still produces a
        # "dropped unknown skill" warning. A cache *hit* therefore reports fewer drop
        # warnings than the fresh run that populated it, exactly as `expand` does.
        by_key = {c.key: c for c in pool}
        to_cache = SkillsSelectionLLM(
            selected=[s for s in llm_result.selected if pool_key(s.skill) in by_key]
        )
        cache_path.write_text(to_cache.model_dump_json(indent=2), encoding="utf-8")

    suggestions, warnings = _accept(llm_result.selected, pool, requirements)
    return SkillsPlan(
        skills=suggestions,
        warnings=warnings,
        model=model_label,
        pool_size=len(pool),
    )
