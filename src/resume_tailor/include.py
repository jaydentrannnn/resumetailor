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
    #: Entry ids omitted from this run entirely, across any experience/project section —
    #: one flat namespace, matching `data.MasterResume._ids_unique`, which already checks
    #: every entry id together regardless of which section holds it.
    exclude_entries: list[str] = Field(default_factory=list)
    #: Whole sections omitted from this run entirely (see `data.MasterResume.sections`).
    exclude_sections: list[str] = Field(default_factory=list)
    #: Per-run display order for `resume.sections`, by section id. `None` keeps the
    #: resume's own order. Sections named here come first, in this order; any section not
    #: named (new since this was saved, or simply never reordered) keeps its relative
    #: position and is appended after. Unknown ids are ignored — same fail-open rule as
    #: the exclusion fields. Lives here, not on `MasterResume`, because display order is a
    #: run preference, not a fact about the resume.
    section_order: list[str] | None = None
    #: Legacy: experience ids omitted. Folded into the same exclusion set as
    #: `exclude_entries` at apply/validate time — kept only so a `settings.json` or CLI
    #: invocation saved before `exclude_entries` existed still behaves the same.
    exclude_experience: list[str] = Field(default_factory=list)
    #: Legacy: project ids omitted. Same treatment as `exclude_experience`.
    exclude_projects: list[str] = Field(default_factory=list)


def _excluded_entry_ids(options: IncludeOptions) -> set[str]:
    """Union of every id-exclusion field — the generalised form plus both legacy ones."""
    return (
        set(options.exclude_entries)
        | set(options.exclude_experience)
        | set(options.exclude_projects)
    )


def apply(resume: MasterResume, options: IncludeOptions) -> MasterResume:
    """Return a deep copy of `resume` with exclusions applied.

    Unknown ids (stale — the entry or section was renamed or deleted since the exclusion
    was saved) are ignored rather than raising: the entry simply renders, which is the
    same "fail open" behaviour a removed tag or a removed coursework title already gets
    elsewhere in this pipeline.
    """
    copy = resume.model_copy(deep=True)
    excluded_entries = _excluded_entry_ids(options)
    excluded_sections = set(options.exclude_sections)

    copy.sections = [s for s in copy.sections if s.id not in excluded_sections]
    for section in copy.sections:
        if section.kind in ("experience", "project"):
            section.entries = [e for e in section.entries if e.id not in excluded_entries]

    if options.section_order:
        order_index = {sid: i for i, sid in enumerate(options.section_order)}
        named = [s for s in copy.sections if s.id in order_index]
        unnamed = [s for s in copy.sections if s.id not in order_index]
        named.sort(key=lambda s: order_index[s.id])
        copy.sections = named + unnamed

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
    excluded_entries = _excluded_entry_ids(options)
    excluded_sections = set(options.exclude_sections)
    remaining = [
        entry
        for section in resume.entry_sections
        if section.id not in excluded_sections
        for entry in section.entries
        if entry.id not in excluded_entries
    ]
    if not remaining:
        problems.append(
            "Every experience entry and every project is excluded; nothing would render."
        )
    return problems
