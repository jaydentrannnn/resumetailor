"""JD-driven selection of project tech tags and education coursework.

A fifth cached LLM stage (purpose ``facets``). The model chooses *which* tags and
courses best fit the posting; pure code then enforces the line budgets so a project
header always fits one line and coursework always fits two. Skipping the LLM still
runs the budget truncation over each pool in its original order.

Called once per run, before the fit loop — same placement as ``rewrite.score_table``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, events, llm
from .data import MasterResume, Project
from .jd import JobRequirements

#: Bumped when `_SYSTEM` or the facets request/response shape changes.
_PROMPT_VERSION = 1

#: Prefix of the coursework bullet; subtracted from the two-line character budget.
_COURSEWORK_PREFIX = "Relevant Coursework: "

#: Word tokens for acronym / containment checks (letters and digits only).
_WORDS_ONLY = re.compile(r"[A-Za-z0-9]+")

#: Acronym lengths considered when expanding consecutive source words.
_INITIALISM_LENGTHS = (2, 3, 4, 5)


class ProjectTech(BaseModel):
    """Chosen tech labels for one project, keyed by project id."""

    id: str
    #: Selected labels, best-first. Must be drawn from that project's pool.
    tech: list[str] = Field(default_factory=list)
    #: Optional renames: original pool label -> JD wording. Guarded in code.
    renamed: dict[str, str] = Field(default_factory=dict)


class FacetSelection(BaseModel):
    """Raw model output before budget truncation and rename validation."""

    projects: list[ProjectTech] = Field(default_factory=list)
    #: Selected coursework titles, best-first. Must be drawn from the education pool.
    coursework: list[str] = Field(default_factory=list)


@dataclass
class FacetResult:
    """Validated, budget-trimmed facet choices ready to apply to a resume."""

    projects: dict[str, list[str]] = field(default_factory=dict)
    coursework: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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

Return one `projects` entry per input project id. Return `coursework` as a list of \
exact titles from the pool (empty if none fit).
"""


def project_header_tech_budget(
    proj: Project,
    *,
    include_project_links: bool = True,
) -> int:
    """Usable character width for the tech list on one project header line.

    Layout is `{name} | {tech}{link}` with `{date}` right-aligned after a tab. The date
    still consumes horizontal space in the character-budget approximation used here.
    """
    link_suffix = ""
    if include_project_links and proj.link:
        link_suffix = f" | {proj.link}"
    return max(
        0,
        config.CHARS_PER_LINE
        - len(proj.name)
        - len(" | ")
        - len(link_suffix)
        - len(proj.date)
        - config.PROJECT_HEADER_GAP,
    )


def coursework_char_budget() -> int:
    """Max characters for the joined coursework list under a two-line bullet."""
    return max(
        0,
        config.COURSEWORK_MAX_LINES * config.CHARS_PER_LINE
        - len(_COURSEWORK_PREFIX)
        - config.WIDOW_SAFETY,
    )


def fit_tech_to_budget(
    ordered: list[str],
    budget: int,
    *,
    max_tags: int | None = None,
) -> list[str]:
    """Keep best-first tags while the joined string fits `budget` and the tag cap."""
    cap = config.MAX_PROJECT_TECH if max_tags is None else max_tags
    kept: list[str] = []
    for tag in ordered:
        if not tag or tag in kept:
            continue
        if len(kept) >= cap:
            break
        candidate = kept + [tag]
        if len(", ".join(candidate)) > budget:
            break
        kept = candidate
    return kept


def fit_coursework_to_budget(
    ordered: list[str],
    budget: int | None = None,
) -> list[str]:
    """Keep best-first courses while 'Relevant Coursework: …' stays within `budget`."""
    limit = coursework_char_budget() if budget is None else budget
    kept: list[str] = []
    for course in ordered:
        if not course or course in kept:
            continue
        candidate = kept + [course]
        if len(", ".join(candidate)) > limit:
            break
        kept = candidate
    return kept


def _norm_ws(text: str) -> str:
    """Lowercase and collapse whitespace for JD anchoring comparisons."""
    return " ".join(text.lower().split())


def _alnum_compact(text: str) -> str:
    """Lowercase alphanumeric-only form for prefix / containment checks."""
    return "".join(_WORDS_ONLY.findall(text.lower()))


