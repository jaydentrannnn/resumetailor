"""Resolving the model's facet selection against the resume's own pools (pure)."""

from __future__ import annotations

from .. import config
from ..content.data import MasterResume, Project, SkillGroup
from . import facets_budget, facets_labels, facets_models
from .jd import JobRequirements


def _pool_lookup(pool: list[str]) -> dict[str, str]:
    """Map normalised label -> original pool spelling (first wins)."""
    out: dict[str, str] = {}
    for item in pool:
        key = facets_labels._norm_ws(item)
        if key and key not in out:
            out[key] = item
    return out

def _resolve_project_tech(
    proj: Project,
    proposal: facets_models.ProjectTech | None,
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
        rename_map = {facets_labels._norm_ws(k): v for k, v in proposal.renamed.items()}
        for raw in proposal.tech:
            key = facets_labels._norm_ws(raw)
            # Accept either the pool spelling or a proposed rename target that maps back.
            original = pool_map.get(key)
            if original is None:
                # Model returned the renamed form in `tech`; find via renamed values.
                for src_key, dst in rename_map.items():
                    if facets_labels._norm_ws(dst) == key and src_key in pool_map:
                        original = pool_map[src_key]
                        break
            if original is None:
                warnings.append(
                    f"facets: dropped unknown tech {raw!r} for project {proj.id!r}"
                )
                continue

            display = original
            new_label = rename_map.get(facets_labels._norm_ws(original))
            if new_label and facets_labels._norm_ws(new_label) != facets_labels._norm_ws(original):
                if facets_labels.rename_is_jd_anchored(
                    new_label, requirements
                ) and facets_labels.labels_are_equivalent(original, new_label):
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

    budget = facets_budget.project_header_tech_budget(
        proj, include_project_links=include_project_links
    )
    return facets_budget.fit_tech_to_budget(ordered_originals, budget)

def _resolve_coursework(
    pool: list[str],
    proposed: list[str],
    warnings: list[str],
    requirements: JobRequirements | None = None,
) -> list[str]:
    """Validate coursework against the pool and trim to the two-line budget."""
    pool_map = _pool_lookup(pool)
    ordered: list[str] = []
    for raw in proposed:
        key = facets_labels._norm_ws(raw)
        original = pool_map.get(key)
        if original is None:
            warnings.append(f"facets: dropped unknown coursework {raw!r}")
            continue
        if original not in ordered:
            ordered.append(original)
    if not ordered:
        ordered = list(pool)
    return facets_budget.fit_coursework_to_budget(
        ordered, pool=pool,
        jd_keywords=[k.phrase for k in requirements.keywords] if requirements else [],
    )

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
        new_label = renames.get(facets_labels._norm_ws(original))
        if not new_label or facets_labels._norm_ws(new_label) == facets_labels._norm_ws(original):
            continue
        if not (
            facets_labels.rename_is_jd_anchored(new_label, requirements)
            and facets_labels.labels_are_equivalent(original, new_label)
            and facets_labels.rename_preserves_claim(original, new_label)
        ):
            warnings.append(
                f"facets: rejected skill rename {original!r} -> {new_label!r} "
                f"in group {group.label!r}; keeping original"
            )
            continue
        if any(
            facets_labels._norm_ws(x) == facets_labels._norm_ws(new_label)
            for j, x in enumerate(items)
            if j != i
        ):
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
    raw: facets_models.FacetSelection | None,
    requirements: JobRequirements,
    *,
    include_project_links: bool = True,
) -> facets_models.FacetResult:
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
        requirements,
    )

    skill_renames = {
        facets_labels._norm_ws(k): v for k, v in (raw.skill_renames if raw else {}).items()
    }
    skills = [
        _resolve_skill_group(group, skill_renames, requirements, warnings=warnings)
        for group in resume.skills
    ]
    matched_keys = {
        facets_labels._norm_ws(item) for group in resume.skills for item in group.items
    }
    for key in skill_renames:
        if key and key not in matched_keys:
            warnings.append(f"facets: skill rename key {key!r} matched no item; ignored")

    return facets_models.FacetResult(
        projects=projects, coursework=coursework, coursework_pool=coursework_pool,
        skills=skills, warnings=warnings
    )
