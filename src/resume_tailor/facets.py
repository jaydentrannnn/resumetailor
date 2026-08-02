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
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, events, llm
from .data import MasterResume, Project, SkillGroup
from .jd import JobRequirements

#: Bumped when `_SYSTEM` or the facets request/response shape changes.
_PROMPT_VERSION = 2

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
    #: Optional renames: exact skill item (any group) -> posting wording. Guarded in code.
    #: Flat map rather than per-group like `ProjectTech.renamed` because nothing is
    #: *selected* for skills — only wording may change — so there is no per-group id to
    #: key on, and items are unique across groups in practice.
    skill_renames: dict[str, str] = Field(default_factory=dict)


@dataclass
class FacetResult:
    """Validated, budget-trimmed facet choices ready to apply to a resume."""

    projects: dict[str, list[str]] = field(default_factory=dict)
    coursework: list[str] = field(default_factory=list)
    #: One entry per `resume.skills` group, same order. Positional (not keyed by label)
    #: since `SkillGroup` has no id and `label` is not guaranteed unique.
    skills: list[list[str]] = field(default_factory=list)
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


def _aligns(a: str, b: str) -> bool:
    """True when every word of `a` maps in order onto `b`, expanding acronyms.

    Greedy left-to-right: a word matches a `b` word by prefix either way, or a run of
    2-5 `b` words whose initials spell it ("RAG" -> "retrieval augmented generation").
    Requires BOTH sides fully consumed, so alignment can never drop a claim — that is
    why `rename_preserves_claim` can short-circuit on it.
    """
    a_words = [w.lower() for w in _WORDS_ONLY.findall(a)]
    b_words = [w.lower() for w in _WORDS_ONLY.findall(b)]
    i = j = 0
    while i < len(a_words) and j < len(b_words):
        word = a_words[i]
        if b_words[j] == word or b_words[j].startswith(word) or word.startswith(b_words[j]):
            i += 1
            j += 1
            continue
        matched = False
        for n in _INITIALISM_LENGTHS:
            if j + n > len(b_words):
                continue
            if "".join(w[0] for w in b_words[j : j + n]) == word:
                i += 1
                j += n
                matched = True
                break
        if not matched:
            return False
    return i == len(a_words) and j == len(b_words)


def labels_are_equivalent(old: str, new: str) -> bool:
    """True when `new` names the same technology as `old` under the rename rules.

    Accepts: identical after ``canonical_tag``, acronym expansion either way, alphanumeric
    *prefix* containment either way, full token-set containment either way, or a full
    word-by-word alignment that expands an acronym embedded in a longer phrase (``RAG
    pipelines`` <-> ``retrieval-augmented generation pipelines``).
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

    # Whole-phrase alignment: an acronym embedded alongside other words, not just the
    # entire label (LLM fine-tuning <-> large language model fine-tuning).
    if _aligns(old, new) or _aligns(new, old):
        return True
    return False


#: Characters that join *distinct* claims inside one label. "." "-" "+" "#" are internal
#: to a single name (Next.js, scikit-learn, C++) and are deliberately NOT split on.
_CLAIM_SPLIT = re.compile(r"[\s/&,;]+")


def _claim_parts(text: str) -> list[str]:
    """Split `text` into distinct claims for `rename_preserves_claim`."""
    return [p for p in _CLAIM_SPLIT.split(text) if p]


def rename_preserves_claim(old: str, new: str) -> bool:
    """True when `new` does not drop anything `old` claims (the "not less" guard).

    `labels_are_equivalent` alone accepts token-set containment, alphanumeric prefix
    containment, and sub-phrase acronyms — all safe for single-word project tags but
    unsafe for skill *phrases*, where each lets a rename narrow to part of what the item
    claims (``"hybrid retrieval & reranking" -> "retrieval"``,
    ``"Scikit-learn/XGBoost" -> "scikit-learn"``, ``"hybrid retrieval & reranking" ->
    "HR"``). This is deliberately a separate predicate rather than a flag on
    `labels_are_equivalent`, since narrowing arrives via three different branches there
    and a single flag cannot close all three without also touching project-tag behaviour.
    """
    if _aligns(old, new) or _aligns(new, old):
        return True  # full word-by-word coverage either way: nothing dropped
    if len(_claim_parts(old)) <= 1:
        return True  # a single claim cannot lose a claim by being respelled
    new_tokens = _token_set(new)
    return all(
        any(t == word or t.startswith(word) for t in new_tokens)
        for word in _token_set(old)
    )


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


def _resolve_skill_group(
    group: SkillGroup,
    renames: dict[str, str],
    requirements: JobRequirements,
    *,
    warnings: list[str],
) -> list[str]:
    """Reword items in one skills group, never adding/dropping/reordering any.

    Greedy: each accepted rename is re-measured against the *accumulated* item list, so
    several individually-safe renames cannot jointly push the group over its line budget.
    """
    baseline = config.line_span(config.skill_group_line(group.label, group.items))
    items = list(group.items)
    for i, original in enumerate(group.items):
        new_label = renames.get(_norm_ws(original))
        if not new_label or _norm_ws(new_label) == _norm_ws(original):
            continue
        if not (
            rename_is_jd_anchored(new_label, requirements)
            and labels_are_equivalent(original, new_label)
            and rename_preserves_claim(original, new_label)
        ):
            warnings.append(
                f"facets: rejected skill rename {original!r} -> {new_label!r} "
                f"in group {group.label!r}; keeping original"
            )
            continue
        if any(_norm_ws(x) == _norm_ws(new_label) for j, x in enumerate(items) if j != i):
            warnings.append(
                f"facets: skipped skill rename {original!r} -> {new_label!r} "
                f"in group {group.label!r}; would duplicate an existing item"
            )
            continue
        candidate = items[:i] + [new_label] + items[i + 1 :]
        if config.line_span(config.skill_group_line(group.label, candidate)) > baseline:
            warnings.append(
                f"facets: skipped skill rename {original!r} -> {new_label!r} "
                f"in group {group.label!r}; it would add a line"
            )
            continue
        items = candidate
    return items


def finalise_selection(
    resume: MasterResume,
    raw: FacetSelection | None,
    requirements: JobRequirements,
    *,
    include_project_links: bool = True,
) -> FacetResult:
    """Turn model output (or None) into budget-safe tech/coursework/skills lists."""
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

    skill_renames = {_norm_ws(k): v for k, v in (raw.skill_renames if raw else {}).items()}
    skills = [
        _resolve_skill_group(group, skill_renames, requirements, warnings=warnings)
        for group in resume.skills
    ]
    matched_keys = {
        _norm_ws(item) for group in resume.skills for item in group.items
    }
    for key in skill_renames:
        if key and key not in matched_keys:
            warnings.append(f"facets: skill rename key {key!r} matched no item; ignored")

    return FacetResult(
        projects=projects, coursework=coursework, skills=skills, warnings=warnings
    )


def apply(
    resume: MasterResume,
    result: FacetResult,
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

    for group, items in zip(copy.skills, result.skills):
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
            f"{_COURSEWORK_PREFIX!r} prefix).\n\n"
            f"<skill_groups>\n{_format_skills(resume)}\n</skill_groups>"
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