def _token_set(text: str) -> set[str]:
    """Lowercase word tokens from `text`."""
    return {w.lower() for w in _WORDS_ONLY.findall(text)}


def _initialisms_from(text: str) -> set[str]:
    """Acronyms formable from consecutive words in `text` (lowercase)."""
    out: set[str] = set()
    words = _WORDS_ONLY.findall(text)
    for n in _INITIALISM_LENGTHS:
        for i in range(len(words) - n + 1):
            out.add("".join(w[0] for w in words[i : i + n]).lower())
    return out


def _jd_anchors(requirements: JobRequirements) -> set[str]:
    """Normalised JD phrases and canonicals a rename may target."""
    anchors: set[str] = set()
    for kw in requirements.keywords:
        if kw.phrase.strip():
            anchors.add(_norm_ws(kw.phrase))
        if kw.canonical.strip():
            anchors.add(_norm_ws(kw.canonical))
    return anchors


def rename_is_jd_anchored(new_label: str, requirements: JobRequirements) -> bool:
    """True when `new_label` matches a JD keyword phrase or canonical."""
    target = _norm_ws(new_label)
    if not target:
        return False
    return target in _jd_anchors(requirements)


def labels_are_equivalent(old: str, new: str) -> bool:
    """True when `new` names the same technology as `old` under the rename rules.

    Accepts: identical after ``canonical_tag``, acronym expansion either way, alphanumeric
    *prefix* containment either way, or full token-set containment either way.
    Rejects substring-only matches (so ``SQL`` does not license ``MySQL``).
    """
    if not old.strip() or not new.strip():
        return False
    if config.canonical_tag(old) == config.canonical_tag(new):
        return True

    old_n, new_n = _norm_ws(old), _norm_ws(new)
    if old_n == new_n:
        return True

    # Acronym: GRPO <-> Group Relative Policy Optimization (either direction).
    old_acro = _alnum_compact(old)
    new_acro = _alnum_compact(new)
    if len(old_acro) >= 2 and old_acro in _initialisms_from(new):
        return True
    if len(new_acro) >= 2 and new_acro in _initialisms_from(old):
        return True

    # Prefix containment on alphanumerics (postgres / postgresql), not bare substring.
    if old_acro and new_acro:
        if old_acro.startswith(new_acro) or new_acro.startswith(old_acro):
            return True

    old_tokens, new_tokens = _token_set(old), _token_set(new)
    if old_tokens and new_tokens:
        if old_tokens <= new_tokens or new_tokens <= old_tokens:
            return True
    return False


def _pool_lookup(pool: list[str]) -> dict[str, str]:
    """Map normalised label -> original pool spelling (first wins)."""
    out: dict[str, str] = {}
    for item in pool:
        key = _norm_ws(item)
        if key and key not in out:
            out[key] = item
    return out


def _resolve_project_tech(
    proj: Project,
    proposal: ProjectTech | None,
    requirements: JobRequirements,
    *,
    include_project_links: bool,
    warnings: list[str],
) -> list[str]:
    """Validate, rename-guard, and budget-trim tech for one project."""
    pool_map = _pool_lookup(proj.tech)
    ordered_originals: list[str] = []

    if proposal is None:
        ordered_originals = list(proj.tech)
    else:
        rename_map = {_norm_ws(k): v for k, v in proposal.renamed.items()}
        for raw in proposal.tech:
            key = _norm_ws(raw)
            # Accept either the pool spelling or a proposed rename target that maps back.
            original = pool_map.get(key)
            if original is None:
                # Model returned the renamed form in `tech`; find via renamed values.
                for src_key, dst in rename_map.items():
                    if _norm_ws(dst) == key and src_key in pool_map:
                        original = pool_map[src_key]
                        break
            if original is None:
                warnings.append(
                    f"facets: dropped unknown tech {raw!r} for project {proj.id!r}"
                )
                continue

            display = original
            new_label = rename_map.get(_norm_ws(original))
            if new_label and _norm_ws(new_label) != _norm_ws(original):
                if rename_is_jd_anchored(new_label, requirements) and labels_are_equivalent(
                    original, new_label
                ):
                    display = new_label
                else:
                    warnings.append(
                        f"facets: rejected rename {original!r} -> {new_label!r} "
                        f"for project {proj.id!r}; keeping original"
                    )
            if display not in ordered_originals:
                ordered_originals.append(display)

        if not ordered_originals:
            ordered_originals = list(proj.tech)

    budget = project_header_tech_budget(
        proj, include_project_links=include_project_links
    )
    return fit_tech_to_budget(ordered_originals, budget)


