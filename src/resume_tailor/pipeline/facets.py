"""JD-driven selection of project tech tags, education coursework, and skill wording.

A fifth cached LLM stage (purpose ``facets``). The model chooses *which* tags and courses
best fit the posting, and may reword skill-group items toward the posting's own wording;
pure code then enforces the line budgets so a project header always fits one line,
coursework always fits two, and a skills group never grows past its current line count.
Skipping the LLM still runs the budget truncation over each pool in its original order,
leaving skill items unrenamed.

Called once per run, before the fit loop — same placement as ``rewrite.score_table``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import config
from ..content import industries
from ..content.data import MasterResume
from ..infra import llm, telemetry
from . import events, facets_budget, facets_models, facets_resolve
from .jd import JobRequirements

#: Bumped when `_SYSTEM` or the facets request/response shape changes.
_PROMPT_VERSION = 3


_SYSTEM = """\
You select which project technology labels and which coursework titles to show on a \
resume tailored to one specific job posting.

You are GIVEN the candidate pools. You may only choose from those pools — never invent \
a technology or course that is not listed.

Project tech:
- For EACH project, pick the labels that best match the posting's skills and domain.
- Order them best-first (most relevant first). Code will keep only as many as fit one \
header line, capped at four, so ordering matters.
- You may rename a chosen label to the posting's own wording ONLY when the two name the \
same technology (e.g. "Postgres" -> "PostgreSQL", "k8s" -> "Kubernetes"). Put the \
original pool label as the key and the JD wording as the value in `renamed`. Do not \
rename toward a more specific product the pool does not claim (e.g. never "SQL" -> \
"Snowflake").
- Prefer fewer strong matches over padding with weakly related tags.

Coursework:
- Pick course titles from the supplied list that best support this role.
- Order best-first. Keep original titles exactly — no renaming.
- Prefer courses that demonstrate skills the posting asks for.

Skills:
- Every skill group and every item in it always shows — you are never adding, dropping, \
or reordering skill items, only rewording individual items when useful.
- You may reword a skill item to the posting's exact wording ONLY when the two name the \
same thing (e.g. "Postgres" -> "PostgreSQL", "RAG pipelines" -> "retrieval-augmented \
generation pipelines", "fuzzy matching" -> "fuzzy string matching").
- Never drop part of what an item claims. Do not shorten a multi-part item to one of its \
parts (never "hybrid retrieval & reranking" -> "retrieval", never \
"Scikit-learn/XGBoost" -> "scikit-learn") and do not abbreviate a phrase down to initials.
- Each skill group has a character budget for its whole rendered line. A reword that would \
push the group over budget is discarded, so prefer rewords no longer than the original and \
skip ones that clearly won't fit.
- Return `skill_renames` as a flat map of exact original item text -> new wording, covering \
only the items you are rewording. Leave it empty if nothing in the posting matches.

