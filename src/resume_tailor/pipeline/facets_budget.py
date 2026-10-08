"""Line budgets for project tech and coursework, and fitting a selection to them (pure)."""

from __future__ import annotations

import math

from .. import config
from ..content.data import Project
from ..document.render import project_date
from . import facets_labels

#: Prefix of the coursework bullet; subtracted from the two-line character budget.
_COURSEWORK_PREFIX = "Relevant Coursework: "

def project_header_tech_budget(
    proj: Project,
    *,
    include_project_links: bool = True,
) -> int:
    """Usable character width for the tech list on one project header line.

    Layout is `{name} | {tech}{link}` with `{date}` right-aligned after a tab. The date
    still consumes horizontal space in the character-budget approximation used here.
    `config.project_header_chars` is the measured header width; the rendered header is
    still checked afterwards (`fit_shrink.header_pass`).
    """
    return max(0, config.project_header_chars() - header_overhead(
        proj, include_project_links=include_project_links,
    ))


def header_overhead(proj: Project, *, include_project_links: bool = True) -> int:
    """Characters a project header spends on everything but its tech list."""
    link_suffix = ""
    if include_project_links and proj.link:
        link_suffix = f" | {proj.link}"
    return len(proj.name) + len(" | ") + len(link_suffix) + len(project_date(proj))


def header_text(proj: Project, *, include_project_links: bool = True) -> str:
    """The project header line as rendered (`render.build_context`), tab as a space."""
    text = proj.name
    if proj.tech:
        text += " | " + ", ".join(proj.tech)
    if include_project_links and proj.link:
        text += " | " + proj.link
    return f"{text} {project_date(proj)}".rstrip()

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
    *,
    pool: list[str] | None = None,
    jd_keywords: list[str] | None = None,
    chars_per_line: float | None = None,
    last_fill: float | None = None,
    rendered_lines: int | None = None,
) -> list[str]:
    """Fill coursework from its source pool, then trim a stranded short final line."""
    span = chars_per_line or config.CHARS_PER_LINE
    limit = (coursework_char_budget() if budget is None else budget)
    if chars_per_line is not None and budget is None:
        limit = max(0, int(config.COURSEWORK_MAX_LINES * span - len(_COURSEWORK_PREFIX)
                           - config.WIDOW_SAFETY))
    source_pool = list(dict.fromkeys(pool if pool is not None else ordered))
    keyword_words = facets_labels._token_set(" ".join(jd_keywords or []))
    remainder = [course for course in source_pool if course not in ordered]
    remainder.sort(key=lambda course: -len(facets_labels._token_set(course) & keyword_words))
    ordered = list(dict.fromkeys(course for course in ordered if course in source_pool))
    # Translate the measured physical fill into equivalent character capacity.
    # Retaining this offset while adding/removing courses keeps the baseline tied
    # to the PDF rather than replacing its short-line measurement with len % width.
    offset = 0.0
    if last_fill is not None and rendered_lines is not None and ordered:
        offset = ((rendered_lines - 1 + last_fill) * span
                  - len(_COURSEWORK_PREFIX + ", ".join(ordered)))

    def length(courses: list[str]) -> float:
        return len(_COURSEWORK_PREFIX + ", ".join(courses)) + offset if courses else 0

    def fill(courses: list[str]) -> float:
        remainder_chars = length(courses) % span
        return (remainder_chars / span) if remainder_chars else 1.0

    kept: list[str] = []
    for course in ordered:
        if not course or course in kept:
            continue
        candidate = kept + [course]
        if length(candidate) > len(_COURSEWORK_PREFIX) + limit:
            continue
        kept = candidate
    if kept and math.ceil(length(kept) / span) > 1 and fill(kept) < 0.50:
        for course in ordered + remainder:
            if not course or course in kept:
                continue
            candidate = kept + [course]
            if length(candidate) > len(_COURSEWORK_PREFIX) + limit:
                continue
            kept = candidate
            if fill(kept) >= 0.80:
                break
    if kept and fill(kept) < 0.50:
        original_lines = math.ceil(length(kept) / span)
        if original_lines > 1:
            while kept and math.ceil(length(kept) / span) >= original_lines:
                kept.pop()
    return kept