def _resolve_coursework(
    pool: list[str],
    proposed: list[str],
    warnings: list[str],
) -> list[str]:
    """Validate coursework against the pool and trim to the two-line budget."""
    pool_map = _pool_lookup(pool)
    ordered: list[str] = []
    for raw in proposed:
        key = _norm_ws(raw)
        original = pool_map.get(key)
        if original is None:
            warnings.append(f"facets: dropped unknown coursework {raw!r}")
            continue
        if original not in ordered:
            ordered.append(original)
    if not ordered:
        ordered = list(pool)
    return fit_coursework_to_budget(ordered)


def finalise_selection(
    resume: MasterResume,
    raw: FacetSelection | None,
    requirements: JobRequirements,
    *,
    include_project_links: bool = True,
) -> FacetResult:
    """Turn model output (or None) into budget-safe tech/coursework lists."""
    warnings: list[str] = []
    by_id = {p.id: p for p in (raw.projects if raw else [])}
    projects: dict[str, list[str]] = {}
    for proj in resume.projects:
        projects[proj.id] = _resolve_project_tech(
            proj,
            by_id.get(proj.id),
            requirements,
            include_project_links=include_project_links,
            warnings=warnings,
        )

    coursework_pool: list[str] = []
    for edu in resume.education:
        coursework_pool.extend(edu.coursework)
    coursework = _resolve_coursework(
        coursework_pool,
        list(raw.coursework) if raw else [],
        warnings,
    )
    return FacetResult(projects=projects, coursework=coursework, warnings=warnings)


def apply(
    resume: MasterResume,
    result: FacetResult,
) -> MasterResume:
    """Return a deep copy of `resume` with tech and coursework replaced by `result`.

    Education entries share one coursework selection (the posting gets one coursework
    bullet). The trimmed list is written onto the first education entry that has a
    non-empty pool; others keep theirs only if they had no pool to begin with.
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
    return copy


def _cache_path(resume: MasterResume, requirements: JobRequirements) -> Path:
    """Cache key covering prompt, backend, JD, and every candidate pool."""
    pool_lines: list[str] = []
    for proj in resume.projects:
        pool_lines.append(f"{proj.id}\t{','.join(proj.tech)}")
    for edu in resume.education:
        pool_lines.append(f"coursework\t{','.join(edu.coursework)}")
    payload = "\n".join(
        [
            str(_PROMPT_VERSION),
            config.fingerprint("facets"),
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
        budget = project_header_tech_budget(
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


def select_facets(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    use_cache: bool = True,
    include_project_links: bool = True,
    on_event: events.ProgressCallback | None = None,
) -> FacetResult:
    """Ask the model which tech tags and coursework to show; enforce budgets in code.

    On cache hit or successful parse, returns a ``FacetResult``. LLM failures propagate
    as ``LLMError`` / ``RuntimeError`` for the caller to decide (CLI warns and falls
    back to budget-only truncation).
    """
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(resume, requirements)
    raw: FacetSelection | None = None

    if use_cache and cache_path.exists():
        events.emit(on_event, "facets", "Reusing cached facet selection", cached=True)
        raw = FacetSelection.model_validate_json(cache_path.read_text(encoding="utf-8"))
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
            f"Coursework joined-list character budget: {coursework_char_budget()} "
            f"(must fit {config.COURSEWORK_MAX_LINES} lines including the "
            f"{_COURSEWORK_PREFIX!r} prefix)."
        )

        client = llm.client_for("facets")
        response = client.messages.parse(
            model=config.model_for("facets"),
            max_tokens=config.max_tokens_for("facets"),
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=FacetSelection,
            output_config={"effort": config.effort_for("facets")},
        )
        raw = response.parsed_output
        if raw is None:
            raise RuntimeError(
                f"Model did not return parseable facet selection "
                f"(stop_reason={response.stop_reason!r})."
            )
        cache_path.write_text(raw.model_dump_json(indent=2), encoding="utf-8")

    return finalise_selection(
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
) -> FacetResult:
    """Trim pools in original order without calling the model (``--no-facets`` path)."""
    return finalise_selection(
        resume,
        None,
        requirements,
        include_project_links=include_project_links,
    )