Return one `projects` entry per input project id. Return `coursework` as a list of \
exact titles from the pool (empty if none fit).
"""


def apply(
    resume: MasterResume,
    result: facets_models.FacetResult,
) -> MasterResume:
    """Return a deep copy of `resume` with tech, coursework, and skills replaced by `result`.

    Education entries share one coursework selection (the posting gets one coursework
    bullet). The trimmed list is written onto the first education entry that has a
    non-empty pool; others keep theirs only if they had no pool to begin with. Skills are
    positional — `result.skills[i]` replaces `copy.skills[i].items` — since `SkillGroup`
    has no id and `zip` degrades safely if a hand-built `FacetResult` omits skills.
    """
    copy = resume.model_copy(deep=True)
    for proj in copy.projects:
        if proj.id in result.projects:
            proj.tech = list(result.projects[proj.id])

    assigned = False
    for edu in copy.education:
        if not edu.coursework:
            continue
        if not assigned:
            edu.coursework = list(result.coursework)
            assigned = True
        else:
            # Secondary education blocks: clear so we do not duplicate the line.
            edu.coursework = []

    for group, items in zip(copy.skills, result.skills, strict=False):
        group.items = list(items)
    return copy


def _cache_path(resume: MasterResume, requirements: JobRequirements) -> Path:
    """Cache key covering prompt, backend, JD, every candidate pool, and the char budget.

    `CHARS_PER_LINE` is included because the prompt advertises per-project and per-group
    character budgets computed from it — recalibration changes what the model is told to
    optimise for, so it must invalidate cached selections the same way a prompt edit does.
    """
    pool_lines: list[str] = []
    for proj in resume.projects:
        pool_lines.append(f"{proj.id}\t{','.join(proj.tech)}")
    for edu in resume.education:
        pool_lines.append(f"coursework\t{','.join(edu.coursework)}")
    for group in resume.skills:
        pool_lines.append(f"skills:{group.label}\t{','.join(group.items)}")
    payload = "\n".join(
        [
            str(_PROMPT_VERSION),
            config.fingerprint("facets"),
            str(config.CHARS_PER_LINE),
            requirements.model_dump_json(),
            *pool_lines,
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.facets.json"


def _format_keywords(requirements: JobRequirements) -> str:
    """One keyword per line for the facets user message."""
    lines = []
    for kw in requirements.keywords:
        marker = "REQUIRED" if kw.importance == "must_have" else "preferred"
        lines.append(f"  [{marker}] {kw.phrase} (canonical: {kw.canonical})")
    return "\n".join(lines) or "  (none extracted)"


def _format_projects(resume: MasterResume, *, include_project_links: bool) -> str:
    """XML-ish project pools with per-project character budgets for the prompt."""
    blocks: list[str] = []
    for proj in resume.projects:
        budget = facets_budget.project_header_tech_budget(
            proj, include_project_links=include_project_links
        )
        pool = ", ".join(proj.tech) or "(empty)"
        blocks.append(
            f"<project id={proj.id!r} name={proj.name!r} "
            f"tech_char_budget={budget} max_tags={config.MAX_PROJECT_TECH}>\n"
            f"  <tech_pool>{pool}</tech_pool>\n"
            f"</project>"
        )
    return "\n".join(blocks) or "  (no projects)"


def _format_coursework_pool(resume: MasterResume) -> str:
    """Comma-joined coursework candidates for the prompt."""
    courses: list[str] = []
    for edu in resume.education:
        courses.extend(edu.coursework)
    if not courses:
        return "  (none)"
    return "\n".join(f"  - {c}" for c in courses)


def _format_skills(resume: MasterResume) -> str:
    """XML-ish skill-group pools with per-group character budgets for the prompt.

    `max_chars` is `line_span(current) * CHARS_PER_LINE` — the exact ceiling
    `_resolve_skill_group` enforces, not padded with `WIDOW_SAFETY` (that constant is for
    bullet widows; advertising a different number here would let prompt and code disagree).
    """
    blocks: list[str] = []
    for group in resume.skills:
        current = config.skill_group_line(group.label, group.items)
        max_chars = config.line_span(current) * config.CHARS_PER_LINE
        items = "\n".join(f"    - {item}" for item in group.items) or "    (empty)"
        blocks.append(
            f"<skill_group label={group.label!r} "
            f"current_chars={len(current)} max_chars={max_chars}>\n{items}\n</skill_group>"
        )
    return "\n".join(blocks) or "  (no skill groups)"


@telemetry.stage("facets")
def select_facets(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    use_cache: bool = True,
    include_project_links: bool = True,
    on_event: events.ProgressCallback | None = None,
) -> facets_models.FacetResult:
    """Ask the model which tech tags and coursework to show; enforce budgets in code.

    On cache hit or successful parse, returns a ``FacetResult``. LLM failures propagate
    as ``LLMError`` / ``RuntimeError`` for the caller to decide (CLI warns and falls
    back to budget-only truncation).
    """
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(resume, requirements)
    raw: facets_models.FacetSelection | None = None

    if use_cache and cache_path.exists():
        events.emit(on_event, "facets", "Reusing cached facet selection", cached=True)
        raw = facets_models.FacetSelection.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )
    else:
        events.emit(
            on_event,
            "facets",
            "Selecting project tech and coursework for this posting",
            cached=False,
            projects=len(resume.projects),
            model=config.model_for("facets"),
        )
        notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
        user = (
            f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
            f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n"
            f"<skills_the_posting_asks_for>\n{_format_keywords(requirements)}\n"
            f"</skills_the_posting_asks_for>\n\n"
            f"<projects>\n{_format_projects(resume, include_project_links=include_project_links)}\n"
            f"</projects>\n\n"
            f"<coursework_pool>\n{_format_coursework_pool(resume)}\n</coursework_pool>\n\n"
            f"Coursework joined-list character budget: {facets_budget.coursework_char_budget()} "
            f"(must fit {config.COURSEWORK_MAX_LINES} lines including the "
            f"{facets_budget._COURSEWORK_PREFIX!r} prefix).\n\n"
            f"<skill_groups>\n{_format_skills(resume)}\n</skill_groups>"
        )

        client = llm.client_for("facets")
        response = client.messages.parse(
            model=config.model_for("facets"),
            max_tokens=config.max_tokens_for("facets"),
            system=industries.system("facets", _SYSTEM),
            messages=[{"role": "user", "content": user}],
            output_format=facets_models.FacetSelection,
            output_config={"effort": config.effort_for("facets")},
        )
        raw = response.parsed_output
        if raw is None:
            raise RuntimeError(
                f"Model did not return parseable facet selection "
                f"(stop_reason={response.stop_reason!r})."
            )
        cache_path.write_text(raw.model_dump_json(indent=2), encoding="utf-8")

    return facets_resolve.finalise_selection(
        resume,
        raw,
        requirements,
        include_project_links=include_project_links,
    )


def budget_only(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    include_project_links: bool = True,
) -> facets_models.FacetResult:
    """Trim pools in original order without calling the model (``--no-facets`` path)."""
    return facets_resolve.finalise_selection(
        resume,
        None,
        requirements,
        include_project_links=include_project_links,
    )
