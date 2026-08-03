"""What the tailored resume leaves out — contact fields, GPA, coursework, whole entries.

Pure, no-LLM, code-only — the same shape as `facets.py`'s `apply`: an options model plus a
transform returning a deep copy. Lives in core (not `web/schemas.py`) so `tailor.py` can use
it without importing the web layer.

Applied once, before `facets.select_facets`, so the model never sees pools an excluded
entry or a suppressed GPA/coursework line would have contributed — see CLAUDE.md's
pipeline diagram and the `web/jobs.py` / `tailor.py` call sites for why this specific
placement (after scoring, before facets) matters.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .data import MasterResume
from .template_profile import ContactField


class IncludeOptions(BaseModel):
    """What to leave out of one run. Everything defaults to included."""

    #: Ordered contact-line fields, name excluded — it renders on its own paragraph and
    #: is always first. Omitting a field both hides it and shortens the line (see
    #: `render._contact_richtext`, which iterates exactly this order and skips anything
    #: not listed). `None` keeps the active template profile's order.
    contact_fields: list[ContactField] | None = None
    gpa: bool = True
    coursework: bool = True
    #: Experience ids omitted from this run entirely (see `data.Experience.id`).
    exclude_experience: list[str] = Field(default_factory=list)
    #: Project ids omitted from this run entirely (see `data.Project.id`).
    exclude_projects: list[str] = Field(default_factory=list)


def apply(resume: MasterResume, options: IncludeOptions) -> MasterResume:
    """Return a deep copy of `resume` with exclusions applied.

    Unknown ids in `exclude_experience` / `exclude_projects` (stale — the entry was
    renamed or deleted since the exclusion was saved) are ignored rather than raising:
    the entry simply renders, which is the same "fail open" behaviour a removed tag or a
    removed coursework title already gets elsewhere in this pipeline.
    """
    copy = resume.model_copy(deep=True)
    exclude_exp = set(options.exclude_experience)
    exclude_proj = set(options.exclude_projects)
    copy.experience = [e for e in copy.experience if e.id not in exclude_exp]
    copy.projects = [p for p in copy.projects if p.id not in exclude_proj]

    for edu in copy.education:
        edu.show_gpa = options.gpa
        if not options.coursework:
            edu.coursework = []

    return copy


def contact_order(options: IncludeOptions, layout: dict) -> list[ContactField] | None:
    """Resolve which contact fields render and in what order.

    `options.contact_fields` wins when set; otherwise the active template profile's
    order (already resolved into `layout` by `template_profile.active_layout`) applies.
    """
    if options.contact_fields is not None:
        return list(options.contact_fields)
    order = layout.get("contact_field_order")
    return list(order) if order else None


def validate(resume: MasterResume, options: IncludeOptions) -> list[str]:
    """Human-readable problems that should block a run before any paid LLM call.

    Currently just the one failure mode that would otherwise surface many minutes later
    as an opaque `FitError("No experience or project entries were selected...")` out of
    `fit.choose_entries`.
    """
    problems: list[str] = []
    exclude_exp = set(options.exclude_experience)
    exclude_proj = set(options.exclude_projects)
    remaining_experience = [e for e in resume.experience if e.id not in exclude_exp]
    remaining_projects = [p for p in resume.projects if p.id not in exclude_proj]
    if not remaining_experience and not remaining_projects:
        problems.append(
            "Every experience entry and every project is excluded; nothing would render."
        )
    return problems
